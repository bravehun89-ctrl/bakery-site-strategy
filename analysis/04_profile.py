# -*- coding: utf-8 -*-
"""시장 전체 추세 + 추천 상권 프로필 + 유명 상권 순위 → data/site.json (웹페이지·영상이 쓰는 수치의 단일 원천)."""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 60); pd.set_option("display.max_rows", 300)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P = pd.read_pickle(os.path.join(ROOT, "data", "panel.pkl"))
S = pd.read_csv(os.path.join(ROOT, "data", "scores.csv"), dtype={"cd": str}).set_index("cd")
R = json.load(open(os.path.join(ROOT, "data", "result.json"), encoding="utf-8"))
QS = sorted(P.q.unique())
L4, P4 = QS[-4:], QS[-8:-4]
AGE = ["10", "20", "30", "40", "50", "60_ABOVE"]
TZ = ["00_06", "06_11", "11_14", "14_17", "17_21", "21_24"]
DAY = ["MON", "TUES", "WED", "THUR", "FRI", "SAT", "SUN"]


def shares(df: pd.DataFrame) -> dict:
    tot = df.bk_THSMON_SELNG_AMT.sum()
    asum = sum(df[f"bk_AGRDE_{a}_SELNG_AMT"].sum() for a in AGE)
    gsum = df.bk_FML_SELNG_AMT.sum() + df.bk_ML_SELNG_AMT.sum()
    return {
        "age": [round(float(df[f"bk_AGRDE_{a}_SELNG_AMT"].sum() / asum * 100), 1) for a in AGE],
        "tz": [round(float(df[f"bk_TMZON_{t}_SELNG_AMT"].sum() / tot * 100), 1) for t in TZ],
        "day": [round(float(df[f"bk_{d}_SELNG_AMT"].sum() / tot * 100), 1) for d in DAY],
        "female": round(float(df.bk_FML_SELNG_AMT.sum() / gsum * 100), 1),
        "ticket": int(round(tot / df.bk_THSMON_SELNG_CO.sum())),
    }


out: dict = {"quarters": QS}
B = P[P.bk_THSMON_SELNG_AMT.notna()]

# 1) 서울 전체 제과점 추세
g = B.groupby("q").agg(amt=("bk_THSMON_SELNG_AMT", "sum"), cnt=("bk_THSMON_SELNG_CO", "sum"))
out["seoul"] = {"amt_eok": [round(v / 1e8) for v in g.amt], "cnt_man": [round(v / 1e4) for v in g.cnt],
                "ticket": [round(a / c) for a, c in zip(g.amt, g.cnt)]}
B2 = B.assign(yr=B.q.str[:4], qn=B.q.str[4])
h1 = B2[B2.qn.isin(["1", "2"])].groupby("yr")[[f"bk_AGRDE_{a}_SELNG_AMT" for a in AGE]].sum()
out["age_h1_eok"] = {yr: [round(v / 1e8) for v in row] for yr, row in h1.iterrows()}
out["seoul_now"] = shares(B[B.q.isin(L4)])
print("서울 상반기 연령별 매출(억원):"); print((h1 / 1e8).round(0).to_string())
print("서울 현재 구성:", out["seoul_now"])

# 2) 유명 상권의 점수 순위
hot_kw = ["성수동카페거리", "뚝섬", "서울숲", "연남", "홍대", "압구정로데오", "가로수길", "도산", "한남", "이태원", "강남역",
          "명동", "송리단", "잠실", "망원", "익선", "용리단", "신용산", "삼각지", "북촌", "을지로", "여의도", "성수"]
hot = S[S.name.apply(lambda n: any(k in n for k in hot_kw))].sort_values("score", ascending=False)
print("\n유명 상권 순위:"); print(hot[["name", "gu", "score", "rank", "bk_sales", "sps", "g3", "p_W3_5060매출비중",
                                 "p_R2_외식폐업률(역)", "p_M1_베이커리매출증가"]].round(2).to_string())
out["hot"] = [{"name": r["name"], "gu": r.gu, "score": round(r.score, 1), "rank": int(r["rank"]),
               "bk_eok": round(r.bk_sales / 1e8, 1), "g3": None if pd.isna(r.g3) else round(r.g3, 3)}
              for _, r in hot.iterrows()]

