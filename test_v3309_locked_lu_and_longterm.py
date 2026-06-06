"""v3.30.9 🔒鎖漲停 + 📈長線持有 標籤測試"""
import sys
sys.path.insert(0, '.')

from master_profile import (
    _derive_limit_up_price, _is_locked_at_lu, _compute_long_term_metrics,
    compute_operation_metrics, generate_labels, generate_narrative,
    extract_master_trades, build_master_profile, THRESH,
)

all_pass = True
print("=" * 64)
print("  v3.30.9 🔒鎖漲停 + 📈長線持有 測試")
print("=" * 64)


def mk_stock(code, buy_lot, buy_amt, lu_price=None, prev_close=None, style='partial'):
    """合成 stock dict, 支援 limit_up_price / prev_close 注入."""
    s = {'code': code, 'name': f'股{code}', 'buy_lot': buy_lot, 'buy_amt': buy_amt,
         'sell_lot': 0, 'sell_amt': 0, 'is_limit_up': True, 'trade_style': style}
    if lu_price is not None:
        s['limit_up_price'] = lu_price
    if prev_close is not None:
        s['prev_close'] = prev_close
    return s


# ─── 1. _derive_limit_up_price ───
print("\n1. _derive_limit_up_price 三層 fallback")
# 1a. 直接欄位
ok1a = _derive_limit_up_price({'limit_up_price': 100.0}) == 100.0
# 1b. 從 prev_close (有 price_utils tick 精確)
lu = _derive_limit_up_price({'prev_close': 100.0})
ok1b = lu is not None and 109.5 <= lu <= 110.5   # tick 容忍
# 1c. 都沒 → None
ok1c = _derive_limit_up_price({}) is None
print(f"  {'OK' if ok1a and ok1b and ok1c else 'FAIL'} 直接={ok1a}, prev_close={ok1b} (lu={lu}), 無資料={ok1c}")
if not (ok1a and ok1b and ok1c): all_pass = False

# ─── 2. _is_locked_at_lu 判定 ───
print("\n2. _is_locked_at_lu: 買均 vs 漲停價判定")
# 蔣承翰式: 漲停價 100, 買均 100 (鎖死) → True
ok2a = _is_locked_at_lu(mk_stock('A', 100, 10_000, lu_price=100), 0.99)  # avg=100
# 0.5% 內: avg 99.5 vs lu 100 → True
ok2b = _is_locked_at_lu(mk_stock('B', 100, 9_950, lu_price=100), 0.99)
# 2% 外: avg 98 vs lu 100 → False (容忍 1%)
ok2c = not _is_locked_at_lu(mk_stock('C', 100, 9_800, lu_price=100), 0.99)
# buy_lot=0 → False
ok2d = not _is_locked_at_lu(mk_stock('D', 0, 0, lu_price=100), 0.99)
# 無 lu_price 且無 prev_close → False
ok2e = not _is_locked_at_lu(mk_stock('E', 100, 10_000), 0.99)
print(f"  {'OK' if all([ok2a,ok2b,ok2c,ok2d,ok2e]) else 'FAIL'} 鎖死={ok2a} 容忍內={ok2b} 容忍外={ok2c} 零張={ok2d} 無漲停價={ok2e}")
if not all([ok2a,ok2b,ok2c,ok2d,ok2e]): all_pass = False

# ─── 3. _compute_long_term_metrics ───
print("\n3. _compute_long_term_metrics: 單檔被加碼 ≥ N 天")
# fixture: 3443 連續 6 天加碼 (達標), 2330 只 2 天 (不達標)
trades = []
for d in ['20260520', '20260521', '20260522', '20260525', '20260526', '20260527']:
    trades.append({'date': d, 'stock_code': '3443', 'buy_amt': 100_000, 'buy_lot': 50})
for d in ['20260520', '20260521']:
    trades.append({'date': d, 'stock_code': '2330', 'buy_amt': 50_000, 'buy_lot': 20})
lt_count, lt_ratio = _compute_long_term_metrics(trades, days_threshold=5)
# 3443: 600,000 / total 700,000 = 0.857
ok3 = lt_count == 1 and 0.85 <= lt_ratio <= 0.86
print(f"  {'OK' if ok3 else 'FAIL'} 長線股數={lt_count} (應 1), 占比={lt_ratio} (應 ~0.857)")
if not ok3: all_pass = False

# ─── 4. 蔣承翰式: 漲停獵手 + 🔒鎖漲停 + 短打型 ───
print("\n4. 蔣承翰式 trades → 漲停獵手 + 🔒鎖漲停 + 短打型")
# 所有 trades 都鎖漲停 (買均 = 漲停價)
sniper_trades = []
for d in ['20260520', '20260521', '20260522']:
    sniper_trades.append({'date': d, 'stock_code': '3443', 'stock_name': '創意',
                          'buy_lot': 100, 'sell_lot': 0, 'buy_amt': 50_000_000, 'sell_amt': 0,
                          'is_limit_up': True, 'trade_style': 'partial',
                          'limit_up_price': 500_000.0})   # 仟元/張(=元/股) avg=500_000
# 注意: buy_avg = 50_000_000 仟元 / 100 張 = 500_000 元/股, 等於 limit_up_price → 鎖死
op = compute_operation_metrics(sniper_trades)
# 模擬 timing
timing = {'active_days': 3, 'total_window_days': 3, 'active_days_ratio': 1.0,
          'max_streak_days': 3, 'avg_streak_days': 3.0, 'streak_count': 1,
          'avg_trades_per_active_day': 1.0, 'weekday_distribution': {}}
