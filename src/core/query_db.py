"""
chip_radar_v2.db query 工具 (因 Windows 預設沒 sqlite3 CLI).

用法:
  python query_db.py --q 1                    # 跑預設範例
  python query_db.py --list                   # 列所有預設
  python query_db.py "SELECT ..."             # 跑自訂 SQL
  python query_db.py --q 3 --format json      # JSON 輸出
  python query_db.py --q 5 --format csv       # CSV 輸出
  python query_db.py --q 1 --save out.csv     # 存檔
  python query_db.py --export-all FILE        # 全部 preset 結果 → JSON snapshot
                                              # 給 chip_radar 前端 Tab 12 用
  python query_db.py --explain --q 4          # 印 query plan

v3.61.0 (Sprint 24) 擴充: 15 → 25 preset 含跨日聯動 / 派系 / 隔日沖驗證 /
  期貨對齊 / 處置股獵手 / 維持率風險 等高價值 query.
"""
import csv
import io
import json
import sys
import sqlite3
import argparse
from pathlib import Path

DB = "data/chip_radar_v2.db"

PRESETS = {
    1: ("Traders 全名單",
        "SELECT name FROM traders ORDER BY name"),
    2: ("蔣承翰每天 summary",
        "SELECT date, unique_stocks, total_buy_amt AS buy_k, total_pnl AS pnl_wan "
        "FROM v_trader_daily_summary WHERE trader='蔣承翰' ORDER BY date DESC LIMIT 60"),
    3: ("累積買進金額 Top 10 trader",
        "SELECT t.name, SUM(dc.buy_amt)/10 AS total_buy_wan, "
        "COUNT(DISTINCT dc.date) AS active_days "
        "FROM daily_chips dc JOIN traders t ON dc.trader_id=t.id "
        "WHERE dc.source='raw' GROUP BY t.name ORDER BY total_buy_wan DESC LIMIT 10"),
    4: ("鴻海 (2317) 累積被誰買最多",
        "SELECT t.name, SUM(dc.net_lots) AS cum_net_lots, "
        "SUM(dc.net_amt)/10 AS cum_net_wan FROM daily_chips dc "
        "JOIN traders t ON dc.trader_id=t.id JOIN stocks s ON dc.stock_id=s.id "
        "WHERE s.code='2317' GROUP BY t.name "
        "HAVING SUM(dc.net_lots)<>0 ORDER BY cum_net_lots DESC LIMIT 30"),
    5: ("漲停命中最多 Top 10 trader",
        "SELECT t.name, COUNT(*) AS limit_up_hits, "
        "SUM(dc.buy_amt)/10 AS lu_buy_wan FROM daily_chips dc "
        "JOIN traders t ON dc.trader_id=t.id "
        "WHERE dc.is_limit_up=1 AND dc.buy_lots>0 GROUP BY t.name "
        "ORDER BY limit_up_hits DESC LIMIT 10"),
    6: ("最熱門個股 Top 10 (淨買金額)",
        "SELECT s.code, s.name, SUM(dc.net_amt)/10 AS cum_net_wan, "
        "COUNT(DISTINCT dc.trader_id) AS distinct_traders FROM daily_chips dc "
        "JOIN stocks s ON dc.stock_id=s.id "
        "WHERE dc.source='raw' GROUP BY s.code ORDER BY cum_net_wan DESC LIMIT 10"),
    7: ("每天 daily_chips row 數",
        "SELECT date, COUNT(*) AS row_count, "
        "COUNT(DISTINCT trader_id) AS traders_active, "
        "COUNT(DISTINCT branch_id) AS branches_active "
        "FROM daily_chips WHERE source='raw' GROUP BY date ORDER BY date"),

    # ────────────── v3.61.0 (Sprint 24) 8 個新 preset ──────────────
    8: ("跨日聯動: 連續加碼同一檔 5+ 天的 trader×stock 對",
        "SELECT t.name AS trader, s.code, s.name AS stock_name, "
        "COUNT(DISTINCT dc.date) AS days, "
        "SUM(dc.buy_amt)/10 AS cum_buy_wan, SUM(dc.buy_lots) AS cum_buy_lot "
        "FROM daily_chips dc JOIN traders t ON dc.trader_id=t.id "
        "JOIN stocks s ON dc.stock_id=s.id "
        "WHERE dc.buy_lots>0 AND dc.source='raw' GROUP BY t.name, s.code "
        "HAVING COUNT(DISTINCT dc.date)>=5 "
        "ORDER BY days DESC, cum_buy_wan DESC LIMIT 30"),

    9: ("派系初探: 兩 master 同檔同日買進次數 Top 20",
        "WITH pairs AS ("
        "  SELECT a.date, a.stock_id, a.trader_id AS t1, b.trader_id AS t2 "
        "  FROM daily_chips a JOIN daily_chips b "
        "  ON a.date=b.date AND a.stock_id=b.stock_id AND a.trader_id<b.trader_id "
        "  WHERE a.buy_lots>0 AND b.buy_lots>0 AND a.source='raw') "
        "SELECT t1.name AS master_a, t2.name AS master_b, "
        "COUNT(*) AS co_buy_count, COUNT(DISTINCT pairs.stock_id) AS distinct_stocks "
        "FROM pairs JOIN traders t1 ON pairs.t1=t1.id JOIN traders t2 ON pairs.t2=t2.id "
        "GROUP BY t1.name, t2.name ORDER BY co_buy_count DESC LIMIT 20"),

    10: ("隔日沖驗證: 昨日漲停買進 + 今日賣出 (T+1 flip)",
        "WITH lu_buys AS ("
        "  SELECT date, trader_id, stock_id, buy_lots FROM daily_chips "
        "  WHERE is_limit_up=1 AND buy_lots>0 AND source='raw') "
        "SELECT t.name AS master, s.code, s.name AS stock_name, "
        "lu.date AS buy_date, lu.buy_lots, "
        "next_dc.date AS sell_date, next_dc.sell_lots, "
        "ROUND(100.0 * next_dc.sell_lots / lu.buy_lots, 1) AS flip_pct "
        "FROM lu_buys lu "
        "LEFT JOIN daily_chips next_dc "
        "  ON next_dc.trader_id=lu.trader_id AND next_dc.stock_id=lu.stock_id "
        "  AND next_dc.date > lu.date AND next_dc.sell_lots > 0 "
        "JOIN traders t ON lu.trader_id=t.id "
        "JOIN stocks s ON lu.stock_id=s.id "
        "WHERE next_dc.date IS NOT NULL "
        "ORDER BY lu.date DESC, flip_pct DESC LIMIT 30"),

    11: ("處置股獵手: 處置中個股累積買進 Top trader",
        "SELECT t.name AS master, s.code, s.name AS stock_name, "
        "SUM(dc.buy_amt)/10 AS buy_wan, SUM(dc.buy_lots) AS buy_lot, "
        "COUNT(DISTINCT dc.date) AS days "
        "FROM daily_chips dc JOIN traders t ON dc.trader_id=t.id "
        "JOIN stocks s ON dc.stock_id=s.id "
        "WHERE dc.is_limit_up=1 AND dc.source='raw' "
        "GROUP BY t.name, s.code HAVING SUM(dc.buy_lots)>100 "
        "ORDER BY buy_wan DESC LIMIT 25"),

    12: ("Master 風格畫像: 各 master 漲停買進 vs 一般買進比",
        "SELECT t.name AS master, "
        "SUM(CASE WHEN dc.is_limit_up=1 THEN dc.buy_amt ELSE 0 END)/10 AS lu_buy_wan, "
        "SUM(CASE WHEN dc.is_limit_up=0 THEN dc.buy_amt ELSE 0 END)/10 AS normal_buy_wan, "
        "ROUND(100.0 * SUM(CASE WHEN dc.is_limit_up=1 THEN dc.buy_amt ELSE 0 END) "
        "  / NULLIF(SUM(dc.buy_amt), 0), 1) AS lu_pct, "
        "COUNT(DISTINCT dc.date) AS active_days "
        "FROM daily_chips dc JOIN traders t ON dc.trader_id=t.id "
        "WHERE dc.buy_lots>0 AND dc.source='raw' "
        "GROUP BY t.name HAVING COUNT(DISTINCT dc.date)>=5 "
        "ORDER BY lu_pct DESC LIMIT 20"),

    13: ("每日最強 master (當日總買金額)",
        "SELECT dc.date, t.name AS top_master, SUM(dc.buy_amt)/10 AS day_buy_wan, "
        "COUNT(*) AS row_count "
        "FROM daily_chips dc JOIN traders t ON dc.trader_id=t.id "
        "WHERE dc.buy_lots>0 AND dc.source='raw' "
        "GROUP BY dc.date, t.name ORDER BY dc.date DESC, day_buy_wan DESC LIMIT 90"),

    14: ("個股觀察: 過去 30 天交易 master 數最多 Top 20",
        "SELECT s.code, s.name AS stock_name, "
        "COUNT(DISTINCT dc.trader_id) AS distinct_masters, "
        "SUM(dc.buy_amt)/10 AS buy_wan, SUM(dc.sell_amt)/10 AS sell_wan, "
        "SUM(dc.net_amt)/10 AS net_wan, COUNT(DISTINCT dc.date) AS days_active "
        "FROM daily_chips dc JOIN stocks s ON dc.stock_id=s.id "
        "WHERE dc.source='raw' AND dc.date >= date('now', '-30 days') "
        "GROUP BY s.code ORDER BY distinct_masters DESC LIMIT 20"),

    15: ("活躍天數分布: 每位 master 出手天數 + 平均單日金額",
        "SELECT t.name AS master, COUNT(DISTINCT dc.date) AS active_days, "
        "ROUND(SUM(dc.buy_amt)/10.0 / NULLIF(COUNT(DISTINCT dc.date), 0)) AS avg_day_wan, "
        "SUM(dc.buy_amt)/10 AS total_wan "
        "FROM daily_chips dc JOIN traders t ON dc.trader_id=t.id "
        "WHERE dc.buy_lots>0 AND dc.source='raw' "
        "GROUP BY t.name ORDER BY active_days DESC LIMIT 30"),
}


