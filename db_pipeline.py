"""
========================================================================
Module: db_pipeline.py  (v3.31.2 新增 — Phase 1.0)
功能: 把 raw daily.json (解密後 in-memory dict) ETL 進 SQLite OLAP DB.

設計依使用者 6/1 提供的 HTML 規劃 (7 tables + 4 views + 8 indexes) +
我的補強 (is_estimated_lot / is_limit_up / trade_style / source 雙來源).

使用者決策 (6/1):
  Q1 Source = C 雙來源 (raw 為主 + Excel 備份)
  Q2 更新   = A 整合進 crawler.py
  Q3 舊檔   = A 分層 hot/warm/cold

Phase 1.0 (本檔):
  - SQLite schema (CREATE IF NOT EXISTS)
  - upsert_from_raw_dict(): 從 crawler raw_output 寫入
  - CLI: init / import-day / status

Phase 1.1 (下個 commit):
  - crawler.py 主流程整合
  - archive_manager.py 分層

Phase 1.2 (之後):
  - upsert_from_excel() backup source
  - cross_validate() raw vs excel

Schema 重點:
  - Normalized: traders, branches, stocks, trader_branches (M:N)
  - Fact:      daily_chips (含 source='raw'/'excel' 區分)
  - Flat:      daily_records (含中文, INSERT OR REPLACE 重匯入安全)
  - Log:       import_log

ETL 邏輯 (raw daily.json → DB):
  1. raw_output['branches'] 逐筆遍歷
  2. branch.master (含 co_masters) → trader 維度 upsert
  3. branch.code/name → branch 維度 upsert + trader_branches M:N
  4. branch.buys + sells 合併去重 by code (同股雙榜) → stock 維度 upsert
  5. 寫入 daily_chips (source='raw') + daily_records (同, flat)
  6. 寫 import_log

CLI:
  python db_pipeline.py init                              # 建 schema
  python db_pipeline.py import-day --date 20260601 \\
         --password "$CHIP_RADAR_PASSWORD"                # 從 data/20260601.json 解密+寫入
  python db_pipeline.py status                            # 印 row 數 + 最新日期
========================================================================
"""
import os
import sys
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple

TW_TZ = timezone(timedelta(hours=8))

DEFAULT_DB = "data/chip_radar_v2.db"


# ════════════════════════════════════════════════════════════════════
#  SCHEMA — 7 tables + 4 views + 8 indexes
# ════════════════════════════════════════════════════════════════════

