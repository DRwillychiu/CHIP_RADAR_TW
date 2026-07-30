"""v3.71.8 Phase 3.5: t+1 ~ t+5 multiday backtest.

對 quad_hit_log.json 內每個 quad pick, 從 stock_history 算:
  - cum_1d / cum_2d / cum_3d / cum_4d / cum_5d (持有 N 天累積報酬)
  - peak_within_5d (t+1~t+5 任一日最高點報酬 — 最佳出場潛能)

支援 combo filter (套 sub-population 算 alpha):
  - all_quad: 全部 quad picks (baseline)
  - premium_only: premium master (陳律師/竹科主力/陳族元) 配對
  - standard_only: 無 premium master
  - master_count_ge_12: 大戶數 ≥12
  - 其他自訂 combo

IS/OOS 60/40 split (picks-level, 按日期 sort):
  IS = 前 60% picks
  OOS = 後 40% picks
  比 hit_rate 差 → 反 over-fit guard

輸出 data/multiday_backtest.json:
  {
    "combos": {
      combo_name: {
        "description": "經濟學解釋",
        "is": {n, hit_5d, mean_5d, ci, peak_hit, peak_mean},
        "oos": {同上},
        "all": {同上, + cum_1d / cum_2d / cum_3d / cum_4d}
      }
    }
  }
"""
import json, sys, math
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
QHL_PATH = ROOT / 'data' / 'quad_hit_log.json'
SH_PATH = ROOT / 'data' / 'stock_history.json'
OUT_PATH = ROOT / 'data' / 'multiday_backtest.json'

PREMIUM_MASTERS = {'陳律師', '竹科主力分點', '陳族元'}

# ── Combo definitions ──
# 每個 combo 必含 description (經濟學解釋, 反 over-fit guard)
COMBOS = {
    'all_quad': {
        'description': '全部 quad picks (baseline, 含所有 master)',
        'filter': lambda p: True,
    },
    # Iteration 1 候選
    'premium_only': {
        'description': ('Premium master (≥77% t+1 hit) 配對的 quad picks. '
                        '經濟學: 大戶質量篩選 — 精準 master 訊號應在多日持續 outperform.'),
        'filter': lambda p: bool(set(p.get('matched_masters') or []) & PREMIUM_MASTERS),
    },
}


def wilson_ci(hits, n, z=1.96):
    if n == 0: return (0, 0)
    p = hits / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return ((centre - margin) / denom, (centre + margin) / denom)


