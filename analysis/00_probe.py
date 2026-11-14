# -*- coding: utf-8 -*-
"""상권분석서비스 데이터셋별 전체 건수·컬럼·분기 필터 지원 여부를 확인한다."""
import sys

from seoul_api import fetch

sys.stdout.reconfigure(encoding="utf-8")

SERVICES = [
    ("VwsmTrdarSelngQq", "추정매출-상권"),
    ("VwsmTrdarStorQq", "점포-상권"),
    ("VwsmTrdarFlpopQq", "길단위인구-상권"),
    ("VwsmTrdarRepopQq", "상주인구-상권"),
    ("VwsmTrdarWrcPopltnQq", "직장인구-상권"),
    ("VwsmTrdarIxQq", "상권변화지표-상권"),
    ("VwsmTrdarAptQq", "아파트-상권"),
    ("VwsmTrdarFcltyQq", "집객시설-상권"),
    ("trdarNcmCnsmp", "소득소비-상권"),
    ("TbgisTrdarRelm", "영역-상권"),
    ("VwsmTrdhlSelngQq", "추정매출-상권배후지"),
    ("VwsmTrdhlRepopQq", "상주인구-상권배후지"),
    ("VwsmTrdhlAptQq", "아파트-상권배후지"),
    ("VwsmTrdhlNcmCnsmpQq", "소득소비-상권배후지"),
]

for svc, name in SERVICES:
    try:
        rows, total = fetch(svc, 1, 1)
    except Exception as e:  # noqa: BLE001
        print(f"[X] {svc} ({name}): {e}")
        continue
    cols = list(rows[0].keys()) if rows else []
    print(f"\n== {svc} ({name}) total={total:,} cols={len(cols)}")
    print("   ", ", ".join(cols[:14]), "..." if len(cols) > 14 else "")
    if rows and "STDR_YYQU_CD" in rows[0]:
        seen = {}
        for q in ("20191", "20211", "20231", "20244", "20251", "20252", "20253", "20254", "20261", "20262", "20263"):
            try:
                _, t = fetch(svc, 1, 1, q)
            except Exception as e:  # noqa: BLE001
                t = f"ERR {e}"
            seen[q] = t
        print("    분기별 건수:", seen)