labels = generate_labels(op, timing)
expected = {'漲停獵手', '🔒 鎖漲停', '短打型'}
ok4 = expected.issubset(set(labels))
print(f"  {'OK' if ok4 else 'FAIL'} labels={labels}")
print(f"    locked_ratio_amt={op['limit_up_locked_ratio_amt']}")
if not ok4: all_pass = False

# ─── 5. 迷你哥式: 漲停獵手 ✓ 但 🔒鎖漲停 ✗ (買均低於漲停價) ───
print("\n5. 迷你哥式: 漲停股當沖 (買均 < 漲停價) → 漲停獵手 但 不鎖漲停")
mini_trades = []
for d in ['20260520', '20260521', '20260522']:
    # 漲停價 100, 買均 90 (盤中買, 沒鎖) → 漲停獵手 ✓ 鎖漲停 ✗
    mini_trades.append({'date': d, 'stock_code': '3443', 'stock_name': '創意',
                        'buy_lot': 100, 'sell_lot': 95, 'buy_amt': 9_000, 'sell_amt': 9_500,
                        'is_limit_up': True, 'trade_style': 'daytrade',
                        'limit_up_price': 100.0})   # avg = 9000/100 = 90 元/股
op_m = compute_operation_metrics(mini_trades)
timing_m = timing  # 同前
labels_m = generate_labels(op_m, timing_m)
ok5 = '漲停獵手' in labels_m and '🔒 鎖漲停' not in labels_m and '當沖客' in labels_m
print(f"  {'OK' if ok5 else 'FAIL'} labels={labels_m} (應有漲停獵手+當沖客, 無🔒)")
print(f"    locked_ratio_amt={op_m['limit_up_locked_ratio_amt']} (應 0)")
if not ok5: all_pass = False

# ─── 6. 民哥式: 波段囤貨(中短期) — 沒長線 ───
print("\n6. 民哥式: overnight 高 + 單檔加碼 < 5 天 → 波段囤貨(中短期)")
swing_trades = []
# 多檔股票, 每檔只 1-2 天加碼
for c, days_used in [('2330', 2), ('2317', 1), ('2454', 1)]:
    for i in range(days_used):
        swing_trades.append({'date': f'2026052{i}', 'stock_code': c, 'stock_name': f'股{c}',
                             'buy_lot': 100, 'sell_lot': 5, 'buy_amt': 50_000, 'sell_amt': 2_500,
                             'is_limit_up': False, 'trade_style': 'overnight'})
op_sw = compute_operation_metrics(swing_trades)
labels_sw = generate_labels(op_sw, timing)
ok6 = '📈 長線持有' not in labels_sw   # v3.31.23: 波段不再標, 只確認不是長線
print(f"  {'OK' if ok6 else 'FAIL'} labels={labels_sw}")
print(f"    long_term_ratio={op_sw['long_term_amt_ratio']} (應 0)")
if not ok6: all_pass = False

# ─── 7. v3.31.10: long_term_days 5→15, 16 天加碼才算長線持有 ───
print("\n7. 林滄海式: overnight 高 + 某檔 16 天連續加碼 → 📈長線持有 (v3.31.10 閾值 15)")
long_trades = []
# 16 天連續加碼 (≥ THRESH['long_term_days_threshold'] = 15)
LONG_DATES = ['20260501','20260502','20260503','20260504','20260505','20260506',
              '20260507','20260508','20260509','20260510','20260511','20260512',
              '20260513','20260514','20260515','20260516']
for d in LONG_DATES:
    long_trades.append({'date': d, 'stock_code': '2317', 'stock_name': '鴻海',
                        'buy_lot': 200, 'sell_lot': 10, 'buy_amt': 200_000, 'sell_amt': 10_000,
                        'is_limit_up': False, 'trade_style': 'overnight'})
op_lt = compute_operation_metrics(long_trades)
labels_lt = generate_labels(op_lt, timing)
ok7 = '📈 長線持有' in labels_lt and '波段囤貨(中短期)' not in labels_lt
print(f"  {'OK' if ok7 else 'FAIL'} labels={labels_lt}")
print(f"    long_term_ratio={op_lt['long_term_amt_ratio']}")
if not ok7: all_pass = False

# ─── 8. narrative 含 🔒鎖漲停 + 長線部位資訊 ───
print("\n8. narrative 包含鎖漲停% + 長線檔數")
narr = generate_narrative('蔣承翰', op, timing, labels)
ok8 = '🔒鎖漲停' in narr or '鎖漲停' in narr
print(f"  {'OK' if ok8 else 'FAIL'} narrative 含鎖漲停資訊")
print(f"    narrative: {narr}")
if not ok8: all_pass = False

# ─── 9. 邊界: 漲停股但 buy_lot=0 → 不算鎖漲停, 不崩潰 ───
print("\n9. 邊界: buy_lot=0 → 不崩潰且不算鎖漲停")
edge = [{'date': '20260520', 'stock_code': 'X', 'stock_name': 'X', 'buy_lot': 0,
         'sell_lot': 0, 'buy_amt': 0, 'sell_amt': 0,
         'is_limit_up': True, 'trade_style': 'unknown', 'limit_up_price': 100.0}]
try:
    op_edge = compute_operation_metrics(edge)
    ok9 = op_edge['limit_up_locked_ratio_amt'] == 0 and op_edge['long_term_amt_ratio'] == 0
    print(f"  {'OK' if ok9 else 'FAIL'} 邊界 case 不崩潰, locked=0")
except Exception as e:
    print(f"  FAIL 崩潰: {e}")
    ok9 = False
if not ok9: all_pass = False

print()
print("─" * 64)
print(f"  整體: {'OK ALL PASS' if all_pass else 'FAIL HAS FAIL'}")
sys.exit(0 if all_pass else 1)
