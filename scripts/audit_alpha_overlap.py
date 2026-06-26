"""v3.71.2 Phase 3.4 follow-up: alpha overlap audit.

對歷史每天計算 quad picks vs mild_up picks 重疊比例.
驗證雙層 alpha 是否獨立 — 若 mild_up 大部分是 quad subset, 雙層 sub-banner 該砍.

對每個歷史交易日:
  1. 計算 consensus picks (≥10 大戶共識)
  2. 計算 quad picks (共識 ∩ Q5 偏多 ∩ master vol_spike)
  3. 計算 mild_up picks (共識 ∩ Q5 偏多 ∩ 近 3 天累積 0-8%)
  4. tally:
     - mild_up_total: 所有 mild_up picks 數
     - mild_up_only_total: 不在 quad 內的 mild_up
     - quad_total
     - intersection
  5. 算 hit rate (隔日 chg):
     - quad_only picks (in quad - in mild_up)
     - both picks (in quad AND in mild_up)
     - mild_up_only picks (in mild_up - in quad)
     - 各自 hit / total / mean_change

verdict:
  - 若 mild_up_only / mild_up_total > 60% → mild_up 是「獨立 alpha」, 雙層合理
  - 若 mild_up_only / mild_up_total < 30% → mild_up 是 quad subset, 雙層 redundant
  - 介於 30-60% → 部分獨立, 雙層仍有價值
"""
import json, sys, os, gzip
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipelines.crawler_output import decrypt_data
from src.exports.excel_report import (
    _filter_tracked_branches, _compute_consensus_count,
    _is_tracked_master,
)
from src.analyzers.signal_engine import infer_market_direction

password = os.environ.get('CHIP_RADAR_PASSWORD', '')
if not password:
    print("❌ CHIP_RADAR_PASSWORD 未設"); sys.exit(1)

# Load history
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


def _price_3d_chg(code, today_idx):
    s_data = sh_stocks.get(code, {}).get('daily', {})
    if today_idx < 3:
        return None
    today_close = (s_data.get(sh_dates[today_idx]) or {}).get('close')
    d3_close = (s_data.get(sh_dates[today_idx - 3]) or {}).get('close')
    if today_close is None or d3_close is None or d3_close <= 0:
        return None
    return (today_close / d3_close - 1) * 100


