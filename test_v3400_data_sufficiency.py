# -*- coding: utf-8 -*-
"""
test_v3400_data_sufficiency.py — v3.40.0 B4 樣本不足三檔測試

驗證:
  1. active_days >= 60 → full
  2. active_days 20-59 → partial
  3. active_days < 20 → insufficient + caveat
  4. caveat 文字符合預期
  5. profile['data_sufficiency'] 結構完整
  6. 不破壞既有 profile 結構

跑法: python test_v3400_data_sufficiency.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from master_profile import build_master_profile

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


def mk_stock(code, **kw):
    return {'code': code, 'name': 'X', 'buy_lot': 10, 'sell_lot': 0,
            'buy_amt': 1000, 'sell_amt': 0, 'is_limit_up': False,
            'trade_style': 'overnight', **kw}


def mk_history(active_days_count):
    """產生 N 天 history, 每天甲 master 都有交易"""
    h = []
    for i in range(active_days_count):
        date = f'202604{i+1:02d}' if i < 30 else f'202605{i-29:02d}' if i < 60 else f'202606{i-59:02d}'
        h.append({'date': date, 'data': {'branches': [
            {'code': '9A00', 'name': 't', 'master': '甲', 'co_masters': [],
             'buys': [mk_stock('2330')], 'sells': []}
        ]}})
    return h


# ─────────────────────────────────────────────────────────────────────
print("\n[Case 1] active_days >= 60 → full")
p = build_master_profile('甲', mk_history(60), {'甲': ['swing']})
suff = p.get('data_sufficiency') or {}
check("level = full", suff.get('level') == 'full', f"got {suff.get('level')}")
check("label = 充足", suff.get('label') == '充足')
check("active_days = 60", suff.get('active_days') == 60)
check("caveat = None (full 無 caveat)", suff.get('caveat') is None)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 2] active_days 20-59 → partial")
p2 = build_master_profile('甲', mk_history(35), {'甲': ['swing']})
suff2 = p2['data_sufficiency']
check("level = partial", suff2['level'] == 'partial', f"got {suff2['level']}")
check("label = 部分", suff2['label'] == '部分')
check("partial caveat 含「漂移」", '漂移' in (suff2.get('caveat') or ''))

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 3] active_days < 20 → insufficient + caveat")
p3 = build_master_profile('甲', mk_history(10), {'甲': ['swing']})
suff3 = p3['data_sufficiency']
check("level = insufficient", suff3['level'] == 'insufficient')
check("label = 樣本不足", suff3['label'] == '樣本不足')
check("caveat 含「樣本不足」", '樣本不足' in (suff3.get('caveat') or ''))
check("caveat 含「待校準」", '待校準' in (suff3.get('caveat') or ''))

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 4] 邊界 active_days = 19 (insufficient), 20 (partial), 59 (partial), 60 (full)")
for n, expected in [(19, 'insufficient'), (20, 'partial'), (59, 'partial'), (60, 'full')]:
    p_n = build_master_profile('甲', mk_history(n), {'甲': ['swing']})
    got = p_n['data_sufficiency']['level']
    check(f"active_days={n} → {expected}", got == expected, f"got {got}")

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 5] thresholds 結構完整")
check("thresholds.full = 60", suff3.get('thresholds', {}).get('full') == 60)
check("thresholds.partial = 20", suff3.get('thresholds', {}).get('partial') == 20)

# ─────────────────────────────────────────────────────────────────────
print("\n[Case 6] 既有 profile 結構不破壞")
check("data_sufficiency 存在", 'data_sufficiency' in p)
check("strategy_labels 仍存在", 'strategy_labels' in p)
check("operation_metrics 仍存在", 'operation_metrics' in p)
check("timing_metrics 仍存在", 'timing_metrics' in p)
check("narrative 仍存在", 'narrative' in p)

print(f"\n{'='*60}")
print(f"test_v3400_data_sufficiency: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
