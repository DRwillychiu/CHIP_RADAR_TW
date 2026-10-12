"""v3.96.0 insider radar: the holdings identity over every saved per-person page (verification gate 1).
For each official row (common shares): last month's actual holding + this month's own increases
(集中 + 其它原因 + 私募) - own decreases (same three) = this month's actual holding. A row that does not
add up means the page or the column reading is wrong. Offline: reads data/insider_q61_raw only.
    python scripts/check_insider_identity.py [--since YYYYMM] [--until YYYYMM]
Exit 1 when any row does not add up (the rows are listed).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.fetchers import insider_monthly as M  # noqa: E402


def check_page(t):
    """-> (rows checked, [(role, name, prev, inc3, dec3, end)] that do not add up)."""
    n, bad = 0, []
    for c in M._cells(t):
        if len(c) != 7 or not c[0] or c[0] == "身份別" or "普通股" not in c[2]:
            continue
        prev, inc, dec, end = M._nums(c[3]), M._nums(c[4]), M._nums(c[5]), M._nums(c[6])
        if len(prev) < 2 or len(inc) < 3 or len(dec) < 3 or not end:   # the parser needs the same columns
            continue
        n += 1
        if prev[1] + sum(inc[:3]) - sum(dec[:3]) != end[0]:
            bad.append((c[0], c[1], prev[1], inc[:3], dec[:3], end[0]))
    return n, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="000000")
    ap.add_argument("--until", default="999999")
    ap.add_argument("--raw", default=str(ROOT / "data" / "insider_q61_raw"))
    a = ap.parse_args()
    pages = rows = 0
    bad = []
    for f in sorted(Path(a.raw).glob("*_*.html")):
        code, ym = f.stem.rsplit("_", 1)
        if code.startswith("T56") or not (a.since <= ym <= a.until):
            continue
        n, b = check_page(f.read_bytes().decode("utf-8", errors="replace"))   # same reading as build_insider_people
        pages += 1
        rows += n
        bad += [(code, ym) + x for x in b]
    print(f"[identity] {a.since}-{a.until}: pages {pages}, rows {rows}, add up {rows - len(bad)}/{rows}")
    for x in bad[:50]:
        print("   does not add up:", x)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