daily_files = sorted(
    list((ROOT / 'data').glob('[0-9]' * 8 + '.json')) +
    list((ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json')) +
    list((ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json.gz')),
    key=lambda p: p.name[:8]
)

# Per-bucket tracker
buckets = {
    'quad_only':    {'picks': [], 'desc': 'quad ∩ NOT mild_up (master 量爆但 3d chg 不在 0-8%)'},
    'both':         {'picks': [], 'desc': 'quad ∩ mild_up (兩條件都滿足)'},
    'mild_up_only': {'picks': [], 'desc': 'mild_up ∩ NOT quad (溫和上行但無 master 量爆)'},
}
per_day = []

for p in daily_files:
    date = p.name[:8]
    if date not in sh_dates: continue
    idx = sh_dates.index(date)
    if idx + 1 >= len(sh_dates): continue
    next_date = sh_dates[idx + 1]

    data = _read_daily(p)
    if not data: continue
    branches = data.get('branches', [])
    if not branches: continue

    filtered = _filter_tracked_branches(branches)
    consensus = _compute_consensus_count(filtered)
    if not consensus: continue

    # Q5 direction
    th_entry = th_by_date.get(date)
    q5_dir = None
    if th_entry:
        try:
            md = infer_market_direction(th_entry.get('signals') or [])
            q5_dir = md.get('direction')
        except Exception:
            pass
    if q5_dir != '偏多':
        # Phase 3.2/3.4 都 require Q5 偏多 → 跳過非偏多日
        continue

    # Master vol_spike (from daily_trading_signals)
    dts = data.get('daily_trading_signals') or {}
    vol_spike_masters = set()
    for a in (dts.get('anomalies') or []):
        if a.get('type') == 'volume_spike' and _is_tracked_master(a.get('master')):
            vol_spike_masters.add(a.get('master'))

    # 重建 stock-level master ownership
    stock_masters = {}
    for b in filtered:
        m = b.get('master')
        if not m: continue
        for s in (b.get('buys') or []) + (b.get('sells') or []):
            code = s.get('code')
            if not code or code.startswith('00'): continue
            net = (s.get('buy_amt') or 0) - (s.get('sell_amt') or 0)
            if net <= 0: continue
            stock_masters.setdefault(code, set()).add(m)

    day_quad = set()
    day_mild = set()
    for c in consensus:
        code = c['code']
        # quad: 共識 (已 by definition) + Q5 偏多 (整天 filter) + master vol_spike 交集
        if stock_masters.get(code, set()) & vol_spike_masters:
            day_quad.add(code)
        # mild_up: 共識 + Q5 偏多 + 近 3 天 0-8%
        chg_3d = _price_3d_chg(code, idx)
        if chg_3d is not None and 0 <= chg_3d <= 8.0:
            day_mild.add(code)

    # Tally per pick
    for code in (day_quad | day_mild):
        s_data = sh_stocks.get(code, {}).get('daily', {})
        nd = s_data.get(next_date) or {}
        nxt_chg = nd.get('change_pct')
        nxt_close = nd.get('close')
        if nxt_chg is None or nxt_close is None:
            continue
        is_q = code in day_quad
        is_m = code in day_mild
        if is_q and is_m:
            bucket = 'both'
        elif is_q:
            bucket = 'quad_only'
        else:
            bucket = 'mild_up_only'
        buckets[bucket]['picks'].append({
            'date': date, 'next_date': next_date, 'code': code,
            'next_chg': nxt_chg,
            'hit': 1 if nxt_chg > 0 else 0,
        })

    per_day.append({
        'date': date, 'next_date': next_date,
        'quad_n': len(day_quad), 'mild_n': len(day_mild),
        'intersection': len(day_quad & day_mild),
        'quad_only': len(day_quad - day_mild),
        'mild_only': len(day_mild - day_quad),
    })
    print(f"  {date} → {next_date}: quad={len(day_quad)} mild={len(day_mild)} "
          f"∩={len(day_quad & day_mild)} quad_only={len(day_quad - day_mild)} "
          f"mild_only={len(day_mild - day_quad)}")


def _stats(bucket):
    picks = bucket['picks']
    n = len(picks)
    if n == 0:
        return {'n': 0, 'hits': 0, 'hit_rate': 0, 'mean_change': 0, 'median_change': 0}
    hits = sum(p['hit'] for p in picks)
    chgs = sorted(p['next_chg'] for p in picks)
    mean_c = sum(chgs) / n
    median_c = chgs[n // 2] if n % 2 else (chgs[n // 2 - 1] + chgs[n // 2]) / 2
    return {'n': n, 'hits': hits, 'hit_rate': hits / n,
            'mean_change': mean_c, 'median_change': median_c}


print(f"\n{'='*70}\nAlpha Overlap Summary\n{'='*70}\n")
print(f"{'bucket':<15} {'n':>4} {'hits':>4} {'hit%':>5}  {'mean%':>6} {'median%':>7}")
print('-' * 60)
results = {}
for name, b in buckets.items():
    st = _stats(b)
    results[name] = st
    print(f"  {name:<13} {st['n']:>4} {st['hits']:>4} {st['hit_rate']*100:>5.1f}% "
          f"{st['mean_change']:>+5.2f}% {st['median_change']:>+6.2f}%")

# Verdict
mild_total = results['both']['n'] + results['mild_up_only']['n']
mild_only_pct = (results['mild_up_only']['n'] / mild_total * 100) if mild_total else 0
quad_total = results['both']['n'] + results['quad_only']['n']
both_overlap_pct = (results['both']['n'] / quad_total * 100) if quad_total else 0

print(f"\nmild_up 獨立性: mild_up_only / (both + mild_up_only) = "
      f"{results['mild_up_only']['n']}/{mild_total} = {mild_only_pct:.1f}%")
print(f"quad 被 mild_up 覆蓋: both / (both + quad_only) = "
      f"{results['both']['n']}/{quad_total} = {both_overlap_pct:.1f}%")

if mild_total == 0:
    verdict = "樣本不足"
elif mild_only_pct >= 60:
    verdict = "雙層獨立 — mild_up 大部分非 quad subset, 維持雙層 sub-banner 合理"
elif mild_only_pct >= 30:
    verdict = "部分獨立 — mild_up 大部分非 quad subset, 雙層仍有獨立信息"
else:
    verdict = "雙層 redundant — mild_up 大部分是 quad subset, 建議砍 sub-banner"
print(f"\n判定: {verdict}")

# Hit rate 對比 (insight: 重疊 bucket 是否最強?)
print(f"\n=== Hit rate 對比 (重疊 = 強 alpha?) ===")
for name in ['quad_only', 'both', 'mild_up_only']:
    st = results[name]
    if st['n'] > 0:
        print(f"  {name:<13} hit {st['hit_rate']*100:>5.1f}%  mean {st['mean_change']:>+5.2f}%  (n={st['n']})")

# Write
out = ROOT / 'data' / 'alpha_overlap_audit.json'
import datetime
out_data = {
    'updated_at': datetime.datetime.now().isoformat(),
    'days_analyzed': len(per_day),
    'summary': {
        'mild_only_pct': mild_only_pct,
        'both_overlap_pct_of_quad': both_overlap_pct,
        'verdict': verdict,
    },
    'buckets': results,
    'per_day': per_day,
}
out.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"\n✅ 寫入 {out}")
