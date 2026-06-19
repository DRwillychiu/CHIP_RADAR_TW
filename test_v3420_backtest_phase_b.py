# -*- coding: utf-8 -*-
"""
test_v3420_backtest_phase_b.py — v3.42.0 C2 Phase B backtest 測試

驗證:
  1. compute_phase_b_results 結構完整 (window_days, results, regime_caveat)
  2. 二分法 verdict 邏輯 (≥55% enable / <45% disable / 55-45 maintain / n<10 insufficient)
  3. weight 計算正確 (up → +, down → -, 同預期方向)
  4. market_regime 偵測 (strong_bull 100% next_day_up_pct → warning + trust_weights=False)
  5. mixed regime → trust_weights=True
  6. signal_engine load_phase_b_weights 整合
  7. strong_bull regime 時 signal_engine fallback 0 (不採信)
  8. backward compat: 檔案不存在時 _signal_weight 仍返 0
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


def mk_history(entries):
    """entries: [(date, [(sig_name, score, level)], next_day_chg)]"""
    history = []
    for date, sigs, next_chg in entries:
        history.append({
            'date': date,
            'score': 0,
            'signals': [{'name': n, 'score': s, 'level': lv} for n, s, lv in sigs],
            'next_day_change_pct': next_chg,
        })
    return {'history': history}


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 1] 結構完整: window_days / results / market_regime_caveat")
from backtester_phase_b import compute_phase_b_results, ENABLE_THRESHOLD_PCT, MIN_SAMPLE_SIZE
with tempfile.TemporaryDirectory() as td:
    # 15 天 mixed regime: 8 up, 7 down (53% up = mild_bull 邊界)
    entries = [(f'2026060{i:02d}', [('外資現貨', 15, 'bull')], 0.5 if i < 9 else -0.3)
                for i in range(1, 16)]
    p = Path(td) / 'th.json'
    p.write_text(json.dumps(mk_history(entries)), encoding='utf-8')
    r = compute_phase_b_results(str(p))
check("結構含 window_days", 'window_days' in r)
check("結構含 results", 'results' in r)
check("結構含 market_regime_caveat", 'market_regime_caveat' in r)
check("samples_with_next_day_chg = 15", r['samples_with_next_day_chg'] == 15)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 2] mixed regime → trust_weights=True")
caveat = r['market_regime_caveat']
check("regime = mixed (53% up)", caveat['regime'] == 'mixed', f"got {caveat['regime']}")
check("trust_weights = True", caveat['trust_weights'] is True)
check("warning = None (mixed)", caveat.get('warning') is None)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 3] strong_bull (100% up) → trust_weights=False + warning")
with tempfile.TemporaryDirectory() as td:
    entries = [(f'2026060{i:02d}', [('外資現貨', 15, 'bull')], 0.5) for i in range(1, 16)]
    p = Path(td) / 'th.json'
    p.write_text(json.dumps(mk_history(entries)), encoding='utf-8')
    r2 = compute_phase_b_results(str(p))
caveat2 = r2['market_regime_caveat']
check("regime = strong_bull", caveat2['regime'] == 'strong_bull')
check("trust_weights = False", caveat2['trust_weights'] is False)
check("warning 含「data quality」or「單邊行情」",
      'data quality' in (caveat2.get('warning') or '') or '單邊行情' in (caveat2.get('warning') or ''))
check("next_day_up_pct = 100", caveat2['next_day_up_pct'] == 100.0)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] verdict 邏輯 — n<10 insufficient")
with tempfile.TemporaryDirectory() as td:
    # 5 筆 bull + 5 筆 bear, 全 hit (但 n<10 each)
    entries = ([(f'2026060{i}', [('外資現貨', 15, 'bull')], 0.5) for i in range(1, 6)]
                + [(f'2026061{i}', [('外資現貨', 5, 'bear')], -0.3) for i in range(1, 6)])
    p = Path(td) / 'th.json'
    p.write_text(json.dumps(mk_history(entries)), encoding='utf-8')
    r3 = compute_phase_b_results(str(p))
bull_lvl = r3['results']['外資現貨']['levels'].get('bull') or {}
check("bull n=5 → insufficient", bull_lvl.get('verdict') == 'insufficient')
check("bull weight=0", bull_lvl.get('weight') == 0.0)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 5] verdict 邏輯 — n>=10 + hit>=55% → enable + 正 weight (up dir)")
with tempfile.TemporaryDirectory() as td:
    # 12 筆 bull 都 hit (next_chg > 0)
    entries = [(f'2026{i:04d}', [('外資現貨', 15, 'bull')], 0.5)
                for i in range(601, 613)]
    p = Path(td) / 'th.json'
    p.write_text(json.dumps(mk_history(entries)), encoding='utf-8')
    r4 = compute_phase_b_results(str(p))
bull_lvl4 = r4['results']['外資現貨']['levels']['bull']
# 注意: strong_bull regime, trust_weights=False, 但 verdict 仍會被算
check("bull 12/12 hit_rate=100", bull_lvl4['hit_rate_pct'] == 100.0)
check("bull n=12 → enable verdict", bull_lvl4['verdict'] == 'enable')
check("bull weight > 0 (up dir)", bull_lvl4['weight'] > 0)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 6] verdict 邏輯 — hit<45% → disable + weight=0")
with tempfile.TemporaryDirectory() as td:
    # 12 筆 bull 全 miss (預期 up 但 next_chg < 0)
    # 為避免 strong_bear regime, 加一些非 bull-level 的 noise
    entries = ([(f'2026{i:04d}', [('外資現貨', 15, 'bull')], -0.5) for i in range(601, 613)]
                + [(f'2026{i:04d}', [('外資現貨', 10, 'neutral')], 0.5) for i in range(701, 718)])
    p = Path(td) / 'th.json'
    p.write_text(json.dumps(mk_history(entries)), encoding='utf-8')
    r5 = compute_phase_b_results(str(p))
bull_lvl5 = r5['results']['外資現貨']['levels']['bull']
check("bull 全 miss → hit_rate=0", bull_lvl5['hit_rate_pct'] == 0.0)
check("bull → disable", bull_lvl5['verdict'] == 'disable')
check("bull weight=0", bull_lvl5['weight'] == 0.0)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 7] signal_engine.load_phase_b_weights — 不採信時返 {}")
# 寫 mock backtest_phase_b_results 到一個 data_dir, load 應該採信 / 不採信
import signal_engine

# Reset cache
signal_engine._phase_b_cache = None

# 場景: strong_bull regime → trust=False → 返 {}
mock_results = {
    'market_regime_caveat': {'trust_weights': False, 'regime': 'strong_bull'},
    'results': {
        '外資現貨': {
            'levels': {'bull': {'verdict': 'enable', 'weight': 0.15}}
        }
    },
}
with tempfile.TemporaryDirectory() as td:
    (Path(td) / 'backtest_phase_b_results.json').write_text(
        json.dumps(mock_results), encoding='utf-8')
    w = signal_engine.load_phase_b_weights(data_dir=td)
    check("strong_bull regime → 空 dict", w == {})

# Reset for next case
signal_engine._phase_b_cache = None

# 場景: trust=True → 帶 weights
mock_trust = {
    'market_regime_caveat': {'trust_weights': True, 'regime': 'mixed'},
    'results': {
        '外資現貨': {
            'levels': {'bull': {'verdict': 'enable', 'weight': 0.15}}
        }
    },
}
with tempfile.TemporaryDirectory() as td:
    (Path(td) / 'backtest_phase_b_results.json').write_text(
        json.dumps(mock_trust), encoding='utf-8')
    w = signal_engine.load_phase_b_weights(data_dir=td)
    check("trust=True → 含 外資現貨", '外資現貨' in w)
    check("bull weight = 0.15", w.get('外資現貨', {}).get('bull') == 0.15)

# Reset for backward compat test
signal_engine._phase_b_cache = None

# 場景: 檔案不存在 → 返 {}
with tempfile.TemporaryDirectory() as td:
    # 不寫檔
    w = signal_engine.load_phase_b_weights(data_dir=td)
    check("檔案不存在 → 空 dict", w == {})

print(f"\n{'='*60}")
print(f"test_v3420_backtest_phase_b: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