SCHEMA_SQL = """
-- WAL mode 提高並發
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ═══════════════════════════════════════════
-- Dimension tables (4)
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS traders (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS branches (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT
);

CREATE TABLE IF NOT EXISTS stocks (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT
);

CREATE TABLE IF NOT EXISTS trader_branches (
    trader_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    PRIMARY KEY (trader_id, branch_id),
    FOREIGN KEY (trader_id) REFERENCES traders(id),
    FOREIGN KEY (branch_id) REFERENCES branches(id)
);

-- ═══════════════════════════════════════════
-- Fact: daily_chips (normalized)
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS daily_chips (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,
    trader_id       INTEGER,                    -- nullable (有些 branch 無 master)
    branch_id       INTEGER NOT NULL,
    stock_id        INTEGER NOT NULL,
    buy_lots        INTEGER DEFAULT 0,           -- 張
    sell_lots       INTEGER DEFAULT 0,
    net_lots        INTEGER DEFAULT 0,
    buy_amt         INTEGER DEFAULT 0,           -- 仟元 (crawler convention)
    sell_amt        INTEGER DEFAULT 0,
    net_amt         INTEGER DEFAULT 0,
    avg_buy_price   REAL DEFAULT 0,              -- 元/股
    avg_sell_price  REAL DEFAULT 0,
    pnl             REAL DEFAULT 0,              -- 萬元
    is_estimated_lot INTEGER DEFAULT 0,          -- v3.27.2 高價低張反推 flag
    is_limit_up     INTEGER DEFAULT 0,
    trade_style     TEXT,                        -- daytrade/partial/overnight/unknown
    source          TEXT DEFAULT 'raw',          -- 'raw' / 'excel' (Q1.C 雙來源區分)
    UNIQUE(date, trader_id, branch_id, stock_id, source),
    FOREIGN KEY (trader_id) REFERENCES traders(id),
    FOREIGN KEY (branch_id) REFERENCES branches(id),
    FOREIGN KEY (stock_id) REFERENCES stocks(id)
);

-- ═══════════════════════════════════════════
-- Flat: daily_records (含中文, INSERT OR REPLACE 重匯入安全)
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS daily_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,
    trader          TEXT,
    branch_name     TEXT,
    branch_code     TEXT,
    stock_name      TEXT,
    stock_code      TEXT,
    buy_lots        INTEGER, sell_lots INTEGER,
    buy_amt         INTEGER, sell_amt  INTEGER, net_amt INTEGER,
    avg_buy_price   REAL, avg_sell_price REAL,
    pnl             REAL,
    is_estimated_lot INTEGER, is_limit_up INTEGER,
    trade_style     TEXT,
    source          TEXT DEFAULT 'raw',
    UNIQUE(date, trader, branch_code, stock_code, source)
);

-- ═══════════════════════════════════════════
-- Log
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS import_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,
    source        TEXT NOT NULL,
    imported_at   TEXT NOT NULL,
    row_count     INTEGER,
    source_file   TEXT,
    notes         TEXT
);

-- ═══════════════════════════════════════════
-- Indexes (8)
-- ═══════════════════════════════════════════
CREATE INDEX IF NOT EXISTS idx_dc_date          ON daily_chips(date);
CREATE INDEX IF NOT EXISTS idx_dc_trader_date   ON daily_chips(trader_id, date);
CREATE INDEX IF NOT EXISTS idx_dc_stock_date    ON daily_chips(stock_id, date);
CREATE INDEX IF NOT EXISTS idx_dc_branch_date   ON daily_chips(branch_id, date);
CREATE INDEX IF NOT EXISTS idx_dc_date_net      ON daily_chips(date, net_amt DESC);
CREATE INDEX IF NOT EXISTS idx_dr_date          ON daily_records(date);
CREATE INDEX IF NOT EXISTS idx_dr_trader_date   ON daily_records(trader, date);
CREATE INDEX IF NOT EXISTS idx_dr_stock_date    ON daily_records(stock_code, date);

-- ═══════════════════════════════════════════
-- Views (4)
-- ═══════════════════════════════════════════
DROP VIEW IF EXISTS v_daily_detail;
CREATE VIEW v_daily_detail AS
    SELECT
        dc.date,
        t.name AS trader,
        b.code AS branch_code, b.name AS branch_name,
        s.code AS stock_code, s.name AS stock_name,
        dc.buy_lots, dc.sell_lots, dc.net_lots,
        dc.buy_amt, dc.sell_amt, dc.net_amt,
        dc.avg_buy_price, dc.avg_sell_price, dc.pnl,
        dc.is_estimated_lot, dc.is_limit_up, dc.trade_style, dc.source
    FROM daily_chips dc
    LEFT JOIN traders  t ON dc.trader_id = t.id
    JOIN branches b ON dc.branch_id = b.id
    JOIN stocks   s ON dc.stock_id  = s.id;

DROP VIEW IF EXISTS v_trader_daily_summary;
CREATE VIEW v_trader_daily_summary AS
    SELECT
        dc.date,
        t.name AS trader,
        COUNT(DISTINCT dc.stock_id)  AS unique_stocks,
        SUM(dc.buy_amt)              AS total_buy_amt,
        SUM(dc.sell_amt)             AS total_sell_amt,
        SUM(dc.net_amt)              AS total_net_amt,
        SUM(dc.buy_lots)             AS total_buy_lots,
        SUM(dc.sell_lots)            AS total_sell_lots,
        SUM(dc.pnl)                  AS total_pnl
    FROM daily_chips dc
    JOIN traders t ON dc.trader_id = t.id
    WHERE dc.source = 'raw'
    GROUP BY dc.date, t.name;

DROP VIEW IF EXISTS v_stock_flow;
CREATE VIEW v_stock_flow AS
    SELECT
        dc.date,
        s.code AS stock_code, s.name AS stock_name,
        COUNT(DISTINCT dc.trader_id) AS distinct_traders,
        SUM(dc.net_amt)              AS total_net_amt,
        SUM(dc.net_lots)             AS total_net_lots
    FROM daily_chips dc
    JOIN stocks s ON dc.stock_id = s.id
    WHERE dc.source = 'raw'
    GROUP BY dc.date, s.code;

DROP VIEW IF EXISTS v_trader_stock_history;
CREATE VIEW v_trader_stock_history AS
    SELECT
        dc.date,
        t.name AS trader,
        s.code AS stock_code, s.name AS stock_name,
        dc.net_lots, dc.net_amt,
        SUM(dc.net_lots) OVER (PARTITION BY dc.trader_id, dc.stock_id ORDER BY dc.date) AS cum_net_lots,
        SUM(dc.net_amt)  OVER (PARTITION BY dc.trader_id, dc.stock_id ORDER BY dc.date) AS cum_net_amt
    FROM daily_chips dc
    JOIN traders t ON dc.trader_id = t.id
    JOIN stocks  s ON dc.stock_id  = s.id
    WHERE dc.source = 'raw';
"""


