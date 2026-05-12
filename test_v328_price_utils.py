"""v3.28 精確漲跌停價計算測試

驗證:
  1. get_tick_size 各區間
  2. calc_limit_up_price 真實 case (5/12 11 個可疑漲停股)
  3. calc_limit_down_price 對稱性
  4. is_limit_up_exact 抓出 false positive (睿生光電)
"""
import sys
sys.path.insert(0, '.')

from price_utils import (
    get_tick_size, calc_limit_up_price, calc_limit_down_price,
    is_limit_up_exact, is_limit_down_exact,
)

print("=" * 70)
print("  v3.28 price_utils 測試 (5/12 真實案例)")
print("=" * 70)

# ────────────────── 1. get_tick_size ──────────────────
print("\n1. get_tick_size 區間驗證")
tick_cases = [
    (5.0, 0.01),   # < 10
    (9.99, 0.01),
    (10.0, 0.05),  # 10~50 區間
    (49.99, 0.05),
    (50.0, 0.1),   # 50~100
    (99.99, 0.1),
    (100.0, 0.5),  # 100~500
    (499.99, 0.5),
    (500.0, 1.0),  # 500~1000
    (999.99, 1.0),
    (1000.0, 5.0), # >= 1000
    (5000.0, 5.0),
]
ok_count = 0
for price, expected in tick_cases:
    actual = get_tick_size(price)
    ok = actual == expected
    if ok: ok_count += 1
    print(f"  {'✅' if ok else '❌'} price={price} → tick={actual} (expect {expected})")
print(f"  小計: {ok_count}/{len(tick_cases)}")

# ────────────────── 2. calc_limit_up_price (5/12 真實 case) ──────────────────
print("\n2. calc_limit_up_price — 5/12 收盤 11 筆 near_boundary 個股")
# (name, prev_close, today_close, expected_limit_up_price, today_actually_limit_up)
lu_cases = [
    ("祥碩(5269)",   1390.0,  1525.0, 1525.0,  True),   # tick 5
    ("彩晶(6116)",      9.71,  10.65,  10.65,  True),   # tick 0.05
    ("愛普*(6531)",   962.0,  1055.0, 1055.0,  True),   # tick 5 (raw 1058 → 1055)
    ("廣穎(4973)",    109.5,   120.0,  120.0,  True),   # tick 0.5
    ("信昌電(6173)",  134.0,   147.0,  147.0,  True),   # tick 0.5
    ("凌航(3135)",    194.5,   213.5,  213.5,  True),   # tick 0.5
    ("凌巨(8105)",     13.45,   14.75,  14.75, True),   # tick 0.05
    ("楠梓電(2316)",  123.5,   135.5,  135.5,  True),   # tick 0.5
    ("睿生光電(6861)", 389.0,   426.0,  427.5, False),  # 收 426, 漲停 427.5 → NOT limit-up
    ("光環(3234)",     97.5,   107.0,  107.0,  True),   # raw 107.25 tick 0.5 (raw 區間 100+) → 107.0
    ("陽程(3498)",    102.5,   112.5,  112.5,  True),   # tick 0.5
    # 額外 sanity case: 台積電 close 在漲停下面
    ("台積電(2330)",  2290.0, 2510.0, 2515.0, False),  # raw 2519, tick 5 → 2515. close 2510 < 2515 → False
    ("台積電@LU",    2290.0, 2515.0, 2515.0, True),    # 同股,close 剛好 = 漲停價 → True
]
lu_ok = 0
for name, prev_c, close, expected_lu, expected_is_lu in lu_cases:
    actual_lu = calc_limit_up_price(prev_c)
    lu_match = abs(actual_lu - expected_lu) < 0.005
    actual_is_lu = is_limit_up_exact(close, prev_c)
    is_match = actual_is_lu == expected_is_lu
    overall_ok = lu_match and is_match
    if overall_ok: lu_ok += 1
    icon = "✅" if overall_ok else "❌"
    print(f"  {icon} {name:<14} prev={prev_c:<7} → 漲停={actual_lu} (expect {expected_lu}) | "
          f"close={close} is_limit_up={actual_is_lu} (expect {expected_is_lu})")
print(f"  小計: {lu_ok}/{len(lu_cases)}")

# ────────────────── 3. calc_limit_down_price (對稱性) ──────────────────
print("\n3. calc_limit_down_price 跌停價對稱檢查")
ld_cases = [
    # prev_close, expected_ld
    (100.0, 90.0),     # 100*0.9=90, tick 0.1 (raw 90 落在 50~100 區間), floor(90/0.1)*0.1=90
    (1000.0, 900.0),   # 1000*0.9=900, tick 1 (500~1000 區間), 900
    (10.0, 9.0),       # 10*0.9=9, tick 0.01 (<10), 9.00
    (50.0, 45.0),      # 50*0.9=45, tick 0.05 (10~50), 45.0
]
ld_ok = 0
for prev_c, expected_ld in ld_cases:
    actual_ld = calc_limit_down_price(prev_c)
    ok = abs(actual_ld - expected_ld) < 0.01
    if ok: ld_ok += 1
    print(f"  {'✅' if ok else '❌'} prev={prev_c} → 跌停={actual_ld} (expect {expected_ld})")
print(f"  小計: {ld_ok}/{len(ld_cases)}")

# ────────────────── 4. False Positive 抓得到嗎 (核心 case) ──────────────────
print("\n4. 核心 case: 睿生光電 5/12 False Positive 偵測")
# 睿生光電 prev=389, 今收 426. 9.5% threshold 標漲停. 但精確算法應 NOT 漲停.
prev_c = 389.0
close = 426.0
api_change_pct = 9.51
print(f"  個股: 睿生光電 prev_close={prev_c} close={close} API change_pct={api_change_pct}%")
old_logic = api_change_pct >= 9.5
new_logic = is_limit_up_exact(close, prev_c)
limit_price = calc_limit_up_price(prev_c)
print(f"  舊邏輯 (>=9.5%): is_limit_up={old_logic}  ← 標漲停 (False Positive)")
print(f"  新邏輯 (精確價): 漲停價={limit_price}, 今收={close} → is_limit_up={new_logic}")
fp_caught = (old_logic == True and new_logic == False)
print(f"  {'✅ FP 成功攔截' if fp_caught else '❌ FP 沒攔到'}")

# ────────────────── Summary ──────────────────
total = len(tick_cases) + len(lu_cases) + len(ld_cases) + 1
total_ok = ok_count + lu_ok + ld_ok + (1 if fp_caught else 0)
print()
print("─" * 70)
print(f"  整體: {total_ok}/{total} {'✅ ALL PASS' if total_ok == total else '❌ HAS FAIL'}")
sys.exit(0 if total_ok == total else 1)
