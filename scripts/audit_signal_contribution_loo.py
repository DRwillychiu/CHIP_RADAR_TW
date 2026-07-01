"""v3.71.23 L3: per-signal Q5 hit contribution (LOO).

對 temp_history 每個 entry 重跑 infer_market_direction, 對每個 signal S_i:
  1. baseline = 所有 signal 都用
  2. leave_out_S_i = 移除 signal S_i 後重算
  3. 對比兩者的 Q5 hit rate

揭穿:
  - 核心 signal (刪掉後 hit rate 大跌)
  - dead weight (刪掉後無變化, weight=0 or killed)
  - 拖後腿 (刪掉後 hit rate 反而上升)

⚠️ 應用 v3.71.20 補完 stale guard (chg=0.0 AND close=None → skip).
"""
import json, sys
from copy import deepcopy
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analyzers.signal_engine import infer_market_direction

with open(ROOT / 'data' / 'temp_history.json', 'r', encoding='utf-8') as f:
    th = json.load(f)
history = th.get('history') or []

# 7 signals
SIGNAL_NAMES = ['外資現貨', '外資期貨', 'P/C Ratio', '分點漲停',
                '融資熱度', '法人共識', '結算日壓力']


def _compute_hit(picks_signals_list):
    """對 list of (signals, next_chg) 跑 Q5 + tally hit."""
    b_h = b_t = 0
    r_h = r_t = 0
    for signals, nxt in picks_signals_list:
        if nxt is None: continue
        # stale guard
        if nxt == 0.0: continue
        md = infer_market_direction(signals)
        d = md.get('direction')
        if d == '偏多':
            b_t += 1
            if nxt > 0: b_h += 1
        elif d == '偏空':
            r_t += 1
            if nxt < 0: r_h += 1
    total_t = b_t + r_t
    total_h = b_h + r_h
    return {
        'bull_hit': b_h, 'bull_total': b_t, 'bull_rate': b_h / b_t if b_t else 0,
        'bear_hit': r_h, 'bear_total': r_t, 'bear_rate': r_h / r_t if r_t else 0,
        'total_hit': total_h, 'total_total': total_t,
        'overall_rate': total_h / total_t if total_t else 0,
    }


# Build entries
entries = []
for e in history:
    sigs = e.get('signals') or []
    nxt = e.get('next_day_change_pct')
    if not sigs or nxt is None: continue
    # skip stale
    if nxt == 0.0 and e.get('next_day_close') is None: continue
    entries.append((sigs, nxt))
print(f"Valid entries after stale guard: {len(entries)}\n")

# Baseline (all signals)
baseline = _compute_hit(entries)
print(f"=== Baseline (全 7 signals) ===")
print(f"  偏多: {baseline['bull_hit']}/{baseline['bull_total']} = {baseline['bull_rate']*100:.1f}%")
print(f"  偏空: {baseline['bear_hit']}/{baseline['bear_total']} = {baseline['bear_rate']*100:.1f}%")
print(f"  整體: {baseline['total_hit']}/{baseline['total_total']} = {baseline['overall_rate']*100:.1f}%")
print()

# LOO for each signal
results = []
print(f"=== LOO per-signal ===")
print(f"{'Signal':<15} {'n_used':>6} {'hit':>4} {'hit%':>6} {'Δ vs baseline':>15}  Verdict")
print('-' * 75)
for s_name in SIGNAL_NAMES:
    # Modified entries: remove signal s_name from each entry's signals list
    modified = []
    n_affected = 0
    for sigs, nxt in entries:
        new_sigs = [s for s in sigs if s.get('name') != s_name]
        if len(new_sigs) < len(sigs): n_affected += 1
        modified.append((new_sigs, nxt))
    stat = _compute_hit(modified)
    delta = (stat['overall_rate'] - baseline['overall_rate']) * 100
    if abs(delta) < 0.5:
        verdict = '⚪ Dead weight (weight=0 or 移除無影響)'
    elif delta < -5:
        verdict = '⭐ 核心 alpha (移除後 hit 大跌)'
    elif delta < 0:
        verdict = '✅ 輔助 (移除後 hit 微降)'
    elif delta < 5:
        verdict = '🟡 中性 (移除後 hit 微升)'
    else:
        verdict = '⚠️ 拖後腿 (移除後 hit 大升!)'
    print(f"  {s_name:<13}  {stat['total_total']:>4}  {stat['total_hit']:>4}  "
          f"{stat['overall_rate']*100:>5.1f}%  {delta:>+7.1f}pp     {verdict}")
    results.append({
        'signal': s_name, 'n_affected': n_affected,
        'stat_without': stat, 'delta_pp': delta, 'verdict': verdict,
    })

# Save
import datetime
today = history[-1].get('date') if history else datetime.datetime.now().strftime('%Y%m%d')
op = ROOT / 'data' / f'signal_contribution_loo_{today}.json'
op.write_text(json.dumps({
    'audited_at': datetime.datetime.now().isoformat(),
    'baseline': baseline,
    'per_signal_loo': results,
}, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"\n✅ 寫入 {op}")
