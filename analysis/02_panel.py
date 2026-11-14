# -*- coding: utf-8 -*-
"""원천 데이터(data/raw) → 상권×분기 패널(data/panel.pkl).

단위: 매출=원/분기, 인구=명(분기 기준), 점포=개, 소득=원/월.
베이커리 = 서비스업종코드 CS100005(제과점), 커피 = CS100010(커피-음료), 외식 = CS1000xx 전체.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data")

BAKERY, COFFEE = "CS100005", "CS100010"
KEY = ["TRDAR_CD", "STDR_YYQU_CD"]


def load(svc: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(RAW, f"{svc}.csv.gz"), dtype={"TRDAR_CD": str, "STDR_YYQU_CD": str,
                                                                 "SVC_INDUTY_CD": str, "ADSTRD_CD": str,
                                                                 "SIGNGU_CD": str})
    return df.drop_duplicates()


def main() -> None:
    # ── 매출 ──────────────────────────────────────────────────────────────
    s = load("VwsmTrdarSelngQq")
    print("매출 행:", len(s), "분기:", s.STDR_YYQU_CD.min(), "~", s.STDR_YYQU_CD.max())
    num = [c for c in s.columns if c.endswith("_AMT") or c.endswith("_CO")]
    bk = s[s.SVC_INDUTY_CD == BAKERY].set_index(KEY)[num].add_prefix("bk_")
    cf = s[s.SVC_INDUTY_CD == COFFEE].set_index(KEY)[["THSMON_SELNG_AMT", "THSMON_SELNG_CO"]]
    cf.columns = ["cf_amt", "cf_cnt"]
    food = s[s.SVC_INDUTY_CD.str.startswith("CS1")].groupby(KEY)[["THSMON_SELNG_AMT", "THSMON_SELNG_CO"]].sum()
    food.columns = ["food_amt", "food_cnt"]
    tot = s.groupby(KEY)[["THSMON_SELNG_AMT"]].sum()
    tot.columns = ["all_amt"]

    # ── 점포 ──────────────────────────────────────────────────────────────
    st = load("VwsmTrdarStorQq")
    cols = ["SIMILR_INDUTY_STOR_CO", "STOR_CO", "FRC_STOR_CO", "OPBIZ_STOR_CO", "CLSBIZ_STOR_CO"]
    bks = st[st.SVC_INDUTY_CD == BAKERY].set_index(KEY)[cols]
    bks.columns = ["bk_stores", "bk_indep", "bk_frc", "bk_open", "bk_close"]
    cfs = st[st.SVC_INDUTY_CD == COFFEE].set_index(KEY)[["SIMILR_INDUTY_STOR_CO"]]
    cfs.columns = ["cf_stores"]
    fds = st[st.SVC_INDUTY_CD.str.startswith("CS1")].groupby(KEY)[
        ["SIMILR_INDUTY_STOR_CO", "OPBIZ_STOR_CO", "CLSBIZ_STOR_CO"]].sum()
    fds.columns = ["food_stores", "food_open", "food_close"]
    als = st.groupby(KEY)[["SIMILR_INDUTY_STOR_CO"]].sum()
    als.columns = ["all_stores"]

    # ── 인구·소득·변화지표 ────────────────────────────────────────────────
    fl = load("VwsmTrdarFlpopQq").set_index(KEY)
    fl = fl[[c for c in fl.columns if c.endswith("_CO")]].add_prefix("fl_")
    rp = load("VwsmTrdarRepopQq").set_index(KEY)
    rp = rp[[c for c in rp.columns if c.endswith("_CO")]].add_prefix("rp_")
    wk = load("VwsmTrdarWrcPopltnQq").set_index(KEY)
    wk = wk[[c for c in wk.columns if c.endswith("_CO")]].add_prefix("wk_")
    inc = load("trdarNcmCnsmp").set_index(KEY)
    inc = inc[[c for c in inc.columns if c.endswith("AMT") or c.endswith("_CD")]].drop(
        columns=["TRDAR_SE_CD"], errors="ignore").add_prefix("inc_")
    ix = load("VwsmTrdarIxQq").set_index(KEY)[
        ["TRDAR_CHNGE_IX", "TRDAR_CHNGE_IX_NM", "OPR_SALE_MT_AVRG", "CLS_SALE_MT_AVRG",
         "SU_OPR_SALE_MT_AVRG", "SU_CLS_SALE_MT_AVRG"]].add_prefix("ix_")

    panel = pd.concat([bk, cf, food, tot, bks, cfs, fds, als, fl, rp, wk, inc, ix], axis=1, join="outer")
    panel = panel.reset_index().rename(columns={"TRDAR_CD": "cd", "STDR_YYQU_CD": "q"})
    panel = panel[(panel.q >= "20211") & (panel.q <= "20262")]

    relm = load("TbgisTrdarRelm").rename(columns={
        "TRDAR_CD": "cd", "TRDAR_CD_NM": "name", "TRDAR_SE_CD_NM": "type", "SIGNGU_CD_NM": "gu",
        "ADSTRD_CD_NM": "dong", "XCNTS_VALUE": "x", "YDNTS_VALUE": "y", "RELM_AR": "area_m2"})
    relm = relm[["cd", "name", "type", "gu", "dong", "x", "y", "area_m2"]]
    panel = panel.merge(relm, on="cd", how="left")

    # 선택 데이터(있으면 붙인다)
    for svc, pre in (("VwsmTrdarFcltyQq", "fc_"), ("VwsmTrdarAptQq", "apt_"), ("VwsmTrdhlAptQq", "hapt_"),
                     ("VwsmTrdhlRepopQq", "hrp_"), ("VwsmTrdhlNcmCnsmpQq", "hinc_")):
        p = os.path.join(RAW, f"{svc}.csv.gz")
        if not os.path.exists(p):
            print("  (없음)", svc)
            continue
        d = load(svc).rename(columns={"TRDAR_CD": "cd", "STDR_YYQU_CD": "q"})
        keep = [c for c in d.columns if c.endswith("_CO") or c.endswith("AMT") or c.endswith("_PRC") or c.endswith("_AR")]
        d = d[["cd", "q"] + keep].drop_duplicates(["cd", "q"])
        d.columns = ["cd", "q"] + [pre + c for c in keep]
        panel = panel.merge(d, on=["cd", "q"], how="left")

    panel = panel.sort_values(["cd", "q"]).reset_index(drop=True)
    panel.to_pickle(os.path.join(OUT, "panel.pkl"))
    print("패널:", panel.shape, "상권:", panel.cd.nunique(), "분기:", sorted(panel.q.unique())[0], "~",
          sorted(panel.q.unique())[-1])
    print("베이커리 매출이 있는 상권(최신 분기):", panel[(panel.q == "20262") & panel.bk_THSMON_SELNG_AMT.notna()].cd.nunique())
    print(panel[panel.q == "20262"][["bk_THSMON_SELNG_AMT", "bk_stores", "fl_TOT_FLPOP_CO", "rp_TOT_REPOP_CO",
                                     "wk_TOT_WRC_POPLTN_CO", "inc_EXPNDTR_TOTAMT"]].describe().T.to_string())


if __name__ == "__main__":
    main()
