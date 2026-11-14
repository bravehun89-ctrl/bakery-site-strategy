# -*- coding: utf-8 -*-
"""2분 발표 영상 빌드: 문장별 TTS(edge-tts) + 장면 캡처(Playwright/Edge) + ffmpeg 합성.

    pip install edge-tts playwright imageio-ffmpeg
    python video/build.py        → assets/pitch.mp4, assets/poster.png
형식: 1920x1080, 30fps, 한국어 내레이션, Answer First(결론부터).
지도·그래프는 data/site.json(분석 결과)에서 SVG로 직접 그린다.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys

import edge_tts
import imageio_ffmpeg
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
TMP = os.path.join(HERE, "_tmp"); os.makedirs(TMP, exist_ok=True)
OUT = os.path.join(ROOT, "assets"); os.makedirs(OUT, exist_ok=True)
FF = imageio_ffmpeg.get_ffmpeg_exe()
VOICE, RATE, GAP, LIMIT = "ko-KR-HyunsuMultilingualNeural", "+6%", 0.35, 118.0

D = json.load(open(os.path.join(ROOT, "data", "site.json"), encoding="utf-8"))
PK, SN, BT = D["picks"]["둔촌역"], D["seoul_now"], D["backtest"][0]
ACC, INK, MUTE, GRID, GRAY = "#C4501B", "#1B1713", "#8a8074", "#E2D9CA", "#CFC5B5"
XL = [(0, "2021"), (4, "2022"), (8, "2023"), (12, "2024"), (16, "2025"), (20, "2026")]


# ── SVG 그리기 ───────────────────────────────────────────────────────────────
def _g(step) -> str:
    return f' data-s="{step}"' if step else ""


def svg_map(w, h, marks):
    """서울 상권 1,650곳(회색)과 제과점 상권 337곳(점수가 높을수록 진하고 큼). marks: (상권명, 라벨, 단계, dx, dy, 정렬)"""
    bg = D["map_bg"]
    xs, ys = [p[0] for p in bg], [p[1] for p in bg]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    s = min((w - 30) / (x1 - x0), (h - 30) / (y1 - y0))
    ox, oy = (w - (x1 - x0) * s) / 2, (h - (y1 - y0) * s) / 2
    X = lambda x: ox + (x - x0) * s
    Y = lambda y: h - oy - (y - y0) * s
    o = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">']
    o += [f'<circle cx="{X(a):.1f}" cy="{Y(b):.1f}" r="2.4" fill="#DDD3C3"/>' for a, b in bg]
    for m in sorted(D["map"], key=lambda m: m[2]):
        t = max(0.0, (m[2] - 30) / 55)
        o.append(f'<circle cx="{X(m[0]):.1f}" cy="{Y(m[1]):.1f}" r="{3 + t * 5:.1f}" fill="rgba(196,80,27,{0.12 + t * 0.85:.2f})"/>')
    for name, label, step, dx, dy, anchor in marks:
        m = next(v for v in D["map"] if v[3] == name)
        cx, cy = X(m[0]), Y(m[1])
        o.append(f'<g{_g(step)}><circle cx="{cx:.1f}" cy="{cy:.1f}" r="17" fill="none" stroke="{INK}" stroke-width="4.5"/>'
                 f'<text x="{cx + dx:.1f}" y="{cy + dy:.1f}" font-size="30" font-weight="800" text-anchor="{anchor}" fill="{INK}" '
                 f'paint-order="stroke" stroke="#F5F0E6" stroke-width="9" stroke-linejoin="round">{label}</text></g>')
    return "".join(o) + "</svg>"


def svg_line(w, h, series, ymin, ymax, xl=XL, mark=None):
    L, R, T, B = 70, 120, 18, 40
    n = len(series[0]["d"])
    X = lambda i: L + i * (w - L - R) / (n - 1)
    Y = lambda v: h - B - (v - ymin) / (ymax - ymin) * (h - T - B)
    o = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">']
    for v in (ymin, (ymin + ymax) / 2, ymax):
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{GRID}" stroke-width="2"/>'
                 f'<text x="{L - 10}" y="{Y(v) + 7:.1f}" font-size="20" text-anchor="end" fill="{MUTE}">{v:,.0f}</text>')
    for i, t in xl:
        o.append(f'<text x="{X(i):.1f}" y="{h - 8}" font-size="20" text-anchor="middle" fill="{MUTE}">{t}</text>')
    if mark:
        i, t = mark
        o.append(f'<line x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{T}" y2="{h - B}" stroke="{ACC}" stroke-width="2.5" stroke-dasharray="8 6"/>'
                 f'<text x="{X(i) - 10:.1f}" y="{T + 22}" font-size="22" font-weight="700" text-anchor="end" fill="{ACC}">{t}</text>')
    for s in series:
        pts = [(X(i), Y(v)) for i, v in enumerate(s["d"]) if v is not None]
        d = " ".join(("M" if k == 0 else "L") + f"{x:.1f} {y:.1f}" for k, (x, y) in enumerate(pts))
        c = s["c"]
        o.append(f'<g{_g(s.get("step"))}><path d="{d}" fill="none" stroke="{c}" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"/>'
                 f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="9" fill="{c}"/>'
                 f'<text x="{pts[-1][0] + 16:.1f}" y="{pts[-1][1] + 9:.1f}" font-size="26" font-weight="800" fill="{c}">{s.get("end", "")}</text>')
        if s.get("start"):
            o.append(f'<text x="{pts[0][0]:.1f}" y="{pts[0][1] + s.get("start_dy", -16):.1f}" font-size="22" font-weight="700" fill="{c}">{s["start"]}</text>')
        o.append("</g>")
    return "".join(o) + "</svg>"


def svg_gbars(w, h, labels, sets, neg=False):
    L, R = 10, 10
    T, B = (50, 36) if neg else (34, 40)
    vmax = max(abs(v) for s in sets for v in s["d"]) * 1.02
    n = len(labels); gw = (w - L - R) / n; bw = gw / (len(sets) + 0.7)
    sc = (h - T - B) / vmax
    y0 = T if neg else h - B
    o = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
         f'<line x1="{L}" x2="{w - R}" y1="{y0}" y2="{y0}" stroke="#B9AE9E" stroke-width="2.5"/>']
    for i, lb in enumerate(labels):
        o.append(f'<text x="{L + i * gw + gw / 2:.1f}" y="{T - 18 if neg else h - 10}" font-size="22" font-weight="600" text-anchor="middle" fill="{MUTE}">{lb}</text>')
    for j, s in enumerate(sets):
        o.append(f"<g{_g(s.get('step'))}>")
        for i, v in enumerate(s["d"]):
            c = s["c"][i] if isinstance(s["c"], list) else s["c"]
            x = L + i * gw + bw * 0.35 + j * bw; hh = abs(v) * sc
            y = y0 if neg else y0 - hh
            ty = (y0 + hh + 26) if neg else (y - 8)
            o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw - 6:.1f}" height="{max(hh, 2):.1f}" rx="5" fill="{c}"/>'
                     f'<text x="{x + (bw - 6) / 2:.1f}" y="{ty:.1f}" font-size="21" font-weight="800" text-anchor="middle" fill="{INK}">{f"{v:.1f}".replace("-", "−")}</text>')
        o.append("</g>")
    return "".join(o) + "</svg>"


def svg_stack(w, rows, lw=96):
    """가로 누적 막대. rows: (제목, [(라벨, 값, 색)], 단계, 오른쪽 위 메모)"""
    RH, GP = 56, 36
    h = len(rows) * (RH + GP)
    o = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">']
    for r, (title, segs, step, note) in enumerate(rows):
        y = r * (RH + GP) + GP - 6; tot = sum(v for _, v, _ in segs); x = lw
        o.append(f'<g{_g(step)}><text x="0" y="{y + 37}" font-size="24" font-weight="800" fill="{INK}">{title}</text>')
        if note:
            o.append(f'<text x="{w}" y="{y - 9}" font-size="22" font-weight="800" text-anchor="end" fill="#2F6B4F">{note}</text>')
        for lb, v, c in segs:
            ww = v / tot * (w - lw)
            o.append(f'<rect x="{x:.1f}" y="{y}" width="{max(ww - 3, 1):.1f}" height="{RH}" rx="4" fill="{c}"/>')
            est = sum(20 if ord(ch) > 127 else 11 for ch in f"{lb} {v:g}") + 14
            if ww > est:
                o.append(f'<text x="{x + ww / 2:.1f}" y="{y + 36}" font-size="20" font-weight="700" text-anchor="middle" fill="#fff">{lb} {v:g}</text>')
            x += ww
        o.append("</g>")
    return "".join(o) + "</svg>"


def svg_hbars(w, items, vmax):
    RH, LW = 44, 250
    h = len(items) * RH
    o = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">']
    for r, (lb, v, c, bold) in enumerate(items):
        y = r * RH; ww = v / vmax * (w - LW - 90)
        o.append(f'<text x="0" y="{y + 30}" font-size="24" font-weight="{800 if bold else 600}" fill="{INK}">{lb}</text>'
                 f'<rect x="{LW}" y="{y + 6}" width="{ww:.1f}" height="{RH - 14}" rx="5" fill="{c}"/>'
                 f'<text x="{LW + ww + 12:.1f}" y="{y + 30}" font-size="24" font-weight="800" fill="{INK}">{v:.1f}</text>')
    return "".join(o) + "</svg>"


PLAN = f"""<svg viewBox="0 0 820 310" width="820" height="310">
<rect x="6" y="6" width="808" height="250" rx="6" fill="#FFFDF8" stroke="{INK}" stroke-width="4"/>
<rect x="8" y="8" width="804" height="112" fill="#EFE8DA"/>
<text x="410" y="58" font-size="26" font-weight="800" text-anchor="middle" fill="{INK}">주방 40㎡</text>
<text x="410" y="92" font-size="21" text-anchor="middle" fill="{MUTE}">오전 6시 · 오후 3시, 하루 두 번 반죽</text>
<line x1="8" x2="812" y1="120" y2="120" stroke="{INK}" stroke-width="2" stroke-dasharray="10 6"/>
<rect x="26" y="168" width="190" height="78" rx="6" fill="{ACC}"/>
<text x="121" y="204" font-size="26" font-weight="800" text-anchor="middle" fill="#fff">데크 오븐</text>
<text x="121" y="232" font-size="20" font-weight="700" text-anchor="middle" fill="#fff">다음 굽기 16:30</text>
<rect x="250" y="140" width="300" height="48" rx="6" fill="{GRID}"/>
<text x="400" y="172" font-size="21" font-weight="700" text-anchor="middle" fill="{INK}">진열대 · 높이 1.1m 이하</text>
<rect x="250" y="204" width="136" height="42" rx="6" fill="#FFFDF8" stroke="{INK}" stroke-width="2.5"/>
<text x="318" y="232" font-size="20" font-weight="700" text-anchor="middle" fill="{INK}">계산 · 포장</text>
<rect x="414" y="204" width="136" height="42" rx="6" fill="#FFFDF8" stroke="{INK}" stroke-width="2.5"/>
<text x="482" y="232" font-size="20" font-weight="700" text-anchor="middle" fill="{INK}">커팅 · 포장</text>
<rect x="690" y="136" width="108" height="110" rx="6" fill="#FFFDF8" stroke="{INK}" stroke-width="2.5"/>
<text x="744" y="186" font-size="22" font-weight="800" text-anchor="middle" fill="{INK}">창가 벤치</text>
<text x="744" y="214" font-size="20" text-anchor="middle" fill="{MUTE}">좌석 8석</text>
<g data-s="3"><rect x="244" y="198" width="312" height="54" rx="9" fill="none" stroke="{ACC}" stroke-width="5"/>
<rect x="684" y="130" width="120" height="122" rx="9" fill="none" stroke="{ACC}" stroke-width="5"/>
<text x="620" y="232" font-size="21" font-weight="800" text-anchor="middle" fill="{ACC}">통로 1.2m</text></g>
<rect x="580" y="250" width="90" height="12" fill="#F5F0E6"/>
<text x="625" y="290" font-size="21" font-weight="700" text-anchor="middle" fill="{INK}">입구</text>
<text x="121" y="290" font-size="21" font-weight="700" text-anchor="middle" fill="{ACC}">보도에서 오븐이 보임</text>
<text x="400" y="290" font-size="21" text-anchor="middle" fill="{MUTE}">보도 · 역에서 시장으로 가는 퇴근 동선</text>
</svg>"""

MAP_HERO = svg_map(640, 480, [("둔촌역", "둔촌역 · 14위", 2, -26, -16, "end")])
MAP_SITE = svg_map(600, 470, [("둔촌역", "둔촌역", 0, 18, 52, "end"), ("마들역", "마들역 · 2호점 후보", 2, -26, 8, "end"),
                              ("성수동카페거리", "성수 301위", 2, -24, 8, "end")])
MAP_END = svg_map(640, 500, [("둔촌역", "둔촌역", 0, -26, -16, "end")])
LINE_SEOUL = svg_line(820, 320, [{"d": D["seoul"]["amt_eok"], "c": ACC, "end": f'{D["seoul"]["amt_eok"][-1]:,}'}], 0, 2400)
_yrs = sorted(D["age_h1_eok"])
_a20, _a60 = [D["age_h1_eok"][y][1] for y in _yrs], [D["age_h1_eok"][y][5] for y in _yrs]
LINE_AGE = svg_line(820, 320, [{"d": _a20, "c": "#8D8377", "start": f"20대 {_a20[0]}", "end": str(_a20[-1])},
                               {"d": _a60, "c": ACC, "start": f"60대 이상 {_a60[0]}", "start_dy": 36, "end": str(_a60[-1])}],
                    300, 800, xl=[(i, y) for i, y in enumerate(_yrs)])
BARS_BT = svg_gbars(1000, 360, ["하위 20%", "20~40%", "40~60%", "60~80%", "상위 20%"], [
    {"d": [v * 100 for v in BT["Q_추세만"]], "c": [GRAY, GRAY, GRAY, GRAY, "#6E655B"]},
    {"d": [v * 100 for v in BT["Q_가중"]], "c": [ACC, "#E3A988", "#E3A988", "#E3A988", ACC], "step": 2}], neg=True)
LINE_DC = svg_line(980, 230, [{"d": PK["q_bk_eok"], "c": ACC, "end": f'{PK["q_bk_eok"][-1]:.1f}'}], 10, 24, mark=(15, "포레온 입주 시작"))
BARS_AGE = svg_gbars(820, 205, ["10대", "20대", "30대", "40대", "50대", "60대+"], [{"d": PK["age"], "c": ACC}, {"d": SN["age"], "c": GRAY}])
BARS_TZ = svg_gbars(820, 205, ["~6시", "6~11시", "11~14시", "14~17시", "17~21시", "21~24시"], [{"d": PK["tz"], "c": ACC}, {"d": SN["tz"], "c": GRAY}])
MENU = svg_stack(820, [("", [("식사빵", 35, "#8C3A14"), ("저녁 굽기", 20, ACC), ("조리빵", 15, "#DD8A5E"), ("주말", 15, "#B9AE9E"),
                             ("페이스트리", 10, "#8D8377"), ("음료", 5, GRAY)], None, "")], lw=0)
_C = ["#8C3A14", ACC, "#DD8A5E", "#B9AE9E", "#8D8377", "#2F6B4F"]
_N = ["재료", "인건", "임차", "기타", "감가", "이익"]
STACK_PNL = svg_stack(820, [
    ("1년차", list(zip(_N, [36, 30, 11.8, 12.7, 7.9, 1.7], _C)), None, "영업이익 1.7%"),
    ("3년차", list(zip(_N, [35, 27, 10.4, 12.2, 6.6, 8.8], _C)), 2, "영업이익 8.8%")])
HB_LABOR = svg_hbars(820, [("본 제안", 30.0, ACC, True), ("아티제", 30.4, GRAY, False), ("성심당", 31.1, GRAY, False),
                           ("런던베이글뮤지엄", 38.1, GRAY, False)], 40)

SCENES = [
    {"tag": "결론", "html": f"""
      <div class="split" style="grid-template-columns:1.15fr .85fr"><div>
        <h1 style="font-size:96px">뜨는 상권이 아니라<br><em>버티는 생활권</em>에 냅니다.</h1>
        <div class="row" data-s="2"><div class="pill">추천 입지</div><div class="xl">강동구 둔촌역 상권</div></div></div>
        <div>{MAP_HERO}<p class="src" style="text-align:center">점 하나가 상권 하나 · 진할수록 성장성 점수가 높음</p></div></div>
      <div class="kp sm" data-s="2"><div><b>14위 / 337</b><span>성장성 점수 · 상위 4%</span></div><div><b>5.6억 원</b><span>점포당 제과점 연매출 · 상위 9%</span></div><div><b>8.8%</b><span>3년차 영업이익률</span></div></div>""",
     "lines": ["결론부터 말씀드립니다. 다음 매장은 뜨는 상권이 아니라, 버티는 생활권에 내야 합니다.",
               "추천 입지는 강동구 둔촌역 상권입니다."]},
    {"tag": "시장", "html": f"""
      <h2 style="margin-bottom:24px">빵 시장은 5년째 제자리, <em>고객만 바뀌었습니다.</em></h2>
      <div class="split"><div><div class="cap">서울 제과점 분기 매출 (억 원)</div>{LINE_SEOUL}
        <div class="rank sm"><span>매출 <b>+2.1%</b></span><span>결제 건수 <b>−9.8%</b></span><span>객단가 <b>+13.2%</b></span></div></div>
      <div data-s="2"><div class="cap">연령별 상반기 제과점 매출 (억 원)</div>{LINE_AGE}
        <div class="rank sm"><span>20대 <b>−35%</b></span><span class="hi">60대 이상 <b>+78%</b></span></div></div></div>
      <p class="src">서울 열린데이터광장 추정매출-상권(제과점) · 증감은 2021년 2분기 → 2026년 2분기, 연령은 2021년 → 2026년 상반기</p>""",
     "lines": ["서울 제과점 매출은 5년째 분기 2천억 원에 멈춰 있습니다. 건수는 10% 줄고, 객단가만 올랐습니다.",
               "고객도 바뀌었습니다. 20대 매출은 35% 줄었고, 60대 이상은 78% 늘었습니다."]},
    {"tag": "검증", "html": f"""
      <h2 style="margin-bottom:22px">3년 전 점수로 <em>지금을 맞혀 봤습니다.</em></h2>
      <div class="split" style="grid-template-columns:1.3fr .7fr"><div><div class="cap">2023년 2분기에 나눈 다섯 그룹의 이후 3년 실제 성장률 (중위, %)</div>{BARS_BT}
        <p class="src"><b style="color:#6E655B">■ 과거 1년 매출 증가율 기준</b> <span data-s="2"><b style="color:#C4501B">■ 본 점수 기준</b></span> · 표본 301개 상권</p></div>
      <div><div class="col s"><small>과거 매출 증가율 상위 20%</small><b class="bad">−10.6%</b><span>다섯 그룹 중 최하위</span></div>
        <div class="col s" data-s="2" style="margin-top:16px"><small>본 점수 상위 20%</small><b class="ok">−2.2%</b><span>하위 20%는 −21.4% · 시장 중위 −6.6%</span></div></div></div>
      <div class="rank sm" data-s="3"><span>성수동카페거리 <b>301위</b></span><span>연남동 <b>300위</b></span><span>압구정로데오 <b>333위</b></span><span class="hi">둔촌역 <b>14위</b></span></div>""",
     "lines": ["그래서 3년 전 데이터로 검증했습니다. 당시 매출이 가장 빠르게 늘던 상권 상위 20%는, 3년 뒤 오히려 가장 많이 줄었습니다.",
               "반면 유동인구, 오륙십대 비중, 폐업률 등 여섯 지표로 만든 점수 상위 20%는 2% 감소로 버텼고, 하위 20%는 21% 줄었습니다.",
               "이 점수로 보면, 성수와 연남은 337곳 중 300위 아래입니다."]},
    {"tag": "입지", "html": f"""
      <h2 style="margin-bottom:20px">강동구 <em>둔촌역 상권</em></h2>
      <div class="split" style="grid-template-columns:.75fr 1.25fr"><div>{MAP_SITE}</div>
      <div><div class="kp sm"><div><b>상위 4%</b><span>성장성 점수 74.1 · 14위</span></div><div><b>5.6억 원</b><span>점포당 제과점 연매출 · 상위 9%</span></div><div><b>74.2억 원</b><span>제과점 시장 · 독립 빵집 85%</span></div></div>
        <div data-s="2"><div class="cap">둔촌역 상권 제과점 분기 매출 (억 원)</div>{LINE_DC}
        <div class="rank sm"><span>올림픽파크포레온 <b>12,032세대</b></span><span>유동인구 <b>+8.9%</b></span><span>둔촌동역 일 <b>30,543명</b></span></div></div></div></div>""",
     "lines": ["둔촌역 상권은 성장성 점수 상위 4%, 점포당 제과점 매출은 연 5억 6천만 원으로 상위 9%입니다.",
               "맞은편에 만 2천 세대 올림픽파크포레온이 입주했고, 유동인구는 1년 새 9% 늘었습니다."]},
    {"tag": "공간 · 메뉴", "html": f"""
      <h2 style="margin-bottom:18px">두 번 굽는 <em>동네 식탁</em></h2>
      <div class="split" style="align-items:start"><div><div class="cap">누가 사는가 · 연령별 매출 비중 (%) — 50대 이상 50.7%</div>{BARS_AGE}
        <div class="cap" style="margin-top:8px">언제 사는가 · 시간대별 매출 비중 (%) — 17시 이후 38.4%</div>{BARS_TZ}
        <p class="src"><b style="color:#C4501B">■ 둔촌역</b> <b style="color:#B9AE9E">■ 서울 평균</b> · 2025년 3분기~2026년 2분기</p></div>
      <div data-s="2"><div class="cap">66㎡ 매장 배치 · 오후 4시 30분에 한 번 더 굽는 오븐을 전면에</div>{PLAN}
        <div class="cap" style="margin-top:4px">메뉴 매출 구성 (%)</div>{MENU}
        <p class="src">식사빵 35 · 저녁 굽기 20 · 조리빵 15 · 주말·선물 15 · 페이스트리 10 · 음료 5 · 전 품목 하프 사이즈</p></div></div>""",
     "lines": ["이곳 매출의 절반은 50대 이상에게서, 38%는 오후 다섯 시 이후에 나옵니다.",
               "그래서 컨셉은, 두 번 굽는 동네 식탁입니다. 오후 네 시 반에 한 번 더 굽고, 식사빵과 하프 사이즈를 앞에 둡니다.",
               "좌석은 줄이고, 포장 동선을 넓힙니다."]},
    {"tag": "손익", "html": f"""
      <h2 style="margin-bottom:24px">상권 평균만 해도 <em>손익분기</em></h2>
      <div class="split"><div>
        <div class="kp sm"><div><b>5.6억 원</b><span>1년차 매출 = 상권 점포당 평균</span></div><div><b>일 142건</b><span>손익분기 · 기본 가정 146건</span></div><div><b>9.5%</b><span>1년차 EBITDA 마진</span></div></div>
        <div class="kp sm" data-s="2"><div><b>6.65억 원</b><span>3년차 매출</span></div><div><b>8.8%</b><span>3년차 영업이익률 · 외식업 평균 8.7%</span></div><div><b>약 4.1년</b><span>권리금 포함 3.5억 원 회수</span></div></div></div>
      <div><div class="cap">매출 100원의 쓰임 (%)</div>{STACK_PNL}
        <p class="src" style="margin:4px 0 0"><b style="color:#8C3A14">■ 재료</b> <b style="color:#C4501B">■ 인건</b> <b style="color:#DD8A5E">■ 임차</b> <b style="color:#B9AE9E">■ 수도·포장·수수료 등</b> <b style="color:#8D8377">■ 감가상각</b> <b style="color:#2F6B4F">■ 영업이익</b></p>
        <div data-s="3"><div class="cap" style="margin-top:6px">인건비 비율 대조 (매출 대비 %, DART 2025년)</div>{HB_LABOR}</div></div></div>
      <p class="src">매출은 서울 열린데이터 추정매출 · 비용은 DART 감사보고서(2025년), 한국부동산원(2026년 3분기), 최저임금위원회 기준</p>""",
     "lines": ["66제곱미터 매장 기준, 1년차에 상권 평균 매출인 5억 6천만 원으로 손익분기를 넘깁니다.",
               "3년차에는 매출 6억 6천만 원, 영업이익률 약 9%, 투자금 회수는 약 4년입니다.",
               "비용 가정은 성심당과 아티제의 실제 공시와 대조해 맞췄습니다."]},
    {"tag": "제안", "html": f"""
      <div class="split" style="grid-template-columns:1.15fr .85fr"><div>
        <h1>뜨는 곳이 아니라,<br><em>버티는 곳.</em></h1>
        <div class="xl" style="margin-top:30px">둔촌에서 시작하겠습니다.</div>
        <p class="src" style="margin-top:44px">데이터: 서울 열린데이터광장 상권분석서비스 · 2021년 1분기~2026년 2분기 · 1,650개 상권</p></div>
        <div>{MAP_END}</div></div>""",
     "lines": ["뜨는 곳이 아니라, 버티는 곳. 둔촌에서 시작하겠습니다."]},
]

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
*{box-sizing:border-box}body{margin:0;width:1920px;height:1080px;background:#F5F0E6;color:#1B1713;font-family:Pretendard,"Malgun Gothic",sans-serif;word-break:keep-all;overflow:hidden}
.top{position:absolute;left:96px;right:96px;top:50px;display:flex;justify-content:space-between;font-size:26px;font-weight:700;color:#6E655B}
.top b{color:#C4501B;letter-spacing:.06em}
.stage{position:absolute;left:96px;right:96px;top:120px;bottom:216px;display:flex;flex-direction:column;justify-content:center}
h1{font-size:112px;line-height:1.14;letter-spacing:-.035em;margin:0 0 36px;font-weight:800}
h2{font-size:72px;line-height:1.18;letter-spacing:-.03em;margin:0 0 44px;font-weight:800}
em{font-style:normal;color:#C4501B}
.row{display:flex;align-items:center;gap:22px;margin-bottom:30px}.pill{background:#C4501B;color:#fff;font-size:30px;font-weight:800;padding:10px 24px;border-radius:99px}
.xl{font-size:64px;font-weight:800;letter-spacing:-.02em}
.split{display:grid;grid-template-columns:1fr 1fr;gap:44px;align-items:center}.split>div{min-width:0}
.kp{display:grid;grid-template-columns:repeat(3,1fr);border:3px solid #1B1713;border-radius:24px;background:#FFFDF8;margin-bottom:26px;overflow:hidden}
.kp div{padding:30px 36px;border-right:2px solid #E2D9CA}.kp div:last-child{border:0}
.kp b{display:block;font-size:72px;font-weight:800;letter-spacing:-.03em;line-height:1.1}.kp span{font-size:28px;color:#6E655B}
.kp.sm{margin-bottom:18px}.kp.sm div{padding:18px 24px}.kp.sm b{font-size:52px}.kp.sm span{font-size:21px;display:block;line-height:1.3;margin-top:4px}
.cap{font-size:23px;font-weight:800;color:#6E655B;margin:0 0 6px}
.col{background:#FFFDF8;border:2px solid #E2D9CA;border-radius:24px;padding:30px 36px}
.col small{font-size:26px;font-weight:700;color:#6E655B;display:block}.col b{font-size:104px;font-weight:800;letter-spacing:-.03em;display:block;line-height:1.15}
.col span{font-size:23px;color:#6E655B}.bad{color:#6E655B}.ok{color:#C4501B}.col.s{padding:20px 30px}.col.s b{font-size:84px}
.rank{display:flex;gap:14px;flex-wrap:wrap;margin-top:12px}.rank span{font-size:32px;background:#E9E2D5;border-radius:99px;padding:12px 26px}.rank .hi{background:#C4501B;color:#fff}
.rank.sm span{font-size:26px;padding:9px 20px}
.src{font-size:21px;color:#8a8074;margin:8px 0 0}
svg{display:block;max-width:100%;height:auto}svg text{font-family:Pretendard,"Malgun Gothic",sans-serif}
.sub{position:absolute;left:0;right:0;bottom:0;height:200px;background:#1B1713;color:#F5F0E6;display:flex;align-items:center;justify-content:center;text-align:center;padding:0 150px;font-size:40px;font-weight:600;line-height:1.4}
.prog{position:absolute;left:0;bottom:200px;height:8px;background:#C4501B}
[data-s]{visibility:hidden}
</style></head><body>
<div class="top"><span><b id="tag"></b></span><span>베이커리 신규 출점 전략 · 서울 열린데이터 22개 분기</span></div>
<div class="stage" id="stage"></div><div class="prog" id="prog"></div><div class="sub" id="sub"></div>
<script>
function show(html,tag,step,sub,p){const st=document.getElementById('stage');st.innerHTML=html;document.getElementById('tag').textContent=tag;
document.querySelectorAll('[data-s]').forEach(e=>{e.style.visibility=(+e.dataset.s<=step)?'visible':'hidden'});
document.getElementById('sub').textContent=sub;document.getElementById('prog').style.width=(p*100)+'%';
return [st.scrollHeight,st.clientHeight,st.scrollWidth,st.clientWidth]}
</script></body></html>"""


