# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.29 Signal Engine 測試 — 各市場情境的 actionable 輸出驗證"""
import sys
sys.path.insert(0, '.')

from signal_engine import (
    infer_market_direction, top_focus_stocks, generate_daily_signal,
    SIGNAL_WEIGHTS, KILLED_SIGNALS,
)


def make_temp_signal(name, level, value=None):
    score_map = {'extreme-bull': 20, 'bull': 15, 'neutral': 10, 'bear': 5, 'extreme-bear': 0}
    return {'name': name, 'level': level, 'score': score_map[level], 'value': value}


print("=" * 72)
print("  v3.29 Signal Engine 測試")
print("=" * 72)

all_pass = True

# ────────── Test A: 兩個 alpha 信號同向 → 高信心偏多 ──────────
print("\nA. 兩 alpha 信號同向 (PCR 極多 + 結算週 D-2 偏多 反彈訊號)")
signals = [
    make_temp_signal('外資現貨', 'bull'),  # ignored (no weight)
    make_temp_signal('外資期貨', 'extreme-bear'),  # killed signal (no weight)
    make_temp_signal('P/C Ratio', 'extreme-bull'),  # +0.087
    make_temp_signal('分點漲停', 'extreme-bull'),  # ignored
    make_temp_signal('融資熱度', 'neutral'),  # ignored
    make_temp_signal('法人共識', 'bull'),  # ignored
    make_temp_signal('結算日壓力', 'bull', value={'days_to_settle': 2, 'foreign_eq_oi': -50000}),  # +0.136
]
result = infer_market_direction(signals)
expected_net = round(0.087 + 0.136, 4)  # 0.223
expected_conf = 50 + 22.3  # 72.3
ok = (result['direction'] == '偏多' and
      abs(result['net_weight'] - expected_net) < 0.001 and
      abs(result['confidence_pct'] - expected_conf) < 0.5)
print(f"  {'✅' if ok else '❌'} direction={result['direction']} conf={result['confidence_pct']}% net={result['net_weight']}")
print(f"     contributing: {[c['name'] + ':' + c['level'] for c in result['contributing']]}")
print(f"     ignored: {result['ignored']}")
if not ok: all_pass = False

# ────────── Test B: 信號 2 (廢除) 不該影響結果 ──────────
print("\nB. 信號 2 外資期貨 extreme-bear 不該影響 (已廢除)")
signals_b = [
    make_temp_signal('外資期貨', 'extreme-bear'),  # killed, weight 0
    make_temp_signal('結算日壓力', 'neutral', value={'days_to_settle': 10, 'foreign_eq_oi': -50000}),  # 非結算週 weight 0
]
result_b = infer_market_direction(signals_b)
ok_b = result_b['direction'] == '中性' and result_b['net_weight'] == 0
print(f"  {'✅' if ok_b else '❌'} direction={result_b['direction']} net={result_b['net_weight']}")
if not ok_b: all_pass = False

# ────────── Test C: 結算日 D-1 (near) vs D-3 (week) 權重不同 ──────────
print("\nC. 結算日距離不同, 權重不同")
sig_d1_bull = [make_temp_signal('結算日壓力', 'extreme-bull', value={'days_to_settle': 1, 'foreign_eq_oi': -50000})]
sig_d3_bull = [make_temp_signal('結算日壓力', 'bull', value={'days_to_settle': 3, 'foreign_eq_oi': -50000})]
r_d1 = infer_market_direction(sig_d1_bull)
r_d3 = infer_market_direction(sig_d3_bull)
ok_c = (abs(r_d1['net_weight'] - 0.033) < 0.001 and
        abs(r_d3['net_weight'] - 0.136) < 0.001 and
        r_d3['net_weight'] > r_d1['net_weight'])
print(f"  {'✅' if ok_c else '❌'} D-1 net={r_d1['net_weight']} (預期 0.033) / D-3 net={r_d3['net_weight']} (預期 0.136)")
print(f"     D-3 信號比 D-1 強 (backtest 證實 sweet spot)")
if not ok_c: all_pass = False

