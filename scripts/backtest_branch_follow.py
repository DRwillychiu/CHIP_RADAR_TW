"""v3.96.0 insider radar 5.4 (level 4): does following a confirmed insider branch pay, and does it
beat waiting for the declaration? Monthly proxy (spec section 9): written down before the run.

Branches: data/insider_watch_branches.json (level 2 pass list).
Entry months: months where the branch's net buy is >= 50 % of its average net in its carrier months.
  follow  - buy at the close of the first trading day AFTER that month (we see the month's branch
            total then; a daily follow would be earlier still)
  declare - buy at the insiders' signal day (first trading day after the IRB110 publish date),
            only for entry months the insiders also bought in
Hold 20 trading days; result after costs (0.585 %) and versus the TAIEX.
Out-of-sample: only entry months after the months used to pick the branch count as out-of-sample
(a branch picked from carrier months M is tested on entry months > max(M)).
Pass (spec 9): n >= 30, mean after costs > 0, hit >= 55 %, out-of-sample same sign.
"""
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.run_insider_radar import prices  # noqa: E402
from src.analyzers import insider_radar as R  # noqa: E402

H = 20


def main():
    watch = json.loads((ROOT / "data" / "insider_watch_branches.json").read_text(encoding="utf-8"))["branches"]
    timing = {(x["code"], x["bno"]): x for x in json.loads((ROOT / "data" / "insider_branch_timing.json").read_text(encoding="utf-8"))}
    monthly = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in (ROOT / "data" / "insider_monthly").glob("*.json")}
    closes, index, _ = prices()
    days = sorted(index)
    rows = []
    for w in watch:
        t = timing[(w["code"], w["bno"])]
        series = {ym: v for ym, v in t["series"].items()}
        ref = statistics.mean(abs(series[m]) for m in w["carrier_months"] if m in series) or 1
        for ym, v in sorted(series.items()):
            if v <= 0 or v < 0.5 * ref:
                continue
            y, m = int(ym[:4]), int(ym[4:])
            nxt = f"{y + (m == 12):04d}{(m % 12) + 1:02d}"
            d_follow = next((d for d in days if d[:6] == nxt), None)
            mk = (monthly.get(ym, {}).get("companies", {}).get(w["code"], {}) or {}).get("market", "sii")
            pub = monthly.get(ym, {}).get("published", {}).get(mk)
            d_decl = R.signal_day(ym, pub, days) if ym in t["insider_months"] else None
            row = {"code": w["code"], "branch": w["branch"], "ym": ym, "lots": v,
                   "oos": ym > max(w["carrier_months"]), "insider_month": ym in t["insider_months"]}
            for tag, d0 in (("follow", d_follow), ("declare", d_decl)):
                c = closes.get(w["code"], {})
                if not d0 or d0 not in c or d0 not in days:
                    continue
                i = days.index(d0)
                if i + H >= len(days) or days[i + H] not in c:
                    continue
                d1 = days[i + H]
                r = (c[d1] / c[d0] - 1) * 100
                row[tag] = {"day": d0, "net": round(r - R.COST_PCT, 2),
                            "vs_index": round(r - (index[d1] / index[d0] - 1) * 100, 2)}
            rows.append(row)

    def summ(rs, tag):
        v = [r[tag]["net"] for r in rs if tag in r]
        e = [r[tag]["vs_index"] for r in rs if tag in r]
        return {"n": len(v), "net_mean": round(statistics.mean(v), 2) if v else None,
                "hit": round(sum(x > 0 for x in v) / len(v) * 100, 1) if v else None,
                "vs_index_mean": round(statistics.mean(e), 2) if e else None}
    out = {"rows": rows, "follow_all": summ(rows, "follow"), "follow_oos": summ([r for r in rows if r["oos"]], "follow"),
           "declare_same_months": summ([r for r in rows if "declare" in r and "follow" in r], "declare"),
           "follow_same_months": summ([r for r in rows if "declare" in r and "follow" in r], "follow")}
    fa = out["follow_all"]
    out["pass"] = bool(fa["n"] >= 30 and (fa["net_mean"] or 0) > 0 and (fa["hit"] or 0) >= 55
                       and out["follow_oos"]["n"] and (out["follow_oos"]["net_mean"] or 0) > 0)
    (ROOT / "data" / "insider_branch_follow.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for k in ("follow_all", "follow_oos", "follow_same_months", "declare_same_months"):
        print(f"{k:20} {out[k]}")
    print("pass", out["pass"])
    for r in rows:
        print("  ", r["code"], r["branch"], r["ym"], r["lots"], "oos" if r["oos"] else "is ", r.get("follow"), r.get("declare"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
