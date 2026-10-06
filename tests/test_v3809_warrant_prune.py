# -*- coding: utf-8 -*-
"""v3.80.9 權證不進 stock_history — 權證排除, ETF 保留

背景 (2026-10-01 稽核):
  stock_history.json ~30 MB, 其中 15,618 / 18,027 筆是 TPEx 日收盤帶進來的
  上櫃權證 (70xxxx~73xxxx, 認售尾碼 U), 約 16.7 MB, 下游引用 0 次.
  daily-full 一個月 commit ~100 次 → .git 漲到 2.5 GB.

  ⚠️ 不能一刀切「6 碼全砍」: 00 開頭的 ETF/ETN (00981A / 00953B / 00697B ...)
     在 daily_trading_signals / master_profiles 有被引用, 必須保留.
     4 碼個股裡也有 7 開頭的 (7402 / 7547 ...), 不可誤傷.
"""
import sys, os, json, tempfile
from pathlib import Path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')

import src.fetchers.history as hist
from src.fetchers.history import is_warrant_code, prune_warrants, update_history
import prune_warrants_history as pw

P = F = 0
def check(label, cond, extra=""):
    global P, F
    if cond:
        print(f"  ✅ {label}"); P += 1
    else:
        print(f"  ❌ {label}  {extra}"); F += 1

WARRANTS = ['700008', '710001', '725431', '739999', '72050U', '71845U']
KEEP = {
    '4 碼個股': ['2330', '2317', '7402', '7547', '7003'],
    'ETF/ETN':  ['0050', '00878', '00981A', '00953B', '00697B', '00407A', '00631L', '020001'],
    '其他證券': ['910322', '2887Z1', '01001T', '8349A'],
}

# ─── 1. 代號判定 ───
print("\n[1] is_warrant_code")
for c in WARRANTS:
    check(f"{c} 是權證", is_warrant_code(c))
for kind, codes in KEEP.items():
    for c in codes:
        check(f"{c} ({kind}) 不是權證", not is_warrant_code(c))
check("7 碼 / 5 碼 7 開頭不算", not is_warrant_code('7000001') and not is_warrant_code('70000'))
check("空值 / None 不炸", not is_warrant_code('') and not is_warrant_code(None))

# ─── 2. prune_warrants 冪等 ───
print("\n[2] prune_warrants")
ALL_KEEP = [c for cs in KEEP.values() for c in cs]
h = {'stocks': {c: {'name': '', 'industry': '', 'daily': {}} for c in WARRANTS + ALL_KEEP}}
check("移除筆數 = 權證數", prune_warrants(h) == len(WARRANTS))
check("權證全部移除", not any(c in h['stocks'] for c in WARRANTS))
check("非權證全部保留", all(c in h['stocks'] for c in ALL_KEEP))
check("再跑一次 → 0 筆 (冪等)", prune_warrants(h) == 0)
check("沒有 stocks 欄位不炸", prune_warrants({}) == 0)

# ─── 3. update_history 端到端 (不打網路) ───
print("\n[3] update_history — 新權證略過 + 既有權證自我清除")
hist._fetch_taiex_fmtqik = lambda *a, **k: None
hist._fetch_taiex_index = lambda *a, **k: None
hist._fetch_fmtqik_month = lambda *a, **k: {}

with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    # 模擬被並行排程用舊版蓋回: 檔案裡還留著權證
    seed = {
        'updated_at': None, 'max_days': 60, 'dates': ['20260930'],
        'stocks': {
            '730001': {'name': '', 'industry': '', 'daily': {'20260930': {'close': 1.0, 'change_pct': 0.0}}},
            '72050U': {'name': '', 'industry': '', 'daily': {}},
            '2330':   {'name': '台積電', 'industry': '半導體業',
                       'daily': {'20260930': {'close': 1000.0, 'change_pct': 0.0}}},
        },
        'industry_avg': {}, 'market': {}, 'futures': {},
    }
    (d / 'stock_history.json').write_text(json.dumps(seed, ensure_ascii=False), encoding='utf-8')

    quotes = {c: {'close': 10.0, 'change_pct': 1.0} for c in WARRANTS + ALL_KEEP}
    update_history(d, '20261001', quotes, {'stock_industry': {'2330': '半導體業'}})
    out = json.loads((d / 'stock_history.json').read_text(encoding='utf-8'))
    st = out['stocks']

    check("當日報價的權證沒有寫入", not any(c in st for c in WARRANTS),
          [c for c in WARRANTS if c in st])
    check("檔案裡既有的權證被清掉 (自我修復)", '730001' not in st and '72050U' not in st)
    for kind, codes in KEEP.items():
        check(f"{kind} 全部寫入當日資料",
              all(st.get(c, {}).get('daily', {}).get('20261001') for c in codes),
              [c for c in codes if c not in st])
    check("2330 既有歷史保留", '20260930' in st['2330']['daily'] and st['2330']['name'] == '台積電')
    check("寫入後檔案中零權證", sum(is_warrant_code(c) for c in st) == 0)

# ─── 4. 一次性 script 的引用收集 ───
print("\n[4] collect_referenced_codes / unresolved")
with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    (d / 'daily_trading_signals.json').write_text(json.dumps({
        'anomalies': [{'top_new': [{'code': '00981A'}, {'code': '2330'}]}],
        'consensus': [{'stock_code': '2317'}],
    }), encoding='utf-8')
    (d / 'master_profiles.json').write_text(json.dumps({
        'masters': {'X': {'per_branch_profiles': {'9B25': {'stocks': [{'stock_code': '00407A'}]}}}},
    }), encoding='utf-8')
    refs = pw.collect_referenced_codes(d)
    check("抓到 top_new[].code 與 stock_code",
          refs['daily_trading_signals.json'] == {'00981A', '2330', '2317'},
          refs['daily_trading_signals.json'])
    check("分點代號 (dict key 9B25) 不被當成個股", refs['master_profiles.json'] == {'00407A'},
          refs['master_profiles.json'])
    check("不存在的檔案 → 空集合", refs['quad_hit_log.json'] == set())
    check("unresolved 列出查不到的代號",
          pw.unresolved(refs, {'2330': {}, '2317': {}, '00407A': {}})
          == {'daily_trading_signals.json': ['00981A']})

# ─── 5. 迴歸: production 現況 ───
print("\n[5] 迴歸 — production stock_history 現況")
prod = Path(ROOT) / 'data' / 'stock_history.json'
if prod.exists():
    st = json.loads(prod.read_text(encoding='utf-8')).get('stocks', {})
    w = [c for c in st if is_warrant_code(c)]
    check(f"production 零權證 ({len(st):,} 檔)", not w, f"{len(w)} 檔, e.g. {w[:5]}")
    check("production 仍有 00 開頭 ETF", sum(c.startswith('00') for c in st) >= 100)
    miss = pw.unresolved(pw.collect_referenced_codes(prod.parent), st)
    check("下游引用的代號全部查得到", not miss, miss)
else:
    print("  (跳過 — 無 production 資料)")

print(f"\n{'=' * 58}")
print(f"test_v3809_warrant_prune: {P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
