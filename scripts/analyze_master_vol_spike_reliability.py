"""v3.70.4 Phase 3.2 P1 research: per-master vol_spike 可靠度分析.

問題: 6/16 強森+陳律師 vol_spike → 3 picks 全跑輸大盤 = 隨機 noise 還是 master 訊號偏弱?

方法: 對歷史每個 quad trigger day 的 matched_masters,
      算 per-master:
        - 觸發次數 (vol_spike days)
        - 該 master 出現在 matched_masters 的 picks 總數
        - 那些 picks 的 hit rate + mean_change
"""
import json, sys
from collections import defaultdict
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]

with open(ROOT / 'data' / 'quad_hit_log.json', 'r', encoding='utf-8') as f:
    qhl = json.load(f)

# Per-master: { master: {trigger_days: set, picks: [{hit, change}], picks_with_other_only_for_attribution: ...} }
master_stats = defaultdict(lambda: {
    'trigger_days': set(),
    'all_picks': [],         # all picks where master is in matched_masters
    'solo_picks': [],        # picks where master is the ONLY matched master (cleanest attribution)
})

for td in qhl['trigger_days']:
    vs_masters = set(td.get('vol_spike_masters') or [])
    for m in vs_masters:
        master_stats[m]['trigger_days'].add(td['date'])
    for p in td['quad_picks']:
        matched = set(p.get('matched_masters') or [])
        for m in matched:
            master_stats[m]['all_picks'].append({
                'date': td['date'], 'code': p['code'], 'name': p['name'],
                'next_change': p['next_change_pct'], 'hit': p['hit'],
                'excess': p.get('excess_return'),
            })
            if len(matched) == 1:
                master_stats[m]['solo_picks'].append({
                    'date': td['date'], 'code': p['code'], 'name': p['name'],
                    'next_change': p['next_change_pct'], 'hit': p['hit'],
                })


def summarize(picks):
    if not picks: return None
    n = len(picks)
    hits = sum(1 for p in picks if p['hit'])
    mean = sum(p['next_change'] for p in picks) / n
    return {'n': n, 'hits': hits, 'hr': hits/n, 'mean': mean}


print('=' * 80)
print('Per-master vol_spike 可靠度 (排序 by all_picks 命中率)')
print('=' * 80)
print(f"{'Master':<22} {'trigger days':>12} {'all picks':>10} {'hit':>4} {'hit%':>6} {'mean%':>7}")
print('-' * 80)
rows = []
for m, s in master_stats.items():
    summ = summarize(s['all_picks'])
    if summ:
        rows.append((m, len(s['trigger_days']), summ))
rows.sort(key=lambda x: -x[2]['hr'])
for m, td, summ in rows:
    print(f"  {m:<22} {td:>12} {summ['n']:>10} {summ['hits']:>4} "
          f"{summ['hr']*100:>5.1f}% {summ['mean']:>+6.2f}%")

print()
print('=' * 80)
print('Per-master picks 細節 (倒序 by date)')
print('=' * 80)
for m, td, summ in rows:
    print()
    print(f"--- {m} ({summ['n']} picks, {summ['hr']*100:.0f}% hit) ---")
    picks = sorted(master_stats[m]['all_picks'], key=lambda p: p['date'], reverse=True)
    for p in picks:
        sym = '🟢' if p['hit'] else '🔴'
        ex = f" [excess {p['excess']:+.1f}pp]" if p.get('excess') is not None else ''
        print(f"  {sym} {p['date']} {p['name']}({p['code']}): "
              f"{p['next_change']:+.2f}%{ex}")

print()
print('=' * 80)
print('Solo picks 比對 (master 單獨觸發 vol_spike 的 picks — 最乾淨歸因)')
print('=' * 80)
for m, s in master_stats.items():
    if s['solo_picks']:
        summ = summarize(s['solo_picks'])
        print(f"  {m}: {summ['hits']}/{summ['n']} = {summ['hr']*100:.0f}% "
              f"mean {summ['mean']:+.2f}%")

# 6/16 強森+陳律師 specific
print()
print('=' * 80)
print('6/16 強森+陳律師 配對失敗深入: 哪些 picks, 各自表現?')
print('=' * 80)
td_616 = next((t for t in qhl['trigger_days'] if t['date'] == '20260616'), None)
if td_616:
    for p in td_616['quad_picks']:
        sym = '🟢' if p['hit'] else '🔴'
        m_str = ', '.join(p.get('matched_masters') or [])
        print(f"  {sym} {p['name']}({p['code']}): {p['next_change_pct']:+.2f}% "
              f"(matched: {m_str})")
