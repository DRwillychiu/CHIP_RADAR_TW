# -*- coding: utf-8 -*-
"""
test_v3460_tier2.py — v3.46.0 Tier 2 競品 gap 測試

驗證:
  後7 attention_fetcher: parse 注意股 + cache + fallback
  後6 short_lending_fetcher: parse 借券 + Top borrow 排序
  後8 dividend_fetcher: parse 除權息 + ROC 日期轉換 + upcoming 30d
  後9 main_force_cost: 60 天 history 算 5d/20d 成本線 + premium pct
"""
import sys, io, json, tempfile
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PASS = 0
FAIL = 0
def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 1] attention_fetcher parse_notice")
from attention_fetcher import parse_notice
mock_twse = {
    'stat': 'OK',
    'title': '公布注意有價證券資訊 (115年06月19日)',
    'fields': ['編號', '證券代號', '證券名稱', '累計次數', '注意交易資訊', '日期', '收盤價', '本益比'],
    'data': [
        ['1', '2330', '台積電', '3', '股價漲跌幅', '20260619', '1100.00', '15.2'],
        ['2', '2454', '聯發科', '1', '成交量異常', '20260619', '1200.00', '20.1'],
    ],
}
parsed = parse_notice(mock_twse)
check("count = 2", parsed['count'] == 2)
check("含 2330", '2330' in parsed['by_code'])
check("2330 累計次數 = 3", parsed['by_code']['2330']['cumulative_count'] == 3)
check("applicable_date = 20260619", parsed['applicable_date'] == '20260619')

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 2] short_lending_fetcher parse_twtasu + Top borrow 排序")
from short_lending_fetcher import parse_twtasu
mock_twtasu = {
    'stat': 'OK',
    'title': '115年06月18日當日融券賣出與借券賣出成交量值',
    'data': [
        ['2887   台新新光金', '3', '450', '11122', '1681700'],
        ['2330   台積電', '50', '550000', '500', '5500000'],
        ['0000   零活動', '0', '0', '0', '0'],   # 應被過濾
    ],
}
ps = parse_twtasu(mock_twtasu)
check("含 2887 + 2330 (零活動排除)", '2887' in ps['by_code'] and '2330' in ps['by_code'] and '0000' not in ps['by_code'])
check("Top borrow 第 1 = 2887 (借券 11122 > 500)", ps['top_borrow_sell'][0]['code'] == '2887')
check("2887 borrow/short ratio ≈ 3707", abs(ps['by_code']['2887']['borrow_vs_short_ratio'] - 3707.33) < 1)
check("applicable_date = 20260618", ps['applicable_date'] == '20260618')

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 3] dividend_fetcher — ROC 日期轉換 + upcoming 30d")
from dividend_fetcher import parse_twt48u, _roc_to_yyyymmdd
check("ROC '115/08/15' → 20260815", _roc_to_yyyymmdd('115/08/15') == '20260815')
check("ROC '115年08月15日' → 20260815", _roc_to_yyyymmdd('115年08月15日') == '20260815')
check("空字串 → None", _roc_to_yyyymmdd('') is None)
check("壞輸入 → None", _roc_to_yyyymmdd('not-a-date') is None)
mock_twt48u = {
    'stat': 'OK',
    'fields': ['除權除息日期', '股票代號', '名稱', '除權息', '無償配股率', '現金股利'],
    'data': [
        ['115/06/22', '00713', '元大台灣高息低波', '息', '0', '1.00'],
        ['115/08/15', '2330', '台積電', '息', '0', '4.00'],
        ['115/12/31', '1101', '台泥', '息', '0', '2.50'],
    ],
}
pdr = parse_twt48u(mock_twt48u)
check("count = 3", pdr['count'] == 3)
check("2330 ex_date = 20260815", pdr['by_code']['2330']['ex_date'] == '20260815')
check("2330 cash = 4.00", pdr['by_code']['2330']['cash_dividend'] == 4.00)
# upcoming_30d (從今天 2026-06-19 算): 00713 6/22 在內, 2330 8/15 在外, 1101 12/31 在外
check("upcoming 30d 含 6/22 00713",
      any(it['code'] == '00713' for it in pdr['upcoming_30d']))

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] main_force_cost — 60 天 history 算 5d/20d 成本線")
from main_force_cost import compute_main_force_cost_per_stock, inject_main_force_cost
# Mock 5 天 history: 5 天買台積電, 每天買 100 張 × 1000 元/股 = 100000 仟元
history = []
for d in range(1, 6):
    history.append({
        'date': f'2026060{d}', 'data': {'branches': [
            {'code': '9A00', 'master': '甲', 'co_masters': [], 'buys': [
                {'code': '2330', 'name': '台積電', 'buy_lot': 100,
                 'buy_amt': 100000, 'sell_lot': 0, 'sell_amt': 0,
                 'is_limit_up': False, 'trade_style': 'overnight'},
            ], 'sells': []},
        ]},
    })
costs_5d = compute_main_force_cost_per_stock(history, 5)
# 累計 amt = 500000 仟元, lot = 500 張 → cost = 500000 / 500 = 1000 元
check("5 天成本線 = 1000 元", abs(costs_5d.get('2330', 0) - 1000) < 0.01,
      f"got {costs_5d.get('2330')}")

# inject + premium pct
branches = [{'master': '甲', 'buys': [{'code': '2330', 'name': '台積電'}], 'sells': []}]
quotes = {'2330': {'close': 1100}}   # 高於成本線 10%
r = inject_main_force_cost(branches, history, quotes)
check("注入 1 筆", r['computed'] == 1)
stock = branches[0]['buys'][0]
check("main_force_cost_5d = 1000", stock['main_force_cost_5d'] == 1000)
check("premium_5d_pct ≈ +10", abs(stock['main_force_cost_premium_5d_pct'] - 10.0) < 0.5)

# ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3460_tier2: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
