# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

# -*- coding: utf-8 -*-
"""
test_v3371_tdcc_holdings.py — v3.37.0 TDCC 集保大戶測試

驗證:
  1. parse_csv_to_aggregates: 15 級正確聚合 (big400/mega1000/retail/mid)
  2. Level 16 (差異調整) + 17 (合計) 被略過
  3. effective_date 從第一筆抓取
  4. select_codes_to_keep: watched ∪ Top N by total_shares
  5. compute_vs_prev_week: delta_pp + 缺上週 → None
  6. inject_holdings_into_stocks (branches list 結構)
  7. _compute_movers: risers/fallers 按 delta 排序

跑法: python test_v3371_tdcc_holdings.py
"""
import sys, io, tempfile, json
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import tdcc_holdings as th

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

def mk_csv(stocks):
    """stocks: {code: [(level, holders, shares, ratio), ...]}"""
    lines = ['資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%']
    for code, rows in stocks.items():
        for level, h, s, r in rows:
            lines.append(f'20260618,{code},{level},{h},{s},{r}')
    return '\n'.join(lines)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 1] 15 級正確聚合: big400 = level 12-15")
# 2330 台積電: level 1-8 散戶 5%, level 9-11 中戶 5%, level 12-15 大戶 90%
csv1 = mk_csv({'2330': [
    (i, 100, 1000, 5/8) for i in range(1, 9)   # 散戶 5% 平分 8 級
] + [
    (i, 50, 5000, 5/3) for i in range(9, 12)   # 中戶 5% 平分 3 級
] + [
    (i, 30, 50000, 90/4) for i in range(12, 16)   # 大戶 90% 平分 4 級
]})
date, agg = th.parse_csv_to_aggregates(csv1)
check("effective_date 抓到", date == '20260618')
check("2330 解析到", '2330' in agg)
d = agg['2330']
check("big400_pct ≈ 90", abs(d['big400_pct'] - 90) < 0.1, f"got {d['big400_pct']}")
check("mega1000_pct ≈ 22.5 (level 15)", abs(d['mega1000_pct'] - 22.5) < 0.1)
check("retail_pct ≈ 5 (level 1-8)", abs(d['retail_pct'] - 5) < 0.1)
check("mid_pct ≈ 5 (level 9-11)", abs(d['mid_pct'] - 5) < 0.1)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 2] Level 16/17 被略過")
csv2 = mk_csv({'X': [
    (12, 100, 1000, 10), (15, 50, 5000, 15),
    (16, 999, 99999, 999),   # 差異調整 — 不算
    (17, 999, 99999, 100),   # 合計 — 不算
]})
date, agg = th.parse_csv_to_aggregates(csv2)
check("big400 = 25 (10+15, 不含 16/17)", abs(agg['X']['big400_pct'] - 25) < 0.1,
      f"got {agg['X']['big400_pct']}")

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 3] 壞行處理")
csv3 = mk_csv({'OK': [(12, 100, 1000, 50)]})
csv3 += '\n20260618,BAD,not-int,1,1,1'   # level 非 int
csv3 += '\n20260618,,12,1,1,1'           # 空 code
date, agg = th.parse_csv_to_aggregates(csv3)
check("壞行不爆 + OK 解析正常", 'OK' in agg and 'BAD' not in agg and '' not in agg)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] select_codes_to_keep: watched ∪ Top N")
agg = {f'{i:04d}': {'total_shares': 10000 - i, 'big400_pct': 50}
        for i in range(50)}   # 0000 最大 → 0049 最小
watched = {'0099', '0010'}    # 0099 不在 agg, 0010 在
selected = th.select_codes_to_keep(agg, watched, top_n_by_total_shares=5)
check("Top 5 (0000-0004) + watched 0010 都在", all(c in selected for c in ['0000','0001','0002','0003','0004','0010']))
check("0099 不在 agg → 不在 selected", '0099' not in selected)
check("0030 不在 (沒被 watched 也非 Top 5)", '0030' not in selected)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 5] compute_vs_prev_week delta + 缺上週")
current = {'A': {'big400_pct': 50, 'mega1000_pct': 30, 'retail_pct': 20},
            'B': {'big400_pct': 60, 'mega1000_pct': 40, 'retail_pct': 10}}
