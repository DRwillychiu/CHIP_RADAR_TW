"""v3.96.0 insider radar 1.1 / 1.5: fetch the monthly insider tables (IRB110 + IRB140, listed and
OTC) for a range of months into data/insider_monthly/YYYYMM.json. A month is kept only when both
markets are published; a finished month is never fetched again (resume after a stop).

Polite: one thread, >= 5 s between requests, stop at the first 403 / 429 / 5xx, --max-requests cap.
    python scripts/fetch_insider_monthly.py --start 202410 --end 202609
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from src.fetchers import insider_monthly as M  # noqa: E402
from scripts.backfill_prices import months  # noqa: E402

GAP_S = 5.0
HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://mopsov.twse.com.tw/mops/web/index"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default=str(ROOT / "data" / "insider_monthly"))
    ap.add_argument("--max-requests", type=int, default=50)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n, last = 0, 0.0
    for ym in months(a.start, a.end):
        path = out / f"{ym}.json"
        if path.exists():
            continue
        month = {"ym": ym, "published": {}, "companies": {}, "transfers": []}
        for mkt in ("sii", "otc"):
            for table, parse in (("IRB110", M.parse_irb110), ("IRB140", M.parse_irb140)):
                if n >= a.max_requests:
                    print(f"[insider] max requests {a.max_requests} reached; rerun resumes")
                    return 1
                wait = GAP_S - (time.monotonic() - last)
                if wait > 0:
                    time.sleep(wait)
                n += 1
                r = requests.get(M.url(table, mkt, ym), headers=HEAD, timeout=60)
                last = time.monotonic()
                if r.status_code in (403, 429) or r.status_code >= 500:
                    print(f"[insider] stopped: HTTP {r.status_code} {ym} {mkt} {table}")
                    return 1
                got = parse(M.decode(r.content)) if r.status_code == 200 else None
                if got is None:
                    print(f"  {ym} {mkt} {table}: not published (HTTP {r.status_code})")
                    month = None
                    break
                day, rows = got
                if table == "IRB110":
                    month["published"][mkt] = day
                    for code, row in rows.items():
                        month["companies"][code] = {**row, "market": mkt}
                else:
                    month["transfers"] += [{**x, "market": mkt, "published": day} for x in rows]
            if month is None:
                break
        if month is None:
            continue
        path.write_text(json.dumps(month, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  {ym}: {len(month['companies'])} companies, {len(month['transfers'])} transfers >= 1M, "
              f"published {month['published']}, requests so far {n}")
    print(f"[insider] requests {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
