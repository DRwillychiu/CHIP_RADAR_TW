"""v3.66.9 Phase 2.5: bootstrap data/consensus_backtest.json.

對歷史每天 daily JSON 解密 + 計算 Section 0 強共識股, 然後從 stock_history.json
查隔日漲跌, 計算命中率.

Schema:
  {
    'dates': [...],
    'per_day': {date: {picks: [codes], hits: int, total: int, next_day_changes: {code: pct}}},
    'summary_30d': {total: N, hits: H, hit_rate: %, median_change, mean_change},
  }
"""
import json, sys, os, gzip
from pathlib import Path
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipelines.crawler_output import decrypt_data
from src.exports.excel_report import (
    _filter_tracked_branches, _compute_consensus_count,
)

password = os.environ.get('CHIP_RADAR_PASSWORD', '')
if not password:
    print("❌ CHIP_RADAR_PASSWORD 未設")
    sys.exit(1)

# Load stock_history
with open(ROOT / 'data' / 'stock_history.json', 'r', encoding='utf-8') as f:
    sh = json.load(f)
sh_stocks = sh.get('stocks', {})
sh_dates = sh.get('dates', [])

def _read_daily(p):
    try:
        if str(p).endswith('.gz'):
            with gzip.open(p, 'rt', encoding='utf-8') as f:
                enc = json.load(f)
        else:
            with open(p, 'r', encoding='utf-8') as f:
                enc = json.load(f)
        plain = decrypt_data(enc['data'], password, iterations=enc.get('iterations'))
        return json.loads(plain)
    except Exception as e:
        return None

# Collect daily files
daily_files = sorted(
    list((ROOT / 'data').glob('[0-9]' * 8 + '.json')) +
    list((ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json')) +
    list((ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json.gz')),
    key=lambda p: p.name[:8]
)
print(f"找到 {len(daily_files)} 個 daily JSON")
print(f"stock_history 範圍: {sh_dates[0]} ~ {sh_dates[-1]} ({len(sh_dates)} 天)")
print()

per_day = {}
all_next_day_changes = []
for p in daily_files:
    date = p.name[:8]
    if date not in sh_dates:
        continue
    # 找出隔日
    idx = sh_dates.index(date)
    if idx + 1 >= len(sh_dates):
        # 沒有隔日資料 (今天 6/24 沒有 6/25)
        continue
    next_date = sh_dates[idx + 1]

    data = _read_daily(p)
    if not data:
        continue
    branches = data.get('branches', [])
    if not branches:
        continue
    filtered = _filter_tracked_branches(branches)
    consensus = _compute_consensus_count(filtered)
    consensus.sort(key=lambda x: (-x['total_net_amt'], -x['master_count'], -x['branch_count']))

    hits = 0
    next_changes = {}
    for c in consensus:
        code = c['code']
        s_data = sh_stocks.get(code, {})
        nd = s_data.get('daily', {}).get(next_date, {})
        chg = nd.get('change_pct')
        if chg is None:
            continue
        next_changes[code] = chg
        if chg > 0:
            hits += 1
        all_next_day_changes.append(chg)

    per_day[date] = {
        'picks': [c['code'] for c in consensus],
        'next_date': next_date,
        'hits': hits,
        'total': len(next_changes),
        'next_day_changes': next_changes,
    }
    print(f"  {date} → {next_date}: {len(consensus):2d} 共識, 隔日 {hits}/{len(next_changes)} 漲")

# Summary 30 天
recent_dates = sorted(per_day.keys())[-30:]
total = sum(per_day[d]['total'] for d in recent_dates)
hits = sum(per_day[d]['hits'] for d in recent_dates)
hit_rate = (hits / total) if total else 0
mean_change = (sum(all_next_day_changes[-total:]) / total) if total else 0
sorted_changes = sorted(all_next_day_changes[-total:]) if total else []
median_change = sorted_changes[len(sorted_changes)//2] if sorted_changes else 0

print(f"\n=== Summary 過去 30 天 ===")
print(f"  總共識 picks: {total}")
print(f"  隔日漲: {hits} ({hit_rate*100:.1f}%)")
print(f"  隔日漲跌中位數: {median_change:+.2f}%")
print(f"  隔日漲跌平均: {mean_change:+.2f}%")

out = {
    'dates': recent_dates,
    'per_day': per_day,
    'summary_30d': {
        'total': total,
        'hits': hits,
        'hit_rate': hit_rate,
        'median_change': median_change,
        'mean_change': mean_change,
    },
    'updated_at': datetime.now().isoformat(),
}
out_path = ROOT / 'data' / 'consensus_backtest.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\n✅ 寫入 {out_path}")
