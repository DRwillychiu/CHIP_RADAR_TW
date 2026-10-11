"""v3.96.0 insider radar 2.1: parse the cached per-person pages (data/insider_q61_raw, see
scripts/fetch_insider_people.py) into data/insider_people/YYYYMM.json, and cross-check them with
the official >= 1M-share transfer table (IRB140): every IRB140 person must show the same decrease.
    python scripts/build_insider_people.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.fetchers import insider_monthly as M  # noqa: E402


def main():
    raw = ROOT / "data" / "insider_q61_raw"
    out = ROOT / "data" / "insider_people"
    out.mkdir(parents=True, exist_ok=True)
    queue = json.loads((ROOT / "data" / "insider_people_queue.json").read_text(encoding="utf-8"))
    prio = {(ym, code): p for p, ym, code in queue}
    months = defaultdict(lambda: {"pages": {}, "people": []})
    for f in sorted(raw.glob("*.html")):            # every cached page, also those from older queues
        code, ym = f.stem.split("_")
        p = prio.get((ym, code), 9)                 # 9 = cached earlier, not in the current queue
        recs = M.parse_query6_1(f.read_bytes().decode("utf-8", errors="replace"), code, ym)
        months[ym]["pages"][code] = p
        months[ym]["people"] += [{**r, "control": p == 0} for r in recs]
    checked = matched = 0
    misses = []
    for ym, m in sorted(months.items()):
        (out / f"{ym}.json").write_text(json.dumps({"ym": ym, **m}, ensure_ascii=False, separators=(",", ":")),
                                        encoding="utf-8")
        mf = ROOT / "data" / "insider_monthly" / f"{ym}.json"
        if not mf.exists():
            continue
        for t in json.loads(mf.read_text(encoding="utf-8"))["transfers"]:
            if t["code"] not in m["pages"]:
                continue
            checked += 1
            mine = [r for r in m["people"] if r["code"] == t["code"]]
            if any(r["market_sell"] + r["other_sell"] == t["shares"] for r in mine):
                matched += 1
            else:
                misses.append(f"{t['code']} {ym} {t['role']} {t['name']} {t['shares']}")
    print(f"[people] months {len(months)}, pages {sum(len(m['pages']) for m in months.values())}, "
          f"people {sum(len(m['people']) for m in months.values())}")
    print(f"[people] IRB140 cross-check: {matched}/{checked} transfers found with the same decrease")
    for x in misses[:15]:
        print("   miss", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
