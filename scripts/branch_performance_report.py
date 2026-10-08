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
import quarantine  # noqa: E402

SQL = ("SELECT dc.date, b.code AS bno, b.name AS bname, s.code AS code, "
       "MAX(dc.buy_lots) AS buy_lots, MAX(dc.sell_lots) AS sell_lots, "
       "MAX(dc.buy_amt) AS buy_amt, MAX(dc.sell_amt) AS sell_amt, MAX(dc.is_estimated_lot) AS est "
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
    for bno, rs in sorted(by_branch.items()):
        warm = [r for r in rs if r["date"] < dates[0]]
        win = [r for r in rs if dates[0] <= r["date"] <= dates[-1]]
        if not win:
            continue
        res = bp.evaluate(win, closes, index, dates, warmup_rows=warm, rf_annual=a.rf)
        legacy, legacy_wan = bp.legacy_owner_metric(legacy_rows([r for r in win if r["date"] > dates[0]]))
        res.update({"bno": bno, "name": names.get(bno), "masters": sorted(set(masters.get(bno, []))),
                    "rows": len(win), "active_days": len({r["date"] for r in win}),
                    "estimated_lot_rows": sum(1 for r in win if r["est"]),
                    "legacy_per_10m": legacy, "legacy_per_10m_wan": legacy_wan})
        results.append(res)
    doc = {"window": [dates[0], dates[-1]], "trading_days": len(dates) - 1,
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
