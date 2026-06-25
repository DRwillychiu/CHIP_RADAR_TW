"""v3.66.7 Phase 2.3: bootstrap data/timeseries.json 從歷史 daily JSON.

掃 data/*.json + data/archive/*.json, 對每天 decrypt + 計算 Q1-Q4 寫進 cache.
"""
import json, sys, os, gzip
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipelines.crawler_output import decrypt_data
from src.exports.excel_report import (
    _filter_tracked_branches, TRACKED_MASTERS, _compute_consensus_count,
    _is_excluded_by_market_type, MASTER_MAPPING,
)

password = os.environ.get('CHIP_RADAR_PASSWORD', '')
if not password:
    print("❌ CHIP_RADAR_PASSWORD 未設")
    sys.exit(1)

def _compute_kpis(branches_data):
    """同 _build_section_summary Q1-Q4 計算."""
    filtered = _filter_tracked_branches(branches_data)

    total_buy = sum((s.get('buy_amt') or 0) for b in filtered for s in (b.get('buys') or []))
    seen = set()
    total_sell = 0
    for b in filtered:
        bcode = b.get('code', '')
        for s in (b.get('buys') or []) + (b.get('sells') or []):
            key = (bcode, s.get('code'))
            if key in seen: continue
            seen.add(key)
            total_sell += (s.get('sell_amt') or 0)
    net_billion = (total_buy - total_sell) / 100000

    active_masters = {b.get('master') for b in filtered
                       if (b.get('buys') or []) and b.get('master')}
    active_ratio = len(active_masters) / len(TRACKED_MASTERS)

    consensus_stocks = _compute_consensus_count(filtered)
    consensus_count = len(consensus_stocks)
    consensus_net = sum(s['total_net_amt'] for s in consensus_stocks)
    consensus_net_billion = consensus_net / 100000

    # Q4 全市場
    mkt_buy = sum((s.get('buy_amt') or 0) for b in branches_data for s in (b.get('buys') or []))
    seen2 = set()
    mkt_sell = 0
    for b in branches_data:
        bcode = b.get('code', '')
        for s in (b.get('buys') or []) + (b.get('sells') or []):
            key = (bcode, s.get('code'))
            if key in seen2: continue
            seen2.add(key)
            mkt_sell += (s.get('sell_amt') or 0)
    mkt_net_billion = (mkt_buy - mkt_sell) / 100000
    track_share = (total_buy / mkt_buy) if mkt_buy else 0

    return {
        'q1_active_ratio': active_ratio,
        'q2_net_billion': net_billion,
        'q3_consensus_count': consensus_count,
        'q3_consensus_net_billion': consensus_net_billion,
        'q4_track_share': track_share,
        'q4_mkt_net_billion': mkt_net_billion,
    }

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
        print(f"  ⚠️  {p.name}: {e}")
        return None

# Collect daily files
daily_files = []
for p in (ROOT / 'data').glob('[0-9]' * 8 + '.json'):
    daily_files.append(p)
for p in (ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json'):
    daily_files.append(p)
for p in (ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json.gz'):
    daily_files.append(p)

daily_files = sorted(daily_files, key=lambda p: p.name[:8])
print(f"找到 {len(daily_files)} 個 daily JSON")

# Build cache
keys = ['q1_active_ratio', 'q2_net_billion', 'q3_consensus_count',
        'q3_consensus_net_billion', 'q4_track_share', 'q4_mkt_net_billion']
cache = {'dates': []}
for k in keys: cache[k] = []

for p in daily_files:
    date = p.name[:8]
    data = _read_daily(p)
    if not data: continue
    branches = data.get('branches', [])
    if not branches:
        print(f"  ⚠️  {date}: no branches")
        continue
    kpis = _compute_kpis(branches)
    cache['dates'].append(date)
    for k in keys: cache[k].append(kpis[k])
    print(f"  ✓ {date}: Q1={kpis['q1_active_ratio']:.0%} "
          f"Q2={kpis['q2_net_billion']:+.1f}億 "
          f"Q3={kpis['q3_consensus_count']}檔 "
          f"Q4={kpis['q4_track_share']:.1%}")

# 取最近 60 天
sorted_idx = sorted(range(len(cache['dates'])), key=lambda i: cache['dates'][i])
cache['dates'] = [cache['dates'][i] for i in sorted_idx][-60:]
for k in keys: cache[k] = [cache[k][i] for i in sorted_idx][-60:]

# Save
out = ROOT / 'data' / 'timeseries.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)
print(f"\n✅ 寫入 {out}: {len(cache['dates'])} 天歷史")
