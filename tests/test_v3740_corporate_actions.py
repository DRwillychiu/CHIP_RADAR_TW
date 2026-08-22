# -*- coding: utf-8 -*-
"""v3.74.0 公司行動偵測 + 維持率還原校正 測試

背景 (2026-08-21 用戶回報):
  寶雅 5904 於 20260810 做 1:10 股票分割, stock_history 存未還原收盤價.
  30 日均價窗跨過分割日 → 均價 475 (720 元時代與 79 元時代混算)
  → 維持率 26% 誤判「斷頭區」, 實際約 164% 健康.
  用戶會依維持率警示調整部位 → 假警報直接造成錯誤決策.

驗證:
  1. 還原因子語意 (factor = 事件前 ÷ 事件後)
  2. 跳空偵測門檻 (>11% 才算, ±10% 漲跌停內不算)
  3. spike 過濾 (單日資料錯誤的一去一回不可誤判為兩次公司行動)
  4. adjust_closes 把事件前價格拉到事件後尺度
  5. 多重事件累乘
  6. compute_n_day_avg_close 整合 (寶雅情境端對端)
  7. 官方 > 偵測 的優先序
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from src.fetchers.corporate_actions import (
    detect_from_price_series, detect_bad_price_days, adjust_closes,
    latest_action_within, build_action_map, _roc_to_ad, _f,
)
import src.analyzers.margin_maintenance as mm

P = F = 0
def check(label, cond, extra=""):
    global P, F
    if cond:
        print(f"  ✅ {label}"); P += 1
    else:
        print(f"  ❌ {label}  {extra}"); F += 1


def mk(prices):
    return {d: {'close': c} for d, c in prices.items()}


# ─── 1. 日期轉換 / 數值解析 ───
print("\n[1] 民國日期 + 數值解析")
check("115/08/24 → 20260824", _roc_to_ad('115/08/24') == '20260824')
check("1150824 → 20260824", _roc_to_ad('1150824') == '20260824')
check("空字串 → None", _roc_to_ad('') is None)
check("千分位 '1,234.5' → 1234.5", _f('1,234.5') == 1234.5)
check("'-' → None", _f('-') is None)

# ─── 2. 跳空偵測門檻 ───
print("\n[2] 跳空偵測 (>11% 才算, 漲跌停內不算)")
normal = mk({'20260801': 100, '20260802': 109.9, '20260803': 99.0})
check("±10% 內不觸發", detect_from_price_series(normal) == [])
split = mk({'20260801': 720, '20260802': 79.2, '20260803': 80.0})
acts = detect_from_price_series(split)
check("1:10 分割被偵測到", len(acts) == 1, f"got {len(acts)}")
check("事件日 = 跳空當天", acts and acts[0]['date'] == '20260802')
check("factor = 前收 ÷ 後收 = 9.09",
      acts and abs(acts[0]['factor'] - 720/79.2) < 1e-4, f"got {acts[0]['factor'] if acts else None}")
check("confidence = inferred", acts and acts[0]['confidence'] == 'inferred')

# ─── 3. spike 過濾 (瑞儀 6176 真實情境) ───
print("\n[3] spike 過濾 — 單日資料錯誤不可誤判為公司行動")
spike = mk({'20260528': 102.0, '20260602': 10.0, '20260603': 102.85, '20260604': 103.0})
acts_s = detect_from_price_series(spike)
check("一去一回 → 0 筆行動 (原本會誤報 2 筆)", len(acts_s) == 0, f"got {len(acts_s)}")
bad = detect_bad_price_days(spike)
check("壞資料日正確標出 20260602", bad == ['20260602'], f"got {bad}")

# 真實公司行動不該被 spike 過濾誤殺
real = mk({'20260801': 720, '20260802': 79.2, '20260803': 80.0, '20260804': 81.0})
check("真分割不被 spike 過濾誤殺", len(detect_from_price_series(real)) == 1)
check("真分割日不算壞資料", detect_bad_price_days(real) == [])

# ─── 4. adjust_closes 還原 ───
print("\n[4] adjust_closes — 事件前價格拉到事件後尺度")
daily = mk({'20260801': 720, '20260802': 79.2, '20260803': 80.0})
adj = adjust_closes(daily, [{'date': '20260802', 'factor': 9.090909}])
check("事件前 720 → 約 79.2", abs(adj['20260801'] - 79.2) < 0.1, f"got {adj['20260801']:.2f}")
check("事件後 79.2 不動", adj['20260802'] == 79.2)
check("事件後 80.0 不動", adj['20260803'] == 80.0)

# 無行動 → 原值
check("無行動 → 全部原值", adjust_closes(daily, []) ==
      {'20260801': 720.0, '20260802': 79.2, '20260803': 80.0})

# ─── 5. 多重事件累乘 ───
print("\n[5] 多重公司行動累乘")
d2 = mk({'20260701': 400, '20260801': 200, '20260901': 100})
adj2 = adjust_closes(d2, [{'date': '20260801', 'factor': 2.0},
                           {'date': '20260901', 'factor': 2.0}])
check("最舊經兩次事件 400 → 100", abs(adj2['20260701'] - 100) < 1e-6, f"got {adj2['20260701']}")
check("中間經一次事件 200 → 100", abs(adj2['20260801'] - 100) < 1e-6, f"got {adj2['20260801']}")
check("最新不動 100", adj2['20260901'] == 100)

# ─── 6. latest_action_within ───
print("\n[6] 窗口內事件判定")
A = [{'date': '20260601', 'factor': 2.0}, {'date': '20260810', 'factor': 10.0}]
check("窗內取最近一次", (latest_action_within(A, ['20260801', '20260815']) or {}).get('date') == '20260810')
check("窗外 → None", latest_action_within(A, ['20260901', '20260910']) is None)
check("空 list → None", latest_action_within([], ['20260801']) is None)

# ─── 7. 端對端: 寶雅情境 ───
print("\n[7] 端對端 — 寶雅 5904 分割情境 (維持率不可誤判斷頭)")
prices = {}
for i in range(1, 13):          # 分割前 12 天, 700-720
    prices[f'202607{i:02d}'] = 710.0
for i in range(10, 23):         # 分割後 13 天, 約 77
    prices[f'202608{i:02d}'] = 77.0
sh = {'stocks': {'5904': {'name': '寶雅', 'daily': mk(prices)}}}
ca = {'5904': [{'date': '20260810', 'type': 'detected_gap',
                'factor': 9.090909, 'confidence': 'inferred'}]}

r_no = mm.compute_n_day_avg_close('5904', sh, corporate_actions=None)
r_yes = mm.compute_n_day_avg_close('5904', sh, corporate_actions=ca)
check("未校正: 均價被污染 (>300)", r_no and r_no['avg'] > 300, f"got {r_no['avg']:.1f}" if r_no else 'None')
check("已校正: 均價回到合理區間 (<100)", r_yes and r_yes['avg'] < 100, f"got {r_yes['avg']:.1f}" if r_yes else 'None')
check("已校正標記 adjusted=True", r_yes and r_yes['adjusted'] is True)
check("附帶事件資訊", r_yes and (r_yes.get('action') or {}).get('date') == '20260810')

today = 74.5
m_no = mm.compute_stock_maintenance(today, 5000, r_no['avg'])
m_yes = mm.compute_stock_maintenance(today, 5000, r_yes['avg'])
check("未校正 → 誤判斷頭區", m_no and m_no['margin_risk_level'] == 'margin_call',
      f"got {m_no['margin_maintenance_ratio'] if m_no else None}%")
check("已校正 → 判為健康", m_yes and m_yes['margin_risk_level'] == 'healthy',
      f"got {m_yes['margin_maintenance_ratio'] if m_yes else None}%")

# ─── 8. 官方 > 偵測 優先序 ───
print("\n[8] 官方資料優先於自我偵測")
sh8 = {'stocks': {'9999': {'daily': mk({'20260801': 720, '20260802': 79.2,
                                         '20260803': 80.0, '20260804': 81.0,
                                         '20260805': 82.0})}}}
m8 = build_action_map(sh8, months=1, include_official=False)
check("include_official=False → 只有偵測結果",
      len(m8['actions'].get('9999', [])) == 1 and m8['stats']['inferred'] == 1)
check("不打官方 API 時 official=0", m8['stats']['official'] == 0)

# ─── 9. 退化保護 ───
print("\n[9] 退化保護")
check("stock_history=None → None", mm.compute_n_day_avg_close('X', None) is None)
check("code 不存在 → None", mm.compute_n_day_avg_close('NOPE', sh) is None)
sh9 = {'stocks': {'Y': {'daily': mk({'20260601': 100})}}}
check("樣本不足 → None", mm.compute_n_day_avg_close('Y', sh9) is None)

print(f"\n{'='*58}")
print(f"test_v3740_corporate_actions: {P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
