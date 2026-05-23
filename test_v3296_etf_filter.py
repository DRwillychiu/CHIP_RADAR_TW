"""v3.29.6 ETF 過濾測試

5/24 用戶反映 Excel 仍會出現 ETF (0050/0056/00878 等), 不論 Top 10 還是 Top 20.
ETF 不是「個股」, 老闆 Excel 只看個股, 因此加 market_type filter.

驗證 case (10 個):
  1. _is_excluded_by_market_type:
     A. market_type='ETF' → 排除
     B. market_type='上市' → 保留
     C. market_type 空 + code='0050' → 排除 (heuristic 00 開頭 4 位)
     D. market_type 空 + code='00878' → 排除 (heuristic 00 開頭 5 位)
     E. market_type 空 + code='2330' → 保留
     F. market_type 空 + code='006208' → 排除 (00 開頭 6 位, 邊界)
        - 預期排除嗎? 邊界 case, 視為 ETF 排除 OK (code 6 位等同 00 開頭)
        - 但 helper 邏輯只 len in (4, 5), 6 位不擋, 保留 → 期望 True
        - 改: 邊界 不擋 (避免誤殺 6 位特別股 / 公司債)
  2. _top_stocks_for_branch:
     G. 混合 個股 + ETF → 過濾後只剩個股
     H. ETF 排在 buy_amt 第 1 名 → 過濾後 Top 1 變成個股
     I. 全部都 ETF → 回 [] (空)
  3. 與 sniper / net_buyer filter 順序:
     J. ETF 漲停 (sniper master 持有) → 也排除 (ETF 不該被當 sniper 標的)
"""
import sys
sys.path.insert(0, '.')

from excel_report import (
    _is_excluded_by_market_type, _top_stocks_for_branch,
    EXCLUDED_MARKET_TYPES,
)


def make_stock(code, name, market_type='', buy_amt=0, sell_amt=0,
               buy_lot=0, sell_lot=0, is_limit_up=False):
    return {
        "code": code, "name": name,
        "market_type": market_type,
        "buy_amt": buy_amt, "sell_amt": sell_amt,
        "buy_lot": buy_lot, "sell_lot": sell_lot,
        "net_amt": buy_amt - sell_amt,
        "net_lot": buy_lot - sell_lot,
        "is_limit_up": is_limit_up,
    }


print("=" * 72)
print("  v3.29.6 ETF 過濾測試")
print("=" * 72)
print(f"  EXCLUDED_MARKET_TYPES = {EXCLUDED_MARKET_TYPES}")
print()

all_pass = True

# ────────── _is_excluded_by_market_type ──────────
print("A-F. _is_excluded_by_market_type 邏輯")

cases = [
    # (desc, stock, expected_excluded)
    ('A. market_type=ETF (大寫)',     make_stock('0050', '元大台灣50', market_type='ETF'),  True),
    ('A2. market_type=etf (lowercase)', make_stock('0050', '元大台灣50', market_type='etf'), True),  # v3.29.7
    ('A3. market_type=etf_active',    make_stock('006208A', '主動 ETF', market_type='etf_active'), True),  # v3.29.7
    ('B. market_type=上市',           make_stock('2330', '台積電',    market_type='listed'), False),
    ('C. code=0050 無 market_type',  make_stock('0050', '元大台灣50'),                    True),
    ('D. code=00878 無 market_type', make_stock('00878', '國泰永續高股息'),              True),
    ('E. code=2330 無 market_type',  make_stock('2330', '台積電'),                       False),
    # v3.29.7: 6-char 也擋
    ('F. code=006208 (6 位普通 ETF)', make_stock('006208', '富邦台50'),                   True),
    ('F2. code=00715L (期信 原油)',   make_stock('00715L', '期街口布蘭特正2'),           True),  # v3.29.7
    ('F3. code=00738U (期信 白銀)',   make_stock('00738U', '期元大道瓊白銀'),            True),  # v3.29.7
]
for desc, stock, expected in cases:
    actual = _is_excluded_by_market_type(stock)
    ok = actual == expected
    icon = '✅' if ok else '❌'
    print(f"  {icon} {desc}: actual={actual}, expected={expected}")
    if not ok:
        all_pass = False