# 3) 추천·대안 상권 프로필
PICK = {"둔촌역": "3120245", "마들역": "3120080", "송화벽화시장(송화골목시장)": "3130214"}
out["picks"] = {}
for nm, cd in PICK.items():
    d = P[P.cd == cd].sort_values("q")
    now, prev = d[d.q.isin(L4)], d[d.q.isin(P4)]
    r = S.loc[cd]
    prof = shares(now)
    prof.update({
        "cd": cd, "name": nm, "gu": r.gu, "dong": r.dong, "type": r.type, "score": round(r.score, 1),
        "rank": int(r["rank"]), "top10_prob": round(r.top10_prob, 3),
        "bk_eok": round(now.bk_THSMON_SELNG_AMT.sum() / 1e8, 1), "stores": round(now.bk_stores.mean(), 2),
        "frc": round(now.bk_frc.mean(), 2), "sps_eok": round(r.sps / 1e8, 2), "p_sps": round(r.p_sps, 1),
        "cf_eok": round(now.cf_amt.sum() / 1e8, 1), "cf_stores": round(now.cf_stores.mean(), 1),
        "food_eok": round(now.food_amt.sum() / 1e8, 1),
        "fl": round(now.fl_TOT_FLPOP_CO.mean()), "fl_prev": round(prev.fl_TOT_FLPOP_CO.mean()),
        "rp": round(now.rp_TOT_REPOP_CO.mean()), "wk": round(now.wk_TOT_WRC_POPLTN_CO.mean()),
        "hrp": None if pd.isna(now.hrp_TOT_REPOP_CO.mean()) else round(now.hrp_TOT_REPOP_CO.mean()),
        "hapt": None if pd.isna(now.hapt_APT_HSMP_CO.mean()) else round(now.hapt_APT_HSMP_CO.mean()),
        "q_bk_eok": [None if pd.isna(v) else round(v / 1e8, 2) for v in d.bk_THSMON_SELNG_AMT],
        "q_stores": [None if pd.isna(v) else float(v) for v in d.bk_stores],
        "q_fl": [None if pd.isna(v) else round(v) for v in d.fl_TOT_FLPOP_CO],
        "q_cf_eok": [None if pd.isna(v) else round(v / 1e8, 2) for v in d.cf_amt],
        "ix": list(d.ix_TRDAR_CHNGE_IX_NM.fillna("")),
        "p": {k: round(float(r["p_" + k]), 1) for k in R["weights"]},
        "v": {k: round(float(r["v_" + k]), 4) for k in R["weights"]},
        "fl_age": [round(now[f"fl_AGRDE_{a}_FLPOP_CO"].mean()) for a in AGE],
        "fl_tz": [round(now[f"fl_TMZON_{t}_FLPOP_CO"].mean()) for t in TZ],
        "fl_female": round(now.fl_FML_FLPOP_CO.mean() / now.fl_TOT_FLPOP_CO.mean() * 100, 1),
    })
    out["picks"][nm] = prof
    print(f"\n== {nm} ==")
    for k, v in prof.items():
        print(f"  {k}: {v}")

# 4) 지도용: 유니버스 전체 좌표·점수
out["map"] = [[round(r.x), round(r.y), round(r.score, 1), r["name"], r.gu, round(r.bk_sales / 1e8, 1), int(r["rank"])]
              for _, r in S.iterrows()]
allpts = P.drop_duplicates("cd")[["x", "y"]].dropna()
out["map_bg"] = [[round(a), round(b)] for a, b in zip(allpts.x, allpts.y)]
out.update({k: R[k] for k in ("ic", "ic_cols", "ic_n", "ic_median_growth", "weights", "axes", "backtest", "corr",
                              "universe_n")})
out["top"] = [{"cd": cd, "name": r["name"], "type": r.type, "gu": r.gu, "dong": r.dong, "score": round(r.score, 1),
               "rank": int(r["rank"]), "top10_prob": round(r.top10_prob, 2), "bk_eok": round(r.bk_sales / 1e8, 1),
               "stores": round(r.bk_stores, 1), "sps_eok": round(r.sps / 1e8, 2), "p_sps": round(r.p_sps),
               "p": [round(r["p_" + k]) for k in R["weights"]]}
              for cd, r in S.sort_values("score", ascending=False).head(20).iterrows()]
json.dump(out, open(os.path.join(ROOT, "data", "site.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\nsite.json 저장:", round(os.path.getsize(os.path.join(ROOT, "data", "site.json")) / 1024), "KB")
