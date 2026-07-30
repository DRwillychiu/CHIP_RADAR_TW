"""v3.69.0 Phase 3.2: 共識 ∩ E 異常爆量 backtest.

目的: 驗證「強共識股 ∩ 至少 1 位 master 當日有異常」隔日 hit rate 是否 > 60%.

E 異常定義 (對齊 src/alerts/daily_signals.py):
  - volume_spike: master 今日總買金額 > avg+2σ (n>=5 天歷史)
  - new_stocks  : master 今日買 >=3 檔過去從未買過

Combo 定義 (在 Phase 3.1 上疊加):
  baseline            : 全部共識股
  e_anomaly_only      : 共識 ∩ ≥1 contributing master 當日異常
  e_anomaly_q5_bull   : 共識 ∩ Q5 偏多 ∩ ≥1 contributing master 異常 (三訊號疊加)
  e_volume_spike_only : 共識 ∩ ≥1 contributing master volume_spike
  e_new_stocks_only   : 共識 ∩ ≥1 contributing master new_stocks

寫入 data/phase32_backtest.json
"""
import json, sys, os, gzip, statistics
from pathlib import Path
from datetime import datetime
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
# v3.73.1: 尊重 CHIP_RADAR_DATA_DIR (本機排程用 local_data/, 雲端維持 data/)
DATA = ROOT / os.environ.get('CHIP_RADAR_DATA_DIR', 'data')
sys.path.insert(0, str(ROOT))

from src.pipelines.crawler_output import decrypt_data
from src.exports.excel_report import (
    _filter_tracked_branches, _compute_consensus_count,
)
from src.analyzers.signal_engine import infer_market_direction

ANOMALY_SIGMA = 2.0
MIN_HISTORY_DAYS = 5
NEW_STOCKS_THRESHOLD = 3

password = os.environ.get('CHIP_RADAR_PASSWORD', '')
if not password:
    print("X CHIP_RADAR_PASSWORD not set"); sys.exit(1)

# Load stock_history + temp_history
with open(DATA / 'stock_history.json', 'r', encoding='utf-8') as f:
    sh = json.load(f)
sh_stocks = sh.get('stocks', {})
sh_dates = sh.get('dates', [])

with open(DATA / 'temp_history.json', 'r', encoding='utf-8') as f:
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
    except Exception as e:
        print(f"  decrypt fail {p.name}: {e}")
        return None


# Collect all daily files chronologically
daily_files = sorted(
    list((DATA).glob('[0-9]' * 8 + '.json')) +
    list((DATA / 'archive').glob('[0-9]' * 8 + '.json')) +
    list((DATA / 'archive').glob('[0-9]' * 8 + '.json.gz')),
    key=lambda p: p.name[:8]
)

# Build chronological list (no dups)
seen = set(); files = []
for p in daily_files:
    d = p.name[:8]
    if d in seen: continue
    seen.add(d); files.append((d, p))
files.sort(key=lambda x: x[0])

# Decrypt all into memory (45 files ~25MB OK)
print(f"Loading {len(files)} daily files...")
all_data = {}      # {date: branches_filtered}
for date, p in files:
    data = _read_daily(p)
    if not data: continue
    bs = data.get('branches', [])
    if not bs: continue
    all_data[date] = _filter_tracked_branches(bs)
print(f"  loaded {len(all_data)} days")

# Pre-compute per-day per-master total_buy_amt + stocks set
# (for anomaly z-score / new_stocks computation)
master_daily = defaultdict(dict)   # {master: {date: {'total': X, 'stocks': set}}}
for date, branches in all_data.items():
    for br in branches:
        m = br.get('master')
        co = br.get('co_masters') or []
        all_m = ([m] if m else []) + list(co)
        for mm in all_m:
            if not mm: continue
            slot = master_daily[mm].setdefault(date, {'total': 0, 'stocks': set()})
            for s in (br.get('buys') or []):
                code = s.get('code')
                amt = s.get('buy_amt', 0) or 0
                if code and not code.startswith('00') and amt > 0:
                    slot['total'] += amt
                    slot['stocks'].add(code)


