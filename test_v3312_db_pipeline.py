"""v3.31.2 db_pipeline schema + upsert_from_raw_dict 測試"""
import os
import sys
import sqlite3
import tempfile
sys.path.insert(0, '.')

from db_pipeline import (
    init_db, upsert_from_raw_dict, db_status, SCHEMA_SQL,
)

all_pass = True
print("=" * 64)
print("  v3.31.2 db_pipeline 測試")
print("=" * 64)


def mk_stock(code, name, buy_lot=100, sell_lot=10, buy_amt=10_000, sell_amt=1_000,
              is_lu=False, style='overnight', est=False):
    return {
        'code': code, 'name': name,
        'buy_lot': buy_lot, 'sell_lot': sell_lot,
        'buy_amt': buy_amt, 'sell_amt': sell_amt,
        'net_amt': buy_amt - sell_amt, 'net_lot': buy_lot - sell_lot,
        'buy_avg': buy_amt / buy_lot if buy_lot else 0,
        'sell_avg': sell_amt / sell_lot if sell_lot else 0,
        'is_limit_up': is_lu,
        'trade_style': style,
        'lot_source': 'estimated_from_close' if est else None,
    }


# 合成 raw_output
def mk_raw(date='20260601'):
    return {
        'trade_date': date,
        'branches': [
            {'code': '9227', 'name': '凱基-城中', 'master': '蔣承翰', 'co_masters': [],
             'buys': [mk_stock('3443', '創意', 100, 0, 100000, 0, is_lu=True, style='partial'),
                      mk_stock('6147', '頎邦', 50, 0, 50000, 0, is_lu=True, style='partial')],
             'sells': []},
            {'code': '9B18', 'name': '台新-建北', 'master': '蔣承翰', 'co_masters': [],
             'buys': [mk_stock('3443', '創意', 80, 0, 80000, 0, is_lu=True, style='partial', est=True)],
             'sells': []},
            {'code': '9B25', 'name': '台新-五權西', 'master': '民哥', 'co_masters': [],
             'buys': [mk_stock('2330', '台積電', 200, 5, 400000, 10000)],
             'sells': []},
            {'code': '9216', 'name': '凱基-信義', 'master': '林滄海', 'co_masters': ['陳族元'],
             'buys': [mk_stock('2454', '聯發科', 50, 0, 100000, 0)],
             'sells': []},
        ],
    }


# ── 1. init_db schema 建好 ──
print("\n1. init_db: 7 tables + 4 views + 8 indexes")
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
    db_path = f.name