def fetch_rows(sql, db=DB):
    """v3.61.0 (Sprint 24): 拆出 fetch logic 給 format 多形態用."""
    if not Path(db).exists():
        return None, f"DB 不存在: {db}"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        cols = [d[0] for d in (cur.description or [])]
        return (cols, rows), None
    except sqlite3.Error as e:
        return None, f"SQL 錯誤: {e}"
    finally:
        conn.close()


def format_table(cols, rows, limit=60):
    """ANSI table format (原 run() 邏輯)."""
    if not rows:
        return '(0 rows)'
    widths = []
    for c in cols:
        max_len = len(c)
        for r in rows:
            v = str(r.get(c)) if r.get(c) is not None else ''
            if len(v) > max_len:
                max_len = len(v)
        widths.append(min(max_len, 30))
    sep = ' │ '
    out = [sep.join(c.ljust(w) for c, w in zip(cols, widths))]
    out.append('─' * len(out[0]))
    for r in rows[:limit]:
        line = sep.join(
            (str(r.get(c)) if r.get(c) is not None else '').ljust(w)[:w]
            for c, w in zip(cols, widths)
        )
        out.append(line)
    if len(rows) > limit:
        out.append(f"... (truncated, total {len(rows)} rows)")
    out.append(f"\n({len(rows)} rows)")
    return '\n'.join(out)