def main():
    qhl = json.loads(QHL_PATH.read_text(encoding='utf-8'))
    sh = json.loads(SH_PATH.read_text(encoding='utf-8'))
    sh_stocks = sh.get('stocks', {})
    sh_dates = sh.get('dates', [])

    # 收集所有 picks + multiday returns
    all_picks = []
    for td in qhl.get('trigger_days', []):
        date = td['date']
        if date not in sh_dates: continue
        idx = sh_dates.index(date)
        for p in td.get('quad_picks', []):
            code = p.get('code')
            if not code: continue
            s_data = sh_stocks.get(code, {}).get('daily', {})
            today_close = (s_data.get(date) or {}).get('close')
            if today_close is None: continue

            # 算 t+1 ~ t+5 close
            cums = {}
            closes = []
            for k in range(1, 6):
                if idx + k >= len(sh_dates):
                    cums[f'cum_{k}d'] = None; closes.append(None); continue
                future_date = sh_dates[idx + k]
                fc = (s_data.get(future_date) or {}).get('close')
                if fc is None:
                    cums[f'cum_{k}d'] = None; closes.append(None); continue
                cums[f'cum_{k}d'] = (fc / today_close - 1) * 100
                closes.append(fc)
            # peak_within_5d
            valid_closes = [c for c in closes if c is not None]
            if valid_closes:
                peak = max(valid_closes)
                cums['peak_5d'] = (peak / today_close - 1) * 100
            else:
                cums['peak_5d'] = None

            all_picks.append({
                'date': date, 'code': code, 'name': p.get('name'),
                'matched_masters': p.get('matched_masters') or [],
                **cums,
            })

    print(f"=== Multiday backtest (n_total = {len(all_picks)} picks) ===\n")

    # 按 date sort 做 IS/OOS split
    all_picks.sort(key=lambda p: p['date'])
    n_total = len(all_picks)
    is_cutoff = int(n_total * 0.6)
    is_picks = all_picks[:is_cutoff]
    oos_picks = all_picks[is_cutoff:]
    print(f"IS picks: {len(is_picks)} (前 60%)")
    print(f"OOS picks: {len(oos_picks)} (後 40%)\n")

    def _stats(picks, metric='cum_5d'):
        """算 hit / mean / Wilson CI for a metric."""
        vals = [p[metric] for p in picks if p.get(metric) is not None]
        n = len(vals)
        if n == 0: return None
        hits = sum(1 for v in vals if v > 0)
        mean = sum(vals) / n
        sorted_v = sorted(vals)
        med = sorted_v[n // 2] if n % 2 else (sorted_v[n//2-1] + sorted_v[n//2]) / 2
        cum = sum(vals)
        ci_lo, ci_hi = wilson_ci(hits, n)
        return {
            'n': n, 'hits': hits, 'hit_rate': round(hits / n, 4),
            'mean': round(mean, 3), 'median': round(med, 3),
            'cum': round(cum, 1),
            'ci_lo': round(ci_lo, 4), 'ci_hi': round(ci_hi, 4),
        }

    results = {}
    for combo_name, combo_def in COMBOS.items():
        filt = combo_def['filter']
        combo_all = [p for p in all_picks if filt(p)]
        combo_is = [p for p in is_picks if filt(p)]
        combo_oos = [p for p in oos_picks if filt(p)]

        combo_result = {
            'description': combo_def['description'],
            'all': {
                'cum_1d': _stats(combo_all, 'cum_1d'),
                'cum_3d': _stats(combo_all, 'cum_3d'),
                'cum_5d': _stats(combo_all, 'cum_5d'),
                'peak_5d': _stats(combo_all, 'peak_5d'),
            },
            'is': _stats(combo_is, 'cum_5d'),
            'oos': _stats(combo_oos, 'cum_5d'),
            'peak_is': _stats(combo_is, 'peak_5d'),
            'peak_oos': _stats(combo_oos, 'peak_5d'),
        }
        results[combo_name] = combo_result

        # Print summary
        print(f"--- {combo_name} ---")
        print(f"  desc: {combo_def['description'][:80]}...")
        for metric_label, st in [('cum_1d', combo_result['all']['cum_1d']),
                                   ('cum_3d', combo_result['all']['cum_3d']),
                                   ('cum_5d', combo_result['all']['cum_5d']),
                                   ('peak_5d', combo_result['all']['peak_5d'])]:
            if st:
                print(f"  {metric_label}: n={st['n']} hit={st['hit_rate']*100:.1f}% "
                      f"mean={st['mean']:+.2f}% [CI {st['ci_lo']*100:.1f}-{st['ci_hi']*100:.1f}%]")
        # IS/OOS check
        is_s = combo_result['is']; oos_s = combo_result['oos']
        if is_s and oos_s:
            is_hr = is_s['hit_rate'] * 100
            oos_hr = oos_s['hit_rate'] * 100
            diff = is_hr - oos_hr
            print(f"  cum_5d IS/OOS: IS {is_hr:.1f}% (n={is_s['n']}) vs OOS {oos_hr:.1f}% (n={oos_s['n']}) | diff {diff:+.1f}pp", end='')
            print('  ⚠️ OVER-FIT' if abs(diff) > 10 else '  ✓ ok')
        print()

    # Write
    OUT_PATH.write_text(json.dumps({
        'combos': results,
        'n_total': n_total,
        'is_cutoff_date': is_picks[-1]['date'] if is_picks else None,
        'split': '60/40',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"✅ 寫入 {OUT_PATH}")


if __name__ == '__main__':
    main()
