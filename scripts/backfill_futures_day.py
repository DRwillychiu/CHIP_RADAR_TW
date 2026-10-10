"""v3.95.0 backfill one day's futures_data (TAIFEX) into its encrypted day file and the futures
history. Owner 2026-10-10 "這四項，現在立即解決": 20260917's fetch failed (net OI stored as 0,
no P/C), so the 20-day trends and the futures history charts had a hole.

Polite: one thread, >= 5 s between TAIFEX requests, stop at the first 403 / 429 / 5xx, at most
12 requests. Nothing is written unless the new data has a non-zero foreign net OI and an official
P/C ratio. Usage (repo root):
    CHIP_RADAR_PASSWORD=... python scripts/backfill_futures_day.py --date 20260917
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from src.pipelines.crawler_output import encrypt_data, decrypt_data  # noqa: E402

GAP_S = 5.0
MAX_REQUESTS = 12
_state = {"last": 0.0, "count": 0}
_orig_request = requests.sessions.Session.request


def _polite_request(self, method, url, *a, **kw):
    _state["count"] += 1
    if _state["count"] > MAX_REQUESTS:
        raise SystemExit(f"stopped: more than {MAX_REQUESTS} requests")
    wait = GAP_S - (time.monotonic() - _state["last"])
    if wait > 0:
        time.sleep(wait)
    try:
        r = _orig_request(self, method, url, *a, **kw)
    finally:
        _state["last"] = time.monotonic()
    print(f"  [{_state['count']}] {method} {url.split('/')[-1][:40]} -> {r.status_code}")
    if r.status_code in (403, 429) or r.status_code >= 500:
        raise SystemExit(f"stopped: HTTP {r.status_code} from TAIFEX - nothing written")
    return r


def day_path(data_dir: Path, date: str) -> Path:
    for p in (data_dir / f"{date}.json", data_dir / "archive" / f"{date}.json"):
        if p.exists():
            return p
    raise SystemExit(f"no day file for {date} (looked in data/ and data/archive/)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    a = ap.parse_args()
    password = os.environ.get("CHIP_RADAR_PASSWORD")
    if not password:
        raise SystemExit("CHIP_RADAR_PASSWORD not set")
    data_dir = Path(a.data_dir)
    path = day_path(data_dir, a.date)
    env = json.loads(path.read_text(encoding="utf-8"))
    day = json.loads(decrypt_data(env["data"], password))
    old = (day.get("futures_data") or {}).get("summary") or {}
    print(f"[backfill] {a.date} {path.relative_to(ROOT)}: now foreign_eq_net_oi={old.get('foreign_equivalent_net_oi')} "
          f"pc_ratio_oi={old.get('pc_ratio_oi')}")

    requests.sessions.Session.request = _polite_request
    from src.fetchers.futures import fetch_all_futures_data
    new = fetch_all_futures_data(a.date)
    requests.sessions.Session.request = _orig_request

    s = new.get("summary") or {}
    oi, pc, src = s.get("foreign_equivalent_net_oi"), s.get("pc_ratio_oi"), s.get("pcr_source", "")
    print(f"[backfill] fetched: foreign_eq_net_oi={oi} pc_ratio_oi={pc} pcr_source={src!r} requests={_state['count']}")
    if not oi or pc is None or "備援" in str(src):
        raise SystemExit("not written: the fetch is still incomplete (zero net OI, no P/C, or the estimated P/C)")

    day["futures_data"] = new
    env["data"] = encrypt_data(json.dumps(day, ensure_ascii=False), password)
    path.write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[backfill] day file rewritten: {path.relative_to(ROOT)}")

    from src.fetchers.history import update_futures_history
    update_futures_history(data_dir, a.date, new)


if __name__ == "__main__":
    main()
