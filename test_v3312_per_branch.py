"""v3.30.12 per-branch 細分 測試 (解盲點 #5 巨人傑雙風格)"""
import sys
sys.path.insert(0, '.')

from master_profile import (
    extract_master_trades, _list_master_branches,
    build_master_profile,
)

all_pass = True
print("=" * 64)
print("  v3.30.12 per-branch 細分測試")
print("=" * 64)


def mk_stock(code, lot, lu, style):
    return {'code': code, 'name': f'股{code}',
            'buy_lot': lot, 'sell_lot': lot if style == 'daytrade' else 0,
            'buy_amt': lot * 1000, 'sell_amt': lot * 1000 if style == 'daytrade' else 0,
            'is_limit_up': lu, 'trade_style': style,
            'limit_up_price': 50.0}


# 合成「巨人傑」歷史:
# 9B2n (西松) 純隔日沖 (style=partial, 都漲停)
# 9B2z (文心) 純當沖 (style=daytrade, 都漲停)
def mk_giant_history():
    h = []
    for d in ['20260520', '20260521', '20260522', '20260525', '20260526']:
        h.append({'date': d, 'data': {'branches': [
            {'code': '9B2n', 'name': '台新-西松', 'master': '巨人傑', 'co_masters': [],
             'buys': [mk_stock('3443', 100, True, 'partial'),
                      mk_stock('6147', 80, True, 'partial')],
             'sells': []},
            {'code': '9B2z', 'name': '台新-文心', 'master': '巨人傑', 'co_masters': [],
             'buys': [mk_stock('3443', 50, True, 'daytrade')],
             'sells': []},
        ]}})
    return h


# ── 1. _list_master_branches: 巨人傑找出 2 分點 ──
print("\n1. _list_master_branches: 巨人傑 → {9B2n, 9B2z}")
h = mk_giant_history()
brs = _list_master_branches(h, '巨人傑')
ok = set(brs.keys()) == {'9B2n', '9B2z'} and brs['9B2n'] == '台新-西松'
print(f"  {'OK' if ok else 'FAIL'} branches={brs}")
if not ok: all_pass = False

# ── 2. extract_master_trades with branch_code 只抽該分點 ──
print("\n2. extract_master_trades(branch_code='9B2n') 只抽西松")
trades_west = extract_master_trades(h, '巨人傑', branch_code='9B2n')
ok = (len(trades_west) == 10 and  # 5 天 × 2 檔
      all(t['branch_code'] == '9B2n' for t in trades_west))
print(f"  {'OK' if ok else 'FAIL'} 西松 trades={len(trades_west)} (應 10), 全來自 9B2n")
if not ok: all_pass = False

# ── 3. build_master_profile 整體 vs branch_filter ──
print("\n3. build_master_profile 巨人傑整體 → 應有 per_branch_profiles")
master_styles = {'巨人傑': ['next_day_flipper', 'day_trader']}
prof = build_master_profile('巨人傑', h, master_styles)
ok = ('per_branch_profiles' in prof and len(prof['per_branch_profiles']) == 2
      and prof['per_branch_count'] == 2)
print(f"  {'OK' if ok else 'FAIL'} per_branch_count={prof.get('per_branch_count')}, "
      f"keys={list(prof.get('per_branch_profiles', {}).keys())}")
if not ok: all_pass = False

# ── 4. 9B2n 細分 → 短打型 (因 partial 100%) ──
print("\n4. 9B2n 西松 細分 labels → 應含「短打型」(partial 100%)")
west_prof = prof['per_branch_profiles']['9B2n']
ok = ('短打型' in west_prof['strategy_labels']
      and '當沖客' not in west_prof['strategy_labels']
      and west_prof['branch_name'] == '台新-西松')
print(f"  {'OK' if ok else 'FAIL'} 9B2n labels={west_prof['strategy_labels']}")
if not ok: all_pass = False

# ── 5. 9B2z 細分 → 當沖客 (因 daytrade 100%) ──
print("\n5. 9B2z 文心 細分 labels → 應含「當沖客」(daytrade 100%)")
wen_prof = prof['per_branch_profiles']['9B2z']
ok = ('當沖客' in wen_prof['strategy_labels']
      and '短打型' not in wen_prof['strategy_labels']
      and wen_prof['branch_name'] == '台新-文心')
print(f"  {'OK' if ok else 'FAIL'} 9B2z labels={wen_prof['strategy_labels']}")
if not ok: all_pass = False

# ── 6. v3.31.10: per-branch 價值 = 兩分點主風格不同 (短打 vs 當沖) ──
# (consistency_high 0.65 較鬆, master 整體 67% partial 也觸發風格純粹,
#  但 per-branch 仍有別: 9B2n 主風格短打型, 9B2z 主風格當沖客)
print("\n6. per-branch 價值: 9B2n 短打型 vs 9B2z 當沖客 (主風格不同)")
master_labels = set(prof['strategy_labels'])
west_labels = set(west_prof['strategy_labels'])
wen_labels = set(wen_prof['strategy_labels'])
ok = ('短打型' in west_labels and '當沖客' not in west_labels
      and '當沖客' in wen_labels and '短打型' not in wen_labels)
print(f"  {'OK' if ok else 'FAIL'} master={master_labels}")
print(f"    9B2n  ={west_labels}")
print(f"    9B2z  ={wen_labels}")
if not ok: all_pass = False

# ── 7. 單一分點 master 不應該有 per_branch_profiles ──
print("\n7. 單一分點 master → 無 per_branch_profiles (節省空間)")
solo_h = [{'date': '20260520', 'data': {'branches': [
    {'code': 'AAA', 'name': '券商', 'master': '單分點哥', 'co_masters': [],
     'buys': [mk_stock('1234', 50, False, 'overnight')], 'sells': []}
]}}]
solo_prof = build_master_profile('單分點哥', solo_h, {'單分點哥': ['swing']})
ok = 'per_branch_profiles' not in solo_prof
print(f"  {'OK' if ok else 'FAIL'} 單分點 master 無 per_branch_profiles 子結構")
if not ok: all_pass = False

# ── 8. branch_filter 模式不再遞迴 (避免無限遞迴) ──
print("\n8. branch_filter 模式 → 不再算 per_branch_profiles (截斷遞迴)")
branch_only = build_master_profile('巨人傑', h, master_styles, branch_filter='9B2n')
ok = 'per_branch_profiles' not in branch_only and branch_only.get('branch_filter') == '9B2n'
print(f"  {'OK' if ok else 'FAIL'} branch_filter='9B2n' 結果無遞迴 per_branch")
if not ok: all_pass = False

print()
print("─" * 64)
print(f"  整體: {'OK ALL PASS' if all_pass else 'FAIL HAS FAIL'}")
sys.exit(0 if all_pass else 1)
