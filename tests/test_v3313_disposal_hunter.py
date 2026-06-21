# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.30.13 ⚠️ 處置股獵手 測試"""
import sys
sys.path.insert(0, '.')

from master_profile import (
    _compute_disposal_metrics, compute_operation_metrics,
    generate_labels, generate_narrative, THRESH,
)

all_pass = True
print("=" * 64)
print("  v3.30.13 ⚠️ 處置股獵手 測試")
print("=" * 64)


def mk_trade(code, amt):
    return {'date': '20260530', 'stock_code': code, 'stock_name': f'股{code}',
            'buy_lot': max(1, amt // 100), 'sell_lot': 0,
            'buy_amt': amt, 'sell_amt': 0,
            'is_limit_up': True, 'trade_style': 'partial',
            'limit_up_price': 100.0}


# 合成處置股 set
DISPOSAL = {'1133', '2302', '2369', '3189'}


# ─── 1. _compute_disposal_metrics 基本 ───
print("\n1. 5 筆: 3 檔在處置 (300k) + 2 檔正常 (200k) → 60% disposal_ratio")
trades = [
    mk_trade('1133', 100_000),  # 處置
    mk_trade('2302', 100_000),  # 處置
    mk_trade('2369', 100_000),  # 處置
    mk_trade('2330', 100_000),  # 正常 (台積電不在 DISPOSAL)
    mk_trade('2454', 100_000),  # 正常
]
m = _compute_disposal_metrics(trades, DISPOSAL)
ok = (m['disposal_stocks_count'] == 3
      and 0.59 <= m['disposal_amt_ratio'] <= 0.61)
print(f"  {'OK' if ok else 'FAIL'} count={m['disposal_stocks_count']}, "
      f"ratio={m['disposal_amt_ratio']}")
if not ok: all_pass = False

# ─── 2. trades 空 → None ───
print("\n2. trades=[] → None")
ok = _compute_disposal_metrics([], DISPOSAL) is None
print(f"  {'OK' if ok else 'FAIL'}")
if not ok: all_pass = False

# ─── 3. disposal_codes=None → None (向後相容) ───
print("\n3. disposal_codes=None → None (向後相容既有 test_v3308/9/11/12)")
ok = _compute_disposal_metrics(trades, None) is None
print(f"  {'OK' if ok else 'FAIL'}")
if not ok: all_pass = False

# ─── 4. compute_operation_metrics 不帶 disposal → 不含 disposal metric ───
print("\n4. compute_operation_metrics 不帶 disposal → op 不含 disposal_amt_ratio")
op_no = compute_operation_metrics(trades)   # 不帶 industry 也不帶 disposal
ok = 'disposal_amt_ratio' not in op_no
print(f"  {'OK' if ok else 'FAIL'}")
if not ok: all_pass = False

# ─── 5. 處置股獵手式: 80% 在處置股 → ⚠️ 觸發 ───
print("\n5. 80% buy_amt 在處置股 → 觸發 ⚠️處置股獵手")
hunter_trades = [
    mk_trade('1133', 400_000),  # 處置
    mk_trade('2302', 400_000),  # 處置
    mk_trade('2330', 200_000),  # 正常
]
op_h = compute_operation_metrics(hunter_trades, disposal_codes=DISPOSAL)
timing = {'active_days': 3, 'total_window_days': 5, 'active_days_ratio': 0.6,
          'max_streak_days': 3, 'avg_streak_days': 3.0, 'streak_count': 1,
          'avg_trades_per_active_day': 1.0, 'weekday_distribution': {}}
labels_h = generate_labels(op_h, timing)
ok = '⚠️ 處置股獵手' in labels_h and op_h['disposal_amt_ratio'] > 0.7
print(f"  {'OK' if ok else 'FAIL'} labels={labels_h}, disposal_ratio={op_h['disposal_amt_ratio']}")
if not ok: all_pass = False

# ─── 6. 一般 master: 0% 處置股 → 不觸發 ───
print("\n6. 0% 處置股 → 不觸發 ⚠️")
normal_trades = [mk_trade('2330', 100_000), mk_trade('2454', 100_000)]
op_n = compute_operation_metrics(normal_trades, disposal_codes=DISPOSAL)
labels_n = generate_labels(op_n, timing)
ok = '⚠️ 處置股獵手' not in labels_n and op_n['disposal_amt_ratio'] == 0
print(f"  {'OK' if ok else 'FAIL'} labels={labels_n}")
if not ok: all_pass = False

# ─── 7. 邊界: 剛好 30% (閾值) → 不觸發 (> 30 才觸發) ───
print("\n7. 邊界: 剛好 30% → 不觸發 (嚴格 > 30)")
edge_trades = [
    mk_trade('1133', 300_000),  # 處置 30%
    mk_trade('2330', 700_000),  # 正常 70%
]
op_e = compute_operation_metrics(edge_trades, disposal_codes=DISPOSAL)
labels_e = generate_labels(op_e, timing)
ok = '⚠️ 處置股獵手' not in labels_e   # 剛好 0.30 不 > 0.30
print(f"  {'OK' if ok else 'FAIL'} 30% → labels={labels_e}, ratio={op_e['disposal_amt_ratio']}")
if not ok: all_pass = False

# ─── 8. narrative 含「⚠️ 處置股部位 X% (N 檔)」 ───
print("\n8. narrative 顯示處置股部位")
narr = generate_narrative('處置獵人', op_h, timing, labels_h)
ok = '處置股部位' in narr and '⚠️' in narr
print(f"  {'OK' if ok else 'FAIL'} narrative 含處置股提示")
print(f"    narrative: {narr}")
if not ok: all_pass = False

print()
print("─" * 64)
print(f"  整體: {'OK ALL PASS' if all_pass else 'FAIL HAS FAIL'}")
sys.exit(0 if all_pass else 1)
