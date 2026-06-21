# v3.61.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""
test_v3610_query_db.py — v3.61.0 Sprint 24 DB 進階查詢

驗證 src/core/query_db.py:
  - 15 個 preset SQL syntax 全 OK (建一個 in-memory DB 跑)
  - format_table / format_json / format_csv 輸出正確
  - export_all_snapshot 生成 snapshot JSON 含全 query
"""
import sys, io, json, sqlite3, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
import query_db
from query_db import (PRESETS, fetch_rows, format_table, format_json,
                       format_csv, export_all_snapshot)

PASS = 0
FAIL = 0
def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def _build_test_db(path):
    """跑跟正式 schema 一致的 in-memory DB + 注 fake data."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
    CREATE TABLE traders (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
    CREATE TABLE branches (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT);
    CREATE TABLE stocks (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT);
    CREATE TABLE trader_branches (trader_id INTEGER, branch_id INTEGER);
    CREATE TABLE daily_chips (
        id INTEGER PRIMARY KEY,
        date TEXT, trader_id INTEGER, branch_id INTEGER, stock_id INTEGER,
        buy_lots INTEGER, sell_lots INTEGER, net_lots INTEGER,
        buy_amt INTEGER, sell_amt INTEGER, net_amt INTEGER,
        is_estimated_lot INTEGER, is_limit_up INTEGER,
        trade_style TEXT, source TEXT
    );
    CREATE VIEW v_trader_daily_summary AS
      SELECT t.name AS trader, dc.date,
             COUNT(DISTINCT dc.stock_id) AS unique_stocks,
             SUM(dc.buy_amt) AS total_buy_amt,
             SUM(dc.net_amt)/10 AS total_pnl
      FROM daily_chips dc JOIN traders t ON dc.trader_id=t.id
      WHERE dc.source='raw' GROUP BY t.name, dc.date;
    INSERT INTO traders (id, name) VALUES (1, '蔣承翰'), (2, '航海王'), (3, '林滄海');
    INSERT INTO branches (id, code, name) VALUES (1, '9227', '富邦-板新'), (2, '779Z', '土地銀-台中');
    INSERT INTO stocks (id, code, name) VALUES (1, '2330', '台積電'), (2, '2317', '鴻海'), (3, '2454', '聯發科');
    INSERT INTO trader_branches VALUES (1, 1), (2, 2), (3, 1);
    INSERT INTO daily_chips (date, trader_id, branch_id, stock_id, buy_lots, sell_lots, net_lots, buy_amt, sell_amt, net_amt, is_limit_up, source) VALUES
      ('20260615', 1, 1, 1, 100, 0, 100, 100000, 0, 100000, 1, 'raw'),
      ('20260616', 1, 1, 1, 150, 0, 150, 150000, 0, 150000, 1, 'raw'),
      ('20260617', 1, 1, 1, 200, 0, 200, 200000, 0, 200000, 0, 'raw'),
      ('20260618', 1, 1, 1, 50, 50, 0, 50000, 50000, 0, 0, 'raw'),
      ('20260619', 1, 1, 1, 0, 100, -100, 0, 100000, -100000, 0, 'raw'),
      ('20260615', 2, 2, 2, 80, 0, 80, 80000, 0, 80000, 0, 'raw'),
      ('20260616', 3, 1, 1, 200, 0, 200, 200000, 0, 200000, 1, 'raw');
    """)
    conn.commit()
    conn.close()


print("\n[Case 1] 15 個 preset 全 SQL 可跑 (in-memory test DB)")
with tempfile.TemporaryDirectory() as td:
    db = Path(td) / 'test.db'
    _build_test_db(db)
    ok = 0
    for k, (title, sql) in PRESETS.items():
        result, err = fetch_rows(sql, str(db))
        if err:
            print(f"  ❌ Q{k} ({title}): {err}")
        else:
            ok += 1
    check(f"15/15 preset SQL syntax OK", ok == len(PRESETS),
          f"only {ok}/{len(PRESETS)} passed")

print("\n[Case 2] format_table / format_json / format_csv")
cols = ['name', 'count', 'amt']
rows = [{'name': '蔣承翰', 'count': 5, 'amt': 100000},
        {'name': '航海王', 'count': 3, 'amt': 80000}]
t = format_table(cols, rows)
check("table 含中文 master name", '蔣承翰' in t and '航海王' in t)
check("table 含 separator '─'", '─' in t)
check("table 含 '(2 rows)'", '(2 rows)' in t)

j = format_json(cols, rows)
parsed = json.loads(j)
check("JSON columns 正確", parsed['columns'] == cols)
check("JSON count = 2", parsed['count'] == 2)
check("JSON rows[0].name = 蔣承翰", parsed['rows'][0]['name'] == '蔣承翰')

c = format_csv(cols, rows)
check("CSV 含 UTF-8 BOM", c.startswith('﻿'))
check("CSV 含 header", 'name,count,amt' in c)
check("CSV 含 蔣承翰", '蔣承翰,5,100000' in c)

print("\n[Case 3] export_all_snapshot 生成 snapshot JSON")
with tempfile.TemporaryDirectory() as td:
    db = Path(td) / 'test.db'
    _build_test_db(db)
    snap_path = Path(td) / 'snapshot.json'
    export_all_snapshot(str(snap_path), str(db))
    snap = json.loads(snap_path.read_text(encoding='utf-8'))
    check("snapshot 含 queries dict", 'queries' in snap)
    check("snapshot count > 0", snap['count'] > 0)
    check("Q1 in snapshot", '1' in snap['queries'])
    check("Q1 含 title", 'Traders' in snap['queries']['1']['title'])
    check("Q1 含 sql", 'SELECT' in snap['queries']['1']['sql'])
    check("Q1 含 columns", isinstance(snap['queries']['1']['columns'], list))
    check("Q1 含 rows", isinstance(snap['queries']['1']['rows'], list))

print(f"\n{'='*60}")
print(f"test_v3610_query_db: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
