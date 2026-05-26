"""v3.30.2 histock_branch_audit 單元測試"""
import sys
import json
sys.path.insert(0, '.')

from histock_branch_audit import (
    parse_histock_table,
    build_sample_list,
    build_our_branches_for_stock,
    cross_check_stock,
    BUY_LOT_WARN_PCT,
    BUY_LOT_ERROR_PCT,
    BUY_AMT_WARN_PCT,
)

all_pass = True
print("=" * 60)
print("  v3.30.2 histock_branch_audit 單元測試")
print("=" * 60)

# ── 1. parser ──
print("\n1. parse_histock_table 真實 HTML (2330)")
try:
    with open('/tmp/histock_2330_sample.html', encoding='utf-8') as f:
        html = f.read()
    result = parse_histock_table(html, '2330')
    ok = (
        result is not None
        and len(result['sells']) == 15
        and len(result['buys']) == 15
        and result['sells'][0]['bno'] == '1480'
        and result['buys'][0]['bno'] == '9A9g'
        and result['buys'][0]['buy_lot'] == 550
        and result['buys'][0]['avg_price'] > 2000
    )
    print(f"  {'OK' if ok else 'FAIL'} parser: 15 sells + 15 buys, bno+buy_lot+avg_price 全到位")
    if not ok:
        all_pass = False
        print(f"    raw: {result}")
except FileNotFoundError:
    print(f"  ⏭️ SKIP (/tmp/histock_2330_sample.html 不存在,需先 fetch)")

# ── 2. build_sample_list 優先順序 ──
print("\n2. build_sample_list 動態 sample 優先順序")
mock_latest = {
    'trade_date': '20260526',
    'limit_up_summary': {
        'limit_up_codes': ['3443', '6861'],
    },
    'branches': [
        {
            'code': '9A9g', 'name': '永豐金-內湖', 'master': '蔣承翰',
            'buys': [
                {'code': '3443', 'buy_lot': 100, 'buy_amt': 154_600_000},  # 漲停
                {'code': '6861', 'buy_lot': 50, 'buy_amt': 80_000_000},   # 漲停
                {'code': '2330', 'buy_lot': 5, 'buy_amt': 11_500_000},    # 不漲停但 sniper 買
            ],
            'sells': [],
        },
        {
            'code': '9251', 'name': '元大-永和', 'master': '民哥',
            'buys': [
                {'code': '2454', 'buy_lot': 200, 'buy_amt': 60_000_000},  # 高金額
            ],
            'sells': [],
        },
    ],
    'co_buy_ranking': [
        {'code': '2317'}, {'code': '2454'},
    ],
}
sample = build_sample_list(mock_latest, max_stocks=10)
expected_in = {'3443', '6861', '2330', '2454', '2317'}
ok = expected_in.issubset(set(sample))
print(f"  {'OK' if ok else 'FAIL'} sample 包含全部優先個股: {sample}")
if not ok:
    all_pass = False

# ── 3. cross_check 完全匹配 ──
print("\n3. cross_check 完全匹配 → PASS")
our = [
    {'branch_code': '9A9g', 'buy_lot': 550, 'buy_amt': 1_260_578_000, 'sell_lot': 25, 'sell_amt': 57_299_000},
]
hi = {
    'buys': [{'bno': '9A9g', 'name': '永豐金-內湖', 'buy_lot': 550, 'sell_lot': 25, 'net': 524, 'avg_price': 2291.96}],
    'sells': [],
}
v, ms = cross_check_stock('2330', our, hi)
ok = v == 'PASS' and len(ms) == 0
print(f"  {'OK' if ok else 'FAIL'} verdict={v}, mismatches={len(ms)}")
if not ok:
    all_pass = False
    print(f"    ms: {ms}")