def init_db(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    """建 schema (CREATE IF NOT EXISTS, 重複跑無害)."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def _now_tw_iso() -> str:
    return datetime.now(TW_TZ).isoformat()


def _upsert_dim(conn: sqlite3.Connection, table: str, key_col: str, key_val: str,
                 extra_cols: Optional[Dict[str, Any]] = None) -> int:
    """INSERT OR IGNORE 維度表, 回傳 id."""
    if not key_val:
        return 0
    cur = conn.cursor()
    cur.execute(f"INSERT OR IGNORE INTO {table} ({key_col}) VALUES (?)", (key_val,))
    if extra_cols:
        for col, val in extra_cols.items():
            cur.execute(f"UPDATE {table} SET {col} = COALESCE({col}, ?) WHERE {key_col} = ?",
                        (val, key_val))
    cur.execute(f"SELECT id FROM {table} WHERE {key_col} = ?", (key_val,))
    row = cur.fetchone()
    return row[0] if row else 0


def _upsert_trader_branch(conn: sqlite3.Connection, trader_id: int, branch_id: int) -> None:
    if trader_id and branch_id:
        conn.execute(
            "INSERT OR IGNORE INTO trader_branches (trader_id, branch_id) VALUES (?, ?)",
            (trader_id, branch_id),
        )


# ════════════════════════════════════════════════════════════════════
#  Core: upsert_from_raw_dict
# ════════════════════════════════════════════════════════════════════

def upsert_from_raw_dict(conn: sqlite3.Connection,
                          raw_output: Dict[str, Any],
                          trade_date: Optional[str] = None,
                          source: str = 'raw',
                          source_file: str = '<in-memory>') -> Dict[str, int]:
    """從 crawler raw_output dict 寫入 DB.

    raw_output 結構 (crawler 主流程產出, 解密後):
      {
        'trade_date': '20260601',
        'branches': [
          {'code': '9227', 'name': '凱基-城中', 'master': '蔣承翰', 'co_masters': [],
           'buys': [{...stock dict...}, ...],
           'sells': [{...stock dict...}, ...]},
          ...
        ],
        ...
      }

    每個 stock dict (crawler merge_rows 已 merge):
      {'code': '3443', 'name': '創意', 'buy_lot': 100, 'sell_lot': 50,
       'buy_amt': 1000, 'sell_amt': 500, 'net_amt': 500, 'net_lot': 50,
       'buy_avg': 100.0, 'sell_avg': 100.0, 'is_limit_up': True,
       'trade_style': 'partial', 'lot_source': 'estimated_from_close', ...}

    回傳 stats: {rows_inserted, rows_updated, traders_added, branches_added, stocks_added}
    """
    td = trade_date or raw_output.get('trade_date')
    if not td:
        raise ValueError("trade_date 缺失 (raw_output 沒 trade_date 也沒傳)")

    cur = conn.cursor()
    stats = {'daily_chips_rows': 0, 'daily_records_rows': 0,
             'traders': 0, 'branches': 0, 'stocks': 0}

    # 先記下 dimension 表現有 ID set, 用來算 added count
    pre_traders  = {r[0] for r in cur.execute("SELECT name FROM traders")}
    pre_branches = {r[0] for r in cur.execute("SELECT code FROM branches")}
    pre_stocks   = {r[0] for r in cur.execute("SELECT code FROM stocks")}

    for br in raw_output.get('branches', []):
        branch_code = br.get('code')
        branch_name = br.get('name', '')
        if not branch_code:
            continue
        master = br.get('master')
        co_masters = br.get('co_masters') or []
        all_masters = [master] + list(co_masters) if master else list(co_masters)

        branch_id = _upsert_dim(conn, 'branches', 'code', branch_code, {'name': branch_name})

        # 同分點同股 buys + sells union by code (crawler merge_rows 已合, 但雙榜可能重複)
        seen_codes = {}
        for side in ('buys', 'sells'):
            for s in (br.get(side) or []):
                code = s.get('code')
                if not code:
                    continue
                if code not in seen_codes:
                    seen_codes[code] = s
                # 不覆蓋 (用 buys 優先版本; 實際上 merge_rows 後同股應一致)

        for stock_code, s in seen_codes.items():
            stock_name = s.get('name', '')
            stock_id = _upsert_dim(conn, 'stocks', 'code', stock_code, {'name': stock_name})

            buy_lots = int(s.get('buy_lot', 0) or 0)
            sell_lots = int(s.get('sell_lot', 0) or 0)
            net_lots = int(s.get('net_lot', buy_lots - sell_lots) or 0)
            buy_amt = int(s.get('buy_amt', 0) or 0)
            sell_amt = int(s.get('sell_amt', 0) or 0)
            net_amt = int(s.get('net_amt', buy_amt - sell_amt) or 0)
            avg_buy = float(s.get('buy_avg', 0) or 0)
            avg_sell = float(s.get('sell_avg', 0) or 0)
            pnl = float(s.get('pnl_intraday', 0) or 0)
            is_est = 1 if s.get('lot_source') == 'estimated_from_close' else 0
            is_lu = 1 if s.get('is_limit_up') else 0
            trade_style = s.get('trade_style', 'unknown')

            # 對每個 trader (含 co_masters) 各寫一筆 (因為 daily_chips 唯一鍵含 trader_id)
            # 若無 master, trader_id=NULL 一筆
            traders_for_row = all_masters if all_masters else [None]
            for trader_name in traders_for_row:
                trader_id = _upsert_dim(conn, 'traders', 'name', trader_name) if trader_name else None
                if trader_id:
                    _upsert_trader_branch(conn, trader_id, branch_id)

                # daily_chips (normalized) — INSERT OR REPLACE
                cur.execute("""
                    INSERT OR REPLACE INTO daily_chips
                    (date, trader_id, branch_id, stock_id,
                     buy_lots, sell_lots, net_lots, buy_amt, sell_amt, net_amt,
                     avg_buy_price, avg_sell_price, pnl,
                     is_estimated_lot, is_limit_up, trade_style, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (td, trader_id, branch_id, stock_id,
                       buy_lots, sell_lots, net_lots, buy_amt, sell_amt, net_amt,
                       avg_buy, avg_sell, pnl,
                       is_est, is_lu, trade_style, source))
                stats['daily_chips_rows'] += 1

                # daily_records (flat 中文)
                cur.execute("""
                    INSERT OR REPLACE INTO daily_records
                    (date, trader, branch_name, branch_code, stock_name, stock_code,
                     buy_lots, sell_lots, buy_amt, sell_amt, net_amt,
                     avg_buy_price, avg_sell_price, pnl,
                     is_estimated_lot, is_limit_up, trade_style, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (td, trader_name, branch_name, branch_code, stock_name, stock_code,
                       buy_lots, sell_lots, buy_amt, sell_amt, net_amt,
                       avg_buy, avg_sell, pnl,
                       is_est, is_lu, trade_style, source))
                stats['daily_records_rows'] += 1

    # Log
    cur.execute("""
        INSERT INTO import_log (date, source, imported_at, row_count, source_file, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (td, source, _now_tw_iso(), stats['daily_chips_rows'], source_file, None))

    conn.commit()

    # 算新增 dimension
    post_traders  = {r[0] for r in cur.execute("SELECT name FROM traders")}
    post_branches = {r[0] for r in cur.execute("SELECT code FROM branches")}
    post_stocks   = {r[0] for r in cur.execute("SELECT code FROM stocks")}
    stats['traders']  = len(post_traders  - pre_traders)
    stats['branches'] = len(post_branches - pre_branches)
    stats['stocks']   = len(post_stocks   - pre_stocks)

    return stats


# ════════════════════════════════════════════════════════════════════
#  Helper: import daily from encrypted json file
# ════════════════════════════════════════════════════════════════════

def import_day_from_file(db_path: str, json_path: str, password: str) -> Dict[str, int]:
    """從 data/YYYYMMDD.json (加密) 解密 → upsert."""
    with open(json_path, 'r', encoding='utf-8') as f:
        enc = json.load(f)
    if enc.get('encrypted'):
        from crawler import decrypt_data
        plaintext = decrypt_data(enc['data'], password)
        raw_output = json.loads(plaintext)
    else:
        raw_output = enc.get('data', enc)

    conn = init_db(db_path)
    try:
        stats = upsert_from_raw_dict(conn, raw_output,
                                      source='raw', source_file=str(Path(json_path).name))
        return stats
    finally:
        conn.close()


def db_status(db_path: str) -> Dict[str, Any]:
    """印 DB row counts + 最新日期."""
    if not Path(db_path).exists():
        return {'exists': False}
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    tables = ['traders', 'branches', 'stocks', 'trader_branches',
              'daily_chips', 'daily_records', 'import_log']
    counts = {}
    for t in tables:
        try:
            counts[t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            counts[t] = None
    latest = cur.execute("SELECT MAX(date) FROM daily_chips").fetchone()
    latest_date = latest[0] if latest else None
    earliest = cur.execute("SELECT MIN(date) FROM daily_chips").fetchone()
    earliest_date = earliest[0] if earliest else None
    conn.close()
    return {
        'exists': True, 'path': db_path,
        'counts': counts,
        'earliest_date': earliest_date,
        'latest_date': latest_date,
    }


# ════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='v3.31.2 DB pipeline ETL')
    sub = parser.add_subparsers(dest='cmd', required=True)

    sub.add_parser('init', help='建 SQLite schema')
    p_imp = sub.add_parser('import-day', help='從加密 daily.json import')
    p_imp.add_argument('--date', required=True, help='YYYYMMDD (找 data/YYYYMMDD.json)')
    p_imp.add_argument('--password', default=None, help='或設 CHIP_RADAR_PASSWORD env')
    p_imp.add_argument('--data-dir', default='data')

    sub.add_parser('status', help='印 DB row counts + 日期範圍')

    p_imp_all = sub.add_parser('import-all', help='import 所有 data/*.json (歷史 backfill)')
    p_imp_all.add_argument('--password', default=None)
    p_imp_all.add_argument('--data-dir', default='data')

    p_imp_all_or_imp = sub.choices  # noqa
    args = parser.parse_args()

    db_path = DEFAULT_DB
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    if args.cmd == 'init':
        conn = init_db(db_path)
        conn.close()
        print(f"✅ schema 建好: {db_path}")

    elif args.cmd == 'import-day':
        pwd = args.password or os.environ.get('CHIP_RADAR_PASSWORD', '')
        if not pwd:
            print("❌ 需要 --password 或 CHIP_RADAR_PASSWORD env")
            sys.exit(1)
        json_path = Path(args.data_dir) / f"{args.date}.json"
        if not json_path.exists():
            print(f"❌ {json_path} 不存在")
            sys.exit(1)
        stats = import_day_from_file(db_path, str(json_path), pwd)
        print(f"✅ {args.date} import 完成: {stats}")

    elif args.cmd == 'import-all':
        pwd = args.password or os.environ.get('CHIP_RADAR_PASSWORD', '')
        if not pwd:
            print("❌ 需要 --password 或 CHIP_RADAR_PASSWORD env")
            sys.exit(1)
        data_dir = Path(args.data_dir)
        files = sorted(data_dir.glob('[0-9]' * 8 + '.json'))
        print(f"準備 import {len(files)} 個 daily.json...")
        success = 0
        for f in files:
            try:
                stats = import_day_from_file(db_path, str(f), pwd)
                print(f"  ✓ {f.stem}: {stats['daily_chips_rows']} rows")
                success += 1
            except Exception as e:
                print(f"  ❌ {f.stem}: {type(e).__name__}: {e}")
        print(f"完成 {success}/{len(files)}")

    elif args.cmd == 'status':
        s = db_status(db_path)
        if not s['exists']:
            print(f"❌ DB 不存在: {db_path}")
            sys.exit(1)
        print(f"DB: {s['path']}")
        print(f"  date range: {s['earliest_date']} ~ {s['latest_date']}")
        for t, c in s['counts'].items():
            print(f"  {t:20s} {c:>8} rows" if c is not None else f"  {t:20s}    N/A")


if __name__ == '__main__':
    main()
