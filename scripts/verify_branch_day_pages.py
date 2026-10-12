"""v3.96.5 insider radar 5: day-level check of the per-stock branch page with a date range (owner 2026-10-12:
「要」 - 30 requests). The insider branch work reads Fubon's per-stock page over a MONTH range; this checks the
same page over ONE day against our nightly crawl of the tracked branches for that day (each nightly crawl is
audited against date-pinned Fubon branch pages). Sample: 30 random (stock, day) of 2026-05..08 where a tracked
branch traded a stock with an insider event. Every tracked branch on both lists must show the same net lots.
Pages go to data/insider_branch_raw/_day/ (not in git). Polite: one thread, >= 5 s, stop at 403 / 429 / 5xx.
    python scripts/verify_branch_day_pages.py [--n 30]
Prints totals only (branch data is private); exit 1 on any difference.
"""
import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from src.core.fubon_codec import decode_fubon  # noqa: E402
from src.core.fubon_pacing import FUBON_MIN_GAP_S, note_request  # noqa: E402
from src.exports.transfer_watch import read_day  # noqa: E402
from src.fetchers import stock_branch_ranking as S  # noqa: E402

URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a={code}&e={y}-{m}-{d}&f={y}-{m}-{d}"
OUT = ROOT / "data" / "insider_branch_raw" / "_day"
GAP_S, SEED = max(5.0, FUBON_MIN_GAP_S), 20261012


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    a = ap.parse_args()
    pw = os.environ["CHIP_RADAR_PASSWORD"]
    OUT.mkdir(parents=True, exist_ok=True)
    stocks = {k.split("_")[0] for k in json.loads((ROOT / "data" / "insider_branch_links.json").read_text(encoding="utf-8"))}
    days = sorted({p.name[:8] for p in (ROOT / "data").glob("2026????.json")} |
                  {p.name[:8] for p in (ROOT / "data" / "archive").glob("2026????.json*")})
    nightly, pool = {}, []
    for day in [d for d in days if "20260501" <= d <= "20260831"]:
        d = read_day(ROOT / "data", day, pw) or {}
        for b in d.get("branches") or []:
            if b.get("error"):
                continue
            for side in ("buys", "sells"):
                for x in b.get(side) or []:
                    if isinstance(x, dict) and x.get("code") in stocks:
                        nightly[(day, x["code"], b["code"])] = int(x.get("net_lot") or 0)
                        pool.append((day, x["code"]))
    pick = random.Random(SEED).sample(sorted(set(pool)), min(a.n, len(set(pool))))
    s, last, n, cmp, diff = S._get_session(), 0.0, 0, 0, []
    for day, code in pick:
        f = OUT / f"{code}_{day}.html"
        if not f.exists():
            wait = GAP_S - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            n += 1
            note_request()
            try:
                r = s.get(URL.format(code=code, y=int(day[:4]), m=int(day[4:6]), d=int(day[6:])), timeout=20)
            except requests.RequestException as x:
                print(f"[day-check] stopped: {type(x).__name__} at {code} {day}", flush=True)
                break
            last = time.monotonic()
            if r.status_code in (403, 429) or r.status_code >= 500:
                print(f"[day-check] stopped: HTTP {r.status_code} at {code} {day}", flush=True)
                break
            t = decode_fubon(r.content)
            if f"{int(day[:4])}/{int(day[4:6])}/{int(day[6:])}" not in t:
                print(f"[day-check] stopped: {code} {day} page does not show the date", flush=True)
                break
            f.write_text(t, encoding="utf-8")
        p = S.parse_fubon_stock_page(f.read_text(encoding="utf-8"), code) or {}
        for r in (p.get("buys") or []) + (p.get("sells") or []):
            k = (day, code, r.get("bno"))
            if k in nightly:
                cmp += 1
                if nightly[k] != int(r.get("net") or 0):
                    diff.append(k)
    print(f"[day-check] sample {len(pick)} stock-days, requests {n}, tracked-branch rows compared {cmp}, "
          f"equal {cmp - len(diff)}, different {len(diff)}")
    return 1 if diff or not cmp else 0


if __name__ == "__main__":
    sys.exit(main())