# ── 4. cross_check buy_lot 差 5% → WARN ──
print("\n4. cross_check buy_lot 差 8% → WARN")
our = [
    {'branch_code': '9A9g', 'buy_lot': 595, 'buy_amt': 1_363_715_000, 'sell_lot': 25, 'sell_amt': 0},  # 550 → 595 = +8%
]
hi = {
    'buys': [{'bno': '9A9g', 'name': '永豐金-內湖', 'buy_lot': 550, 'sell_lot': 25, 'net': 524, 'avg_price': 2291.96}],
    'sells': [],
}
v, ms = cross_check_stock('2330', our, hi)
# 至少有 1 個 buy_lot warning
ok = v == 'WARN' and any(m['field'] == 'buy_lot' and m['severity'] == 'warning' for m in ms)
print(f"  {'OK' if ok else 'FAIL'} verdict={v}, mismatches={len(ms)}, fields={[m['field'] for m in ms]}")
if not ok:
    all_pass = False
    for m in ms: print(f"    {m}")

# ── 5. cross_check buy_lot 差 30% → FAIL ──
print("\n5. cross_check buy_lot 差 50% → FAIL (error)")
our = [
    {'branch_code': '9A9g', 'buy_lot': 275, 'buy_amt': 630_289_000, 'sell_lot': 25, 'sell_amt': 0},  # 550 → 275 = -50%
]
hi = {
    'buys': [{'bno': '9A9g', 'name': '永豐金-內湖', 'buy_lot': 550, 'sell_lot': 25, 'net': 524, 'avg_price': 2291.96}],
    'sells': [],
}
v, ms = cross_check_stock('2330', our, hi)
ok = v == 'FAIL' and any(m['severity'] == 'error' for m in ms)
print(f"  {'OK' if ok else 'FAIL'} verdict={v}, errors={sum(1 for m in ms if m['severity']=='error')}")
if not ok:
    all_pass = False
    for m in ms: print(f"    {m}")

# ── 6. cross_check histock 沒這分點 → skip ──
print("\n6. histock 沒列出我們的分點 → skip (PASS)")
our = [
    {'branch_code': 'UNKNOWN_BNO', 'buy_lot': 100, 'buy_amt': 1_000_000, 'sell_lot': 0, 'sell_amt': 0},
]
hi = {
    'buys': [{'bno': '9A9g', 'name': '永豐金-內湖', 'buy_lot': 550, 'sell_lot': 25, 'net': 524, 'avg_price': 2291.96}],
    'sells': [],
}
v, ms = cross_check_stock('2330', our, hi)
ok = v == 'PASS' and len(ms) == 0  # 沒交集 = 不可比 = PASS
print(f"  {'OK' if ok else 'FAIL'} verdict={v}, mismatches={len(ms)}")
if not ok:
    all_pass = False

# ── 7. build_our_branches_for_stock 反向查詢 ──
print("\n7. build_our_branches_for_stock 反向 by-stock view")
ours = build_our_branches_for_stock(mock_latest, '3443')
ok = len(ours) == 1 and ours[0]['branch_code'] == '9A9g' and ours[0]['buy_lot'] == 100
print(f"  {'OK' if ok else 'FAIL'} 從 by-branch 反向組 by-stock: {ours}")
if not ok:
    all_pass = False

# ── 8. buy_amt 反推差異 (avg × lot × 1000) ──
print("\n8. buy_amt implied 計算正確")
# implied = 550 * 2291.96 * 1000 = 1,260,578,000
# 我們 buy_amt 1,260,578,000 → 0% diff → PASS
# 我們 buy_amt 800,000,000 → 36.5% diff → FAIL (error >30%)
our = [{'branch_code': '9A9g', 'buy_lot': 550, 'buy_amt': 800_000_000, 'sell_lot': 25, 'sell_amt': 0}]
hi = {
    'buys': [{'bno': '9A9g', 'name': '永豐金-內湖', 'buy_lot': 550, 'sell_lot': 25, 'net': 524, 'avg_price': 2291.96}],
    'sells': [],
}
v, ms = cross_check_stock('2330', our, hi)
amt_ms = [m for m in ms if m['field'] == 'buy_amt']
ok = len(amt_ms) == 1 and amt_ms[0]['severity'] == 'error'
print(f"  {'OK' if ok else 'FAIL'} buy_amt 反推抓到 error: {amt_ms}")
if not ok:
    all_pass = False

print()
print("─" * 60)
print(f"  整體: {'OK ALL PASS' if all_pass else 'FAIL HAS FAIL'}")
sys.exit(0 if all_pass else 1)
