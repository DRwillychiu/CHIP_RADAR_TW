"""v3.71.16 N1: Master 對 quad alpha 貢獻度分析 (Leave-One-Out 簡化).

對每個追蹤 master M, 算:
  with_M:    quad_hit_log 內 含 M 在 matched_masters 的 picks
  without_M: quad_hit_log 內 不含 M (純由其他 master trigger)

  contribution_score = picks_with_M / total_picks
  alpha_when_kept   = hit_rate(with_M)
  alpha_when_excluded = hit_rate(without_M)  # 如果刪 M, 整體 hit 變什麼樣

判定:
  - 「核心 alpha」: contribution >= 30% AND hit(with) > hit(without)
  - 「中性」: contribution < 30% OR hit 差 <5pp
  - 「拖後腿」: hit(with M only) < hit(without M)
  - 「未貢獻」: contribution = 0 (從未 trigger)

輸出 data/master_contribution.json + console table.
"""
import json, sys
from collections import defaultdict
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
QHL = ROOT / 'data' / 'quad_hit_log.json'
OUT = ROOT / 'data' / 'master_contribution.json'

# 從 master mapping 抓 13 位 (用 excel_report 的 TRACKED_MASTERS)
sys.path.insert(0, str(ROOT / 'src'))
from exports.excel_report import TRACKED_MASTERS, PREMIUM_MASTERS

qhl = json.loads(QHL.read_text(encoding='utf-8'))
trigger_days = qhl.get('trigger_days', [])
all_picks = []
for td in trigger_days:
    for p in td.get('quad_picks', []):
        all_picks.append({
            'matched_masters': set(p.get('matched_masters') or []),
            'next_chg': p.get('next_change_pct'),
            'hit': p.get('hit', 0),
        })
total_n = len(all_picks)
total_hits = sum(p['hit'] for p in all_picks)
total_hr = total_hits / total_n if total_n else 0
print(f"=== Quad pool baseline: n={total_n}, hits={total_hits}, hit_rate={total_hr*100:.1f}% ===\n")

# Per-master LOO
rows = []
for m in sorted(TRACKED_MASTERS):
    picks_with = [p for p in all_picks if m in p['matched_masters']]
    picks_without = [p for p in all_picks if m not in p['matched_masters']]
    n_with = len(picks_with)
    n_without = len(picks_without)
    contrib_pct = n_with / total_n * 100 if total_n else 0
    hr_with = sum(p['hit'] for p in picks_with) / n_with * 100 if n_with else 0
    hr_without = sum(p['hit'] for p in picks_without) / n_without * 100 if n_without else 0
    delta_pp = hr_with - hr_without
    is_premium = m in PREMIUM_MASTERS

    # Verdict
    if n_with == 0:
        verdict = '未貢獻'
    elif contrib_pct >= 30 and delta_pp > 0:
        verdict = '核心 alpha'
    elif delta_pp < -5:
        verdict = '拖後腿'
    elif abs(delta_pp) <= 5:
        verdict = '中性'
    else:
        verdict = '輔助'

    rows.append({
        'master': m, 'is_premium': is_premium,
        'contrib_pct': contrib_pct, 'n_with': n_with,
        'hr_with': hr_with, 'hr_without': hr_without,
        'delta_pp': delta_pp, 'verdict': verdict,
    })

# Sort: contribution desc
rows.sort(key=lambda r: -r['contrib_pct'])

# Print table
print(f"{'Master':<22} {'⭐⭐':<3} {'貢獻%':>6} {'n_with':>7} {'hit%':>5} {'no_M %':>7} {'Δpp':>6}  Verdict")
print('-' * 80)
for r in rows:
    star = '⭐⭐' if r['is_premium'] else '  '
    print(f"  {r['master']:<20} {star:<3} {r['contrib_pct']:>5.1f}% {r['n_with']:>7} "
          f"{r['hr_with']:>4.0f}% {r['hr_without']:>6.0f}% {r['delta_pp']:>+5.1f}pp  {r['verdict']}")

# Summary by verdict
print("\n=== Summary by verdict ===")
from collections import Counter
verdicts = Counter(r['verdict'] for r in rows)
for v in ['核心 alpha', '輔助', '中性', '拖後腿', '未貢獻']:
    if verdicts[v]:
        names = [r['master'] for r in rows if r['verdict'] == v]
        print(f"  {v}: {verdicts[v]} 位 → {', '.join(names)}")

# Write
out_data = {
    'baseline': {'n': total_n, 'hits': total_hits, 'hit_rate': total_hr},
    'per_master': rows,
    'summary_counts': dict(verdicts),
}
OUT.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"\n✅ 寫入 {OUT}")