def dur(path: str) -> float:
    err = subprocess.run([FF, "-i", path], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


async def tts(items):
    async def one(i, text):
        await edge_tts.Communicate(text, VOICE, rate=RATE).save(os.path.join(TMP, f"a{i:02d}.mp3"))
    await asyncio.gather(*(one(i, t) for i, (_, _, t) in enumerate(items)))


def main() -> None:
    items = [(si, li + 1, line) for si, sc in enumerate(SCENES) for li, line in enumerate(sc["lines"])]
    if "--frames-only" not in sys.argv and "--no-tts" not in sys.argv:   # --no-tts: 이전에 합성한 음성 재사용
        asyncio.run(tts(items))
    durs = [dur(os.path.join(TMP, f"a{i:02d}.mp3")) for i in range(len(items))]
    total = sum(durs) + GAP * len(items)
    tempo = max(1.0, total / LIMIT)
    print(f"문장 {len(items)}개 · 원본 {total:.1f}초 · 속도 보정 x{tempo:.3f}")

    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.set_content(PAGE, wait_until="networkidle")
        pg.evaluate("document.fonts.ready")
        acc = 0.0
        for i, (si, step, line) in enumerate(items):
            acc += durs[i] + GAP
            sh, ch, sw, cw = pg.evaluate("([h,t,s,u,p])=>show(h,t,s,u,p)",
                                         [SCENES[si]["html"], SCENES[si]["tag"], step, line, acc / total])
            if sh > ch + 2 or sw > cw + 2:
                print(f"  [넘침] 장면 {si + 1} 단계 {step}: 내용 {sw}x{sh} > 무대 {cw}x{ch}")
            pg.wait_for_timeout(120)
            pg.screenshot(path=os.path.join(TMP, f"f{i:02d}.png"))
        b.close()
    if "--frames-only" in sys.argv:
        return

    segs = []
    for i in range(len(items)):
        d = (durs[i] + GAP) / tempo
        seg = os.path.join(TMP, f"s{i:02d}.mp4")
        af = (f"atempo={tempo:.4f}," if tempo > 1.001 else "") + f"apad=pad_dur={GAP + 0.5}"
        subprocess.run([FF, "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", os.path.join(TMP, f"f{i:02d}.png"),
                        "-i", os.path.join(TMP, f"a{i:02d}.mp3"), "-filter_complex", f"[1:a]{af}[a]", "-map", "0:v", "-map", "[a]",
                        "-t", f"{d:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
                        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", seg], check=True)
        segs.append(seg)
    lst = os.path.join(TMP, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.writelines(f"file '{s.replace(os.sep, '/')}'\n" for s in segs)
    out = os.path.join(OUT, "pitch.mp4")
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out], check=True)
    shutil.copy(os.path.join(TMP, "f01.png"), os.path.join(OUT, "poster.png"))
    print(f"완성: {out} · {dur(out):.1f}초 · {os.path.getsize(out) / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