prev = {'A': {'big400_pct': 45, 'mega1000_pct': 28, 'retail_pct': 25,
              'effective_date': '20260611'}}
r = th.compute_vs_prev_week(current, prev)
check("A 有 vs_prev_week (+5.0pp)", abs(r['A']['vs_prev_week']['big400_delta_pp'] - 5.0) < 0.01)
check("A retail -5.0pp", abs(r['A']['vs_prev_week']['retail_delta_pp'] - (-5.0)) < 0.01)
check("B 無上週資料 → vs_prev_week=None", r['B']['vs_prev_week'] is None)
check("無上週 prev (None) 全部標 None",
      th.compute_vs_prev_week({'C': {'big400_pct': 50, 'mega1000_pct': 30, 'retail_pct': 20}}, None)['C']['vs_prev_week'] is None)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 6] inject_holdings_into_stocks (branches list)")
branches = [
    {'master': '甲', 'buys': [{'code': '2330'}, {'code': '9999'}], 'sells': []},
    {'master': '乙', 'buys': [{'code': '2330'}], 'sells': [{'code': '3481'}]},
]
cache = {
    'effective_date': '20260618',
    'effective_week_iso': '2026-W25',
    'fetched_at': 'now',
    'count': 3,
    'caveat': 'TDCC 集保',
    'holdings': {
        '2330': {'big400_pct': 88, 'mega1000_pct': 85, 'retail_pct': 8, 'vs_prev_week': None},
        '3481': {'big400_pct': 46, 'mega1000_pct': 41, 'retail_pct': 38, 'vs_prev_week': None},
    },
}
r = th.inject_holdings_into_stocks(branches, cache)
check("injected = 3 (兩 2330 + 一 3481)", r['injected'] == 3,
      f"got {r['injected']}")
check("9999 不在 cache → 不注入", 'tdcc_holdings' not in branches[0]['buys'][1])
check("2330 注入 big400=88", branches[0]['buys'][0]['tdcc_holdings']['big400_pct'] == 88)
check("metadata 透傳 effective_date", r['metadata']['effective_date'] == '20260618')

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 7] _compute_movers risers/fallers 排序")
holdings = {
    'A': {'big400_pct': 90, 'mega1000_pct': 80, 'retail_pct': 5,
          'vs_prev_week': {'big400_delta_pp': 5.0, 'mega1000_delta_pp': 4.0, 'retail_delta_pp': -3.0}},
    'B': {'big400_pct': 30, 'mega1000_pct': 20, 'retail_pct': 60,
          'vs_prev_week': {'big400_delta_pp': -8.0, 'mega1000_delta_pp': -5.0, 'retail_delta_pp': 7.0}},
    'C': {'big400_pct': 50, 'mega1000_pct': 40, 'retail_pct': 30, 'vs_prev_week': None},
}
m = th._compute_movers(holdings)
check("risers 含 A (+5)", m['risers'][0]['code'] == 'A' if False else any(x['code']=='A' for x in m['big400_risers']))
check("fallers Top = B (-8)", m['big400_fallers'][0]['code'] == 'B')
check("C (vs_prev_week=None) 不在 movers", all(x['code'] != 'C' for x in m['big400_risers'] + m['big400_fallers']))

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 8] load_prev_week_snapshot 找最近一週")
with tempfile.TemporaryDirectory() as td:
    hdir = Path(td) / 'tdcc_history'
    hdir.mkdir()
    (hdir / '20260611.json').write_text(json.dumps({'effective_date':'20260611','holdings':{'A':{}}}), encoding='utf-8')
    (hdir / '20260618.json').write_text(json.dumps({'effective_date':'20260618','holdings':{'B':{}}}), encoding='utf-8')
    prev = th.load_prev_week_snapshot(td, current_date='20260618')
    check("找到上週 (20260611)", prev is not None and 'A' in prev)
    check("跳過當週", prev is not None and 'B' not in prev)
    none_dir = th.load_prev_week_snapshot('/nonexistent_dir_xyz')
    check("不存在目錄 → None", none_dir is None)

# ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3371_tdcc_holdings: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
