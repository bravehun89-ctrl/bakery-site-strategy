# -*- coding: utf-8 -*-
"""서울시 상권분석서비스(열린데이터광장 Open API) 원천 데이터를 일괄 수집해 data/raw/*.csv.gz 로 저장한다.

    python analysis/01_fetch.py            # 전체 수집 (이미 받은 파일은 건너뜀)
    python analysis/01_fetch.py --force    # 다시 받기

수집 범위: 2021년 1분기 ~ 2026년 2분기 (API가 제공하는 전 기간), 서울 전체 상권 1,650곳.
"""
from __future__ import annotations

import csv
import gzip
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from seoul_api import PAGE, fetch

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW = os.path.join(ROOT, "data", "raw")
os.makedirs(RAW, exist_ok=True)

QUARTERS = [f"{y}{q}" for y in range(2021, 2027) for q in range(1, 5)]
QUARTERS = [q for q in QUARTERS if q <= "20262"]

# (서비스명, 한글명, 분기 필터 지원 여부)
SERVICES = [
    ("TbgisTrdarRelm", "영역-상권", False),
    ("VwsmTrdarSelngQq", "추정매출-상권", True),
    ("VwsmTrdarStorQq", "점포-상권", True),
    ("VwsmTrdarFlpopQq", "길단위인구-상권", True),
    ("VwsmTrdarIxQq", "상권변화지표-상권", True),
    ("trdarNcmCnsmp", "소득소비-상권", True),
    ("VwsmTrdarRepopQq", "상주인구-상권", False),
    ("VwsmTrdarWrcPopltnQq", "직장인구-상권", False),
    ("VwsmTrdarFcltyQq", "집객시설-상권", False),
    ("VwsmTrdarAptQq", "아파트-상권", False),
    ("VwsmTrdhlAptQq", "아파트-상권배후지", False),
    ("VwsmTrdhlRepopQq", "상주인구-상권배후지", False),
    ("VwsmTrdhlNcmCnsmpQq", "소득소비-상권배후지", False),
]


def pages(total: int):
    return [(s, min(s + PAGE - 1, total)) for s in range(1, total + 1, PAGE)]


def collect(svc: str, by_quarter: bool) -> list[dict]:
    jobs = []
    if by_quarter:
        def head(q):
            return q, fetch(svc, 1, 1, q)[1]
        with ThreadPoolExecutor(8) as ex:
            for q, total in ex.map(head, QUARTERS):
                jobs += [(s, e, (q,)) for s, e in pages(total)]
    else:
        total = fetch(svc, 1, 1)[1]
        jobs = [(s, e, ()) for s, e in pages(total)]

    def work(job):
        s, e, params = job
        return fetch(svc, s, e, *params)[0]

    rows: list[dict] = []
    with ThreadPoolExecutor(8) as ex:
        for i, part in enumerate(ex.map(work, jobs), 1):
            rows += part
            if i % 100 == 0:
                print(f"    {svc}: {i}/{len(jobs)} 페이지", flush=True)
    return rows


def main(force: bool) -> None:
    for svc, name, by_q in SERVICES:
        out = os.path.join(RAW, f"{svc}.csv.gz")
        if os.path.exists(out) and not force:
            print(f"[skip] {svc} ({name})")
            continue
        t0 = time.time()
        try:
            rows = collect(svc, by_q)
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {svc} ({name}): {e}")
            continue
        if not rows:
            print(f"[EMPTY] {svc} ({name})")
            continue
        cols = list(rows[0].keys())
        with gzip.open(out, "wt", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"[ok] {svc} ({name}): {len(rows):,}행 · {time.time() - t0:.0f}초", flush=True)


if __name__ == "__main__":
    main("--force" in sys.argv)