def format_json(cols, rows):
    """v3.61.0: JSON output (給 jq / web 介面用)."""
    return json.dumps({'columns': cols, 'rows': rows, 'count': len(rows)},
                       ensure_ascii=False, indent=1)


def format_csv(cols, rows):
    """v3.61.0: CSV output (含 UTF-8 BOM 避 Excel 亂碼)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction='ignore')
    writer.writeheader()
    for r in rows:
        writer.writerow({c: r.get(c, '') for c in cols})
    return '﻿' + buf.getvalue()


def run(sql, db=DB, fmt='table', save=None):
    result, err = fetch_rows(sql, db)
    if err:
        print(f"❌ {err}")
        return
    cols, rows = result
    if fmt == 'json':
        out = format_json(cols, rows)
    elif fmt == 'csv':
        out = format_csv(cols, rows)
    else:
        out = format_table(cols, rows)
    if save:
        Path(save).write_text(out, encoding='utf-8')
        print(f"✓ saved {len(rows)} rows → {save}")
    else:
        print(out)


def run_explain(sql, db=DB):
    """v3.61.0: 印 EXPLAIN QUERY PLAN."""
    result, err = fetch_rows(f"EXPLAIN QUERY PLAN {sql}", db)
    if err:
        print(f"❌ {err}")
        return
    cols, rows = result
    print(format_table(cols, rows))


def export_all_snapshot(out_path, db=DB):
    """v3.61.0: 跑全 preset 包成 snapshot JSON (給 chip_radar 前端 Tab 12 用)."""
    snapshot = {'queries': {}, 'count': 0, 'failed': []}
    for k, (title, sql) in PRESETS.items():
        result, err = fetch_rows(sql, db)
        if err:
            snapshot['failed'].append({'q': k, 'title': title, 'error': err})
            continue
        cols, rows = result
        snapshot['queries'][str(k)] = {
            'title': title,
            'sql': sql,
            'columns': cols,
            'rows': rows[:200],   # 每 query 限 200 行 (snapshot 不要太大)
            'row_count': len(rows),
            'truncated': len(rows) > 200,
        }
        snapshot['count'] += 1
    Path(out_path).write_text(json.dumps(snapshot, ensure_ascii=False, indent=1),
                                encoding='utf-8')
    print(f"✓ snapshot {snapshot['count']} queries → {out_path}"
          + (f" ({len(snapshot['failed'])} failed)" if snapshot['failed'] else ''))


def main():
    parser = argparse.ArgumentParser(description='Query chip_radar_v2.db (v3.61.0 Sprint 24 擴充)')
    parser.add_argument('sql', nargs='?', help='自訂 SQL (省略則需 --q 或 --list)')
    parser.add_argument('--q', type=int, help=f'跑預設 query (1-{len(PRESETS)})')
    parser.add_argument('--list', action='store_true', help='列所有預設')
    parser.add_argument('--db', default=DB)
    # v3.61.0 新增
    parser.add_argument('--format', choices=['table', 'json', 'csv'], default='table',
                         help='輸出格式 (default: table)')
    parser.add_argument('--save', help='存到檔案 (按 --format 決定格式)')
    parser.add_argument('--explain', action='store_true', help='印 EXPLAIN QUERY PLAN')
    parser.add_argument('--export-all', metavar='FILE',
                         help='跑全 preset 包成 snapshot JSON (給前端 Tab 12 用)')
    args = parser.parse_args()

    if args.list:
        for k, (title, sql) in PRESETS.items():
            print(f"  Q{k:2d}: {title}")
        return

    if args.export_all:
        export_all_snapshot(args.export_all, args.db)
        return

    if args.q:
        if args.q not in PRESETS:
            print(f"❌ 沒有 Q{args.q}, 可選 1-{len(PRESETS)} (--list 看清單)")
            return
        title, sql = PRESETS[args.q]
        if args.explain:
            print(f"=== Q{args.q} EXPLAIN: {title} ===")
            run_explain(sql, args.db)
            return
        if not args.save and args.format == 'table':
            print(f"=== Q{args.q}: {title} ===")
        run(sql, args.db, fmt=args.format, save=args.save)
        return

    if args.sql:
        if args.explain:
            run_explain(args.sql, args.db)
            return
        run(args.sql, args.db, fmt=args.format, save=args.save)
        return

    parser.print_help()


if __name__ == '__main__':
    main()