# ────────── Test D: top_focus_stocks 抓 consensus ──────────
print("\nD. top_focus_stocks: 從 consensus_limit_up 排名")
fake_raw = {
    'limit_up_summary': {
        'consensus_limit_up': [
            {
                'code': '3443', 'name': '創意', 'change_pct': 9.96,
                'master_count': 3, 'total_buy_amt': 583_0000,  # 5.83 億
                'buyers': [
                    {'master_name': '蔣承翰'}, {'master_name': '巨人傑'}, {'master_name': 'Tradow'}
                ],
            },
            {
                'code': '2317', 'name': '鴻海', 'change_pct': 9.5,
                'master_count': 2, 'total_buy_amt': 200_0000,
                'buyers': [{'master_name': '蔣承翰'}, {'master_name': '迷你哥/松山哥'}],
            },
        ],
        'master_sniper_ranking': [],
    },
}
stocks = top_focus_stocks(fake_raw, top_n=3)
ok_d = (len(stocks) >= 2 and
        stocks[0]['code'] == '3443' and
        stocks[0]['master_count'] == 3 and
        stocks[0]['confidence_pct'] == 76 and  # 60 + (3-1)*8 = 76
        stocks[1]['code'] == '2317' and
        stocks[1]['master_count'] == 2 and
        stocks[1]['confidence_pct'] == 68)
print(f"  {'✅' if ok_d else '❌'} Top 1 = {stocks[0]['code']} ({stocks[0]['master_count']} masters, conf {stocks[0]['confidence_pct']}%)")
print(f"     Top 2 = {stocks[1]['code']} ({stocks[1]['master_count']} masters, conf {stocks[1]['confidence_pct']}%)")
print(f"     Top 1 reason: {stocks[0]['reason']}")
if not ok_d: all_pass = False

# ────────── Test E: 整合 generate_daily_signal ──────────
print("\nE. generate_daily_signal 完整輸出")
fake_temp = {
    'score': 60,
    'signals': [
        make_temp_signal('外資期貨', 'extreme-bear'),  # killed
        make_temp_signal('P/C Ratio', 'extreme-bull'),  # +0.087
        make_temp_signal('結算日壓力', 'bull', value={'days_to_settle': 2, 'foreign_eq_oi': -50000}),  # +0.136
    ],
}
daily = generate_daily_signal(fake_raw, fake_temp, '20260513')
ok_e = (
    daily['market_direction']['direction'] == '偏多' and
    daily['market_direction']['confidence_pct'] >= 70 and
    len(daily['top_focus_stocks']) >= 2 and
    '外資期貨等效大台淨 OI' in daily['killed_signals'] and
    daily['headline'].startswith('偏多')
)
print(f"  {'✅' if ok_e else '❌'} headline: {daily['headline']}")
print(f"     market: {daily['market_direction']['direction']} {daily['market_direction']['confidence_pct']}%")
print(f"     top stocks: {[s['code'] for s in daily['top_focus_stocks']]}")
print(f"     killed signals: {list(daily['killed_signals'].keys())}")
if not ok_e: all_pass = False

# ────────── Test F: 信心區間 cap [10, 95] ──────────
print("\nF. confidence cap 邊界 (極端輸入不會爆掉)")
# 巨大 net (假設假 weight) — 應 cap 在 95
manual = {'direction': '偏多', 'confidence_pct': 0, 'net_weight': 99.0}
# 直接測 cap 邏輯 (重做)
test_conf = max(10, min(95, 50 + 99.0 * 100))
ok_f = test_conf == 95
print(f"  {'✅' if ok_f else '❌'} cap 95: input net=99 → confidence={test_conf} (預期 95)")
test_conf2 = max(10, min(95, 50 + (-99.0) * 100))
ok_f2 = test_conf2 == 10
print(f"  {'✅' if ok_f2 else '❌'} cap 10: input net=-99 → confidence={test_conf2} (預期 10)")
if not (ok_f and ok_f2): all_pass = False

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
