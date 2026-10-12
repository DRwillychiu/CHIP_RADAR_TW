"""v3.96.0 insider radar - stage 2 (data -> signals -> evidence). Pure functions, no I/O.

Owner 2026-10-11: "抓到大股東變化，然後轉換成可以賺錢的產出" ... "模仿以及搭配我們既有的籌碼大戶優勢
進行超越". Spec: docs/specs/INSIDER_RADAR_SPEC.md (section 5 = the method; items marked 待決 are
parameters here, both comparison groups are computed).

Input record (one insider, one company, one month), produced by the stage-1 fetcher:
    {"code", "ym": "YYYYMM", "role", "name", "nominee": bool, "delta_shares": int,
     "end_shares": int | None, "pledge_shares": int | None, "declared_on": "YYYYMMDD" | None}
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from statistics import mean, median

BIG_BUY_YI = 1.0              # group A: net buy >= 1 億 ...
FIRST_IN_Y = 2                # ... or the first big buy in 2 years ...
FIRST_MIN_CAP_PCT = 0.2       # ... and >= 0.2 % of market value (the reference site's rule)
DEADLINE_DAY = 15             # monthly declarations are due by the 15th of the next month
HORIZONS = (5, 10, 20, 60, 120, 250)    # trading days held; 120 / 250 owner 2026-10-12 (long holders, a menu choice)
COST_PCT = 0.1425 * 2 + 0.3   # round trip: broker fee both ways + securities transaction tax = 0.585 %
_NOMINEE = re.compile(r"[（(]?(他人名義|配偶|未成年子女|利用他人名義持有)[)）]?")


def base_name(name: str) -> str:
    """'王大明(他人名義)' -> '王大明': nominee holdings belong to the person (spec 5, 歸戶)."""
    return _NOMINEE.sub("", str(name or "")).strip()


def merge_people(records):
    """One row per (code, ym, role, person): nominee and own holdings summed."""
    acc = {}
    for r in records:
        k = (r["code"], r["ym"], r.get("role") or "", base_name(r.get("name")))
        a = acc.setdefault(k, {"code": k[0], "ym": k[1], "role": k[2], "name": k[3], "delta_shares": 0,
                               "end_shares": 0, "pledge_shares": 0, "declared_on": None, "nominee": False})
        a["delta_shares"] += int(r.get("delta_shares") or 0)
        a["end_shares"] += int(r.get("end_shares") or 0)
        a["pledge_shares"] += int(r.get("pledge_shares") or 0)
        a["nominee"] = a["nominee"] or bool(r.get("nominee")) or base_name(r.get("name")) != str(r.get("name") or "").strip()
        d = r.get("declared_on")
        if d and (a["declared_on"] is None or d > a["declared_on"]):
            a["declared_on"] = d
    return list(acc.values())


def role_label(people, side):
    """'董事長(他人名義) 等 5 人' style label for the buyers (side>0) or sellers (side<0)."""
    ps = [p for p in people if (p["delta_shares"] > 0) == (side > 0) and p["delta_shares"]]
    if not ps:
        return ""
    ps.sort(key=lambda p: (-abs(p["delta_shares"]),))
    top = ps[0]
    lab = top["role"] + ("(他人名義)" if top["nominee"] else "")
    return lab + (f" 等 {len(ps)} 人" if len(ps) > 1 else "")


def company_months(people, avg_price, shares_out=None):
    """-> {(code, ym): row}. avg_price[(code, ym)] = that month's average price (yuan);
    shares_out[code] = shares outstanding (for the % of market value). Amounts are estimates."""
    g = defaultdict(list)
    for p in people:
        g[(p["code"], p["ym"])].append(p)
    out = {}
    for (code, ym), ps in g.items():
        net = sum(p["delta_shares"] for p in ps)
        px = (avg_price or {}).get((code, ym))
        amt = round(net * px / 1e8, 2) if px else None          # 億元, estimate
        so = (shares_out or {}).get(code)
        out[(code, ym)] = {
            "code": code, "ym": ym, "net_shares": net, "avg_price": px, "net_yi_est": amt,
            "pct_of_shares": round(net / so * 100, 3) if so else None,
            "buyers": role_label(ps, 1), "sellers": role_label(ps, -1),
            "pledge_shares": sum(p["pledge_shares"] for p in ps),
            "declared_on": max((p["declared_on"] for p in ps if p["declared_on"]), default=None),
            "people": len(ps),
        }
    return out


def _next_trading_day(day: str, trading_days):
    for d in trading_days:
        if d > day:
            return d
    return None


def signal_day(ym: str, declared_on, trading_days):
    """The first trading day on which the data was public - never the month end (no look-ahead).
    Declared date known: the next trading day after it (declarations land after the close or
    at night); unknown: the next trading day after the deadline (the 15th of the next month)."""
    if declared_on:
        return _next_trading_day(declared_on, trading_days)
    y, m = int(ym[:4]), int(ym[4:])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return _next_trading_day(f"{y:04d}{m:02d}{DEADLINE_DAY:02d}", trading_days)


def big_buys_a(rows, years=FIRST_IN_Y, data_start=None):
    """Comparison group A (reference site): net buy >= 1 億, or the first big buy in `years` years
    with >= 0.2 % of the shares. rows: company-month rows of every month (for the look-back).
    data_start = the first month the data covers: only rows only exist for screened months, so the
    look-back counts as covered from the data's start, not from a company's first row (owner
    2026-10-11: 1 year while the data starts 2024-10)."""
    by_code = defaultdict(list)
    for r in rows:
        by_code[r["code"]].append(r)
    out = []
    for code, rs in by_code.items():
        rs.sort(key=lambda r: r["ym"])
        for i, r in enumerate(rs):
            if r["net_shares"] <= 0:
                continue
            big = r["net_yi_est"] is not None and r["net_yi_est"] >= BIG_BUY_YI
            past = [x for x in rs[:i] if _months_between(x["ym"], r["ym"]) <= years * 12]
            start = data_start or rs[0]["ym"]
            covered = (bool(rs[:i]) or data_start is not None) and _months_between(start, r["ym"]) >= years * 12
            first = covered and not any(x["net_shares"] > 0 and (x["pct_of_shares"] or 0) >= FIRST_MIN_CAP_PCT for x in past)
            if big or (first and (r["pct_of_shares"] or 0) >= FIRST_MIN_CAP_PCT):
                out.append({**r, "why": "淨買 ≥ 1 億" if big else f"{years} 年來第一次大買"})
    return out


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[4:]) - int(a[4:])


def group_b(signals_a, branch_net, days_before=10, trading_days=None):
    """Comparison group B (ours): A and our branch masters on the same side in the 10 trading days
    before the signal day. branch_net[(code, day)] = net buy (any unit) of the tracked masters."""
    out = []
    for s in signals_a:
        d0 = s.get("signal_day")
        if not d0 or not trading_days:
            continue
        i = trading_days.index(d0) if d0 in trading_days else None
        if i is None:
            continue
        win = trading_days[max(0, i - days_before):i]
        net = sum(branch_net.get((s["code"], d), 0) for d in win)
        if net > 0:
            out.append({**s, "branch_net_10d": net})
    return out


def event_returns(signals, closes, index_closes, horizons=HORIZONS):
    """After each signal: buy at the signal day's close, hold h trading days.
    ex{h} = stock % - index % (is it the signal or the market?); r{h} = the stock's own %;
    n{h} = what following it leaves after costs (owner 2026-10-11: show the real result too):
    r - COST_PCT for a buy signal; for a sell signal the stock's move is shown as is (r)."""
    days = sorted(index_closes)
    res = []
    for s in signals:
        d0, c = s.get("signal_day"), closes.get(s["code"], {})
        if d0 not in c or d0 not in index_closes:
            continue
        i = days.index(d0)
        row = {"code": s["code"], "ym": s["ym"], "signal_day": d0}
        for h in horizons:
            if i + h < len(days) and days[i + h] in c:
                d1 = days[i + h]
                r = (c[d1] / c[d0] - 1) * 100
                b = (index_closes[d1] / index_closes[d0] - 1) * 100
                row[f"ex{h}"] = round(r - b, 2)
                row[f"r{h}"] = round(r, 2)
                if s.get("net_shares", 1) > 0:
                    row[f"n{h}"] = round(r - COST_PCT, 2)
        res.append(row)
    return res


def summarize(results, horizons=HORIZONS, split_day=None):
    """Count, mean / median excess, hit rate per horizon; in-sample / out-of-sample split when given."""
    def one(rs):
        out = {"n": len(rs)}
        for h in horizons:
            for k in ("ex", "r", "n"):
                v = [r[f"{k}{h}"] for r in rs if f"{k}{h}" in r]
                if k == "ex" or v:
                    out[f"{k}{h}"] = {"n": len(v), "mean": round(mean(v), 2) if v else None,
                                      "median": round(median(v), 2) if v else None,
                                      "hit": round(sum(x > 0 for x in v) / len(v) * 100, 1) if v else None}
        return out
    if not split_day:
        return {"all": one(results)}
    return {"all": one(results), "in": one([r for r in results if r["signal_day"] < split_day]),
            "out": one([r for r in results if r["signal_day"] >= split_day])}
