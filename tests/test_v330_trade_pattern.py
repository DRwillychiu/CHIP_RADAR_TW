# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.30.0 trade_pattern 規則 + narrative 模板 測試

驗證 (12 case):
  A. classify_trade_pattern 5 種模式
  B. generate_narrative 50-100 字 + 含關鍵欄位
  C. inject_trade_patterns 整合測試
"""
import sys
sys.path.insert(0, '.')

from trade_pattern import (
    classify_trade_pattern, generate_narrative,
    inject_trade_patterns, STYLE_LABELS_CHINESE,
)


def make_stock(code, name, buy_lot=0, sell_lot=0, buy_amt=0, sell_amt=0,
               is_limit_up=False, change_pct=None, trade_style='unknown',
               daytrade_ratio=0):
    return {
        "code": code, "name": name,
        "buy_lot": buy_lot, "sell_lot": sell_lot,
        "buy_amt": buy_amt, "sell_amt": sell_amt,
        "net_lot": buy_lot - sell_lot,
        "net_amt": buy_amt - sell_amt,
        "is_limit_up": is_limit_up,
        "change_pct": change_pct,
        "trade_style": trade_style,
        "daytrade_ratio": daytrade_ratio,
    }


print("=" * 72)
print("  v3.30.0 trade_pattern 規則 + narrative 測試")
print("=" * 72)
all_pass = True

# ── A. classify_trade_pattern 5 種模式 ──
print("\nA. classify_trade_pattern 5 種模式")
cases_a = [
    # (desc, stock, master_styles, expected_pattern)
    ('A1. next_day_flipper master + 漲停買',
     make_stock('3443', '創意', buy_lot=11, sell_lot=0, is_limit_up=True, change_pct=9.96, trade_style='overnight'),
     ['next_day_flipper'], '隔日沖'),

    ('A2. 漲停 + overnight + 非 sniper master',
     make_stock('2330', '台積電', buy_lot=10, sell_lot=0, is_limit_up=True, trade_style='overnight'),
     ['swing'], '隔日沖'),  # 漲停 + overnight → 隔日沖 (規則 1)

    ('A3. day_trader master',
     make_stock('2454', '聯發科', buy_lot=100, sell_lot=80, trade_style='daytrade', daytrade_ratio=0.80),
     ['day_trader'], '當沖'),

    ('A4. trade_style daytrade',
     make_stock('2317', '鴻海', buy_lot=200, sell_lot=180, trade_style='daytrade', daytrade_ratio=0.90),
     ['unknown'], '當沖'),

    ('A5. swing master + overnight',
     make_stock('2308', '台達電', buy_lot=50, sell_lot=5, trade_style='overnight', change_pct=1.5),
     ['swing'], '波段持股'),

    ('A6. longterm master + partial',
     make_stock('2891', '中信金', buy_lot=300, sell_lot=100, trade_style='partial', daytrade_ratio=0.33, change_pct=0.5),
     ['longterm'], '波段持股'),

    ('A7. 純 partial 非 master style',
     make_stock('2002', '中鋼', buy_lot=200, sell_lot=120, trade_style='partial', daytrade_ratio=0.6),
     ['unknown'], '部分當沖'),

    ('A8. 純 overnight 非 master style',
     make_stock('1216', '統一', buy_lot=80, sell_lot=10, trade_style='overnight'),
     ['unknown'], '波段持股'),

    ('A9. 完全未明',
     make_stock('1303', '南亞', buy_lot=10, sell_lot=10, trade_style='unknown'),
     [], '未明'),
]

for desc, stock, styles, expected in cases_a:
    actual = classify_trade_pattern(stock, styles)
    ok = actual == expected
    icon = '✅' if ok else '❌'
    print(f"  {icon} {desc}: {actual} (expect {expected})")
    if not ok: all_pass = False

# ── B. generate_narrative 50-100 字 + 關鍵欄位 ──
print("\nB. generate_narrative 字數 + 關鍵欄位")

cases_b = [
    ('B1. 隔日沖 narrative',
     make_stock('3443', '創意', buy_lot=11, sell_lot=0, buy_amt=15465, sell_amt=0, is_limit_up=True, change_pct=9.96, trade_style='overnight'),
     '蔣承翰', '凱基-城中', '隔日沖', ['next_day_flipper'],
     ['蔣承翰', '凱基-城中', '創意', '3443', '11', '隔日沖']),

    ('B2. 當沖 narrative',
     make_stock('2454', '聯發科', buy_lot=100, sell_lot=80, buy_amt=300000, sell_amt=240000, trade_style='daytrade', daytrade_ratio=0.80, change_pct=2.5),
     '迷你哥/松山哥', '凱基-松山', '當沖', ['day_trader'],
     ['迷你哥/松山哥', '凱基-松山', '聯發科', '當沖', '80%']),

    ('B3. 波段持股 narrative',
     make_stock('2330', '台積電', buy_lot=50, sell_lot=5, buy_amt=110000, sell_amt=11000, trade_style='overnight', change_pct=1.5),
     '張濬安(航海王)', '國票-安和', '波段持股', ['swing'],
     ['張濬安', '國票-安和', '台積電', '波段', '基本面']),

    ('B4. 部分當沖 narrative',
     make_stock('2891', '中信金', buy_lot=300, sell_lot=100, buy_amt=15000, sell_amt=5000, trade_style='partial', daytrade_ratio=0.33, change_pct=0.5),
     '林滄海', '富邦-建國', '部分當沖', ['swing', 'longterm'],
     ['林滄海', '富邦-建國', '中信金', '300', '100', '33%']),
]

import re
for desc, stock, master, branch, pattern, styles, keywords in cases_b:
    narrative = generate_narrative(stock, master, branch, pattern, styles)
    n_chars = len(narrative)
    # 字數 50-150 (寬鬆容差, 因為中文標點 + 含括弧)
    chars_ok = 50 <= n_chars <= 150
    # 關鍵字含有
    missing = [kw for kw in keywords if kw not in narrative]
    keywords_ok = not missing
    icon = '✅' if (chars_ok and keywords_ok) else '❌'
    print(f"  {icon} {desc}: 字數 {n_chars} (target 50-100, accept 50-150)")
    if missing:
        print(f"      ❌ 缺少 keywords: {missing}")
    print(f"      內容: {narrative}")
    print()
    if not (chars_ok and keywords_ok):
        all_pass = False

# ── C. inject_trade_patterns 整合測試 ──
print("\nC. inject_trade_patterns 注入完整 branches_data")
fake_branches_data = [
    {
        'code': '9227', 'name': '凱基-城中',
        'buys': [
            make_stock('3443', '創意', buy_lot=11, sell_lot=0, buy_amt=15465, is_limit_up=True, change_pct=9.96, trade_style='overnight'),
        ],
        'sells': [],
    },
]
watched_branches = [
    {'code': '9227', 'name': '凱基-城中', 'master': '蔣承翰'},
]
master_styles_map = {'蔣承翰': ['next_day_flipper']}

count = inject_trade_patterns(fake_branches_data, watched_branches, master_styles_map)
print(f"  注入 stock count = {count}")
injected_stock = fake_branches_data[0]['buys'][0]
ok_c1 = injected_stock.get('trade_pattern') == '隔日沖'
ok_c2 = injected_stock.get('insight_narrative') and len(injected_stock['insight_narrative']) >= 50
icon_c = '✅' if (count == 1 and ok_c1 and ok_c2) else '❌'
print(f"  {icon_c} 注入後 trade_pattern={injected_stock.get('trade_pattern')}, narrative 字數={len(injected_stock.get('insight_narrative', ''))}")
if not (count == 1 and ok_c1 and ok_c2):
    all_pass = False

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
