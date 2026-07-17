"""Concurrent HTTP helpers for the acquirers — bounded parallelism + adaptive 429/5xx backoff.

The acquisition bottleneck is server-side latency (e.g. EPA AQS ~22 s/request), not bandwidth, so requests are
I/O-bound and parallelize well. `fetch_many` fires a bounded pool of concurrent requests; `get_json`/`get_bytes`
retry with exponential backoff on 429 (rate limit) and 5xx. No fixed politeness sleeps — backoff only when the
server pushes back.
"""
from __future__ import annotations

import concurrent.futures
import json
import time
import urllib.error
import urllib.request
from typing import Callable, Iterable

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0"


def _open(url: str, headers: dict | None, timeout: int, retries: int, backoff: float) -> bytes:
    h = {"User-Agent": UA, **(headers or {})}
    last = None
    for a in range(retries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout).read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and a < retries - 1:
                time.sleep(backoff * (2 ** a)); continue
            raise
        except Exception as e:                       # connection reset / timeout -> retry
            last = e
            if a < retries - 1:
                time.sleep(backoff * (2 ** a)); continue
            raise
    raise last if last else RuntimeError("request failed")


def get_json(url: str, headers: dict | None = None, timeout: int = 90, retries: int = 7,
             backoff: float = 1.5) -> dict:
    return json.loads(_open(url, headers, timeout, retries, backoff).decode("utf-8", "ignore"))


def get_bytes(url: str, headers: dict | None = None, timeout: int = 120, retries: int = 5,
              backoff: float = 2.0) -> bytes:
    return _open(url, headers, timeout, retries, backoff)


def fetch_many(items: Iterable, worker: Callable, max_workers: int = 10) -> list[tuple]:
    """Run worker(item) concurrently; returns [(item, result_or_None)]. Exceptions -> None (logged by caller)."""
    items = list(items)
    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(worker, it): it for it in items}
        for f in concurrent.futures.as_completed(futs):
            try:
                out.append((futs[f], f.result()))
            except Exception:
                out.append((futs[f], None))
    return out
