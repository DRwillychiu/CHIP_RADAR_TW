"""
簡易 chip_radar_v2.db query 工具 (因 Windows 預設沒 sqlite3 CLI).

用法:
  python query_db.py --q 1          # 跑預設範例 (1-7)
  python query_db.py --list         # 列所有預設
  python query_db.py "SELECT ..."   # 跑自訂 SQL
"""
import sys
import sqlite3
import argparse
from pathlib import Path

DB = "data/chip_radar_v2.db"

PRESETS = {
    1: ("Traders 全名單 (解 29 之謎)",
        "SELECT name FROM traders ORDER BY name"),
    2: ("蔣承翰 31 天每天 summary",
        "SELECT date, unique_stocks, total_buy_amt AS buy_k, total_pnl AS pnl_wan "
        "FROM v_trader_daily_summary WHERE trader='蔣承翰' ORDER BY date DESC"),
    3: ("31 天累積買進金額 Top 10 trader",
        "SELECT t.name, SUM(dc.buy_amt)/10 AS total_buy_wan, "
        "COUNT(DISTINCT dc.date) AS active_days "
        "FROM daily_chips dc JOIN traders t ON dc.trader_id=t.id "
        "WHERE dc.source='raw' GROUP BY t.name ORDER BY total_buy_wan DESC LIMIT 10"),
    4: ("鴻海 (2317) 31 天累積被誰買最多",
        "SELECT t.name, SUM(dc.net_lots) AS cum_net_lots, "
        "SUM(dc.net_amt)/10 AS cum_net_wan FROM daily_chips dc "
        "JOIN traders t ON dc.trader_id=t.id JOIN stocks s ON dc.stock_id=s.id "
        "WHERE s.code='2317' GROUP BY t.name "
        "HAVING SUM(dc.net_lots)<>0 ORDER BY cum_net_lots DESC"),
    5: ("31 天漲停命中最多 Top 10 trader",
        "SELECT t.name, COUNT(*) AS limit_up_hits, "
        "SUM(dc.buy_amt)/10 AS lu_buy_wan FROM daily_chips dc "
        "JOIN traders t ON dc.trader_id=t.id "
        "WHERE dc.is_limit_up=1 AND dc.buy_lots>0 GROUP BY t.name "
        "ORDER BY limit_up_hits DESC LIMIT 10"),
    6: ("31 天最熱門個股 Top 10 (淨買金額)",
        "SELECT s.code, s.name, SUM(dc.net_amt)/10 AS cum_net_wan, "
        "COUNT(DISTINCT dc.trader_id) AS distinct_traders FROM daily_chips dc "
        "JOIN stocks s ON dc.stock_id=s.id "
        "WHERE dc.source='raw' GROUP BY s.code ORDER BY cum_net_wan DESC LIMIT 10"),
    7: ("每天 daily_chips row 數 (確認每日資料量)",
        "SELECT date, COUNT(*) AS row_count, "
        "COUNT(DISTINCT trader_id) AS traders_active, "
        "COUNT(DISTINCT branch_id) AS branches_active "
        "FROM daily_chips WHERE source='raw' GROUP BY date ORDER BY date"),
}


def run(sql, db=DB):
    if not Path(db).exists():
        print(f"❌ DB 不存在: {db}")
        return
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql)
        rows = cur.fetchall()
    except sqlite3.Error as e:
        print(f"❌ SQL 錯誤: {e}")
        return
    finally:
        pass

    if not rows:
        print("(0 rows)")
        conn.close()
        return

    cols = list(rows[0].keys())
    # 算欄寬
    widths = []
    for c in cols:
        max_len = len(c)
        for r in rows:
            v = str(r[c]) if r[c] is not None else ''
            if len(v) > max_len:
                max_len = len(v)
        widths.append(min(max_len, 30))   # 單欄最多 30 字

    sep = ' │ '
    header = sep.join(c.ljust(w) for c, w in zip(cols, widths))
    print(header)
    print('─' * len(header))

    LIMIT = 60
    for r in rows[:LIMIT]:
        line = sep.join(
            (str(r[c]) if r[c] is not None else '').ljust(w)[:w]
            for c, w in zip(cols, widths)
        )
        print(line)
    if len(rows) > LIMIT:
        print(f"... (truncated, total {len(rows)} rows)")
    print(f"\n({len(rows)} rows)")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description='Query chip_radar_v2.db')
    parser.add_argument('sql', nargs='?', help='自訂 SQL (省略則需 --q 或 --list)')
    parser.add_argument('--q', type=int, help='跑預設 query (1-7)')
    parser.add_argument('--list', action='store_true', help='列所有預設')
    parser.add_argument('--db', default=DB)
    args = parser.parse_args()

    if args.list:
        for k, (title, sql) in PRESETS.items():
            print(f"  Q{k}: {title}")
        return

    if args.q:
        if args.q not in PRESETS:
            print(f"❌ 沒有 Q{args.q}, 可選 1-{len(PRESETS)} (--list 看清單)")
            return
        title, sql = PRESETS[args.q]
        print(f"=== Q{args.q}: {title} ===")
        run(sql, args.db)
        return

    if args.sql:
        run(args.sql, args.db)
        return

    parser.print_help()


if __name__ == '__main__':
    main()
