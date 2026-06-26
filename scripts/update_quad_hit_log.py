"""v3.70.0 Phase 3.2: quad 命中股實戰 hit log.

每日 daily-full 跑完後自動更新.

寫入 data/quad_hit_log.json:
  {
    "trigger_days": [
      {
        "date": "20260520", "next_date": "20260521",
        "q5_direction": "偏多",
        "vol_spike_masters": ["民哥"],
        "quad_picks": [
          {"code": "2330", "name": "台積電", "next_change_pct": 9.91, "hit": true,
           "matched_masters": ["民哥"]},
          ...
        ],
        "n": 5, "hits": 5, "hit_rate": 1.0, "mean_change": 4.5
      },
      ...
    ],
    "rolling_30d": {"trigger_days": N, "n": X, "hits": Y, "hit_rate": Y/X, "mean_change": Z},
    "rolling_all": {"trigger_days": N, "n": X, "hits": Y, "hit_rate": Y/X, "mean_change": Z},
    "vs_expected": {"expected_hit_rate": 0.789, "actual_hit_rate": Y/X, "delta_pp": ...},
    "updated_at": "..."
  }

用途: 月底復盤實際 vs 預期 78.9%, Excel sub-banner 顯示滾動 30 天命中率.
"""
import json, sys, os, gzip, statistics
from pathlib import Path
from datetime import datetime
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipelines.crawler_output import decrypt_data
from src.exports.excel_report import _filter_tracked_branches, _compute_consensus_count
from src.analyzers.signal_engine import infer_market_direction

ANOMALY_SIGMA = 2.0
MIN_HISTORY_DAYS = 5
EXPECTED_HIT_RATE = 0.789

password = os.environ.get('CHIP_RADAR_PASSWORD', '')
if not password:
    print("X CHIP_RADAR_PASSWORD not set"); sys.exit(1)

with open(ROOT / 'data' / 'stock_history.json', 'r', encoding='utf-8') as f:
    sh = json.load(f)
sh_stocks = sh.get('stocks', {})
sh_dates = sh.get('dates', [])

with open(ROOT / 'data' / 'temp_history.json', 'r', encoding='utf-8') as f:
    th = json.load(f)
th_by_date = {e['date']: e for e in (th.get('history') or [])}


def _read_daily(p):
    try:
        if str(p).endswith('.gz'):
            with gzip.open(p, 'rt', encoding='utf-8') as f: enc = json.load(f)
        else:
            with open(p, 'r', encoding='utf-8') as f: enc = json.load(f)
        plain = decrypt_data(enc['data'], password, iterations=enc.get('iterations'))
        return json.loads(plain)
    except Exception:
        return None


