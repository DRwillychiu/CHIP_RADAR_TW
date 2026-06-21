# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

# -*- coding: utf-8 -*-
"""
test_v3450_tier1.py — v3.45.0 Tier 1 後端優化測試

驗證:
  運4 TAIEX 重複日:
    1. backfill_market 偵測 index 跟前日相同 → standard 標 stale_duplicate + pct=0
    2. backtester 算 regime 時排除 0% 重複日
  後3 listing_fetcher:
    3. fetch_listings 抓 TWSE + TPEx 兩源
    4. fetch_listings cache TTL 30 天
    5. universe_filter 自動載 cache (無 listing_data 參數)
    6. universe_filter 對 reference_date 排除未上市 / 已下市

跑法: python test_v3450_tier1.py
"""
import sys, io, json, tempfile
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

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


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 1-2] 運4 — backfill 偵測重複日標 stale + 0%")
from backfill_market_history import backfill_market
with tempfile.TemporaryDirectory() as td:
    sh_path = Path(td) / 'stock_history.json'
    # 製造 3 天: 第二天 index 跟第一天相同 (兜底排程 stale 場景)
    sh_path.write_text(json.dumps({
        'market': {
            '20260601': {'index': 45070.94, 'change_pct': 1.33},   # 首日
            '20260602': {'index': 45070.94, 'change_pct': 1.33},   # 兜底 stale (相同)
            '20260603': {'index': 46000.00, 'change_pct': 2.05},   # 真實漲
        },
        'dates': ['20260601', '20260602', '20260603'],
    }), encoding='utf-8')
    backfill_market(td, dry_run=False)
    sh_fixed = json.loads(sh_path.read_text(encoding='utf-8'))
    d2 = sh_fixed['market']['20260602']
    d3 = sh_fixed['market']['20260603']
    check("重複日 pct 改成 0.0", d2['change_pct'] == 0.0)
    check("重複日 source 標 index_diff_stale_duplicate",
          d2['change_pct_source'] == 'index_diff_stale_duplicate')
    check("第三日仍正確 verified",
          d3['change_pct_source'] == 'index_diff_verified' and d3['change_pct'] > 0)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 3] 後3 listing_fetcher — TWSE+TPEx 兩源")
from listing_fetcher import fetch_listings, load_listings
with tempfile.TemporaryDirectory() as td:
    # Force fetch (cache 不存在)
    r = fetch_listings(td, force_refresh=True)
    check("fetch_listings 成功", r is not None)
    check("含 TWSE 1000+ 檔", r['count']['twse'] > 1000)
    check("含 TPEx 800+ 檔", r['count']['tpex'] > 800)
    check("listings 含 2330 台積電", '2330' in r['listings'])
    check("2330 first_listed 是 8 位 YYYYMMDD",
          len(r['listings']['2330']['first_listed']) == 8)
    check("2330 market = TWSE", r['listings']['2330']['market'] == 'TWSE')

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] cache TTL 30 天 (再次呼叫不打網路)")
with tempfile.TemporaryDirectory() as td:
    fetch_listings(td, force_refresh=True)
    # 第二次呼叫應該命中 cache
    import unittest.mock
    with unittest.mock.patch('listing_fetcher._fetch_twse_listings') as mock_t:
        with unittest.mock.patch('listing_fetcher._fetch_tpex_listings') as mock_p:
            r2 = fetch_listings(td, force_refresh=False)
            check("cache 命中時不打網路 (二次呼叫)",
                  not mock_t.called and not mock_p.called)
            check("仍返完整 listings", r2 and r2.get('listings'))

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 5] universe_filter 自動載 cache")
from backtester_phase_b import universe_filter
with tempfile.TemporaryDirectory() as td:
    fetch_listings(td, force_refresh=True)
    # 不傳 listing_data → 自動從 td/listing_history.json 載
    filt = universe_filter(['2330', '6741'], '20240101', listing_data=None, data_dir=td)
    check("universe_filter 自動載 cache + 通過 2330",
          '2330' in filt or '6741' in filt)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 6] universe_filter 排除未上市 / 已下市 (mock 資料)")
listing = {
    '2330': {'first_listed': '19940209'},
    '9999': {'first_listed': '20250101'},                       # 未來上市
    '8888': {'first_listed': '20100101', 'delisted': '20230601'},  # 已下市
}
filt_2024 = universe_filter(['2330', '9999', '8888'], '20240101', listing)
check("2024 backtest: 2330 過", '2330' in filt_2024)
check("2024 backtest: 9999 (2025 上市) 排除", '9999' not in filt_2024)
check("2024 backtest: 8888 (2023 下市) 排除", '8888' not in filt_2024)
filt_2022 = universe_filter(['2330', '8888'], '20220101', listing)
check("2022 backtest: 8888 仍活 → 通過", '8888' in filt_2022)

# ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3450_tier1: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
