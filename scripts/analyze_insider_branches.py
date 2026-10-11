"""v3.96.0 insider radar 5.2 / 5.3: which branches move with the insiders (spec section 9).

Reads data/insider_branch_links.json (scripts/fetch_insider_branches.py). Per event (an insider
company-month of signal size) on the insiders' side of the book (top 15 buyers for a buy month,
top 15 sellers for a sell month):
  geo      - a branch in the company's district (same_dist) or city (same_city)
  carrier  - a branch whose month net is 50 %-150 % of the insiders' market net: most likely the
             insiders' own broker (2515 2025-10: 統一-仁愛 +105,877 lots vs the holder's 101,683).
             Without the upper bound any big broker in a liquid stock qualifies (first run: 105/123).
  repeat   - the same branch as carrier in >= 2 events of the same stock (being in the top 15 every
             month says little: 1712 had 4 brokers in its top 15 in all 5 insider months)
Baseline: the same share on the other side of the book in the same events (a district / city that
is simply full of branches shows up on both sides; a real link shows up on the insiders' side).
Writes data/insider_branch_stats.json (not in git: built from third-party branch data).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINKS = ROOT / "data" / "insider_branch_links.json"
OUT = ROOT / "data" / "insider_branch_stats.json"
CARRIER, CARRIER_MAX = 0.5, 1.5


def main():
    links = json.loads(LINKS.read_text(encoding="utf-8"))
    rows, seen = [], defaultdict(list)
    for key, e in links.items():
        buy = e["net_shares"] > 0
        mine, other = (e["buys"], e["sells"]) if buy else (e["sells"], e["buys"])
        lots = abs(e["net_shares"]) / 1000
        known = bool(e["home"].get("city"))
        carrier = [b for b in mine if lots and CARRIER * lots <= abs(b["net"]) <= CARRIER_MAX * lots]
        rows.append({"key": key, "code": e["code"], "ym": e["ym"], "side": "買" if buy else "賣", "known": known,
                     "dist_mine": any(b["same_dist"] for b in mine), "dist_other": any(b["same_dist"] for b in other),
                     "city_mine": any(b["same_city"] for b in mine), "city_other": any(b["same_city"] for b in other),
                     "carrier": [{"bno": b["bno"], "name": b["name"], "net": b["net"], "same_city": b["same_city"],
                                  "same_dist": b["same_dist"], "cover": round(abs(b["net"]) / lots, 2)} for b in carrier],
                     "top": mine[0]["name"] if mine else None})
        for b in carrier:
            seen[(e["code"], b["bno"], b["name"], "買" if buy else "賣")].append(e["ym"])
    k = [r for r in rows if r["known"]]

    def rate(f):
        return round(sum(1 for r in k if r[f]) / len(k) * 100, 1) if k else None
    repeat = [{"code": c, "bno": bno, "name": nm, "side": sd, "months": sorted(ms)}
              for (c, bno, nm, sd), ms in seen.items() if len(set(ms)) >= 2]
    out = {"events": len(rows), "with_geo": len(k),
           "dist": {"insider_side": rate("dist_mine"), "other_side": rate("dist_other")},
           "city": {"insider_side": rate("city_mine"), "other_side": rate("city_other")},
           "carrier_events": sum(1 for r in rows if r["carrier"]),
           "carrier_geo_city": sum(1 for r in rows if any(c["same_city"] for c in r["carrier"])),
           "repeat_branches": sorted(repeat, key=lambda x: (-len(x["months"]), x["code"])), "rows": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"events {out['events']}, company geography known {out['with_geo']}")
    print(f"same district on the insiders' side {out['dist']['insider_side']}% vs other side {out['dist']['other_side']}%")
    print(f"same city     on the insiders' side {out['city']['insider_side']}% vs other side {out['city']['other_side']}%")
    print(f"a branch carrying {CARRIER:.0%}-{CARRIER_MAX:.0%} of the insiders' net: {out['carrier_events']}/{out['events']} events "
          f"({out['carrier_geo_city']} of them in the company's city)")
    print(f"carrier branches in >= 2 months of the same stock: {len(repeat)}")
    for x in out["repeat_branches"][:10]:
        print(f"   {x['code']} {x['name']} {x['side']} {x['months']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