def anomalous_masters_for(date, sorted_dates):
    """回傳當日異常的 master set.
    sorted_dates: 全 sorted dates list (chronological)
    """
    idx = sorted_dates.index(date)
    if idx < MIN_HISTORY_DAYS: return set(), set()
    past_dates = sorted_dates[:idx]   # all past
    vol_spike, new_stocks = set(), set()
    for m, by_date in master_daily.items():
        today_amt = by_date.get(date, {}).get('total', 0)
        today_stk = by_date.get(date, {}).get('stocks', set())
        if today_amt == 0: continue
        past_amts = [by_date[d]['total'] for d in past_dates
                     if d in by_date and by_date[d]['total'] > 0]
        if len(past_amts) < MIN_HISTORY_DAYS: continue
        avg = statistics.mean(past_amts)
        std = statistics.stdev(past_amts) if len(past_amts) > 1 else avg * 0.3
        if std == 0: std = avg * 0.1
        z = (today_amt - avg) / std
        if z > ANOMALY_SIGMA:
            vol_spike.add(m)
        # new stocks
        past_all_stocks = set()
        for d in past_dates:
            if d in by_date:
                past_all_stocks |= by_date[d]['stocks']
        new_set = today_stk - past_all_stocks
        if len(new_set) >= NEW_STOCKS_THRESHOLD:
            new_stocks.add(m)
    return vol_spike, new_stocks


sorted_dates = sorted(all_data.keys())

# Combo definitions
COMBOS = {
    'baseline':            '全部共識股 (對照)',
    'e_anomaly_only':      '共識 ∩ ≥1 master 異常 (vol_spike OR new_stocks)',
    'e_volume_spike_only': '共識 ∩ ≥1 master volume_spike',
    'e_new_stocks_only':   '共識 ∩ ≥1 master new_stocks',
    'e_anomaly_q5_bull':   '共識 ∩ Q5 偏多 ∩ ≥1 master 異常 (3 訊號)',
    'e_vol_spike_q5_bull': '共識 ∩ Q5 偏多 ∩ ≥1 master volume_spike (嚴格 3 訊號)',
    'q5_bull_only':        '共識 ∩ Q5 偏多 (Phase 3.1 對比)',
}
combo_changes = {k: [] for k in COMBOS}
combo_days = {k: set() for k in COMBOS}
per_day_log = []

print()
print("=" * 78)
print(f"{'date':<10} {'cons':>4} {'next':>4} {'q5':>5} {'vsM':>4} {'nsM':>4} {'eHit':>5}")
print("=" * 78)

for date in sorted_dates:
    if date not in sh_dates: continue
    idx = sh_dates.index(date)
    if idx + 1 >= len(sh_dates): continue
    next_date = sh_dates[idx + 1]

    branches = all_data[date]
    consensus = _compute_consensus_count(branches)
    if not consensus: continue

    # rebuild stock_branches mapping
    stock_branches = {}
    for b in branches:
        m = b.get('master')
        if not m: continue
        for s in (b.get('buys') or []):
            code = s.get('code')
            if not code or code.startswith('00'): continue
            amt = s.get('buy_amt', 0) or 0
            if amt <= 0: continue
            stock_branches.setdefault(code, set()).add(m)

    # Q5 direction
    q5_dir = None
    th_entry = th_by_date.get(date)
    if th_entry:
        try:
            md = infer_market_direction(th_entry.get('signals') or [])
            q5_dir = md.get('direction')
        except Exception: pass

    # Anomalous masters for this day
    vol_spike, new_stk = anomalous_masters_for(date, sorted_dates)

    # Per pick, classify and tally
    picks_valid = 0; e_hits = 0
    for c in consensus:
        code = c['code']
        s_data = sh_stocks.get(code, {})
        nd = s_data.get('daily', {}).get(next_date, {})
        nxt_close = nd.get('close')
        nxt_chg = nd.get('change_pct')
        if nxt_chg is None or nxt_close is None: continue
        # v3.70.5 ROLLBACK stale guard 2 — TWSE 證實 6/22 鴻海/台達電/華通 close 真的 flat
        # (intraday 有波動但收盤剛好同 6/18). 之前 stale guard 2 是錯誤假設.
        picks_valid += 1
        cmasters = stock_branches.get(code, set())
        is_e_vol = bool(cmasters & vol_spike)
        is_e_new = bool(cmasters & new_stk)
        is_e_any = is_e_vol or is_e_new
        is_q5_bull = (q5_dir == '偏多')

        combo_changes['baseline'].append(nxt_chg)
        combo_days['baseline'].add(date)
        if is_e_any:
            combo_changes['e_anomaly_only'].append(nxt_chg)
            combo_days['e_anomaly_only'].add(date)
        if is_e_vol:
            combo_changes['e_volume_spike_only'].append(nxt_chg)
            combo_days['e_volume_spike_only'].add(date)
        if is_e_new:
            combo_changes['e_new_stocks_only'].append(nxt_chg)
            combo_days['e_new_stocks_only'].add(date)
        if is_e_any and is_q5_bull:
            combo_changes['e_anomaly_q5_bull'].append(nxt_chg)
            combo_days['e_anomaly_q5_bull'].add(date)
        if is_e_vol and is_q5_bull:
            combo_changes['e_vol_spike_q5_bull'].append(nxt_chg)
            combo_days['e_vol_spike_q5_bull'].add(date)
        if is_q5_bull:
            combo_changes['q5_bull_only'].append(nxt_chg)
            combo_days['q5_bull_only'].add(date)
        if is_e_any and nxt_chg > 0:
            e_hits += 1

    per_day_log.append({
        'date': date, 'next': next_date, 'cons': len(consensus),
        'next_avail': picks_valid, 'q5': q5_dir,
        'vol_spike_masters': len(vol_spike), 'new_stocks_masters': len(new_stk),
        'e_hits': e_hits,
    })
    print(f"{date:<10} {len(consensus):>4} {picks_valid:>4} {(q5_dir or '-'):>5} "
          f"{len(vol_spike):>4} {len(new_stk):>4} {e_hits:>5}")

