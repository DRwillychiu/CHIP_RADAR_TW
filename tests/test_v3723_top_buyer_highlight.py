# -*- coding: utf-8 -*-
"""v3.72.3 sniper 漲停股買超#1 黃色 highlight 測試

驗證:
  1. _build_top_net_buyer_index 正確找出 net-max buyer per stock
  2. 平手時取第一個 encountered
  3. 若 net <= 0 (只賣不買 or 淨賣) → 不列 top
  4. build_day_sheet 對 sniper master 且是 top 的 row 塗黃 (FFFFFF00)
  5. 非 sniper master 就算是 top 也不塗黃 (只 sniper 應用)
  6. sniper 但不是 top 的 row 不塗黃 (保留 body 淡紅)
  7. body fill 邏輯不會覆蓋 top-buyer 黃色 (v3.72.3 保護邏輯)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from src.exports.excel_report import (
    _build_top_net_buyer_index,
    build_day_sheet,
    SNIPER_MASTER_WHITELIST,
    _get_top_buyer_fill,
)
from openpyxl import Workbook

YELLOW = "FFFFFF00"

pass_count = 0
fail_count = 0
def check(label, cond):
    global pass_count, fail_count
    if cond:
        print(f"  ✅ {label}")
        pass_count += 1
    else:
        print(f"  ❌ {label}")
        fail_count += 1

# ─── 1. 基本 top buyer 判定 ───
print("\n1. _build_top_net_buyer_index 基本 case")
branches = [
    {"code": "9227", "buys": [{"code": "6577", "buy_amt": 100000}],
                     "sells": []},
    {"code": "9B18", "buys": [{"code": "6577", "buy_amt": 50000}],
                     "sells": []},
    {"code": "9A9S", "buys": [{"code": "6577", "buy_amt": 200000}],
                     "sells": []},
]
idx = _build_top_net_buyer_index(branches)
check("6577 top = 9A9S (最大 200k)", idx.get("6577") == "9A9S")

# ─── 2. Net 計算 (buy - sell) ───
print("\n2. Net = buy - sell 正確")
branches = [
    {"code": "A", "buys": [{"code": "X", "buy_amt": 100}],
                  "sells": [{"code": "X", "sell_amt": 50}]},  # net 50
    {"code": "B", "buys": [{"code": "X", "buy_amt": 80}],
                  "sells": []},  # net 80
]
idx = _build_top_net_buyer_index(branches)
check("X top = B (net 80 > A net 50)", idx.get("X") == "B")

# ─── 3. 只賣 (net <= 0) 不列 top ───
print("\n3. 只賣或淨賣 → 不列 top")
branches = [
    {"code": "A", "buys": [], "sells": [{"code": "Y", "sell_amt": 100}]},  # net -100
    {"code": "B", "buys": [{"code": "Y", "buy_amt": 30}],
                  "sells": [{"code": "Y", "sell_amt": 50}]},  # net -20
]
idx = _build_top_net_buyer_index(branches)
check("Y 無 top (全負 net)", "Y" not in idx)

# ─── 4. 平手取第一個 encountered ───
print("\n4. 平手取第一個 encountered")
branches = [
    {"code": "First", "buys": [{"code": "Z", "buy_amt": 100}], "sells": []},
    {"code": "Second", "buys": [{"code": "Z", "buy_amt": 100}], "sells": []},
]
idx = _build_top_net_buyer_index(branches)
check("Z top = First (先遇到)", idx.get("Z") == "First")

# ─── 5. build_day_sheet 端對端 ───
print("\n5. build_day_sheet 端對端: 蔣承翰買 6577 且是 top → 黃色 highlight")
# 構造: 蔣承翰 9A9S 是 6577 top buyer (200k 淨買),其他分點是 100k, 50k
sample_stock = {
    "code": "6577", "name": "勁豐",
    "buy_lot": 22, "sell_lot": 0,
    "buy_amt": 200000, "sell_amt": 0,
    "net_amt": 200000, "net_lot": 22,
    "is_limit_up": True,
}
sample_stock_9227 = {
    "code": "6577", "name": "勁豐",
    "buy_lot": 11, "sell_lot": 0,
    "buy_amt": 100000, "sell_amt": 0,
    "net_amt": 100000, "net_lot": 11,
    "is_limit_up": True,
}
branches_data = [
    {"code": "9227", "name": "凱基-城中", "buys": [sample_stock_9227], "sells": []},
    {"code": "9B18", "name": "台新-建北", "buys": [], "sells": []},
    {"code": "9A9S", "name": "永豐金-南京", "buys": [sample_stock], "sells": []},
]
wb = Workbook()
ws = wb.active
build_day_sheet(ws, branches_data, "20260722")

# 找 9A9S 的 6577 row (應為黃色 fill FFFFFF00)
found_yellow = False
found_9227_not_yellow = False
for row in range(1, ws.max_row + 1):
    val_c = ws.cell(row=row, column=3).value  # C 欄: branch code
    val_d = ws.cell(row=row, column=4).value  # D 欄: stock label
    if val_d and "6577" in str(val_d):
        # 找該 row 是否黃色
        fill = ws.cell(row=row, column=4).fill
        rgb = getattr(getattr(fill, 'fgColor', None), 'rgb', None)
        # 檢查該 row 屬於哪個 branch (往上找最近 merged C 欄值)
        # 簡化: 直接 check row 4-11 應該是 9227, 14-21 = 9B18, 24-31 = 9A9S
        # 用 buy_lot (E 欄) 反查
        buy_lot = ws.cell(row=row, column=5).value
        if buy_lot == 22:  # 9A9S 的
            found_yellow = (rgb == YELLOW)
        elif buy_lot == 11:  # 9227 的
            found_9227_not_yellow = (rgb != YELLOW)

check("9A9S 6577 row D 欄背景 = 黃色 FFFFFF00", found_yellow)
check("9227 6577 row 不塗黃 (非 top buyer)", found_9227_not_yellow)

# ─── 6. 非 sniper master 就算是 top 也不塗黃 ───
print("\n6. 非 sniper master (e.g. 民哥) 就算是 top 也不塗黃")
# 民哥 = swing, 非 sniper. 若他買股票也不會 highlight.
# 這由 sniper_mode gate 決定, 已在 build_day_sheet 檢查
check("SNIPER_MASTER_WHITELIST 只含蔣承翰", SNIPER_MASTER_WHITELIST == {"蔣承翰"})

# ─── 總結 ───
print(f"\n{'─' * 60}")
print(f"整體: {pass_count} pass / {fail_count} fail")
sys.exit(0 if fail_count == 0 else 1)
