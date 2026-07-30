"""v3.71.22 L2 溫度計閾值分位合理性 audit.

對 temp_history.json 過去 N 天 entry, 統計每個 signal 的:
  1. raw value 分布 (min/max/mean/median/p25/p75)
  2. tier 分布 (extreme-bull / bull / neutral / bear / extreme-bear 五分)
  3. 對照理想分布 (每 tier 15-25%)
  4. 判定:
     - ✅ 合理 (每 tier 10-30%)
     - ⚠️ 偏誤 (某 tier > 50%)
     - 🔴 崩盤 (某 tier > 80%, signal 幾乎沒 informativeness)

閾值改善建議: 若某 signal 分布明顯偏,推薦新閾值 (基於 p20/p40/p60/p80 分位).

輸出: data/temp_thresholds_audit_YYYYMMDD.json + console table
"""
import json, sys, statistics
from collections import Counter
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
TH_PATH = ROOT / 'data' / 'temp_history.json'

th = json.loads(TH_PATH.read_text(encoding='utf-8'))
history = th.get('history') or []
print(f"=== Threshold Distribution Audit (n={len(history)} entries) ===\n")

# TEMP_THRESHOLDS 從 algo_params (hardcoded here for audit)
THRESHOLDS = {
    '外資現貨':  (50000, 10000, -10000, -50000),
    '外資期貨':  (30000, 10000, -10000, -30000),
    'P/C Ratio': (1.3, 1.0, 0.8, 0.6),
    '分點漲停':  (8, 4, 1, 0),
    '融資熱度':  (30, 10, -10, -30),
}

# Collect values + levels per signal
per_signal = {}   # name -> {values: [...], levels: [...]}
for e in history:
    for s in (e.get('signals') or []):
        name = s.get('name')
        val = s.get('value')
        lvl = s.get('level')
        # skip dict values (法人共識/結算日壓力) - not scalar threshold
        if not isinstance(val, (int, float)): continue
        per_signal.setdefault(name, {'values': [], 'levels': []})
        per_signal[name]['values'].append(val)
        per_signal[name]['levels'].append(lvl)

# Ideal distribution (~20% per tier)
IDEAL = 0.20

results = []
for name, thr in THRESHOLDS.items():
    d = per_signal.get(name)
    if not d or not d['values']:
        print(f"--- {name} ---  NO DATA")
        continue
    vals = d['values']
    lvls = d['levels']
    n = len(vals)
    # Stats
    v_min, v_max = min(vals), max(vals)
    v_mean = statistics.mean(vals)
    v_med = statistics.median(vals)
    sorted_v = sorted(vals)
    p25 = sorted_v[int(n * 0.25)]
    p75 = sorted_v[int(n * 0.75)]
    p20 = sorted_v[int(n * 0.20)] if n >= 5 else None
    p40 = sorted_v[int(n * 0.40)] if n >= 5 else None
    p60 = sorted_v[int(n * 0.60)] if n >= 5 else None
    p80 = sorted_v[int(n * 0.80)] if n >= 5 else None

    # Tier distribution
    tier_count = Counter(lvls)
    tier_pct = {k: v / n for k, v in tier_count.items()}

    # Verdict
    max_tier_pct = max(tier_pct.values()) if tier_pct else 0
    if max_tier_pct >= 0.80:
        verdict = f'🔴 崩盤 (某 tier {max_tier_pct*100:.0f}%)'
    elif max_tier_pct >= 0.50:
        verdict = f'⚠️ 偏誤 (某 tier {max_tier_pct*100:.0f}%)'
    else:
        verdict = f'✅ 合理'

    print(f"--- {name} ---")
    print(f"  n={n} | value: min={v_min:.3f} p25={p25:.3f} med={v_med:.3f} "
          f"mean={v_mean:.3f} p75={p75:.3f} max={v_max:.3f}")
    print(f"  現閾值: {thr}")
    if p20 is not None:
        print(f"  P20/40/60/80 建議: ({p80:.3f}, {p60:.3f}, {p40:.3f}, {p20:.3f})")
    print(f"  Tier 分布:")
    for lvl in ['extreme-bull', 'bull', 'neutral', 'bear', 'extreme-bear']:
        cnt = tier_count.get(lvl, 0)
        pct = tier_pct.get(lvl, 0)
        bar = '█' * int(pct * 30)
        print(f"    {lvl:<15} {cnt:>3} ({pct*100:>5.1f}%)  {bar}")
    print(f"  {verdict}")
    print()

    results.append({
        'signal': name, 'n': n,
        'value_stats': {'min': v_min, 'p25': p25, 'median': v_med,
                        'mean': v_mean, 'p75': p75, 'max': v_max},
        'current_thresholds': list(thr),
        'suggested_thresholds': [p80, p60, p40, p20] if p20 else None,
        'tier_dist_pct': tier_pct,
        'max_tier_pct': max_tier_pct,
        'verdict': verdict,
    })

# Summary
print("\n=== Summary ===")
for r in results:
    print(f"  {r['signal']:<12}  {r['verdict']}")

# Save
import datetime
today = history[-1].get('date') if history else datetime.datetime.now().strftime('%Y%m%d')
op = ROOT / 'data' / f'temp_thresholds_audit_{today}.json'
op.write_text(json.dumps({
    'audited_at': datetime.datetime.now().isoformat(),
    'window_days': len(history),
    'results': results,
}, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"\n✅ 寫入 {op}")
