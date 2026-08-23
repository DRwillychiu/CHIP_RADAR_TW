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

# v3.75.0 稽核修正:
#   (a) 單位統一 — 原本 baseline.hit_rate 是分數(0.51) 但 per_master.hr_with 是
#       百分比(83.3), 同一份 JSON 兩種單位, 下游必踩雷. 全部統一為百分比 (_pct 後綴).
#   (b) 加 updated_at / source_updated_at — 原本無時間戳, 過期而不自知.
#       (實測發現此檔 baseline n=257 但 quad_hit_log 已是 233, 即已過期)
#   (c) 樣本門檻 — 原本 n=8~12 也直接下「輔助/拖後腿」判定.
#       n=12 的 83.3% 其實是 10/12, Wilson CI 約 [55%, 95%], 寬到無判別力.
MIN_N_FOR_VERDICT = 20      # 低於此只標「樣本不足」, 不下判定

def _wilson_pct(hits, n, z=1.96):
    """回傳 (lo%, hi%) — Wilson 95% 信賴區間, 單位為百分比."""
    if n <= 0:
        return (None, None)
    import math
    p = hits / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((c - m) / d * 100, 1), round((c + m) / d * 100, 1))


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

    hits_with = sum(p['hit'] for p in picks_with)
    ci_lo, ci_hi = _wilson_pct(hits_with, n_with)

    # Verdict — v3.75.0 加樣本門檻, 樣本不足不下判定
    if n_with == 0:
        verdict = '未貢獻'
    elif n_with < MIN_N_FOR_VERDICT:
        verdict = f'樣本不足 (n={n_with}<{MIN_N_FOR_VERDICT})'
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
        'contrib_pct_pct': contrib_pct, 'n_with': n_with, 'hits_with': hits_with,
        'hr_with_pct': hr_with, 'hr_without_pct': hr_without,
        'ci_lo_pct': ci_lo, 'ci_hi_pct': ci_hi,
        'delta_pp': delta_pp, 'verdict': verdict,
        'verdict_reliable': n_with >= MIN_N_FOR_VERDICT,
    })

# Sort: contribution desc
rows.sort(key=lambda r: -r['contrib_pct_pct'])

# Print table
print(f"{'Master':<22} {'⭐⭐':<3} {'貢獻%':>6} {'n':>5} {'hit%':>6} {'Wilson95%':>15} {'no_M%':>7} {'Δpp':>7}  Verdict")
print('-' * 108)
for r in rows:
    star = '⭐⭐' if r['is_premium'] else '  '
    ci = (f"[{r['ci_lo_pct']:.0f},{r['ci_hi_pct']:.0f}]"
          if r['ci_lo_pct'] is not None else '—')
    print(f"  {r['master']:<20} {star:<3} {r['contrib_pct_pct']:>5.1f}% {r['n_with']:>5} "
          f"{r['hr_with_pct']:>5.1f}% {ci:>15} {r['hr_without_pct']:>6.1f}% "
          f"{r['delta_pp']:>+6.1f}pp  {r['verdict']}")

# Summary by verdict
print("\n=== Summary by verdict ===")
from collections import Counter
verdicts = Counter(r['verdict'] for r in rows)
for v in ['核心 alpha', '輔助', '中性', '拖後腿', '未貢獻']:
    if verdicts[v]:
        names = [r['master'] for r in rows if r['verdict'] == v]
        print(f"  {v}: {verdicts[v]} 位 → {', '.join(names)}")

# Write
from datetime import datetime, timezone, timedelta
_tw = datetime.now(timezone(timedelta(hours=8)))
_base_lo, _base_hi = _wilson_pct(total_hits, total_n)
out_data = {
    # v3.75.0: 全面改用 _pct 後綴, 單位一律百分比 (不再分數/百分比混用)
    'schema_version': 2,
    'updated_at': _tw.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
    'source_updated_at': qhl.get('updated_at'),      # 來源 quad_hit_log 的時間
    'min_n_for_verdict': MIN_N_FOR_VERDICT,
    'baseline': {
        'n': total_n, 'hits': total_hits,
        'hit_rate_pct': round(total_hr * 100, 1),
        'ci_lo_pct': _base_lo, 'ci_hi_pct': _base_hi,
    },
    'per_master': rows,
    'summary_counts': dict(verdicts),
}
OUT.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"\n✅ 寫入 {OUT}")
