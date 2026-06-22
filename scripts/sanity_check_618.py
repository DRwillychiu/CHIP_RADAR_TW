"""6/18 真實資料 sanity check — Section 0 共同買超 top 10 + 全部 13 個追蹤大戶覆蓋"""
import json, sys, os
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipelines.crawler_output import decrypt_data
from src.exports.excel_report import TRACKED_MASTERS, MASTER_MAPPING, _filter_tracked_branches

password = os.environ.get('CHIP_RADAR_PASSWORD', '')
with open(ROOT/'data'/'20260618.json', 'r', encoding='utf-8') as f:
    enc = json.load(f)
data = json.loads(decrypt_data(enc['data'], password, iterations=enc.get('iterations')))
branches_data = data.get('branches', [])

print(f"=== 全部 branches: {len(branches_data)}")
filtered = _filter_tracked_branches(branches_data)
print(f"=== 追蹤 branches: {len(filtered)} (from TRACKED_MASTERS = {len(TRACKED_MASTERS)})")
print()

# 每個追蹤 master 有幾個 branch
master_branch_count = {}
master_buy_count = {}
for b in filtered:
    m = b.get('master')
    master_branch_count[m] = master_branch_count.get(m, 0) + 1
    if b.get('buys'):
        master_buy_count[m] = master_buy_count.get(m, 0) + 1

print("=== 13 位追蹤大戶 6/18 覆蓋率 ===")
for m in sorted(TRACKED_MASTERS):
    bc = master_branch_count.get(m, 0)
    has_data = master_buy_count.get(m, 0)
    status = "✓" if has_data else "○ (今日無資料)"
    print(f"  {status} {m}: {bc} branches, {has_data} 有 buys")
print()

# 計算 Section 0 共同買超
print("=== Section 0 共同買超 Top 10 (真實 6/18) ===")
stock_map = {}
for b in filtered:
    m = b.get('master')
    if not m: continue
    for s in (b.get('buys') or []) + (b.get('sells') or []):
        code = s.get('code')
        if not code: continue
        net = (s.get('buy_amt') or 0) - (s.get('sell_amt') or 0)
        if net <= 0: continue
        e = stock_map.setdefault(code, {'name': s.get('name', ''), 'branches': []})
        if not e['name']:
            e['name'] = s.get('name', '')
        e['branches'].append({
            'master': m, 'branch_code': b.get('code'),
            'branch_name': b.get('name'), 'net': net,
        })

consensus = []
for code, info in stock_map.items():
    if len(info['branches']) >= 2:
        masters = {br['master'] for br in info['branches']}
        total = sum(br['net'] for br in info['branches'])
        consensus.append({
            'code': code, 'name': info['name'],
            'branch_count': len(info['branches']),
            'master_count': len(masters),
            'masters': masters,
            'total': total,
            'branches': info['branches'],
        })
consensus.sort(key=lambda x: (-x['master_count'], -x['branch_count'], -x['total']))

print(f"總共同買超個股數: {len(consensus)}")
print()
for i, c in enumerate(consensus[:10]):
    print(f"#{i+1} {c['code']:8} {c['name']:<20} | {c['branch_count']} 分點 / {c['master_count']} 大戶 / {int(c['total']/10):,}萬")
    masters_str = ' / '.join(sorted(c['masters']))
    print(f"      大戶: {masters_str}")
    # Branch breakdown
    by_master = {}
    for br in c['branches']:
        by_master.setdefault(br['master'], []).append(f"{br['branch_name']}:{int(br['net']/10):,}萬")
    for m in sorted(by_master.keys()):
        print(f"      {m}: {' | '.join(by_master[m])}")
    print()
