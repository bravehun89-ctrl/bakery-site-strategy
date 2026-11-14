# -*- coding: utf-8 -*-
"""성장 상권 스코어링 + 백테스트.

- 지표는 모두 '기준 분기 T 시점에 알 수 있는 정보'만으로 계산한다 (TTM = 최근 4개 분기).
- 백테스트 A: T=2023년 2분기 → 3년 뒤(2026년 2분기) 실제 제과점 매출 성장률과 비교
- 백테스트 B: T=2024년 2분기 → 2년 뒤(2026년 2분기)
- 현재 점수: T=2026년 2분기 → 2029년 2분기 전망용
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 60); pd.set_option("display.max_rows", 300)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P = pd.read_pickle(os.path.join(ROOT, "data", "panel.pkl"))
QS = sorted(P.q.unique())
QI = {q: i for i, q in enumerate(QS)}
META = P.drop_duplicates("cd").set_index("cd")[["name", "type", "gu", "dong", "x", "y", "area_m2"]]


def wide(col: str) -> pd.DataFrame:
    return P.pivot(index="cd", columns="q", values=col).reindex(columns=QS)


W = {}


def w(col: str) -> pd.DataFrame:
    if col not in W:
        W[col] = wide(col)
    return W[col]


def ttm(col: str, T: str, lag: int = 0, how: str = "sum") -> pd.Series:
    """T에서 lag분기 앞선 시점까지의 최근 4개 분기 합(또는 평균). 4개 분기가 모두 있어야 한다."""
    i = QI[T] - lag
    blk = w(col).iloc[:, i - 3:i + 1]
    ok = blk.notna().sum(axis=1) == 4
    v = blk.sum(axis=1) if how == "sum" else blk.mean(axis=1)
    return v.where(ok)


def growth(col: str, T: str, how: str = "sum") -> pd.Series:
    a, b = ttm(col, T, 0, how), ttm(col, T, 4, how)
    return (a / b - 1).where((b > 0) & (a > 0))


def features(T: str) -> pd.DataFrame:
    f = pd.DataFrame(index=w("bk_THSMON_SELNG_AMT").index)
    bk = ttm("bk_THSMON_SELNG_AMT", T)
    cnt = ttm("bk_THSMON_SELNG_CO", T)
    st = ttm("bk_stores", T, how="mean")
    f["bk_sales"] = bk
    f["bk_stores"] = st
    # ── D. 수요 모멘텀: 사람과 지출이 늘고 있는가 ──
    f["D1_유동인구증가"] = growth("fl_TOT_FLPOP_CO", T, "mean")
    f["D2_상주인구증가"] = growth("rp_TOT_REPOP_CO", T, "mean")
    f["D3_직장인구증가"] = growth("wk_TOT_WRC_POPLTN_CO", T, "mean")
    f["D4_외식매출증가"] = growth("food_amt", T)
    # ── S. 공급 여력: 늘어난 수요를 나눠 가질 경쟁이 적은가 ──
    f["S1_점포당매출"] = bk / st
    f["S2_커피대비베이커리갭"] = -(bk / ttm("cf_amt", T))            # 커피 매출 대비 베이커리 매출이 작을수록 +
    f["S3_유동인구당점포(역)"] = -(st / ttm("fl_TOT_FLPOP_CO", T, how="mean"))
    f["S4_점포증가(역)"] = -(st / ttm("bk_stores", T, 4, "mean") - 1)
    # ── W. 구매력·고객 적합: 객단가를 받쳐 줄 지갑인가 ──
    f["W1_1인당지출"] = ttm("inc_EXPNDTR_TOTAMT", T, how="mean") / ttm("rp_TOT_REPOP_CO", T, how="mean")
    f["W2_객단가"] = bk / cnt
    a50 = ttm("bk_AGRDE_50_SELNG_AMT", T) + ttm("bk_AGRDE_60_ABOVE_SELNG_AMT", T)
    f["W3_5060매출비중"] = a50 / bk
    f["W4_여성매출비중"] = ttm("bk_FML_SELNG_AMT", T) / bk
    # ── R. 지속성: 성장이 꺼지지 않을 구조인가 ──
    q8 = w("bk_THSMON_SELNG_AMT").iloc[:, QI[T] - 7:QI[T] + 1]
    f["R1_매출안정성"] = -(q8.std(axis=1) / q8.mean(axis=1)).where(q8.notna().sum(axis=1) == 8)
    f["R2_외식폐업률(역)"] = -(ttm("food_close", T) / ttm("food_stores", T, how="mean"))
    f["R3_운영점포영업개월"] = ttm("ix_OPR_SALE_MT_AVRG", T, how="mean")
    f["R4_주말매출비중"] = ttm("bk_WKEND_SELNG_AMT", T) / bk
    f["R5_저녁매출비중"] = ttm("bk_TMZON_17_21_SELNG_AMT", T) / bk
    # ── M. 과거 자기 모멘텀 (검증 대상: 추세 추종이 통하는가?) ──
    f["M1_베이커리매출증가"] = growth("bk_THSMON_SELNG_AMT", T)
    f["M2_베이커리건수증가"] = growth("bk_THSMON_SELNG_CO", T)
    f["M3_베이커리매출규모"] = bk
    return f


def universe(f: pd.DataFrame) -> pd.Index:
    """표본 안정성: 최근 4분기 제과점 매출이 모두 있고, 점포 3개 이상·연매출 3억 원 이상."""
    return f.index[(f.bk_sales >= 3e8) & (f.bk_stores >= 3)]


def fwd_growth(T: str, H: str) -> pd.Series:
    a, b = ttm("bk_THSMON_SELNG_AMT", H), ttm("bk_THSMON_SELNG_AMT", T)
    return (a / b - 1).where((a > 0) & (b > 0))


FEATS = [c for c in features(QS[-1]).columns if c[0] in "DSWRM" and c[1].isdigit()]


def ic_table() -> pd.DataFrame:
    rows = {}
    for tag, T, H in (("A_3년(23Q2→26Q2)", "20232", "20262"), ("B_2년(24Q2→26Q2)", "20242", "20262"),
                      ("C_2년(23Q2→25Q2)", "20232", "20252"), ("D_1년(25Q2→26Q2)", "20252", "20262")):
        f = features(T)
        u = universe(f)
        y = fwd_growth(T, H).reindex(u)
        ok = y.notna()
        col = {}
        for c in FEATS:
            x = f.loc[u, c]
            m = ok & x.notna()
            col[c] = x[m].rank().corr(y[m].rank()) if m.sum() > 30 else np.nan
        col["_표본수"] = int(ok.sum())
        col["_중위성장률"] = float(y.median())
        rows[tag] = col
    return pd.DataFrame(rows)


# ── 최종 성장성 점수 ─────────────────────────────────────────────────────────
# 채택 기준: 4개 백테스트 중 3개 이상에서 부호가 같고 평균 IC ≥ 0.03.
# 가중치 = 평균 IC × 부호 일관성(같은 부호 비율) 을 정규화한 뒤 5%p 단위로 반올림.
AXES = {
    "유입 (사람이 느는가)": ["D1_유동인구증가"],
    "고객 (살 사람이 있는가)": ["W3_5060매출비중"],
    "체력 (가게가 버티는가)": ["R2_외식폐업률(역)", "R3_운영점포영업개월"],
    "흐름 (매출이 실제로 느는가)": ["M1_베이커리매출증가", "R1_매출안정성"],
}
WEIGHTS = {"D1_유동인구증가": 15, "W3_5060매출비중": 25, "R2_외식폐업률(역)": 20, "R3_운영점포영업개월": 15,
           "M1_베이커리매출증가": 15, "R1_매출안정성": 10}
BT = [("A", "3년", "20232", "20262"), ("B", "2년", "20242", "20262"), ("C", "2년", "20232", "20252"),
      ("D", "1년", "20252", "20262")]


def pct(f: pd.DataFrame, u: pd.Index, cols) -> pd.DataFrame:
    return (f.loc[u, cols].rank(pct=True) * 100).fillna(50.0)


def score(f: pd.DataFrame, u: pd.Index, weights: dict) -> pd.Series:
    p = pct(f, u, list(weights))
    wsum = sum(weights.values())
    return sum(p[c] * wt for c, wt in weights.items()) / wsum


def final() -> None:
    out: dict = {}
    ic = ic_table()
    ic.to_csv(os.path.join(ROOT, "data", "ic_table.csv"), encoding="utf-8-sig")
    out["ic"] = {c: [None if pd.isna(v) else round(float(v), 3) for v in ic.loc[c]] for c in FEATS}
    out["ic_cols"] = list(ic.columns)
    out["ic_n"] = [int(v) for v in ic.loc["_표본수"]]
    out["ic_median_growth"] = [round(float(v), 4) for v in ic.loc["_중위성장률"]]
    out["weights"] = WEIGHTS
    out["axes"] = AXES

    # 종합 점수의 백테스트 (가중 / 동일가중 / 과거 매출 추세만)
    bt = []
    for tag, hz, T, H in BT:
        f = features(T); u = universe(f)
        y = fwd_growth(T, H).reindex(u)
        ok = y.notna()
        row = {"tag": tag, "horizon": hz, "T": T, "H": H, "n": int(ok.sum())}
        for nm, sc in (("가중", score(f, u, WEIGHTS)), ("동일가중", score(f, u, {k: 1 for k in WEIGHTS})),
                       ("추세만", f.loc[u, "M1_베이커리매출증가"]), ("규모만", f.loc[u, "bk_sales"])):
            m = ok & sc.notna()
            row[f"IC_{nm}"] = round(float(sc[m].rank().corr(y[m].rank())), 3)
            q = pd.qcut(sc[m].rank(method="first"), 5, labels=False)
            g = y[m].groupby(q).median()
            row[f"Q_{nm}"] = [round(float(v), 4) for v in g]
            row[f"hit_{nm}"] = round(float((y[m][q == 4] > y[m].median()).mean()), 3)
        bt.append(row)
        print(tag, hz, T, "→", H, "n=", row["n"], "| IC 가중", row["IC_가중"], "동일", row["IC_동일가중"], "추세만",
              row["IC_추세만"], "| 5분위 중위성장(가중):", row["Q_가중"], "| 추세만:", row["Q_추세만"], "| 상위20% 적중",
              row["hit_가중"])
    out["backtest"] = bt

    # 현재 점수 (T = 최신 분기)
    T = QS[-1]
    f = features(T); u = universe(f)
    p = pct(f, u, list(WEIGHTS))
    sc = score(f, u, WEIGHTS)
    res = META.loc[u].copy()
    res["score"] = sc
    res["rank"] = sc.rank(ascending=False).astype(int)
    for c in WEIGHTS:
        res["p_" + c] = p[c]; res["v_" + c] = f.loc[u, c]
    res["bk_sales"] = f.loc[u, "bk_sales"]; res["bk_stores"] = f.loc[u, "bk_stores"]
    res["sps"] = f.loc[u, "S1_점포당매출"]; res["ticket"] = f.loc[u, "W2_객단가"]
    res["p_sps"] = res.sps.rank(pct=True) * 100
    res["fem"] = f.loc[u, "W4_여성매출비중"]; res["wkend"] = f.loc[u, "R4_주말매출비중"]
    res["even"] = f.loc[u, "R5_저녁매출비중"]
    res["frc_share"] = ttm("bk_frc", T, how="mean").reindex(u) / f.loc[u, "bk_stores"]
    res["fl"] = ttm("fl_TOT_FLPOP_CO", T, how="mean").reindex(u)
    res["rp"] = ttm("rp_TOT_REPOP_CO", T, how="mean").reindex(u)
    res["wk"] = ttm("wk_TOT_WRC_POPLTN_CO", T, how="mean").reindex(u)
    res["g3"] = (ttm("bk_THSMON_SELNG_AMT", T) / ttm("bk_THSMON_SELNG_AMT", T, 12) - 1).reindex(u)
    # 가중치 민감도: 각 가중치를 ±50% 범위에서 2,000회 무작위로 흔들어 Top10 유지 확률
    rng = np.random.default_rng(7)
    cols = list(WEIGHTS); base = np.array([WEIGHTS[c] for c in cols], float)
    P_ = p[cols].to_numpy()
    cnt = np.zeros(len(u))
    for _ in range(2000):
        wv = base * rng.uniform(0.5, 1.5, len(cols))
        s_ = P_ @ wv
        cnt[np.argsort(-s_)[:10]] += 1
    res["top10_prob"] = cnt / 2000
    res = res.sort_values("score", ascending=False)
    res.to_csv(os.path.join(ROOT, "data", "scores.csv"), encoding="utf-8-sig")
    show = ["name", "type", "gu", "dong", "score", "top10_prob", "bk_sales", "bk_stores", "sps", "p_sps", "ticket",
            "g3", "frc_share", "fl", "rp", "wk"] + ["p_" + c for c in WEIGHTS]
    d = res[show].head(30).copy()
    d["bk_sales"] = (d.bk_sales / 1e8).round(1); d["sps"] = (d.sps / 1e8).round(2)
    print("\n== 성장성 점수 Top 30 (T=2026Q2) ==")
    print(d.round(2).to_string())
    print("\n지표 간 스피어만 상관(채택 6개):")
    print(f.loc[u, cols].corr(method="spearman").round(2).to_string())
    out["corr"] = f.loc[u, cols].corr(method="spearman").round(2).values.tolist()
    out["universe_n"] = int(len(u))
    out["scores"] = json.loads(res.reset_index().to_json(orient="records", force_ascii=False, double_precision=4))
    with open(os.path.join(ROOT, "data", "result.json"), "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False)


if __name__ == "__main__":
    final()
