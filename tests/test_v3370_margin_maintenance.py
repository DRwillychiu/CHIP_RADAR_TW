# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

# -*- coding: utf-8 -*-
"""
test_v3370_margin_maintenance.py — v3.37.0 個股融資維持率市場估算測試

驗證:
  1. compute_n_day_avg_close 公式 (排除 None/0 close)
  2. compute_stock_maintenance 公式 + 分級 (健康/警戒/高風險/斷頭)
  3. 邊界: 餘額 < MIN_BALANCE / today_close=0 / cost=None → None
  4. detect_ex_dividend 偵測單日跌 >7% (含 None)
  5. inject_maintenance_into_stocks 整合 (branches list 結構)
  6. 同股多分點 cache 重用
  7. 全市場 summary counts + Top 30 排序

跑法: python test_v3370_margin_maintenance.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import margin_maintenance as mm

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

def mk_sh(daily_data):
    """daily_data: {code: {date: close}}"""
    return {'stocks': {code: {'daily': {d: {'close': c} for d, c in days.items()}}
                        for code, days in daily_data.items()}}

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 1] compute_n_day_avg_close 公式")
sh = mk_sh({'2330': {f'2026060{i}': 1000+i*10 for i in range(1, 10)}})
r1 = mm.compute_n_day_avg_close('2330', sh, n_days=9)
expected = sum(1000+i*10 for i in range(1,10)) / 9   # = 1050
# v3.74.0: 回傳型別 float → dict {'avg','adjusted','action','n_used',...}
check("回傳 dict 含 avg (v3.74.0 契約)", isinstance(r1, dict) and 'avg' in r1, f"got {type(r1)}")
avg = r1['avg']
check("9 天均價 = 1050", abs(avg - 1050) < 0.1, f"got {avg}")
check("無公司行動 → adjusted=False", r1['adjusted'] is False)
check("n_used = 9", r1['n_used'] == 9, f"got {r1['n_used']}")

print("[Case 2] None close / 0 close 自動排除")
# 需 ≥ max(5, 30//6) = 5 個有效樣本 → 給 6 個 (其中 2 個壞)
sh2 = mk_sh({'X': {'20260601': 100, '20260602': 0, '20260603': 110,
                     '20260604': 120, '20260605': 130, '20260606': 140}})
sh2['stocks']['X']['daily']['20260602'] = {'close': None}
r2 = mm.compute_n_day_avg_close('X', sh2)
# (100+110+120+130+140) / 5 = 120
check("排除 None+0 後均價 120", r2 and r2['avg'] == 120.0, f"got {r2}")

print("[Case 3] 資料不足 → None")
sh3 = mk_sh({'Y': {'20260601': 100}})
check("只有 1 天 < 5 → None", mm.compute_n_day_avg_close('Y', sh3) is None)
check("不存在 code → None", mm.compute_n_day_avg_close('Z', sh3) is None)
check("None stock_history → None", mm.compute_n_day_avg_close('X', None) is None)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] compute_stock_maintenance 分級")
# 初始維持率 ≈ 166.67% (price = cost)
r = mm.compute_stock_maintenance(100, 5000, 100)
check("price=cost 維持率 ≈ 166.7%", abs(r['margin_maintenance_ratio'] - 166.7) < 1)
check("166.7% → 健康", r['margin_risk_level'] == 'healthy')
# 漲到 200 → 333%
r2 = mm.compute_stock_maintenance(200, 5000, 100)
check("price 2× cost → 333%", abs(r2['margin_maintenance_ratio'] - 333.3) < 1)
# 跌到 89 → 148.3% (警戒, 150% 邊界是 healthy)
r3 = mm.compute_stock_maintenance(89, 5000, 100)
check("price 89 cost 100 → 148.3% 警戒", r3['margin_risk_level'] == 'watch',
      f"got {r3['margin_risk_level']} ratio={r3['margin_maintenance_ratio']}")
# 跌到 75 → 125% 高風險
r4 = mm.compute_stock_maintenance(75, 5000, 100)
check("125% → 高風險", r4['margin_risk_level'] == 'high_risk')
# 跌到 70 → 116.7% 斷頭區
r5 = mm.compute_stock_maintenance(70, 5000, 100)
check("116.7% → 斷頭區", r5['margin_risk_level'] == 'margin_call')

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 5] 邊界: 返回 None")
check("today_close=0 → None", mm.compute_stock_maintenance(0, 5000, 100) is None)
check("balance < MIN → None", mm.compute_stock_maintenance(100, 50, 100) is None)
check("cost=None → None", mm.compute_stock_maintenance(100, 5000, None) is None)
check("cost=0 → None", mm.compute_stock_maintenance(100, 5000, 0) is None)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 6] detect_ex_dividend (跳空偵測)")
check("跌 10% → True", mm.detect_ex_dividend(90, 100) is True)
check("跌 5% → False", mm.detect_ex_dividend(95, 100) is False)
check("上漲 → False", mm.detect_ex_dividend(110, 100) is False)
check("prev_close None → False", mm.detect_ex_dividend(90, None) is False)
# 維持率計算後 stale flag
r_stale = mm.compute_stock_maintenance(80, 5000, 100, prev_close=100)
check("跌 20% 維持率仍算 + stale flag",
      r_stale is not None and r_stale.get('margin_stale_due_to_ex_div') is True)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 7] inject_maintenance_into_stocks 整合")
branches = [
    {'master': '甲', 'buys': [{'code': '2330', 'name': '台積電'}], 'sells': []},
    {'master': '乙', 'buys': [{'code': '2330', 'name': '台積電'}], 'sells': []},  # 同股不同分點
    {'master': '丙', 'buys': [{'code': '3481', 'name': '群創'}], 'sells': []},
]
margin_all = {'2330': {'margin_balance': 5000, 'name': '台積電'},
              '3481': {'margin_balance': 8000, 'name': '群創'}}
quotes = {'2330': {'close': 75, 'prev_close': 78},   # 125% 高風險
          '3481': {'close': 50, 'prev_close': 52}}   # 健康
sh_test = mk_sh({'2330': {f'2026060{i}': 100 for i in range(1, 10)},
                  '3481': {f'2026060{i}': 30 for i in range(1, 10)}})
r = mm.inject_maintenance_into_stocks(branches, margin_all, quotes, sh_test)
check("computed = 3 (兩分點都有 2330)", r['computed'] == 3)
check("2330 high_risk_codes", '2330' in r['high_risk_codes'])
check("3481 不在 high_risk", '3481' not in r['high_risk_codes'])
check("甲 2330 標 高風險", branches[0]['buys'][0]['margin_risk_label'] == '高風險')
check("乙 2330 也標到 (cache 重用)", branches[1]['buys'][0]['margin_risk_label'] == '高風險')
check("丙 3481 標健康", branches[2]['buys'][0]['margin_risk_label'] == '健康')

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 8] summary 全市場 counts + Top N 排序")
s = r['summary']
check("summary 存在", s is not None)
check("counts 包含全部分級",
      all(k in s['counts'] for k in ['healthy', 'watch', 'high_risk', 'margin_call', 'insufficient_data']))
check("high_risk_stocks 按 ratio 升冪", all(
    s['high_risk_stocks'][i]['ratio'] <= s['high_risk_stocks'][i+1]['ratio']
    for i in range(len(s['high_risk_stocks']) - 1)))
check("caveat 含「市場估算非個人帳戶」", '市場估算' in s.get('caveat', ''))

# ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3370_margin_maintenance: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
