# -*- coding: utf-8 -*-
"""2분 발표 영상 빌드: 문장별 TTS(edge-tts) + 장면 캡처(Playwright/Edge) + ffmpeg 합성.

    pip install edge-tts playwright imageio-ffmpeg
    python video/build.py        → assets/pitch.mp4, assets/poster.png
형식: 1920x1080, 30fps, 한국어 내레이션, Answer First(결론부터).
"""
from __future__ import annotations

import asyncio
import os
import re
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

SCENES = [
    {"tag": "결론", "html": """
      <h1>뜨는 상권이 아니라<br><em>버티는 생활권</em>에 냅니다.</h1>
      <div class="row" data-s="2"><div class="pill">추천 입지</div><div class="xl">강동구 둔촌역 상권</div></div>
      <div class="kp" data-s="2"><div><b>14위 / 337</b><span>성장성 점수 · 상위 4%</span></div><div><b>5.6억 원</b><span>점포당 제과점 연매출 · 상위 9%</span></div><div><b>8.8%</b><span>3년차 영업이익률</span></div></div>""",
     "lines": ["결론부터 말씀드립니다. 다음 매장은 뜨는 상권이 아니라, 버티는 생활권에 내야 합니다.",
               "추천 입지는 강동구 둔촌역 상권입니다."]},
    {"tag": "시장", "html": """
      <h2>빵 시장은 5년째 제자리, <em>고객만 바뀌었습니다.</em></h2>
      <div class="kp"><div><b>+2.1%</b><span>분기 매출 1,961억 → 2,002억 원</span></div><div><b>−9.8%</b><span>결제 건수 2,035만 → 1,835만 건</span></div><div><b>+13.2%</b><span>객단가 9,638 → 10,914원</span></div></div>
      <div class="duo" data-s="2"><div class="neg"><b>20대 −35%</b><span>691억 → 451억 원</span></div><div class="pos"><b>60대 이상 +78%</b><span>394억 → 703억 원</span></div></div>
      <p class="src">서울 열린데이터광장 추정매출-상권(제과점), 2021년 2분기 → 2026년 2분기 · 연령은 상반기 매출</p>""",
     "lines": ["서울 제과점 매출은 5년째 분기 2천억 원에 멈춰 있습니다. 건수는 10% 줄고, 객단가만 올랐습니다.",
               "고객도 바뀌었습니다. 20대 매출은 35% 줄었고, 60대 이상은 78% 늘었습니다."]},
    {"tag": "검증", "html": """
      <h2>3년 전 점수로 <em>지금을 맞혀 봤습니다.</em></h2>
      <div class="bt"><div class="col"><small>과거 1년 매출 증가율 상위 20%</small><b class="bad">−10.6%</b><span>3년 뒤 실제 성장률 · 다섯 그룹 중 최하위</span></div>
      <div class="col" data-s="2"><small>본 점수 상위 20%</small><b class="ok">−2.2%</b><span>유입·고객·체력·흐름 6개 지표</span></div>
      <div class="col" data-s="2"><small>본 점수 하위 20%</small><b>−21.4%</b><span>시장 중위 −6.6%</span></div></div>
      <div class="rank" data-s="3"><span>성수동카페거리 <b>301위</b></span><span>연남동 <b>300위</b></span><span>압구정로데오 <b>333위</b></span><span class="hi">둔촌역 <b>14위</b></span></div>
      <p class="src">백테스트 A: 2023년 2분기 채점 → 2026년 2분기 실제 제과점 매출 성장률(중위), 표본 301개 상권</p>""",
     "lines": ["그래서 3년 전 데이터로 검증했습니다. 당시 매출이 가장 빠르게 늘던 상권 상위 20%는, 3년 뒤 오히려 가장 많이 줄었습니다.",
               "반면 유동인구, 오륙십대 비중, 폐업률 등 여섯 지표로 만든 점수 상위 20%는 2% 감소로 버텼고, 하위 20%는 21% 줄었습니다.",
               "이 점수로 보면, 성수와 연남은 337곳 중 300위 아래입니다."]},
    {"tag": "입지", "html": """
      <h2>강동구 <em>둔촌역 상권</em></h2>
      <div class="kp"><div><b>상위 4%</b><span>성장성 점수 74.1 · 337곳 중 14위</span></div><div><b>5.6억 원</b><span>점포당 제과점 연매출 · 상위 9%</span></div><div><b>74.2억 원</b><span>상권 제과점 시장 · 독립 빵집 85%</span></div></div>
      <div class="kp" data-s="2"><div><b>12,032세대</b><span>올림픽파크포레온 · 2024년 11월 입주 시작</span></div><div><b>+8.9%</b><span>유동인구 전년 대비</span></div><div><b>30,543명</b><span>5호선 둔촌동역 일 승하차</span></div></div>
      <p class="src">2025년 3분기~2026년 2분기 기준 · 승하차 2026년 11월 10일 · 세대수 강동구청 준공 인가 자료</p>""",
     "lines": ["둔촌역 상권은 성장성 점수 상위 4%, 점포당 제과점 매출은 연 5억 6천만 원으로 상위 9%입니다.",
               "맞은편에 만 2천 세대 올림픽파크포레온이 입주했고, 유동인구는 1년 새 9% 늘었습니다."]},
    {"tag": "공간 · 메뉴", "html": """
      <h2>두 번 굽는 <em>동네 식탁</em></h2>
      <div class="chain"><div><small>상권 데이터</small><b>50대 이상 50.7%</b><span>서울 40.0%</span></div><i>→</i><div data-s="2"><small>메뉴</small><b>식사빵 35% · 하프 사이즈</b><span>객단가 목표 10,500원</span></div></div>
      <div class="chain"><div><small>상권 데이터</small><b>17시 이후 38.4%</b><span>서울 32.7%</span></div><i>→</i><div data-s="2"><small>공간</small><b>16:30 두 번째 굽기</b><span>오븐을 보도 쪽 전면에</span></div></div>
      <div class="chain" data-s="3"><div><small>상권 데이터</small><b>커피 시장은 빵의 0.5배</b><span>서울은 3.5배</span></div><i>→</i><div><small>공간</small><b>좌석 8석 · 포장대 2곳</b><span>66㎡ 소형 고회전</span></div></div>""",
     "lines": ["이곳 매출의 절반은 50대 이상에게서, 38%는 오후 다섯 시 이후에 나옵니다.",
               "그래서 컨셉은, 두 번 굽는 동네 식탁입니다. 오후 네 시 반에 한 번 더 굽고, 식사빵과 하프 사이즈를 앞에 둡니다.",
               "좌석은 줄이고, 포장 동선을 넓힙니다."]},
    {"tag": "손익", "html": """
      <h2>상권 평균만 해도 <em>손익분기</em></h2>
      <div class="kp"><div><b>5.6억 원</b><span>1년차 매출 = 상권 점포당 평균</span></div><div><b>일 142건</b><span>손익분기 · 기본 가정 146건</span></div><div><b>9.5%</b><span>1년차 EBITDA 마진</span></div></div>
      <div class="kp" data-s="2"><div><b>6.65억 원</b><span>3년차 매출</span></div><div><b>8.8%</b><span>3년차 영업이익률 · 외식업 평균 8.7%</span></div><div><b>약 4.1년</b><span>권리금 포함 투자 3.5억 원 회수</span></div></div>
      <div class="rank" data-s="3"><span>인건비 30.0% · <b>성심당 31.1% · 아티제 30.4%</b></span><span>임차료 ㎡당 8.3만 원 · <b>천호 5.8만 원</b></span><span>재료비 36% · <b>아티제 34.1%</b></span></div>
      <p class="src">매출은 서울 열린데이터 추정매출 · 비용은 DART 감사보고서(2025년), 한국부동산원(2026년 3분기), 최저임금위원회 기준</p>""",
     "lines": ["66제곱미터 매장 기준, 1년차에 상권 평균 매출인 5억 6천만 원으로 손익분기를 넘깁니다.",
               "3년차에는 매출 6억 6천만 원, 영업이익률 약 9%, 투자금 회수는 약 4년입니다.",
               "비용 가정은 성심당과 아티제의 실제 공시와 대조해 맞췄습니다."]},
    {"tag": "제안", "html": """
      <h1>뜨는 곳이 아니라,<br><em>버티는 곳.</em></h1>
      <div class="xl" style="margin-top:40px">둔촌에서 시작하겠습니다.</div>
      <p class="src" style="margin-top:60px">데이터: 서울 열린데이터광장 상권분석서비스 · 2021년 1분기~2026년 2분기 · 1,650개 상권</p>""",
     "lines": ["뜨는 곳이 아니라, 버티는 곳. 둔촌에서 시작하겠습니다."]},
]

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
*{box-sizing:border-box}body{margin:0;width:1920px;height:1080px;background:#F5F0E6;color:#1B1713;font-family:Pretendard,"Malgun Gothic",sans-serif;word-break:keep-all;overflow:hidden}
.top{position:absolute;left:96px;right:96px;top:56px;display:flex;justify-content:space-between;font-size:26px;font-weight:700;color:#6E655B}
.top b{color:#C4501B;letter-spacing:.06em}
.stage{position:absolute;left:96px;right:96px;top:150px;bottom:230px;display:flex;flex-direction:column;justify-content:center}
h1{font-size:112px;line-height:1.14;letter-spacing:-.035em;margin:0 0 36px;font-weight:800}
h2{font-size:76px;line-height:1.18;letter-spacing:-.03em;margin:0 0 44px;font-weight:800}
em{font-style:normal;color:#C4501B}
.row{display:flex;align-items:center;gap:22px;margin-bottom:30px}.pill{background:#C4501B;color:#fff;font-size:30px;font-weight:800;padding:10px 24px;border-radius:99px}
.xl{font-size:64px;font-weight:800;letter-spacing:-.02em}
.kp{display:grid;grid-template-columns:repeat(3,1fr);border:3px solid #1B1713;border-radius:24px;background:#FFFDF8;margin-bottom:26px;overflow:hidden}
.kp div{padding:30px 36px;border-right:2px solid #E2D9CA}.kp div:last-child{border:0}
.kp b{display:block;font-size:72px;font-weight:800;letter-spacing:-.03em;line-height:1.1}.kp span{font-size:28px;color:#6E655B}
.duo{display:grid;grid-template-columns:1fr 1fr;gap:26px}.duo div{border-radius:24px;padding:30px 40px}.duo b{display:block;font-size:84px;font-weight:800;letter-spacing:-.03em}
.duo span{font-size:30px}.neg{background:#E9E2D5;color:#6E655B}.pos{background:#C4501B;color:#fff}
.bt{display:grid;grid-template-columns:repeat(3,1fr);gap:26px;margin-bottom:28px}.col{background:#FFFDF8;border:2px solid #E2D9CA;border-radius:24px;padding:30px 36px}
.col small{font-size:28px;font-weight:700;color:#6E655B;display:block}.col b{font-size:104px;font-weight:800;letter-spacing:-.03em;display:block;line-height:1.15}
.col span{font-size:25px;color:#6E655B}.bad{color:#6E655B}.ok{color:#C4501B}
.rank{display:flex;gap:16px;flex-wrap:wrap}.rank span{font-size:32px;background:#E9E2D5;border-radius:99px;padding:12px 26px}.rank .hi{background:#C4501B;color:#fff}
.chain{display:grid;grid-template-columns:1fr 70px 1.15fr;align-items:center;margin-bottom:20px}.chain>div{background:#FFFDF8;border:2px solid #E2D9CA;border-radius:22px;padding:20px 32px}
.chain i{font-style:normal;font-size:50px;color:#C4501B;text-align:center}.chain small{font-size:22px;color:#C4501B;font-weight:800;display:block}
.chain b{font-size:46px;font-weight:800;letter-spacing:-.02em;display:block;line-height:1.2}.chain span{font-size:24px;color:#6E655B}
.src{font-size:22px;color:#8a8074;margin:8px 0 0}
.sub{position:absolute;left:0;right:0;bottom:0;height:200px;background:#1B1713;color:#F5F0E6;display:flex;align-items:center;justify-content:center;text-align:center;padding:0 150px;font-size:40px;font-weight:600;line-height:1.4}
.prog{position:absolute;left:0;bottom:200px;height:8px;background:#C4501B}
[data-s]{visibility:hidden}
</style></head><body>
<div class="top"><span><b id="tag"></b></span><span>베이커리 신규 출점 전략 · 서울 열린데이터 22개 분기</span></div>
<div class="stage" id="stage"></div><div class="prog" id="prog"></div><div class="sub" id="sub"></div>
<script>
function show(html,tag,step,sub,p){document.getElementById('stage').innerHTML=html;document.getElementById('tag').textContent=tag;
document.querySelectorAll('[data-s]').forEach(e=>{e.style.visibility=(+e.dataset.s<=step)?'visible':'hidden'});
document.getElementById('sub').textContent=sub;document.getElementById('prog').style.width=(p*100)+'%'}
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
            pg.evaluate("([h,t,s,u,p])=>show(h,t,s,u,p)", [SCENES[si]["html"], SCENES[si]["tag"], step, line, acc / total])
            pg.wait_for_timeout(120)
            pg.screenshot(path=os.path.join(TMP, f"f{i:02d}.png"))
        b.close()

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
    import shutil
    shutil.copy(os.path.join(TMP, "f01.png"), os.path.join(OUT, "poster.png"))
    print(f"완성: {out} · {dur(out):.1f}초 · {os.path.getsize(out) / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
