# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

# -*- coding: utf-8 -*-
"""
test_v3340_industry_rotation.py — v3.34.0 (B6) 族群輪動追蹤測試

驗證:
  1. 月度 bucket 正確切分
  2. 每月 top 族群 + pct 正確
  3. rotated flag: 最大族群換月時觸發 + rotated_from
  4. raw 金額 (不衰減, bucket 已是時間切片)
  5. 無分類表 / 無 trades → None (graceful)
  6. compute_global_rotation: 多 master 彙總 + flows delta
  7. flows: <1pp 噪音過濾 + |delta| 排序
  8. build_master_profile 整合 (industry_rotation 欄位)
  9. 單月資料 → 無 flows (需 ≥2 月)

跑法: python test_v3340_industry_rotation.py  (免密碼, 合成 fixture)
"""
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from master_profile import (
    compute_industry_rotation,
    compute_global_rotation,
    build_master_profile,
)

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


def mk_trade(date, code, amt):
    return {
        'date': date, 'branch_code': '9A00', 'stock_code': code,
        'stock_name': 'X', 'buy_lot': 10, 'sell_lot': 0,
        'buy_amt': amt, 'sell_amt': 0,
        'is_limit_up': False, 'trade_style': 'overnight',
    }


IND_MAP = {
    '2603': '航運業', '2609': '航運業', '2615': '航運業',
    '2330': '半導體業', '2454': '半導體業', '3034': '半導體業',
    '2317': '電子零組件業',
}

# ────────────────────────────────────────────────────────────────────
print("\n[Case 1] 月度 bucket + top 族群: 5月航運 → 6月半導體")
trades = [
    # 5 月: 航運 8000 + 半導體 2000 → 航運 80%
    mk_trade('20260505', '2603', 5000), mk_trade('20260512', '2609', 3000),
    mk_trade('20260520', '2330', 2000),
    # 6 月: 半導體 9000 + 航運 1000 → 半導體 90%
    mk_trade('20260603', '2330', 4000), mk_trade('20260605', '2454', 5000),
    mk_trade('20260610', '2615', 1000),
]
rot = compute_industry_rotation(trades, IND_MAP)
check("2 個月 bucket", rot is not None and len(rot) == 2, f"got {rot and len(rot)}")
m5, m6 = rot[0], rot[1]
check("月份升冪 (05 → 06)", m5['month'] == '2026-05' and m6['month'] == '2026-06')
check("5月 top = 航運業 80%", m5['top'][0]['name'] == '航運業' and abs(m5['top'][0]['pct'] - 80.0) < 0.1,
      f"got {m5['top'][0]}")
check("6月 top = 半導體業 90%", m6['top'][0]['name'] == '半導體業' and abs(m6['top'][0]['pct'] - 90.0) < 0.1,
      f"got {m6['top'][0]}")
check("5月 total_amt_wan = 1000 (10000仟元)", m5['total_amt_wan'] == 1000,
      f"got {m5['total_amt_wan']}")
check("trades_count 正確 (5月 3 筆)", m5['trades_count'] == 3)

# ────────────────────────────────────────────────────────────────────
print("\n[Case 2] rotated flag: 6月最大族群換了 → rotated=True + from 航運")
check("5月 rotated=False (第一個月)", m5['rotated'] is False)
check("6月 rotated=True", m6['rotated'] is True)
check("6月 rotated_from = 航運業", m6['rotated_from'] == '航運業',
      f"got {m6['rotated_from']}")

# ────────────────────────────────────────────────────────────────────
print("\n[Case 3] 沒輪動: 兩月都同族群 → rotated=False")
trades3 = [mk_trade('20260505', '2603', 5000), mk_trade('20260605', '2609', 5000)]
rot3 = compute_industry_rotation(trades3, IND_MAP)
check("6月 rotated=False (都是航運)", rot3[1]['rotated'] is False and rot3[1]['rotated_from'] is None)

