# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.28.1 sniper 模式必須 net buyer 才入選 — 修補 5/13 微星 false positive

5/13 用戶 review chip_radar_2026-05-13.xlsx 發現:
  蔣承翰(隔日沖, sniper) 兩個分點都顯示微星(2377),
  但實際當日微星是淨賣超(賣 > 買), 不應出現在 sniper 漲停清單。

修法: sniper_mode filter 加 net_amt > 0 條件 (或 net_lot > 0)

驗證:
  1. 漲停股 + 淨買 → 入選 ✅
  2. 漲停股 + 淨賣 → 排除 ✅ (核心修補)
  3. 漲停股 + 淨平 (net=0) → 排除 (保守)
  4. 非漲停股 → 排除 (既有邏輯)
  5. net_amt=0 但 net_lot>0 (高價股估算 case) → 入選
  6. net_amt<0 + net_lot<0 一致賣超 → 排除
"""
import sys
sys.path.insert(0, '.')

from excel_report import _top_stocks_for_branch


def make_stock(code, name, buy_amt=0, sell_amt=0, buy_lot=0, sell_lot=0,
               is_limit_up=False):
    return {
        "code": code,
        "name": name,
        "buy_amt": buy_amt,
        "sell_amt": sell_amt,
        "buy_lot": buy_lot,
        "sell_lot": sell_lot,
        "net_amt": buy_amt - sell_amt,
        "net_lot": buy_lot - sell_lot,
        "is_limit_up": is_limit_up,
    }


print("=" * 70)
print("  v3.28.1 sniper net-buyer filter test")
print("=" * 70)

# 構造案例: 蔣承翰 城中 分點 (sniper_mode)
# 含 4 個漲停股 (淨買, 淨賣, 淨平, 微小淨買) + 2 個非漲停股
branch_data = {
    "code": "9227",
    "name": "凱基-城中",
    "buys": [
        # 微星 漲停 但實際淨賣 (5/13 蔣承翰實況)
        make_stock("2377", "微星",   buy_amt=500_000, sell_amt=800_000,
                   buy_lot=80, sell_lot=130, is_limit_up=True),
        # 創意 漲停 大量淨買 (真正 sniper)
        make_stock("3443", "創意",   buy_amt=600_000, sell_amt=50_000,
                   buy_lot=110, sell_lot=10, is_limit_up=True),
        # 聯電 漲停 但 net=0 (買=賣)
        make_stock("2303", "聯電",   buy_amt=300_000, sell_amt=300_000,
                   buy_lot=2000, sell_lot=2000, is_limit_up=True),
        # 台積電 非漲停 但有大量買 (應排除 — 非漲停)
        make_stock("2330", "台積電", buy_amt=400_000, sell_amt=20_000,
                   buy_lot=50, sell_lot=2, is_limit_up=False),
        # 高價股 case: amt 反推誤差導致 net_amt=0 但 net_lot=10 (應入選)
        make_stock("6679", "鈺太",   buy_amt=400_000, sell_amt=400_000,
                   buy_lot=15, sell_lot=5, is_limit_up=True),
    ],
    "sells": [
        # 一致賣超漲停股 (應排除)
        make_stock("2317", "鴻海",   buy_amt=100_000, sell_amt=500_000,
                   buy_lot=400, sell_lot=2000, is_limit_up=True),
    ],
}

# 跑 sniper_mode
result = _top_stocks_for_branch(branch_data, sniper_mode=True)
result_codes = [s["code"] for s in result]

print(f"\nsniper_mode 入選 ({len(result)} 檔): {result_codes}")
expected_in = ["3443", "6679"]   # 創意(淨買) + 鈺太(amt=0 但 lot>0)
expected_out = ["2377", "2303", "2330", "2317"]  # 微星淨賣 / 聯電 net=0 / 台積電非漲停 / 鴻海淨賣

all_pass = True
for code in expected_in:
    if code in result_codes:
        print(f"  ✅ {code} 應入選 → 入選")
    else:
        print(f"  ❌ {code} 應入選 → 沒入選 [FAIL]")
        all_pass = False
for code in expected_out:
    if code not in result_codes:
        print(f"  ✅ {code} 應排除 → 排除")
    else:
        print(f"  ❌ {code} 應排除 → 被選入 [FAIL]")
        all_pass = False

# v3.29.1 更新: sniper_mode=False (swing master) 也加 net_buyer filter
# 原 v3.28.1 行為 "全 6 入選" 已修正 (5/19 用戶 review 發現 13% rows 是淨賣污染)
print(f"\nsniper_mode=False (swing master) v3.29.1 後也 filter net_buyer:")
result_swing = _top_stocks_for_branch(branch_data, sniper_mode=False)
result_swing_codes = [s["code"] for s in result_swing]
print(f"  入選 ({len(result_swing)} 檔): {result_swing_codes}")
# v3.29.1: swing 也 filter net > 0. 預期入選:
#   3443 (淨買漲停), 6679 (net_lot>0 漲停), 2330 (淨買非漲停 — swing 可入, sniper 不可)
# 預期排除:
#   2377 微星 (淨賣 v3.28.1 fixture 已標), 2303 net=0, 2317 鴻海淨賣
expected_in_swing_v3291 = {"3443", "6679", "2330"}
expected_out_swing_v3291 = {"2377", "2303", "2317"}
actual_set = set(result_swing_codes)
swing_ok = (expected_in_swing_v3291 <= actual_set and not (expected_out_swing_v3291 & actual_set))
print(f"  {'✅' if swing_ok else '❌'} swing master v3.29.1 行為 (filter net_buyer): {'PASS' if swing_ok else 'FAIL'}")
if not swing_ok:
    print(f"     expected_in: {expected_in_swing_v3291}, actual: {actual_set}")
    all_pass = False

# 邊界: 全空 branch_data
print(f"\n邊界: 空 branch_data:")
empty = _top_stocks_for_branch({}, sniper_mode=True)
ok = empty == []
print(f"  {'✅' if ok else '❌'} 空輸入 → 空輸出")
if not ok:
    all_pass = False

print()
print("─" * 70)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