try:
    conn = init_db(db_path)
    cur = conn.cursor()
    tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    views = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    indexes = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")}
    expected_tables = {'traders', 'branches', 'stocks', 'trader_branches',
                       'daily_chips', 'daily_records', 'import_log'}
    expected_views = {'v_daily_detail', 'v_trader_daily_summary', 'v_stock_flow', 'v_trader_stock_history'}
    ok = (expected_tables.issubset(tables) and expected_views.issubset(views)
          and len(indexes) >= 8)
    print(f"  {'OK' if ok else 'FAIL'} tables={len(tables)} (含 expected), views={len(views)}, indexes={len(indexes)}")
    if not ok:
        all_pass = False
        print(f"    diff tables: {expected_tables - tables}, views: {expected_views - views}")

    # ── 2. upsert_from_raw_dict 基本 ──
    print("\n2. upsert_from_raw_dict: 4 branches × buys → daily_chips")
    raw = mk_raw('20260601')
    stats = upsert_from_raw_dict(conn, raw)
    # 預期: 蔣承翰 9227 (2 股) + 蔣承翰 9B18 (1 股) + 民哥 9B25 (1 股) +
    #       林滄海 9216 (1 股) + 陳族元 9216 (1 股, co_master) = 6 row
    expected_rows = 6   # 含 co_master 9216 雙 trader
    ok = stats['daily_chips_rows'] == expected_rows
    print(f"  {'OK' if ok else 'FAIL'} daily_chips rows={stats['daily_chips_rows']} (應 {expected_rows})")
    if not ok: all_pass = False

    # ── 3. dimension 表 ──
    print("\n3. Dimension: traders=3, branches=4, stocks=4 (3443/6147/2330/2454)")
    cur.execute("SELECT COUNT(*) FROM traders")
    traders_n = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM branches")
    branches_n = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM stocks")
    stocks_n = cur.fetchone()[0]
    # 蔣承翰/民哥/林滄海/陳族元 = 4 traders
    ok = traders_n == 4 and branches_n == 4 and stocks_n == 4
    print(f"  {'OK' if ok else 'FAIL'} traders={traders_n} branches={branches_n} stocks={stocks_n}")
    if not ok: all_pass = False

    # ── 4. trader_branches M:N ──
    print("\n4. trader_branches M:N (林滄海+陳族元 共用 9216)")
    cur.execute("""
        SELECT t.name, b.code FROM trader_branches tb
        JOIN traders t ON tb.trader_id = t.id
        JOIN branches b ON tb.branch_id = b.id
        WHERE b.code = '9216' ORDER BY t.name
    """)
    pairs = cur.fetchall()
    ok = len(pairs) == 2 and set(p[0] for p in pairs) == {'林滄海', '陳族元'}
    print(f"  {'OK' if ok else 'FAIL'} 9216 共用 master: {pairs}")
    if not ok: all_pass = False

    # ── 5. is_estimated_lot flag ──
    print("\n5. is_estimated_lot: 蔣承翰 9B18 創意 lot_source=estimated → flag=1")
    cur.execute("""
        SELECT is_estimated_lot FROM daily_chips dc
        JOIN branches b ON dc.branch_id = b.id
        WHERE b.code='9B18' AND dc.date='20260601'
    """)
    row = cur.fetchone()
    ok = row and row[0] == 1
    print(f"  {'OK' if ok else 'FAIL'} flag={row[0] if row else None}")
    if not ok: all_pass = False

    # ── 6. is_limit_up + trade_style ──
    print("\n6. 蔣承翰買的 3 筆都 is_limit_up=1 + trade_style=partial")
    cur.execute("""
        SELECT COUNT(*) FROM daily_chips dc
        JOIN traders t ON dc.trader_id = t.id
        WHERE t.name='蔣承翰' AND is_limit_up=1 AND trade_style='partial'
    """)
    n = cur.fetchone()[0]
    ok = n == 3
    print(f"  {'OK' if ok else 'FAIL'} 蔣承翰漲停+partial 筆數={n} (應 3)")
    if not ok: all_pass = False

    # ── 7. INSERT OR REPLACE re-import 安全 ──
    print("\n7. 重複 import 同日 → 不重複, 用 INSERT OR REPLACE")
    stats2 = upsert_from_raw_dict(conn, raw)   # 同樣資料再跑一次
    cur.execute("SELECT COUNT(*) FROM daily_chips WHERE date='20260601'")
    after_2nd = cur.fetchone()[0]
    ok = after_2nd == expected_rows   # 數字沒變 (REPLACE 不重複)
    print(f"  {'OK' if ok else 'FAIL'} 重 import 後 row 數={after_2nd} (應 {expected_rows})")
    if not ok: all_pass = False

    # ── 8. import_log 記錄 ──
    print("\n8. import_log 兩次 import 都有記錄")
    cur.execute("SELECT COUNT(*) FROM import_log WHERE date='20260601'")
    log_n = cur.fetchone()[0]
    ok = log_n == 2   # 兩次 import 都記
    print(f"  {'OK' if ok else 'FAIL'} import_log rows={log_n} (應 2)")
    if not ok: all_pass = False

    # ── 9. v_daily_detail view ──
    print("\n9. v_daily_detail view 可 query")
    cur.execute("SELECT date, trader, branch_code, stock_code, buy_amt FROM v_daily_detail WHERE date='20260601' LIMIT 3")
    rows = cur.fetchall()
    ok = len(rows) > 0 and all(len(r) == 5 for r in rows)
    print(f"  {'OK' if ok else 'FAIL'} view rows: {len(rows)}, sample: {rows[0] if rows else None}")
    if not ok: all_pass = False

    # ── 10. v_trader_daily_summary view ──
    print("\n10. v_trader_daily_summary: 蔣承翰 total_buy_amt 應為 230,000 仟元 (100k+50k+80k)")
    cur.execute("SELECT total_buy_amt FROM v_trader_daily_summary WHERE date='20260601' AND trader='蔣承翰'")
    row = cur.fetchone()
    ok = row and row[0] == 230_000
    print(f"  {'OK' if ok else 'FAIL'} 蔣承翰 total_buy_amt={row[0] if row else None}")
    if not ok: all_pass = False

    conn.close()
finally:
    if os.path.exists(db_path):
        os.unlink(db_path)
    # WAL/SHM 副檔也清
    for ext in ('-wal', '-shm'):
        p = db_path + ext
        if os.path.exists(p):
            os.unlink(p)

print()
print("─" * 64)
print(f"  整體: {'OK ALL PASS' if all_pass else 'FAIL HAS FAIL'}")
sys.exit(0 if all_pass else 1)
