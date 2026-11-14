# -*- coding: utf-8 -*-
"""서울 열린데이터광장 Open API 공용 모듈 (표준 라이브러리만 사용).

인증키는 환경변수 SEOUL_API_KEY 에서만 읽는다. 키는 저장소에 포함하지 않는다.
발급: https://data.seoul.go.kr  (무료)
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://openapi.seoul.go.kr:8088"
PAGE = 1000


_KEY = None


def key() -> str:
    """환경변수 SEOUL_API_KEY → SEOUL_ENV_FILE 이 가리키는 .env → 저장소 루트의 .env 순으로 찾는다."""
    global _KEY
    if _KEY:
        return _KEY
    k = os.environ.get("SEOUL_API_KEY", "").strip()
    if not k:
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.environ.get("SEOUL_ENV_FILE", ""), os.path.join(here, "..", ".env")):
            if not p or not os.path.exists(p):
                continue
            with open(p, encoding="utf-8-sig") as f:
                for line in f:
                    name, _, val = line.strip().partition("=")
                    if name.strip() == "SEOUL_API_KEY" and val.strip():
                        k = val.strip().strip("'\"")
            if k:
                break
    if not k:
        raise SystemExit("SEOUL_API_KEY 가 필요합니다 (data.seoul.go.kr 에서 무료 발급).")
    _KEY = k
    return k


def fetch(service: str, start: int, end: int, *params, retries: int = 4):
    """(rows, total) 반환. 데이터 없음(INFO-200)은 ([], 0)."""
    path = "/".join(urllib.parse.quote(str(p), safe="") for p in (service, start, end, *params))
    url = f"{BASE}/{key()}/json/{path}"
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
            body = data.get(service)
            if isinstance(body, dict):
                return body.get("row") or [], int(body.get("list_total_count") or 0)
            res = data.get("RESULT") or {}
            if res.get("CODE") == "INFO-200":
                return [], 0
            last = RuntimeError(f"{service}: {res.get('CODE')} {res.get('MESSAGE')}")
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
            last = RuntimeError(f"{service}: {type(e).__name__}")
        time.sleep(1.5 * (attempt + 1))
    raise last
