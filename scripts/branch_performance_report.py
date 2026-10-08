"""v3.82.0 branch performance report: every tracked branch through the
branch_performance model (FIFO + costs + GIPS returns + risk + benchmark).

Data (no new fetching): data/chip_radar_v2.db daily_chips (source='raw'; one
row per date x branch x stock - shared branches appear once per master, so
rows are de-duplicated), data/stock_history.json (60 trading days of closes +
TAIEX), data/quarantine.json (misattributed branch-days excluded).
Window = the stock_history dates; DB rows before it = warm-up inventory.

Output: JSON {window, assumptions, branches: [...]} to --out; with
--encrypt the file is AES-GCM encrypted with CHIP_RADAR_PASSWORD (same format
as the day files), because the repo is public.
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import src  # noqa: F401,E402

import branch_performance as bp  # noqa: E402
import branch_relations as rel  # noqa: E402
import quarantine  # noqa: E402

SQL = ("SELECT dc.date, b.code AS bno, b.name AS bname, s.code AS code, MAX(s.name) AS sname, "
       "MAX(dc.buy_lots) AS buy_lots, MAX(dc.sell_lots) AS sell_lots, "
       "MAX(dc.buy_amt) AS buy_amt, MAX(dc.sell_amt) AS sell_amt, MAX(dc.is_estimated_lot) AS est, MAX(dc.is_limit_up) AS lu "
       "FROM daily_chips dc JOIN branches b ON dc.branch_id=b.id JOIN stocks s ON dc.stock_id=s.id "
       "WHERE dc.source='raw' GROUP BY dc.date, b.code, s.code")


def load_rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(SQL)]
        masters = defaultdict(list)
        for bno, name in conn.execute(
                "SELECT b.code, t.name FROM trader_branches tb JOIN branches b ON tb.branch_id=b.id "
                "JOIN traders t ON tb.trader_id=t.id"):
            masters[bno].append(name)
    finally:
        conn.close()
    return rows, masters


def legacy_rows(rows):
    """Owner's sheet layout per stock over the window: (buy_lots, sell_lots, buy_wan, buy_avg, sell_avg)."""
    agg = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for r in rows:
        a = agg[r["code"]]
        a[0] += r["buy_lots"] or 0
        a[1] += r["sell_lots"] or 0
        a[2] += r["buy_amt"] or 0
        a[3] += r["sell_amt"] or 0
    out = []
    for bl, sl, ba, sa in agg.values():
        if bl and sl:
            out.append((bl, sl, ba / 10, ba / bl, sa / sl))     # 仟元 -> 萬; 仟元/張 = 元/股
        elif bl:
            out.append((bl, 0, ba / 10, ba / bl, 0.0))
    return out


SIX = ("臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市")


