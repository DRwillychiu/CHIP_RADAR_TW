# -*- coding: utf-8 -*-
"""v3.72.4 sniper 漲停股「全市場」買超#1 黃色 highlight 測試

v3.72.4 修訂: 判定範圍改用 histock 全市場分點榜, 不再限於 tracked branches.

驗證:
  1. _fetch_histock_top_buyer 用 cache 避免重複 fetch
  2. _build_top_net_buyer_index 只 fetch sniper_stock_codes 內的
  3. 端對端: histock top = 蔣承翰 bno → 黃色; histock top = 別人 → 不塗黃
  4. sniper 沒買漲停 → 不 fetch (省流量)
  5. histock fetch 失敗 → 不 crash, 不塗黃 (safe fallback)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from unittest.mock import patch
from openpyxl import Workbook

from src.exports.excel_report import (
    _fetch_histock_top_buyer,
    _build_top_net_buyer_index,
    build_day_sheet,
    SNIPER_MASTER_WHITELIST,
)

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

# Mock histock 資料
MOCK_HISTOCK = {
    "6577": {  # 蔣承翰 9A9S 是 top #1
        "buys": [
            {"bno": "9A9S", "name": "永豐金-南京", "net": 22000},
            {"bno": "OTHER", "name": "其他-分點", "net": 15000},
        ]
    },
    "2330": {  # 台積電 - top #1 不是蔣承翰
        "buys": [
            {"bno": "1480", "name": "元大", "net": 800000},
            {"bno": "9227", "name": "凱基-城中", "net": 100000},
        ]
    },
    "9999": None,  # fetch 失敗
}

def mock_fetch_histock_branch(stock_code, timeout=8, max_retries=1):
    return MOCK_HISTOCK.get(stock_code)


# ─── 1. cache 避免重複 fetch ───
print("\n1. _fetch_histock_top_buyer cache 生效")
with patch("src.audit.histock_branch_audit.fetch_histock_branch",
           side_effect=mock_fetch_histock_branch) as m:
    cache = {}
    _fetch_histock_top_buyer("6577", cache)
    _fetch_histock_top_buyer("6577", cache)  # 應該直接 hit cache
    check("6577 cache 存在", cache.get("6577") == "9A9S")
    check("僅 fetch 1 次 (cache hit)", m.call_count == 1)

# ─── 2. _build_top_net_buyer_index 只 fetch sniper 買的漲停 ───
print("\n2. _build_top_net_buyer_index 只 fetch sniper_stock_codes")
with patch("src.audit.histock_branch_audit.fetch_histock_branch",
           side_effect=mock_fetch_histock_branch) as m:
    idx = _build_top_net_buyer_index(branches_data=[],
                                      sniper_stock_codes={"6577", "2330"})
    check("6577 → 9A9S", idx.get("6577") == "9A9S")
    check("2330 → 1480", idx.get("2330") == "1480")
    check("fetch 2 次 (每股一次)", m.call_count == 2)

# ─── 3. sniper_stock_codes=None → 不 fetch, 回空 ───
print("\n3. 無 sniper 買漲停 → 不 fetch")
with patch("src.audit.histock_branch_audit.fetch_histock_branch",
           side_effect=mock_fetch_histock_branch) as m:
    idx = _build_top_net_buyer_index(branches_data=[{"code": "9227", "buys": [], "sells": []}],
                                      sniper_stock_codes=None)
    check("空 index", idx == {})
    check("0 次 fetch", m.call_count == 0)

# ─── 4. histock fetch 失敗 → 不塗黃 (safe) ───
print("\n4. histock 失敗 → 不塗黃, 不 crash")
with patch("src.audit.histock_branch_audit.fetch_histock_branch",
           side_effect=mock_fetch_histock_branch):
    cache = {}
    result = _fetch_histock_top_buyer("9999", cache)
    check("9999 (mock None) → 回 None", result is None)
    check("cache 9999 = None (不重試)", cache.get("9999") is None)

# ─── 5. 端對端: 9A9S 買 6577 漲停 + histock 顯示 9A9S #1 → 黃色 ───
print("\n5. 端對端: 9A9S 是 6577 histock top #1 → 黃色 highlight")
sample_stock = {
    "code": "6577", "name": "勁豐",
    "buy_lot": 22, "sell_lot": 0,
    "buy_amt": 200000, "sell_amt": 0,
    "net_amt": 200000, "net_lot": 22,
    "is_limit_up": True,
}
branches_data = [
    {"code": "9227", "name": "凱基-城中", "buys": [], "sells": []},
    {"code": "9B18", "name": "台新-建北", "buys": [], "sells": []},
    {"code": "9A9S", "name": "永豐金-南京", "buys": [sample_stock], "sells": []},
]
wb = Workbook()
ws = wb.active
with patch("src.audit.histock_branch_audit.fetch_histock_branch",
           side_effect=mock_fetch_histock_branch):
    build_day_sheet(ws, branches_data, "20260722")

# 找 6577 row 檢查黃色
found_yellow = False
for row in range(1, ws.max_row + 1):
    val_d = ws.cell(row=row, column=4).value
    if val_d and "6577" in str(val_d):
        buy_lot = ws.cell(row=row, column=5).value
        if buy_lot == 22:  # 9A9S 的
            fill = ws.cell(row=row, column=4).fill
            rgb = getattr(getattr(fill, 'fgColor', None), 'rgb', None)
            found_yellow = (rgb == YELLOW)

check("9A9S 6577 row D 欄 = 黃色 FFFFFF00", found_yellow)

# ─── 6. 若 histock top #1 不是我方 → 不塗黃 ───
print("\n6. histock top 不是蔣承翰 → 不塗黃")
sample_stock_wrong = {
    "code": "2330", "name": "台積電",
    "buy_lot": 5, "sell_lot": 0,
    "buy_amt": 500000, "sell_amt": 0,
    "net_amt": 500000, "net_lot": 5,
    "is_limit_up": True,
}
branches_data2 = [
    {"code": "9227", "name": "凱基-城中", "buys": [sample_stock_wrong], "sells": []},
    {"code": "9B18", "name": "台新-建北", "buys": [], "sells": []},
    {"code": "9A9S", "name": "永豐金-南京", "buys": [], "sells": []},
]
wb2 = Workbook()
ws2 = wb2.active
with patch("src.audit.histock_branch_audit.fetch_histock_branch",
           side_effect=mock_fetch_histock_branch):
    build_day_sheet(ws2, branches_data2, "20260722")

found_not_yellow = False
for row in range(1, ws2.max_row + 1):
    val_d = ws2.cell(row=row, column=4).value
    if val_d and "2330" in str(val_d):
        buy_lot = ws2.cell(row=row, column=5).value
        if buy_lot == 5:  # 9227 的 (蔣承翰買, 但 histock top #1 = 元大 1480)
            fill = ws2.cell(row=row, column=4).fill
            rgb = getattr(getattr(fill, 'fgColor', None), 'rgb', None)
            found_not_yellow = (rgb != YELLOW)

check("9227 買 2330 但 histock top=1480 → 不塗黃", found_not_yellow)

# ─── 7. SNIPER_MASTER_WHITELIST 保持 ───
print("\n7. SNIPER_MASTER_WHITELIST 只含蔣承翰")
check("白名單 = 蔣承翰", SNIPER_MASTER_WHITELIST == {"蔣承翰"})

# ─── 總結 ───
print(f"\n{'─' * 60}")
print(f"整體: {pass_count} pass / {fail_count} fail")
sys.exit(0 if fail_count == 0 else 1)
