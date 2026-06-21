# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

# -*- coding: utf-8 -*-
"""
test_v3430_market_fix.py — v3.43.0 next_day backfill bug 修正測試

驗證:
  1. update_history 修法 — 拿前日 index 算 signed change_pct (蓋過 API sign)
  2. backfill_market_history backfill 邏輯正確
  3. backtester_phase_b regime 0% 排除邏輯 (mild_bull 取代 mild_bear)
  4. methodology_caveats 5 大 disclosure 完整
  5. universe_filter 排除 survivorship 邏輯 (a) 未上市 (b) 已下市
  6. backtest 結果現實情境 (mild_bull regime, trust=True)
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
print("\n[Case 1] backfill — index 下跌時改成負值")
from backfill_market_history import backfill_market
with tempfile.TemporaryDirectory() as td:
    sh_path = Path(td) / 'stock_history.json'
    sh_path.write_text(json.dumps({
        'market': {
            '20260513': {'index': 41898.32, 'change_pct': 0.26},   # buggy
            '20260514': {'index': 41374.50, 'change_pct': 1.25},   # buggy (其實下跌 1.25)
            '20260515': {'index': 41751.75, 'change_pct': 0.91},   # buggy (上漲 0.91)
        },
        'dates': ['20260513', '20260514', '20260515'],
    }), encoding='utf-8')
    r = backfill_market(td, dry_run=False)
    sh_fixed = json.loads(sh_path.read_text(encoding='utf-8'))
    chg14 = sh_fixed['market']['20260514']['change_pct']
    chg15 = sh_fixed['market']['20260515']['change_pct']
    check("5/14 從 +1.25 改 ~-1.25 (跌)", chg14 < -1.0 and chg14 > -1.5, f"got {chg14}")
    check("5/15 從 +0.91 改 ~+0.91 (漲)", chg15 > 0.8 and chg15 < 1.0, f"got {chg15}")
    check("5/14 source 標 index_diff_verified",
          sh_fixed['market']['20260514']['change_pct_source'] == 'index_diff_verified')
    check("5/13 首日 source 標 api_only_first_day",
          sh_fixed['market']['20260513']['change_pct_source'] == 'api_only_first_day')

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 2] backfill 同步重算 temp_history.next_day_change_pct")
with tempfile.TemporaryDirectory() as td:
    sh_path = Path(td) / 'stock_history.json'
    sh_path.write_text(json.dumps({
        'market': {
            '20260513': {'index': 41898.32, 'change_pct': 0.26},
            '20260514': {'index': 41374.50, 'change_pct': 1.25},   # 真實 -1.25
        },
        'dates': ['20260513', '20260514'],
    }), encoding='utf-8')
    th_path = Path(td) / 'temp_history.json'
    th_path.write_text(json.dumps({
        'history': [
            {'date': '20260513', 'next_day_change_pct': 1.25,   # 應改 -1.25
             'taiex_change_pct': 0.26, 'signals': [], 'score': 0},
        ],
    }), encoding='utf-8')
    backfill_market(td, dry_run=False)
    th_fixed = json.loads(th_path.read_text(encoding='utf-8'))
    nc = th_fixed['history'][0]['next_day_change_pct']
    check("temp_history 5/13 next_chg 從 +1.25 → ~-1.25", nc < -1.0 and nc > -1.5)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 3] backtester regime 0% 排除 (mild_bull 不是 mild_bear)")
import importlib
import backtester_phase_b
importlib.reload(backtester_phase_b)
with tempfile.TemporaryDirectory() as td:
    th_path = Path(td) / 'th.json'
    # 12 up + 9 down + 8 zero (重複日)
    # bias 排除 0 後: 12/21 = 57% → mild_bull
    # bias 含 0: 12/29 = 41% → mild_bear (錯)
    entries = []
    for i in range(12): entries.append({
        'date': f'2026{i+10:04d}', 'score': 0, 'signals': [],
        'next_day_change_pct': 0.5})
    for i in range(9): entries.append({
        'date': f'2026{i+22:04d}', 'score': 0, 'signals': [],
        'next_day_change_pct': -0.5})
    for i in range(8): entries.append({
        'date': f'2026{i+31:04d}', 'score': 0, 'signals': [],
        'next_day_change_pct': 0.0})
    th_path.write_text(json.dumps({'history': entries}), encoding='utf-8')
    r = backtester_phase_b.compute_phase_b_results(str(th_path))
caveat = r['market_regime_caveat']
check("regime = mild_bull (57.1%)", caveat['regime'] == 'mild_bull', f"got {caveat['regime']}")
check("next_day_up_pct ~ 57", 55 < caveat['next_day_up_pct'] < 60)
check("n_up=12 n_down=9 (0 不算)", caveat['n_up'] == 12 and caveat['n_down'] == 9)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] methodology_caveats 5 大 disclosure")
mc = r.get('methodology_caveats', {})
for key in ['survivorship_bias', 'look_ahead_bias', 'data_snooping',
             'small_sample', 'regime_dependence']:
    check(f"含 {key} disclosure", key in mc and len(mc[key]) > 30)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 5] universe_filter survivorship 排除")
from backtester_phase_b import universe_filter
listing = {
    '2330': {'first_listed': '19940101'},                          # 老牌
    '6741': {'first_listed': '20210420'},                          # 新上市
    '2342': {'first_listed': '19950820', 'delisted': '20240630'},  # 已下市
}
filt = universe_filter(['2330', '6741', '2342'], '20240101', listing)
check("2330 (1994 上市) 在 2024-01-01 backtest 通過", '2330' in filt)
check("6741 (2021 上市) 在 2024-01-01 backtest 通過 (已上市 2 年多)", '6741' in filt)
check("2342 (2024-06 下市) 在 2024-01-01 backtest 通過 (那時還活著)", '2342' in filt)
# 用更早 backtest date 測「未上市」排除
filt0 = universe_filter(['2330', '6741'], '20200101', listing)
check("6741 (2021 上市) 在 2020-01-01 backtest 排除 (尚未上市)", '6741' not in filt0)
check("2330 在 2020-01-01 backtest 通過 (1994 早上市)", '2330' in filt0)
filt2 = universe_filter(['2342'], '20240701', listing)
check("2342 在 2024-07-01 backtest 排除 (已下市)", '2342' not in filt2)
filt3 = universe_filter(['2330'], '20240101', None)
check("無 listing_data 跳過 filter + 印警告", '2330' in filt3)

# ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3430_market_fix: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
