"""v3.96.0 insider radar: the year-2 test of the hypotheses seen in year 1 (spec section 9).
Written down 2026-10-11 BEFORE the year-2 pages exist (owner: 「要」), so year 2 is a true holdout:
  H1 董事長買  - group A buys whose biggest buyer is the chairman
  H2 大型股    - group A buys in companies worth >= 500 億 (issued shares x month average close)
Only signals of the months 2024-10..2025-08 count (year 1 found the hypotheses; it must not test them).
Pass, each hypothesis on its own: n >= 15 with a 20-day result; 20-day result after costs (0.585 %)
mean > 0; hit rate >= 55 %; 比大盤 mean > 0. Same rules as year 1 apart from n (a subgroup is smaller).
    python scripts/test_hypothesis_y2.py
Output: data/research/hypothesis_y2.json (data/research/ is not in git).
"""
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "research"
Y2 = ("202410", "202508")
N_MIN, HIT_MIN, CAP_YI = 15, 55.0, 500


def summ(rows):
    v = [r["n20"] for r in rows if r.get("n20") is not None]
    e = [r["ex20"] for r in rows if r.get("ex20") is not None]
    return {"signals": len(rows), "n": len(v), "mean_after_cost": round(statistics.mean(v), 2) if v else None,
            "hit": round(sum(x > 0 for x in v) / len(v) * 100, 1) if v else None,
            "vs_index": round(statistics.mean(e), 2) if e else None}


def verdict(s):
    return bool(s["n"] >= N_MIN and (s["mean_after_cost"] or 0) > 0 and (s["hit"] or 0) >= HIT_MIN and (s["vs_index"] or 0) > 0)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    out_json = OUT / "insider_radar_y2.json"      # a separate folder: the web page's files are not touched
    subprocess.run([sys.executable, str(ROOT / "scripts" / "run_insider_radar.py"), "--since", Y2[0], "--out", str(out_json)],
                   check=True, capture_output=True)
    doc = json.loads(out_json.read_text(encoding="utf-8"))
    issued = {}
    for f in sorted((ROOT / "data" / "insider_monthly").glob("*.json")):
        for c, r in json.loads(f.read_text(encoding="utf-8"))["companies"].items():
            issued[(c, f.stem)] = r["issued"]
    a = [s for s in doc["signals"]["A"] if Y2[0] <= s["ym"] <= Y2[1]]
    h1 = [s for s in a if s.get("role_group") == "董事長"]
    h2 = [s for s in a if (issued.get((s["code"], s["ym"])) or 0) * (s.get("avg_price") or 0) / 1e8 >= CAP_YI]
    res = {"window": Y2, "all_A": summ(a), "H1_董事長買": summ(h1), "H2_大型股": summ(h2)}
    for k in ("H1_董事長買", "H2_大型股"):
        res[k]["pass"] = verdict(res[k])
    (OUT / "hypothesis_y2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in res.items():
        print(k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
