"""v3.27.2 高價股盲點修補測試 — 用截圖中真實案例驗證反推邏輯

3 個案例 (5/8 國票-安和 779Z, 張濬安/航海王):
  - 創意(3443) close=5210 buy_amt=54376萬 → expect buy_lot ≈ 104
  - 緯穎(6669) close=5200 buy_amt=8955萬 → expect buy_lot ≈ 17
  - 台積電(2330) close=2290 buy_amt=12446萬 → expect buy_lot ≈ 54

注意: crawler 內部 buy_amt 單位是「仟元」, Excel 顯示時除以 10 變「萬元」。
       所以 Excel 「54,376 萬元」對應 crawler 內 buy_amt = 543,760 仟元。
       反推公式: lot = amt(仟元) / close(元/股) → 54376*10/5210 = 104.4 張
"""
import sys

# 模擬 crawler.py 內 lot 反推邏輯 (直接在這裡重寫小函式)
def estimate_lot_from_close(buy_amt_k, sell_amt_k, buy_lot_raw, sell_lot_raw, close):
    s = {
        "buy_amt": buy_amt_k, "sell_amt": sell_amt_k,
        "buy_lot": buy_lot_raw, "sell_lot": sell_lot_raw,
    }
    if not close or close <= 0:
        return s, "twse"
    estimated = False
    if buy_lot_raw == 0 and buy_amt_k > 0:
        s["buy_lot"] = round(buy_amt_k / close)
        s["buy_avg"] = round(close, 2)
        estimated = True
    if sell_lot_raw == 0 and sell_amt_k > 0:
        s["sell_lot"] = round(sell_amt_k / close)
        s["sell_avg"] = round(close, 2)
        estimated = True
    if buy_amt_k == 0 and buy_lot_raw > 0:
        s["buy_amt"] = int(round(buy_lot_raw * close))
        estimated = True
    if sell_amt_k == 0 and sell_lot_raw > 0:
        s["sell_amt"] = int(round(sell_lot_raw * close))
        estimated = True
    return s, "estimated_from_close" if estimated else "twse"


print("=" * 70)
print("  v3.27.2 高價股反推張數驗證 (5/8 國票-安和 779Z 張濬安)")
print("=" * 70)
# Excel 萬元 → crawler 仟元 = ×10
cases = [
    # name, close, buy_amt_K, buy_lot_raw, expected_lot
    ("創意(3443)",  5210,  54376 * 10, 0, 104),
    ("緯穎(6669)",  5200,   8955 * 10, 0,  17),
    ("台積電(2330)", 2290, 12446 * 10, 0,  54),
    ("南亞科(2408)", 274,  27784 * 10, 923, 923),  # 已有真實 lot,不應改
    ("世界(5347)",  167.5, 17411 * 10, 1020, 1020),  # 已有真實 lot
]

all_pass = True
for name, close, buy_amt_k, buy_lot_raw, expected_lot in cases:
    result, source = estimate_lot_from_close(buy_amt_k, 0, buy_lot_raw, 0, close)
    actual = result["buy_lot"]
    tol = max(2, expected_lot * 0.05)  # 容差 5% 或 2 張
    ok = abs(actual - expected_lot) <= tol
    expected_source = "estimated_from_close" if buy_lot_raw == 0 else "twse"
    source_ok = source == expected_source
    icon = "✅" if (ok and source_ok) else "❌"
    print(f"  {icon} {name:<14} close={close:>7}  amt_K={buy_amt_k:>8} lot_raw={buy_lot_raw:>5}  "
          f"→ lot={actual:>5} (expect ~{expected_lot}, ±{tol:.0f}) src={source}")
    if not (ok and source_ok):
        all_pass = False

# 反向 case: 低價股 amt=0, lot>0
print()
print("  反向 case: 低價股 amt 漏 → 反推金額")
result, source = estimate_lot_from_close(0, 0, 3559, 305, 32.17)  # 群創
print(f"  群創(3481) close=32.17 lot=3559: buy_amt 估算 = {result['buy_amt']} 仟元 = {result['buy_amt']/10:.0f} 萬元")
expected_amt = round(3559 * 32.17)
print(f"    expect {expected_amt} 仟元 = {expected_amt/10:.0f} 萬元 (= Excel 顯示 ~11,449 萬,有差因 32.17 vs 實際買均 32.17)")
print(f"    src={source} (應為 estimated_from_close)")
if abs(result['buy_amt'] - expected_amt) > 5 or source != "estimated_from_close":
    all_pass = False
    print("    ❌ FAIL")
else:
    print("    ✅ PASS")

print()
print("─" * 70)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ FAIL'}")
sys.exit(0 if all_pass else 1)
