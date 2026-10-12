"""v3.96.0 insider radar 5.3b level 2: is a candidate branch really the insiders' branch? (spec 9)
Owner 2026-10-11: 「要進行時間性的比對才對吧?」. Pass rule written down BEFORE the run:
  - concentration: of the branch's absolute monthly net over the 12 months 2025-09..2026-08, >= 70 %
    falls in the months the insiders traded (a month off the top-15 list counts as 0);
  - direction: in every insider month where the branch shows up, it is on the insiders' side;
  - it carried 50-150 % of the insiders' net in >= 2 months (the candidate list from 5.3).
Reads data/insider_branch_stats.json (candidates), data/insider_branch_raw/ (all 12 months of those
stocks, scripts/fetch_insider_branches.py --candidates) and data/insider_people (insider months).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.backfill_prices import months  # noqa: E402
from src.fetchers import stock_branch_ranking as S  # noqa: E402

RAW = ROOT / "data" / "insider_branch_raw"
CONC, WINDOW = 0.70, ("202509", "202608")


def main():
    stats = json.loads((ROOT / "data" / "insider_branch_stats.json").read_text(encoding="utf-8"))
    ins = {}
    for f in sorted((ROOT / "data" / "insider_people").glob("*.json")):
        m = json.loads(f.read_text(encoding="utf-8"))
        for r in m["people"]:
            k = (r["code"], m["ym"])
            ins[k] = ins.get(k, 0) + r["market_buy"] - r["market_sell"]
    out = []
    for c in stats["repeat_branches"]:
        series, missing = {}, []
        for ym in months(*WINDOW):
            f = RAW / f"{c['code']}_{ym}.html"
            if not f.exists():
                missing.append(ym)
                continue
            p = S.parse_fubon_stock_page(f.read_text(encoding="utf-8"), c["code"]) or {"buys": [], "sells": []}
            series[ym] = sum(b["net"] for b in p["buys"] + p["sells"] if b["bno"] == c["bno"])
        side = 1 if c["side"] == "買" else -1
        imonths = {ym for ym in series if ins.get((c["code"], ym), 0) * side > 0}
        total = sum(abs(v) for v in series.values())
        conc = sum(abs(series[ym]) for ym in imonths) / total if total else 0
        agree = all(series[ym] * side >= 0 for ym in imonths)
        ok = not missing and conc >= CONC and agree and len(c["months"]) >= 2
        out.append({**c, "insider_months": sorted(imonths), "series": series, "missing": missing,
                    "concentration": round(conc, 2), "same_direction": agree, "pass": ok})
    (ROOT / "data" / "insider_branch_timing.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"candidates {len(out)}, pass {sum(x['pass'] for x in out)}")
    # 2026-10-12 owner: 「確保第一年做的事情是正確且有意義」. Placebo: on the same stocks, the other branches that were
    # on the insiders' side of the top 15 in >= 2 insider months but did NOT carry 50-150 % of the insiders' net.
    # Same rule. If they pass as often, "matching the insiders' size" adds nothing and a pass means nothing.
    cand = {(c["code"], c["bno"]) for c in stats["repeat_branches"]}
    pl, pl_rows = [], []
    for code in sorted({c["code"] for c in stats["repeat_branches"]}):
        pages = {}
        for ym in months(*WINDOW):
            f = RAW / f"{code}_{ym}.html"
            pages[ym] = (S.parse_fubon_stock_page(f.read_text(encoding="utf-8"), code) or {"buys": [], "sells": []}) if f.exists() else None
        for side_name, side in (("買", 1), ("賣", -1)):
            imonths = {ym for ym in pages if pages[ym] is not None and ins.get((code, ym), 0) * side > 0}
            seen = {}
            for ym in imonths:
                for b in pages[ym]["buys" if side > 0 else "sells"]:
                    if (code, b["bno"]) not in cand:
                        seen.setdefault(b["bno"], set()).add(ym)
            for bno, yms in seen.items():
                if len(yms) < 2:
                    continue
                series = {ym: sum(b["net"] for b in p["buys"] + p["sells"] if b["bno"] == bno) for ym, p in pages.items() if p is not None}
                total = sum(abs(v) for v in series.values())
                conc = sum(abs(series[ym]) for ym in imonths) / total if total else 0
                agree = all(series[ym] * side >= 0 for ym in imonths)
                pl.append(not any(p is None for p in pages.values()) and conc >= CONC and agree)
                pl_rows.append({"code": code, "bno": bno, "side": side_name, "concentration": round(conc, 3), "same_direction": agree,
                                "complete": not any(p is None for p in pages.values()), "insider_months": len(imonths)})
    (ROOT / "data" / "insider_branch_placebo.json").write_text(json.dumps(pl_rows, ensure_ascii=False), encoding="utf-8")
    rate_c = sum(x["pass"] for x in out) / len(out) * 100 if out else 0
    rate_p = sum(pl) / len(pl) * 100 if pl else 0
    print(f"placebo (same stocks, big same-side branches that did not match the insiders' size): {len(pl)}, "
          f"pass {sum(pl)} ({rate_p:.1f} %) vs candidates {rate_c:.1f} %")
    for x in out:
        lots = " ".join(f"{ym[2:]}:{x['series'].get(ym, '-')}" for ym in months(*WINDOW))
        print(f"  {'PASS' if x['pass'] else 'fail'} {x['code']} {x['name']} {x['side']} conc {x['concentration']:.0%} "
              f"dir {'ok' if x['same_direction'] else 'X'} insider months {len(x['insider_months'])} | {lots}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
