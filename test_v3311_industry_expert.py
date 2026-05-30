"""v3.30.11 🎯 族群專家 標籤測試"""
import sys
sys.path.insert(0, '.')

from master_profile import (
    _compute_industry_metrics, compute_operation_metrics,
    generate_labels, generate_narrative, THRESH,
)

all_pass = True
print("=" * 64)
print("  v3.30.11 🎯 族群專家 測試")
print("=" * 64)

# 合成 industry_map (簡化版, 模擬 industry_classifier 結構)
INDUSTRY_MAP = {
    '2330': '半導體業', '2454': '半導體業', '2308': '半導體業',
    '2603': '航運業', '2609': '航運業', '2615': '航運業',
    '2317': '其他電子業', '2207': '汽車工業',
}


def mk_trade(date, code, amt):
    return {'date': date, 'stock_code': code, 'stock_name': f'股{code}',
            'buy_lot': max(1, amt // 100), 'sell_lot': 0,
            'buy_amt': amt, 'sell_amt': 0,
            'is_limit_up': False, 'trade_style': 'overnight'}


# ── 1. _compute_industry_metrics 基本 ──
print("\n1. _compute_industry_metrics: 4 半導體 + 1 航運 → top 半導體 ~80%")
trades = [
    mk_trade('20260520', '2330', 100_000),
    mk_trade('20260521', '2454', 80_000),
    mk_trade('20260522', '2308', 60_000),
    mk_trade('20260525', '2603', 60_000),   # 航運 60K vs 半導體合 240K → 半導體 80%
]
result = _compute_industry_metrics(trades, INDUSTRY_MAP)
ok = (result is not None
      and result['top_industry'] == '半導體業'
      and 79 <= result['top_industry_pct'] <= 81
      and result['industry_count'] == 2)
print(f"  {'OK' if ok else 'FAIL'} top={result['top_industry'] if result else None}, "
      f"pct={result['top_industry_pct'] if result else None}, "
      f"count={result['industry_count'] if result else None}")
if not ok: all_pass = False

# ── 2. _compute_industry_metrics 無 map → None (向後相容) ──
print("\n2. stock_industry_map=None → None (向後相容)")
ok = _compute_industry_metrics(trades, None) is None
print(f"  {'OK' if ok else 'FAIL'} 無 map → None")
if not ok: all_pass = False

# ── 3. compute_operation_metrics 帶 map → 含 top_industry ──
print("\n3. compute_operation_metrics 帶 map → 含族群 metrics")
op = compute_operation_metrics(trades, INDUSTRY_MAP)
ok = 'top_industry' in op and 'top_industry_pct' in op and 'top3_industries' in op
print(f"  {'OK' if ok else 'FAIL'} op keys 含 top_industry/top_industry_pct/top3_industries")
if not ok: all_pass = False

# ── 4. compute_operation_metrics 不帶 map → 不含 top_industry (向後相容) ──
print("\n4. 不帶 map → op 不含族群欄位 (向後相容 test_v3308/v3309)")
op_no_ind = compute_operation_metrics(trades)
ok = 'top_industry' not in op_no_ind
print(f"  {'OK' if ok else 'FAIL'} op 無 top_industry 欄位")
if not ok: all_pass = False

# ── 5. 航海王式: 80% 航運 → 觸發 🎯族群專家 ──
print("\n5. 航海王式: 80% 航運 → 觸發 🎯 族群專家")
ship_trades = [
    mk_trade('20260520', '2603', 200_000),
    mk_trade('20260521', '2609', 180_000),
    mk_trade('20260522', '2615', 170_000),
    mk_trade('20260525', '2317', 80_000),   # 1 檔其他電子 80K vs 航運 550K → 航運 87%
]
op_ship = compute_operation_metrics(ship_trades, INDUSTRY_MAP)
timing = {'active_days': 4, 'total_window_days': 5, 'active_days_ratio': 0.8,
          'max_streak_days': 4, 'avg_streak_days': 4.0, 'streak_count': 1,
          'avg_trades_per_active_day': 1.0, 'weekday_distribution': {}}
labels = generate_labels(op_ship, timing)
ok = '🎯 族群專家' in labels and op_ship['top_industry'] == '航運業'
print(f"  {'OK' if ok else 'FAIL'} labels={labels}")
print(f"    top_industry={op_ship['top_industry']} ({op_ship['top_industry_pct']:.0f}%)")
if not ok: all_pass = False

# ── 6. 民哥式: 分散多族群 → 不觸發 ──
print("\n6. 分散多族群 (每族群 < 60%) → 不觸發 🎯族群專家")
diverse_trades = [
    mk_trade('20260520', '2330', 100_000),  # 半導體
    mk_trade('20260521', '2603', 100_000),  # 航運
    mk_trade('20260522', '2207', 100_000),  # 汽車
    mk_trade('20260525', '2317', 100_000),  # 其他電子
]
op_div = compute_operation_metrics(diverse_trades, INDUSTRY_MAP)
labels_div = generate_labels(op_div, timing)
ok = '🎯 族群專家' not in labels_div and op_div['top_industry_pct'] <= THRESH['top_industry_pct_high']
print(f"  {'OK' if ok else 'FAIL'} labels={labels_div}, top_pct={op_div['top_industry_pct']:.0f}%")
if not ok: all_pass = False

# ── 7. narrative 顯示「主攻 X 族群」 ──
print("\n7. narrative 顯示主攻族群")
narr = generate_narrative('航海王', op_ship, timing, labels)
ok = '航運業' in narr or '航運' in narr
print(f"  {'OK' if ok else 'FAIL'} narrative 含族群名")
print(f"    narrative: {narr}")
if not ok: all_pass = False

# ── 8. 邊界: 全部「未分類」(map 沒覆蓋的 code) ──
print("\n8. 邊界: 全部未分類 code → top_industry='未分類', 仍可觸發族群專家 (集中度)")
unknown_trades = [mk_trade('20260520', 'XXXX', 500_000),
                  mk_trade('20260521', 'YYYY', 500_000)]
op_unk = compute_operation_metrics(unknown_trades, INDUSTRY_MAP)
labels_unk = generate_labels(op_unk, timing)
# 100% 未分類 → top_industry='未分類', top_pct=100, 觸發族群專家 (因 100>60)
ok = op_unk['top_industry'] == '未分類' and '🎯 族群專家' in labels_unk
print(f"  {'OK' if ok else 'FAIL'} top={op_unk['top_industry']} ({op_unk['top_industry_pct']}%), "
      f"labels={labels_unk}")
# 註: 未分類觸發族群專家可能誤導, 是已知限制
print("  NOTE: 全部未分類股觸發族群專家 = 已知限制, 真實使用時 industry_map 應涵蓋大多數")
if not ok: all_pass = False

print()
print("─" * 64)
print(f"  整體: {'OK ALL PASS' if all_pass else 'FAIL HAS FAIL'}")
sys.exit(0 if all_pass else 1)