# Load all daily files chronologically
daily_files = sorted(
    list((ROOT / 'data').glob('[0-9]' * 8 + '.json')) +
    list((ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json')) +
    list((ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json.gz')),
    key=lambda p: p.name[:8]
)
seen = set(); files = []
for p in daily_files:
    d = p.name[:8]
    if d in seen: continue
    seen.add(d); files.append((d, p))
files.sort(key=lambda x: x[0])

print(f"Loading {len(files)} daily files...")
all_data = {}
for date, p in files:
    data = _read_daily(p)
    if not data: continue
    bs = data.get('branches', [])
    if not bs: continue
    all_data[date] = _filter_tracked_branches(bs)
print(f"  loaded {len(all_data)} days")

# Per-master per-day total_buy (for vol_spike z-score)
master_total = defaultdict(dict)
for date, branches in all_data.items():
    for br in branches:
        m = br.get('master')
        co = br.get('co_masters') or []
        all_m = ([m] if m else []) + list(co)
        for mm in all_m:
            if not mm: continue
            for s in (br.get('buys') or []):
                amt = s.get('buy_amt', 0) or 0
                code = s.get('code')
                if amt > 0 and code and not code.startswith('00'):
                    master_total[mm][date] = master_total[mm].get(date, 0) + amt

sorted_dates = sorted(all_data.keys())


def vol_spike_masters(date_idx):
    if date_idx < MIN_HISTORY_DAYS: return set()
    date = sorted_dates[date_idx]
    past_dates = sorted_dates[:date_idx]
    spike = set()
    for m, by_date in master_total.items():
        today = by_date.get(date, 0)
        if today == 0: continue
        past_amts = [by_date[d] for d in past_dates if d in by_date and by_date[d] > 0]
        if len(past_amts) < MIN_HISTORY_DAYS: continue
        avg = statistics.mean(past_amts)
        std = statistics.stdev(past_amts) if len(past_amts) > 1 else avg * 0.3
        if std == 0: std = avg * 0.1
        z = (today - avg) / std
        if z > ANOMALY_SIGMA:
            spike.add(m)
    return spike


# Process each day, identify quad triggers
trigger_days = []

for date_idx, date in enumerate(sorted_dates):
    if date not in sh_dates: continue
    sh_idx = sh_dates.index(date)
    if sh_idx + 1 >= len(sh_dates): continue   # no next_date (today is last day)
    next_date = sh_dates[sh_idx + 1]

    # Check Q5 direction
    th_entry = th_by_date.get(date)
    q5_dir = None
    if th_entry:
        try:
            md = infer_market_direction(th_entry.get('signals') or [])
            q5_dir = md.get('direction')
        except Exception: pass

    if q5_dir != '偏多': continue

    # Check vol_spike
    vs = vol_spike_masters(date_idx)
    if not vs: continue

    # We have a quad trigger day. Compute consensus + quad picks
    branches = all_data[date]
    consensus = _compute_consensus_count(branches)
    if not consensus: continue

    # Build stock -> contributing masters
    stock_masters = {}
    for b in branches:
        m = b.get('master')
        if not m: continue
        for s in (b.get('buys') or []):
            code = s.get('code')
            if not code or code.startswith('00'): continue
            if (s.get('buy_amt') or 0) <= 0: continue
            stock_masters.setdefault(code, set()).add(m)

    # Identify quad picks (consensus stocks with ≥1 vol_spike master)
    quad_picks = []
    for c in consensus:
        code = c['code']
        cmasters = stock_masters.get(code, set())
        matched = cmasters & vs
        if not matched: continue
        # Resolve hit (need next_date close in stock_history)
        nd = sh_stocks.get(code, {}).get('daily', {}).get(next_date, {})
        nxt_close = nd.get('close')
        nxt_chg = nd.get('change_pct')
        if nxt_chg is None or nxt_close is None: continue   # stale guard
        quad_picks.append({
            'code': code,
            'name': c['name'],
            'matched_masters': sorted(matched),
            'next_change_pct': round(nxt_chg, 2),
            'hit': nxt_chg > 0,
        })

    if not quad_picks: continue

    hits = sum(1 for p in quad_picks if p['hit'])
    n = len(quad_picks)
    mean_chg = sum(p['next_change_pct'] for p in quad_picks) / n
    trigger_days.append({
        'date': date,
        'next_date': next_date,
        'q5_direction': q5_dir,
        'vol_spike_masters': sorted(vs),
        'quad_picks': quad_picks,
        'n': n, 'hits': hits,
        'hit_rate': round(hits / n, 4),
        'mean_change': round(mean_chg, 2),
    })

print(f"  found {len(trigger_days)} trigger days")

# Aggregate rolling stats
def aggregate(days_list):
    all_picks = [p for d in days_list for p in d['quad_picks']]
    n = len(all_picks)
    if n == 0:
        return {'trigger_days': len(days_list), 'n': 0, 'hits': 0,
                'hit_rate': 0, 'mean_change': 0}
    hits = sum(1 for p in all_picks if p['hit'])
    mean_chg = sum(p['next_change_pct'] for p in all_picks) / n
    return {
        'trigger_days': len(days_list),
        'n': n, 'hits': hits,
        'hit_rate': round(hits / n, 4),
        'mean_change': round(mean_chg, 2),
    }

# Last 30 calendar days (filter by date string)
from datetime import datetime as _dt, timedelta as _td
if sorted_dates:
    last_dt = _dt.strptime(sorted_dates[-1], '%Y%m%d')
    cutoff_30d = (last_dt - _td(days=30)).strftime('%Y%m%d')
    days_30d = [d for d in trigger_days if d['date'] >= cutoff_30d]
else:
    days_30d = trigger_days

rolling_30d = aggregate(days_30d)
rolling_all = aggregate(trigger_days)

# vs expected
actual_hr = rolling_all['hit_rate']
delta_pp = (actual_hr - EXPECTED_HIT_RATE) * 100

out = {
    'trigger_days': trigger_days,
    'rolling_30d': rolling_30d,
    'rolling_all': rolling_all,
    'vs_expected': {
        'expected_hit_rate': EXPECTED_HIT_RATE,
        'actual_hit_rate': actual_hr,
        'delta_pp': round(delta_pp, 1),
    },
    'updated_at': datetime.now().isoformat(),
}

out_path = ROOT / 'data' / 'quad_hit_log.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print()
print(f"=== Quad Hit Log Summary ===")
print(f"  Trigger days (all): {rolling_all['trigger_days']}")
print(f"  Total quad picks  : {rolling_all['n']}")
print(f"  Hits              : {rolling_all['hits']}")
print(f"  Actual hit rate   : {rolling_all['hit_rate']*100:.1f}%")
print(f"  Expected (Phase 3.2): {EXPECTED_HIT_RATE*100:.1f}%")
print(f"  Delta             : {delta_pp:+.1f}pp")
print(f"  Mean change       : {rolling_all['mean_change']:+.2f}%")
print()
print(f"=== Rolling 30d ===")
print(f"  Trigger days: {rolling_30d['trigger_days']}")
print(f"  Quad picks  : {rolling_30d['n']}")
print(f"  Hits        : {rolling_30d['hits']}")
print(f"  Hit rate    : {rolling_30d['hit_rate']*100:.1f}%")
print()
print(f"Wrote {out_path}")
