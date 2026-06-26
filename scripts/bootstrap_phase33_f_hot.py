"""v3.70.0 Phase 3.3: 共識 ∩ F hot >=N 天 backtest.

F 定義 (對齊 src/alerts/daily_signals.py accumulations):
  master 連續 N 天加碼同一檔股票

Per stock 邏輯:
  max_streak(stock) = max over all consensus masters of (consecutive accumulation days)

Combo 定義:
  baseline             : 全部共識股
  f_hot5               : 共識 ∩ max_streak >= 5
  f_hot7               : 共識 ∩ max_streak >= 7
  f_hot10              : 共識 ∩ max_streak >= 10
  f_hot5_q5_bull       : 共識 ∩ max_streak >= 5 ∩ Q5 偏多
  f_hot7_q5_bull       : 共識 ∩ max_streak >= 7 ∩ Q5 偏多
  f_hot10_q5_bull      : 共識 ∩ max_streak >= 10 ∩ Q5 偏多
  quad_AAAA            : 共識 ∩ Q5 偏多 ∩ vol_spike ∩ max_streak >= 5 (四訊號)

寫入 data/phase33_backtest.json
"""
import json, sys, os, gzip, statistics
from pathlib import Path
from datetime import datetime
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipelines.crawler_output import decrypt_data
from src.exports.excel_report import (
    _filter_tracked_branches, _compute_consensus_count,
)
from src.analyzers.signal_engine import infer_market_direction

ANOMALY_SIGMA = 2.0
MIN_HISTORY_DAYS = 5

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

# Per-day per-master per-stock buy presence + amt
# {master: {date: {code: amt}}}
master_stock_daily = defaultdict(lambda: defaultdict(dict))
master_total_daily = defaultdict(dict)   # {master: {date: total_buy}}

for date, branches in all_data.items():
    for br in branches:
        m = br.get('master')
        co = br.get('co_masters') or []
        all_m = ([m] if m else []) + list(co)
        for mm in all_m:
            if not mm: continue
            for s in (br.get('buys') or []):
                code = s.get('code')
                amt = s.get('buy_amt', 0) or 0
                if code and not code.startswith('00') and amt > 0:
                    master_stock_daily[mm][date][code] = (
                        master_stock_daily[mm][date].get(code, 0) + amt
                    )
                    master_total_daily[mm][date] = (
                        master_total_daily[mm].get(date, 0) + amt
                    )

sorted_dates = sorted(all_data.keys())


def streak_for(master, code, day_idx):
    """day_idx = sorted_dates index. 從 day_idx 往回算連續持有.
    day_idx 必須有 buy。
    """
    streak = 0
    for i in range(day_idx, -1, -1):
        d = sorted_dates[i]
        if code in master_stock_daily[master].get(d, {}):
            streak += 1
        else:
            break
    return streak


def anomalous_volume_spike_masters(date_idx):
    """回傳當日 vol_spike masters (與 Phase 3.2 同).
    """
    if date_idx < MIN_HISTORY_DAYS: return set()
    date = sorted_dates[date_idx]
    past_dates = sorted_dates[:date_idx]
    spike = set()
    for m, by_date in master_total_daily.items():
        today_amt = by_date.get(date, 0)
        if today_amt == 0: continue
        past_amts = [by_date[d] for d in past_dates if d in by_date and by_date[d] > 0]
        if len(past_amts) < MIN_HISTORY_DAYS: continue
        avg = statistics.mean(past_amts)
        std = statistics.stdev(past_amts) if len(past_amts) > 1 else avg * 0.3
        if std == 0: std = avg * 0.1
        z = (today_amt - avg) / std
        if z > ANOMALY_SIGMA:
            spike.add(m)
    return spike


COMBOS = {
    'baseline':            '全部共識股 (對照)',
    'f_hot5':              '共識 ∩ max_streak >= 5',
    'f_hot7':              '共識 ∩ max_streak >= 7',
    'f_hot10':             '共識 ∩ max_streak >= 10',
    'f_hot5_q5_bull':      '共識 ∩ max_streak >= 5 ∩ Q5 偏多',
    'f_hot7_q5_bull':      '共識 ∩ max_streak >= 7 ∩ Q5 偏多',
    'f_hot10_q5_bull':     '共識 ∩ max_streak >= 10 ∩ Q5 偏多',
    'quad_AAAA':           '共識 ∩ Q5 偏多 ∩ vol_spike ∩ max_streak >= 5 (4 訊號)',
    'q5_bull_only':        '共識 ∩ Q5 偏多 (對比)',
}
combo_changes = {k: [] for k in COMBOS}
combo_days = {k: set() for k in COMBOS}
per_day_log = []

