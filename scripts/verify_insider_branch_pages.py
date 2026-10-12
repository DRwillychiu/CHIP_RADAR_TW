"""v3.96.5 insider radar 5: are the per-stock monthly branch pages right? (owner 2026-10-12: 「我必須要確保
第一年做的事情是正確且有意義」). Two independent sources of the same number:
  A - the Fubon per-stock page over a month range (data/insider_branch_raw/{code}_{ym}.html, top 15 each side)
  B - our nightly crawls of the tracked branches (stored day files), summed over the same month
B only sees a stock on days it is in the branch's daily top list (missing days can be of either sign), so only
pairs present on EVERY stored trading day of the month are compared (2026-10-12: 15 of 3,393 pairs; most within
1 %, a few 5-15 %, rounded daily lots add up). Exit 1 when a fully seen pair differs by more than 20 %.
Only full months after the daily data start (2026-04-21). Offline; prints totals only (branch data is private).
    python scripts/verify_insider_branch_pages.py
"""
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.exports.transfer_watch import read_day  # noqa: E402
from src.fetchers import stock_branch_ranking as S  # noqa: E402

RAW = ROOT / "data" / "insider_branch_raw"
MONTHS = ("202605", "202606", "202607", "202608")


def main():
    pw = os.environ["CHIP_RADAR_PASSWORD"]
    days = sorted({p.name[:8] for p in (ROOT / "data").glob("2026????.json")} |
                  {p.name[:8] for p in (ROOT / "data" / "archive").glob("2026????.json*")})
    tot, cmp, big, gaps = 0, 0, [], []
    for ym in MONTHS:
        mdays = [d for d in days if d[:6] == ym]
        daily, seen, tracked = defaultdict(int), defaultdict(int), set()
        for day in mdays:
            d = read_day(ROOT / "data", day, pw) or {}
            for b in d.get("branches") or []:
                if b.get("error") or not b.get("code"):
                    continue
                tracked.add(b["code"])
                for side in ("buys", "sells"):
                    for x in b.get(side) or []:
                        if isinstance(x, dict) and x.get("code"):
                            daily[(b["code"], x["code"])] += int(x.get("net_lot") or 0)
                            seen[(b["code"], x["code"])] += 1
        for f in sorted(RAW.glob(f"*_{ym}.html")):
            code = f.stem.rsplit("_", 1)[0]
            p = S.parse_fubon_stock_page(f.read_text(encoding="utf-8"), code) or {}
            for side in ("buys", "sells"):
                for r in p.get(side) or []:
                    if r.get("bno") not in tracked:
                        continue
                    tot += 1
                    if seen.get((r["bno"], code), 0) != len(mdays) or not r.get("net"):
                        continue
                    cmp += 1
                    g = abs(daily[(r["bno"], code)] - r["net"]) / abs(r["net"]) * 100
                    gaps.append(g)
                    if g > 20:
                        big.append((ym, code, r["bno"]))
    gaps.sort()
    print(f"[branch-check] {MONTHS[0]}-{MONTHS[-1]}: tracked-branch pairs {tot}, seen every day {cmp}, "
          f"gap median {gaps[len(gaps) // 2] if gaps else 0:.1f} %, within 1 % {sum(g <= 1 for g in gaps)}, "
          f"within 5 % {sum(g <= 5 for g in gaps)}, over 20 % {len(big)}")
    return 1 if big else 0


if __name__ == "__main__":
    sys.exit(main())
