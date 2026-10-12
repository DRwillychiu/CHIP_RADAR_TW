"""v3.96.0 insider radar: monthly independent check (owner 2026-10-11: each new month, 5 company-months
go to the independent program; the owner steps in only when it disagrees).

tools/independent/cleanroom_q61.py was written from scratch by a separate agent that never saw
src/fetchers/insider_monthly.py (2026-10-11: 15 pages, 27/27 rows equal). Keep it frozen: never
edit it together with our parser, or it stops being independent.
This script draws n random pages of one month that have market trades, runs both parsers on the
same raw pages and compares market buy / market sell / month-end holdings row by row.
    python scripts/verify_insider_monthly.py --ym 202608 [--n 5]
Exit 0 = all equal; 1 = a difference (written to docs/verify/INSIDER_AUTO_<ym>.md).
"""
import argparse
import csv
import random
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.fetchers import insider_monthly as M  # noqa: E402

RAW = ROOT / "data" / "insider_q61_raw"
CLEAN = ROOT / "tools" / "independent" / "cleanroom_q61.py"


def ours(path, code, ym):
    rs = M.parse_query6_1(path.read_bytes().decode("utf-8", errors="replace"), code, ym)
    return [(code, ym, r["market_buy"], r["market_sell"], r["end_shares"]) for r in rs if r["market_buy"] or r["market_sell"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ym", help="the month to sample (or --all)")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--all", action="store_true", help="every saved page of every month (2026-10-12: 2,028 pages, 0 differences)")
    a = ap.parse_args()
    if not a.all and not a.ym:
        ap.error("--ym or --all")
    pages = []
    for f in sorted(RAW.glob("*_*.html" if a.all else f"*_{a.ym}.html")):
        code, ym = f.stem.rsplit("_", 1)
        if not code.startswith("T56") and ours(f, code, ym):
            pages.append((f, code, ym))
    pick = pages if a.all else random.Random(int(a.ym)).sample(pages, min(a.n, len(pages)))
    a.ym = a.ym or "ALL"
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(CLEAN, Path(tmp) / "cleanroom.py")
        for f, _, _ in pick:
            shutil.copy(f, Path(tmp) / f.name)
        subprocess.run([sys.executable, "-X", "utf8", "-I", "cleanroom.py"], cwd=tmp, check=True, capture_output=True)
        theirs = [(r[0], r[1], int(r[4]), int(r[5]), int(r[6])) for r in csv.reader(open(Path(tmp) / "cleanroom.csv", encoding="utf-8")) if r]
    mine = [x for f, code, ym in pick for x in ours(f, code, ym)]
    A, B = Counter(mine), Counter(theirs)
    ok = A == B
    lines = [f"# 大股東雷達 每月獨立核對 {a.ym}（{time.strftime('%Y-%m-%d %H:%M')}）", "",
             (f"- 全部 {len(pick)} 頁" if a.all else f"- 抽樣 {len(pick)} 頁（種子 {a.ym}）：{', '.join(c for _, c, _ in pick)}"),
             f"- 我們 {len(mine)} 列、獨立程式 {len(theirs)} 列：{'全部一致' if ok else '有差異，需負責人裁決'}"]
    for k in A - B:
        lines.append(f"  - 只有我們：{k}")
    for k in B - A:
        lines.append(f"  - 只有獨立程式：{k}")
    out = ROOT / "docs" / "verify" / f"INSIDER_AUTO_{a.ym}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