print()
print("=" * 90)
print(f"{'date':<10} {'cons':>4} {'next':>4} {'q5':>5} {'vs':>3} {'hot5':>4} {'hot7':>4} {'hot10':>5} {'quad':>4}")
print("=" * 90)

for date_idx, date in enumerate(sorted_dates):
    if date not in sh_dates: continue
    sh_idx = sh_dates.index(date)
    if sh_idx + 1 >= len(sh_dates): continue
    next_date = sh_dates[sh_idx + 1]

    branches = all_data[date]
    consensus = _compute_consensus_count(branches)
    if not consensus: continue

    # rebuild stock -> set of masters who bought
    stock_branches = {}
    for b in branches:
        m = b.get('master')
        if not m: continue
        for s in (b.get('buys') or []):
            code = s.get('code')
            if not code or code.startswith('00'): continue
            if (s.get('buy_amt') or 0) <= 0: continue
            stock_branches.setdefault(code, set()).add(m)

    # Q5 direction
    q5_dir = None
    th_entry = th_by_date.get(date)
    if th_entry:
        try:
            md = infer_market_direction(th_entry.get('signals') or [])
            q5_dir = md.get('direction')
        except Exception: pass

    vol_spike = anomalous_volume_spike_masters(date_idx)

    cnt_hot5 = cnt_hot7 = cnt_hot10 = cnt_quad = 0
    for c in consensus:
        code = c['code']
        s_data = sh_stocks.get(code, {})
        nd = s_data.get('daily', {}).get(next_date, {})
        nxt_close = nd.get('close')
        nxt_chg = nd.get('change_pct')
        if nxt_chg is None or nxt_close is None: continue
        cmasters = stock_branches.get(code, set())
        # max streak over its consensus masters for this stock
        max_streak = 0
        for m in cmasters:
            s = streak_for(m, code, date_idx)
            if s > max_streak: max_streak = s
        is_hot5 = max_streak >= 5
        is_hot7 = max_streak >= 7
        is_hot10 = max_streak >= 10
        is_q5_bull = (q5_dir == '偏多')
        has_vs = bool(cmasters & vol_spike)

        combo_changes['baseline'].append(nxt_chg)
        combo_days['baseline'].add(date)
        if is_hot5:
            combo_changes['f_hot5'].append(nxt_chg); combo_days['f_hot5'].add(date); cnt_hot5 += 1
        if is_hot7:
            combo_changes['f_hot7'].append(nxt_chg); combo_days['f_hot7'].add(date); cnt_hot7 += 1
        if is_hot10:
            combo_changes['f_hot10'].append(nxt_chg); combo_days['f_hot10'].add(date); cnt_hot10 += 1
        if is_q5_bull:
            combo_changes['q5_bull_only'].append(nxt_chg); combo_days['q5_bull_only'].add(date)
        if is_hot5 and is_q5_bull:
            combo_changes['f_hot5_q5_bull'].append(nxt_chg); combo_days['f_hot5_q5_bull'].add(date)
        if is_hot7 and is_q5_bull:
            combo_changes['f_hot7_q5_bull'].append(nxt_chg); combo_days['f_hot7_q5_bull'].add(date)
        if is_hot10 and is_q5_bull:
            combo_changes['f_hot10_q5_bull'].append(nxt_chg); combo_days['f_hot10_q5_bull'].add(date)
        if is_hot5 and is_q5_bull and has_vs:
            combo_changes['quad_AAAA'].append(nxt_chg); combo_days['quad_AAAA'].add(date); cnt_quad += 1

    per_day_log.append({
        'date': date, 'next': next_date, 'cons': len(consensus), 'q5': q5_dir,
        'vol_spike': len(vol_spike),
        'hot5': cnt_hot5, 'hot7': cnt_hot7, 'hot10': cnt_hot10, 'quad': cnt_quad,
    })
    print(f"{date:<10} {len(consensus):>4} {len(consensus):>4} {(q5_dir or '-'):>5} "
          f"{len(vol_spike):>3} {cnt_hot5:>4} {cnt_hot7:>4} {cnt_hot10:>5} {cnt_quad:>4}")

# Summary
print()
print("=" * 80)
print("Phase 3.3 Combo Summary")
print("=" * 80)
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

out = {
    'summary': summary,
    'best': [k for k, _ in best],
    'per_day': per_day_log,
    'updated_at': datetime.now().isoformat(),
    'window_days': len(per_day_log),
    'thresholds': {
        'anomaly_sigma': ANOMALY_SIGMA,
        'min_history_days': MIN_HISTORY_DAYS,
        'streak_thresholds': [5, 7, 10],
    },
}
out_path = ROOT / 'data' / 'phase33_backtest.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\nWrote {out_path}")
