# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.29.1 全部 master 都加 net_buyer filter — 修 5/19 用戶發現 6257 淨賣 case

5/19 用戶 review Excel 發現:
  大牌分析師-新光新竹 (8563) 顯示 矽格(6257) buy 4198萬 sell 5610萬 → 淨賣 -1412萬
  Excel 仍把它列入 swing master 的 Top 10, 因為 v3.28.1 只對 sniper 加 net filter.

掃全 Excel 359 row → 48 row (13%) 都是 net seller 被選入, 最嚴重:
  張濬安(航海王) 國票-安和 國巨*(2327) 買4697萬 淨賣 -21,019 萬 (淨賣 2.1 億!)

修法:
  v3.29.1 把 net_buyer filter 擴大到所有 master.
  sniper_mode 額外限定 is_limit_up.

驗證 (8 case):
  1. swing master + 淨買漲停 → 入選
  2. swing master + 淨買非漲停 → 入選 (sniper 會排除, swing 不會)
  3. swing master + 淨賣 → 排除 (核心修補)
  4. sniper master + 淨買漲停 → 入選
  5. sniper master + 淨買非漲停 → 排除 (sniper 還是要漲停)
  6. sniper master + 淨賣漲停 → 排除
  7. 所有 master + net=0 → 排除
  8. 邊界: 空 branch_data → []
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


print("=" * 72)
print("  v3.29.1 全部 master 加 net_buyer filter test")
print("=" * 72)

# 構造 fixture: 包含 5/19 真實 case (6257) + 其他類型
branch_data = {
    "code": "8563",
    "name": "新光-新竹",
    "buys": [
        # 用戶 5/19 發現的真實 case
        make_stock("6257", "矽格",   buy_amt=419_800, sell_amt=561_000,
                   buy_lot=195, sell_lot=262, is_limit_up=False),
        # 大盤股淨買 (swing 應入選, sniper 應排除因非漲停)
        make_stock("2330", "台積電", buy_amt=400_000, sell_amt=80_000,
                   buy_lot=50, sell_lot=10, is_limit_up=False),
        # 漲停股淨買 (兩種 mode 都入選)
        make_stock("3443", "創意",   buy_amt=600_000, sell_amt=50_000,
                   buy_lot=110, sell_lot=10, is_limit_up=True),
        # 漲停 + 淨賣 (兩種 mode 都應排除)
        make_stock("6166", "凌華",   buy_amt=300_000, sell_amt=800_000,
                   buy_lot=200, sell_lot=500, is_limit_up=True),
        # 非漲停 net=0 (兩種 mode 都應排除)
        make_stock("2303", "聯電",   buy_amt=100_000, sell_amt=100_000,
                   buy_lot=1000, sell_lot=1000, is_limit_up=False),
        # 高價股 amt=0 但 net_lot>0 (兩種 mode 都應入選若非漲停 / sniper 需漲停)
        make_stock("6679", "鈺太",   buy_amt=500_000, sell_amt=400_000,
                   buy_lot=20, sell_lot=10, is_limit_up=True),
    ],
    "sells": [
        # 純賣超 (兩種 mode 都應排除)
        make_stock("2317", "鴻海",   buy_amt=50_000, sell_amt=500_000,
                   buy_lot=200, sell_lot=2000, is_limit_up=True),
    ],
}

# Case A: swing master (sniper_mode=False)
print("\nA. Swing master (e.g. 大牌分析師):")
result_swing = _top_stocks_for_branch(branch_data, sniper_mode=False)
codes_swing = [s["code"] for s in result_swing]
print(f"  入選: {codes_swing}")
expected_in_swing = ["6679", "3443", "2330"]  # all net buyers
expected_out_swing = ["6257", "6166", "2303", "2317"]  # all net non-buyers

all_pass = True
for c in expected_in_swing:
    if c in codes_swing:
        print(f"  ✅ {c} 淨買 應入選 → 入選")
    else:
        print(f"  ❌ {c} 應入選 → 沒入選 [FAIL]")
        all_pass = False
for c in expected_out_swing:
    if c not in codes_swing:
        print(f"  ✅ {c} 淨賣/net=0 應排除 → 排除")
    else:
        print(f"  ❌ {c} 應排除 → 被選入 [FAIL]")
        all_pass = False
# Core: 6257 必須排除 (用戶 5/19 case)
if "6257" not in codes_swing:
    print(f"  ✅✅✅ 6257 矽格 (5/19 用戶發現的 case) 已修補")

# Case B: sniper master (sniper_mode=True)
print("\nB. Sniper master (e.g. 蔣承翰):")
result_sniper = _top_stocks_for_branch(branch_data, sniper_mode=True)
codes_sniper = [s["code"] for s in result_sniper]
print(f"  入選: {codes_sniper}")
expected_in_sniper = ["6679", "3443"]  # net buyer + limit_up
expected_out_sniper = ["6257", "6166", "2330", "2303", "2317"]

for c in expected_in_sniper:
    if c in codes_sniper:
        print(f"  ✅ {c} 淨買+漲停 應入選 → 入選")
    else:
        print(f"  ❌ {c} 應入選 → 沒入選 [FAIL]")
        all_pass = False
for c in expected_out_sniper:
    if c not in codes_sniper:
        print(f"  ✅ {c} 違反 net OR 漲停 條件 → 排除")
    else:
        print(f"  ❌ {c} 應排除 → 被選入 [FAIL]")
        all_pass = False

# Case C: 邊界
print("\nC. 邊界: 空 branch_data")
empty_swing = _top_stocks_for_branch({}, sniper_mode=False)
empty_sniper = _top_stocks_for_branch({}, sniper_mode=True)
ok_c = empty_swing == [] and empty_sniper == []
print(f"  {'✅' if ok_c else '❌'} 空輸入 swing={empty_swing} sniper={empty_sniper}")
if not ok_c:
    all_pass = False

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