# ────────── _top_stocks_for_branch 整合 ──────────
print("\nG. 混合 個股 + ETF → 只回個股")
branch_g = {
    "code": "8563", "name": "新光-新竹",
    "buys": [
        # ETF (應排除)
        make_stock('0050', '元大台灣50', market_type='ETF',
                   buy_amt=1_000_000, sell_amt=10_000),
        # 個股 1
        make_stock('2330', '台積電', market_type='上市',
                   buy_amt=800_000, sell_amt=50_000),
        # ETF (應排除)
        make_stock('00878', '國泰永續高股息',
                   buy_amt=600_000, sell_amt=10_000),
        # 個股 2
        make_stock('2454', '聯發科', market_type='上市',
                   buy_amt=400_000, sell_amt=50_000),
    ],
    "sells": [],
}
result_g = _top_stocks_for_branch(branch_g, sniper_mode=False)
codes_g = [s['code'] for s in result_g]
expected_codes = ['2330', '2454']  # 0050, 00878 應排除
ok_g = codes_g == expected_codes
print(f"  {'✅' if ok_g else '❌'} 入選 codes={codes_g} (expect {expected_codes})")
if not ok_g:
    all_pass = False

# ────────── ETF 排第 1 名 → Top 1 變個股 ──────────
print("\nH. ETF buy_amt 第 1 → Top 1 變個股")
branch_h = {
    "code": "8563", "name": "新光-新竹",
    "buys": [
        make_stock('0050', '元大台灣50', market_type='ETF',
                   buy_amt=10_000_000, sell_amt=100_000),  # buy_amt 第 1
        make_stock('2330', '台積電', market_type='上市',
                   buy_amt=500_000, sell_amt=50_000),
    ],
    "sells": [],
}
result_h = _top_stocks_for_branch(branch_h, sniper_mode=False)
top1_code = result_h[0]['code'] if result_h else None
ok_h = top1_code == '2330'
print(f"  {'✅' if ok_h else '❌'} Top 1 code = {top1_code} (expect 2330, 不是 0050)")
if not ok_h:
    all_pass = False

# ────────── 全部 ETF → 空 ──────────
print("\nI. 全部 ETF → 空 list")
branch_i = {
    "code": "8563", "name": "新光-新竹",
    "buys": [
        make_stock('0050', 'ETF1', market_type='ETF',
                   buy_amt=500_000, sell_amt=10_000),
        make_stock('0056', 'ETF2', market_type='ETF',
                   buy_amt=400_000, sell_amt=10_000),
    ],
    "sells": [],
}
result_i = _top_stocks_for_branch(branch_i, sniper_mode=False)
ok_i = result_i == []
print(f"  {'✅' if ok_i else '❌'} 全 ETF → result = {result_i}")
if not ok_i:
    all_pass = False

# ────────── sniper master + ETF 漲停 → 也排除 ──────────
print("\nJ. ETF 漲停 + sniper master → 排除")
branch_j = {
    "code": "9227", "name": "凱基-城中",
    "buys": [
        # ETF 漲停 (應排除, 即使 sniper)
        make_stock('00637L', '元大滬深300正2', market_type='ETF',
                   buy_amt=1_000_000, sell_amt=10_000, is_limit_up=True),
        # 個股漲停
        make_stock('3443', '創意', market_type='上市',
                   buy_amt=500_000, sell_amt=50_000, is_limit_up=True),
    ],
    "sells": [],
}
result_j = _top_stocks_for_branch(branch_j, sniper_mode=True)
codes_j = [s['code'] for s in result_j]
ok_j = codes_j == ['3443']
print(f"  {'✅' if ok_j else '❌'} sniper Top = {codes_j} (expect ['3443'], ETF 漲停應排除)")
if not ok_j:
    all_pass = False

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