# ────────────────────────────────────────────────────────────────────
print("\n[Case 4] graceful None: 無分類表 / 無 trades / 壞日期")
check("無分類表 → None", compute_industry_rotation(trades, None) is None)
check("無 trades → None", compute_industry_rotation([], IND_MAP) is None)
check("全壞日期 → None", compute_industry_rotation([mk_trade('bad', '2330', 100)], IND_MAP) is None)

# ────────────────────────────────────────────────────────────────────
print("\n[Case 5] 未分類 code 歸「未分類」")
rot5 = compute_industry_rotation([mk_trade('20260605', '9999', 1000)], IND_MAP)
check("未知 code → 未分類族群", rot5[0]['top'][0]['name'] == '未分類')

# ────────────────────────────────────────────────────────────────────
print("\n[Case 6] compute_global_rotation: 兩 master 彙總 + flows")


def mk_buy(code, amt):
    """history fixture 的 buys 用 raw crawler 格式 ('code' key, 非 'stock_code')"""
    return {'code': code, 'name': 'X', 'buy_lot': 10, 'sell_lot': 0,
            'buy_amt': amt, 'sell_amt': 0, 'is_limit_up': False,
            'trade_style': 'overnight'}


history = []
for date, branches in [
    # 5月: 甲買航運 6000, 乙買半導體 4000 → 航運 60% / 半導體 40%
    ('20260505', [('9A00', '甲', [mk_buy('2603', 6000)]),
                  ('9B00', '乙', [mk_buy('2330', 4000)])]),
    # 6月: 甲買航運 2000, 乙買半導體 8000 → 航運 20% / 半導體 80%
    ('20260605', [('9A00', '甲', [mk_buy('2609', 2000)]),
                  ('9B00', '乙', [mk_buy('2454', 8000)])]),
]:
    history.append({'date': date, 'data': {'branches': [
        {'code': c, 'name': c, 'master': m, 'co_masters': [], 'buys': buys}
        for c, m, buys in branches]}})
targets = {'甲': ['swing'], '乙': ['swing']}
g = compute_global_rotation(history, targets, IND_MAP)
check("global months = 2", g is not None and len(g['months']) == 2)
check("flow_months = [2026-05, 2026-06]", g.get('flow_months') == ['2026-05', '2026-06'])
flows = {f['industry']: f for f in g.get('flows', [])}
check("半導體 +40pp 流入", '半導體業' in flows and abs(flows['半導體業']['delta_pp'] - 40.0) < 0.5,
      f"got {flows.get('半導體業')}")
check("航運 -40pp 流出", '航運業' in flows and abs(flows['航運業']['delta_pp'] + 40.0) < 0.5,
      f"got {flows.get('航運業')}")

# ────────────────────────────────────────────────────────────────────
print("\n[Case 7] flows 按 |delta| 排序 + <1pp 過濾")
sorted_ok = all(abs(g['flows'][i]['delta_pp']) >= abs(g['flows'][i+1]['delta_pp'])
                for i in range(len(g['flows']) - 1))
check("按 |delta| 降冪", sorted_ok)
check("無 <1pp 噪音", all(abs(f['delta_pp']) >= 1.0 for f in g['flows']))

# ────────────────────────────────────────────────────────────────────
print("\n[Case 8] build_master_profile 整合: industry_rotation 欄位")
profile = build_master_profile('甲', history, targets, stock_industry_map=IND_MAP)
check("profile 有 industry_rotation", 'industry_rotation' in profile,
      f"keys={list(profile.keys())}")
pr = profile.get('industry_rotation') or []
check("甲: 2 個月都是航運", len(pr) == 2 and all(m['top'][0]['name'] == '航運業' for m in pr))
profile_no_map = build_master_profile('甲', history, targets)
check("無分類表 → profile 無此欄位", 'industry_rotation' not in profile_no_map)

# ────────────────────────────────────────────────────────────────────
print("\n[Case 9] 單月資料 → 無 flows (需 ≥2 月)")
hist_single = [history[1]]   # 只有 6 月
g_single = compute_global_rotation(hist_single, targets, IND_MAP)
check("單月 → months=1 無 flows", g_single is not None and len(g_single['months']) == 1
      and 'flows' not in g_single)

# ────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3340_industry_rotation: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