# Summary
print()
print("=" * 78)
print(f"Phase 3.2 Combo Summary")
print("=" * 78)
print(f"{'Combo':<24} {'n':>4} {'hit':>4} {'hit%':>6} {'mean%':>7} {'days':>5}")
summary = {}
for combo_name, desc in COMBOS.items():
    changes = combo_changes[combo_name]
    days = len(combo_days[combo_name])
    n = len(changes)
    if n == 0:
        summary[combo_name] = {'n': 0, 'hits': 0, 'hit_rate': 0, 'mean_change': 0,
                              'median_change': 0, 'days': days, 'desc': desc}
        print(f"  {combo_name:<24} {n:>4} {'-':>4} {'-':>6} {'-':>7} {days:>5}")
        continue
    hits = sum(1 for c in changes if c > 0)
    hit_rate = hits / n
    mean_chg = sum(changes) / n
    sorted_c = sorted(changes)
    median_chg = sorted_c[n // 2]
    summary[combo_name] = {'n': n, 'hits': hits, 'hit_rate': hit_rate,
                          'mean_change': mean_chg, 'median_change': median_chg,
                          'days': days, 'desc': desc}
    print(f"  {combo_name:<24} {n:>4} {hits:>4} {hit_rate*100:>5.1f}% {mean_chg:>+6.2f}% {days:>5}")

# Find best combos (hit >= 60%, n >= 20)
print()
print("=== Best combos (hit >= 60%, n >= 20) ===")
best = [(k, v) for k, v in summary.items() if v['hit_rate'] >= 0.60 and v['n'] >= 20]
best.sort(key=lambda x: -x[1]['hit_rate'])
if best:
    for k, v in best:
        print(f"  STAR {k}: hit {v['hit_rate']*100:.1f}% (n={v['n']}) "
              f"mean {v['mean_change']:+.2f}% -- {v['desc']}")
else:
    print(f"  No combo hit >= 60% with n >= 20")

# Save
out = {
    'summary': summary,
    'best': [k for k, _ in best],
    'per_day': per_day_log,
    'updated_at': datetime.now().isoformat(),
    'window_days': len(per_day_log),
    'thresholds': {
        'anomaly_sigma': ANOMALY_SIGMA,
        'min_history_days': MIN_HISTORY_DAYS,
        'new_stocks_threshold': NEW_STOCKS_THRESHOLD,
    },
}
out_path = DATA / 'phase32_backtest.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\nWrote {out_path}")