def local_scores(win_by_branch, geo):
    """v3.82.0 地緣: share of a branch's window buy amount in companies of its own
    district / city, and the lift over the all-branch average share."""
    comp, brs = geo.get("companies", {}), geo.get("branches", {})
    tot, by_d, by_c, stocks = defaultdict(float), defaultdict(lambda: defaultdict(float)),         defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(set))
    for bno, rs in win_by_branch.items():
        for r in rs:
            amt = r["buy_amt"] or 0
            if amt <= 0:
                continue
            tot[bno] += amt
            c = comp.get(r["code"]) or {}
            if c.get("city"):
                by_c[bno][c["city"]] += amt
            if c.get("dist"):
                by_d[bno][(c["city"], c["dist"])] += amt
                stocks[bno][(c["city"], c["dist"])].add(r["code"])
    all_tot = sum(tot.values()) or 1.0
    base_d, base_c = defaultdict(float), defaultdict(float)
    for bno in tot:
        for k, v in by_d[bno].items():
            base_d[k] += v / all_tot
        for k, v in by_c[bno].items():
            base_c[k] += v / all_tot
    out = {}
    for bno in tot:
        g = brs.get(bno) or {}
        rec = {"geo_city": g.get("city"), "geo_dist": g.get("dist"), "geo_src": g.get("src")}
        if g.get("city") in SIX and tot[bno] > 0:
            sc = by_c[bno].get(g["city"], 0.0) / tot[bno]
            rec.update(local_city_share=sc, local_city_lift=sc / base_c[g["city"]] if base_c[g["city"]] else None)
            if g.get("dist"):
                k = (g["city"], g["dist"])
                sd = by_d[bno].get(k, 0.0) / tot[bno]
                rec.update(local_dist_share=sd, local_dist_lift=sd / base_d[k] if base_d[k] else None,
                           local_dist_stocks=len(stocks[bno].get(k, ())))
        out[bno] = rec
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "chip_radar_v2.db"))
    ap.add_argument("--history", default=str(ROOT / "data" / "stock_history.json"))
    ap.add_argument("--out", default=str(ROOT / "branch_performance.json"))
    ap.add_argument("--encrypt", action="store_true")
    ap.add_argument("--rf", type=float, default=0.0, help="annual risk-free rate for Sharpe / Sortino")
    ap.add_argument("--geo", default=str(ROOT / "data" / "branch_geo.json"))
    ap.add_argument("--recent", type=int, default=20, help="trading days of the recent window")
    a = ap.parse_args(argv)

    hist = json.loads(Path(a.history).read_text(encoding="utf-8"))
    dates = sorted(hist["dates"])
    closes = {c: {d: v.get("close") for d, v in s.get("daily", {}).items() if v.get("close")}
              for c, s in hist["stocks"].items()}
    index = {d: m.get("index") for d, m in hist.get("market", {}).items() if m.get("index")}
    rows, masters = load_rows(a.db)
    q = quarantine.load()
    by_branch, names, dropped = defaultdict(list), {}, 0
    for r in rows:
        if r["date"] in q.get(r["bno"], {}):
            dropped += 1
            continue
        by_branch[r["bno"]].append(r)
        names[r["bno"]] = r["bname"]
    results = []
    d20 = dates[-(a.recent + 1):]
    try:
        geo = json.loads(Path(a.geo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        geo = {}
    local = local_scores({b: [r for r in rs if dates[0] < r["date"] <= dates[-1]] for b, rs in by_branch.items()},
                         geo)
    # v3.82.1: trading-day ordinals (holding periods) and the owner's declared styles
    day_index = {d: i for i, d in enumerate(sorted({r["date"] for r in rows} | set(dates)))}
    try:
        from branches import MASTER_STYLES
    except ImportError:
        MASTER_STYLES = {}
    for bno, rs in sorted(by_branch.items()):
        warm = [r for r in rs if r["date"] < dates[0]]
        win = [r for r in rs if dates[0] <= r["date"] <= dates[-1]]
        if not win:
            continue
        res = bp.evaluate(win, closes, index, dates, warmup_rows=warm, rf_annual=a.rf, day_index=day_index)
        legacy, legacy_wan = bp.legacy_owner_metric(legacy_rows([r for r in win if r["date"] > dates[0]]))
        res.update({"bno": bno, "name": names.get(bno), "masters": sorted(set(masters.get(bno, []))),
                    "rows": len(win), "active_days": len({r["date"] for r in win}),
                    "estimated_lot_rows": sum(1 for r in win if r["est"]),
                    "legacy_per_10m": legacy, "legacy_per_10m_wan": legacy_wan})
        rec = bp.evaluate([r for r in rs if d20[0] <= r["date"] <= d20[-1]], closes, index, d20,
                          warmup_rows=[r for r in rs if r["date"] < d20[0]], rf_annual=a.rf, day_index=day_index)
        res.update({f"{k}_recent": rec[k] for k in ("info_ratio", "alpha_ann", "twr", "excess_pnl",
                                                     "total_pnl", "return_days", "positions")})
        res.update(local.get(bno, {}))
        # v3.82.1 owner: judge performance on the horizon that fits the branch's style
        res["declared_styles"] = sorted({st for m in res["masters"] for st in MASTER_STYLES.get(m, [])})
        h = "_recent" if res.get("horizon") == "recent" else ""
        res.update(matched_ir=res.get(f"info_ratio{h}"), matched_alpha=res.get(f"alpha_ann{h}"))
        results.append(res)
    # v3.83.0 R2 co-trading on the window's visible rows (net buy amount per date x stock x branch)
    cells = {}
    for bno, rs in by_branch.items():
        for r in rs:
            if dates[0] < r["date"] <= dates[-1]:
                cells.setdefault((r["date"], r["code"]), {})[bno] = (r["buy_amt"] or 0) - (r["sell_amt"] or 0)
    edges = rel.co_trading(cells, dates[1:], masters={b: masters.get(b, []) for b in by_branch})
    # v3.83.3: notable = FDR q <= 1%, lift >= 2; a relation (clusters) also needs q <= 0.1%,
    # lift >= 3 and >= 20 common visible days (branch_relations.is_relation)
    strong = [e for e in edges if e.get("q_value", 1) <= 1e-2 and e["lift"] >= 2]
    # v3.83.2: spell out the co-buy events of the notable edges (stock name, both net amounts)
    sname = {r["code"]: r.get("sname") for r in rows}
    for e in strong:
        e["events"] = [{"x_date": dx, "y_date": dy, "code": c, "name": sname.get(c),
                        "x_net_k": (cells.get((dx, c)) or {}).get(e["x"]),
                        "y_net_k": (cells.get((dy, c)) or {}).get(e["y"])} for dx, dy, c in e.get("events", [])]
    relations = {"edges": strong[:400], "edges_total": len(edges), "strong_total": len(strong),
                 "relations_total": sum(1 for e in edges if rel.is_relation(e)),
                 "clusters": rel.clusters(edges), "params": {"big_q": rel.BIG_Q, "min_big_k": rel.MIN_BIG_K,
                                                             "min_co": rel.MIN_CO, "lags": [0, 1],
                                                             "max_q": rel.MAX_Q,
                                                             "min_overlap_days": rel.MIN_OVERLAP_DAYS}}
    doc = {"window": [dates[0], dates[-1]], "trading_days": len(dates) - 1, "recent_window": [d20[0], d20[-1]],
           "relations": relations,
           "assumptions": {"commission": bp.COMMISSION, "tax_sell": bp.TAX_SELL, "rf_annual": a.rf,
                           "lot_matching": "FIFO", "return": "Modified Dietz (GIPS) + daily TWR",
                           "visibility": "daily top-50 net-buy / net-sell lists only"},
           "quarantined_rows_dropped": dropped, "branches": results}
    text = json.dumps(doc, ensure_ascii=False)
    if a.encrypt:
        from crawler_output import encrypt_data
        text = json.dumps({"encrypted": True, "token": encrypt_data(text, os.environ["CHIP_RADAR_PASSWORD"])})
    Path(a.out).write_text(text, encoding="utf-8")
    print(f"::notice title=Branch performance::{len(results)} branches, window {dates[0]}-{dates[-1]} "
          f"({len(dates) - 1} trading days), quarantined rows dropped {dropped}, out {Path(a.out).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
