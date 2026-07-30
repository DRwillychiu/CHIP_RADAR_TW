"""v3.68.0 Phase 3.1: 訊號組合 backtest

對歷史每天的強共識股, 套用各種「過濾條件組合」, 計算隔日 hit rate.
目標: 找出 hit rate > 60% 的組合 = 真 alpha 訊號.

組合定義:
  baseline      : 全部共識股 (對照組, ~50%)
  q5_bull       : 共識 ∩ Q5 偏多 (Q5 預測 alignment)
  high_conv     : 共識 ∩ 領頭佔比 <50% (真共識, 非 1 人獨大)
  extra_breadth : 共識 ∩ 大戶數 ≥12 (廣度極端)
  combo_AAA     : 共識 ∩ Q5 偏多 ∩ 高 conviction (3 條件全)

每組合輸出: n_picks, n_hits, hit_rate, mean_change, median_change
寫入 data/combo_backtest.json
"""
import json, sys, os, gzip
from pathlib import Path
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipelines.crawler_output import decrypt_data
from src.exports.excel_report import (
    _filter_tracked_branches, _compute_consensus_count,
)
from src.analyzers.signal_engine import infer_market_direction

password = os.environ.get('CHIP_RADAR_PASSWORD', '')
if not password:
    print("❌ CHIP_RADAR_PASSWORD 未設"); sys.exit(1)

# Load stock_history + temp_history
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

# 組合定義 (filter functions take pick dict + q5_direction)
# v3.71.0: 加 8 個 price-based filter 探索 baseline 提升空間
#   pick dict 加 today_chg / chg_3d / chg_5d / pct_from_high20 / pct_from_low20
COMBOS = {
    'baseline': {
        'desc': '全部共識股 (對照)',
        'filter': lambda p, q5: True,
    },
    'q5_bull': {
        'desc': '共識 ∩ Q5 偏多',
        'filter': lambda p, q5: q5 == '偏多',
    },
    'q5_bear': {
        'desc': '共識 ∩ Q5 偏空',
        'filter': lambda p, q5: q5 == '偏空',
    },
    'high_conv': {
        'desc': '共識 ∩ 領頭佔比 <50% (真共識)',
        'filter': lambda p, q5: p['leader_pct'] < 0.5,
    },
    'extra_breadth': {
        'desc': '共識 ∩ 大戶數 ≥12',
        'filter': lambda p, q5: p['master_count'] >= 12,
    },
    'combo_AAA': {
        'desc': '共識 ∩ Q5 偏多 ∩ 真共識',
        'filter': lambda p, q5: q5 == '偏多' and p['leader_pct'] < 0.5,
    },
    # v3.71.0 — Price-based filters (single)
    'ex_chase': {
        'desc': '排除追高 (今日漲 ≤+3%)',
        'filter': lambda p, q5: (p.get('today_chg') or 0) <= 3.0,
    },
    'ex_falling_knife': {
        'desc': '排除接刀 (今日跌 ≥-3%)',
        'filter': lambda p, q5: (p.get('today_chg') or 0) >= -3.0,
    },
    'mild_uptrend': {
        'desc': '近 3 天累積 0-8% (溫和上行)',
        'filter': lambda p, q5: 0 <= (p.get('chg_3d') or 0) <= 8.0,
    },
    'pullback_buy': {
        'desc': '近 3 天累積 -5 ~ -1% (短線回檔)',
        'filter': lambda p, q5: -5.0 <= (p.get('chg_3d') or 0) <= -1.0,
    },
    'fresh_breakout': {
        'desc': '今日 close 距 20d high 5% 內 + 今日漲 >1%',
        'filter': lambda p, q5: (p.get('pct_from_high20') or -1) >= -0.05 and (p.get('today_chg') or 0) > 1.0,
    },
    'near_low_rebound': {
        'desc': '今日 close 距 20d low 5% 內 + 今日漲 >0',
        'filter': lambda p, q5: (p.get('pct_from_low20') or 1) <= 0.05 and (p.get('today_chg') or 0) > 0,
    },
    # v3.71.0 — Combo filters (疊加 q5_bull)
    'q5_bull_ex_chase': {
        'desc': 'Q5 偏多 ∩ 排除追高',
        'filter': lambda p, q5: q5 == '偏多' and (p.get('today_chg') or 0) <= 3.0,
    },
    'q5_bull_mild_up': {
        'desc': 'Q5 偏多 ∩ 近 3 天溫和上行',
        'filter': lambda p, q5: q5 == '偏多' and 0 <= (p.get('chg_3d') or 0) <= 8.0,
    },
}

# Accumulator: {combo_name: list of next_day_changes}
combo_changes = {k: [] for k in COMBOS}
combo_q5_days = {k: set() for k in COMBOS}   # 唯一 day 統計

per_day_log = []

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

    # Compute consensus with richer metadata
    filtered = _filter_tracked_branches(branches)
    consensus = _compute_consensus_count(filtered)
    if not consensus: continue

    # 重建 raw branches per consensus stock (因為 _compute_consensus_count 不暴露)
    stock_branches = {}   # {code: [{master, net_amt}]}
    for b in filtered:
        m = b.get('master')
        if not m: continue
        for s in (b.get('buys') or []) + (b.get('sells') or []):
            code = s.get('code')
            if not code or code.startswith('00'): continue
            net = (s.get('buy_amt') or 0) - (s.get('sell_amt') or 0)
            if net <= 0: continue
            stock_branches.setdefault(code, []).append({'master': m, 'net_amt': net})

    # v3.71.0: pre-compute today/3d/5d/20d 價格特徵 (給 price-based filter 用)
    # 找到 date 在 sh_dates 中的 index, 拿 N 天前的 close
    def _price_features(code, today_idx):
        s_data = sh_stocks.get(code, {}).get('daily', {})
        today = s_data.get(sh_dates[today_idx], {})
        today_close = today.get('close')
        today_chg = today.get('change_pct')
        if today_close is None:
            return {}
        def _close_at(k):
            if today_idx - k < 0: return None
            return (s_data.get(sh_dates[today_idx - k], {}) or {}).get('close')
        c3 = _close_at(3)
        c5 = _close_at(5)
        chg_3d = ((today_close / c3 - 1) * 100) if c3 else None
        chg_5d = ((today_close / c5 - 1) * 100) if c5 else None
        # 20-day high/low (含今日)
        window_lo = max(0, today_idx - 19)
        closes_20 = [(s_data.get(sh_dates[i], {}) or {}).get('close')
                     for i in range(window_lo, today_idx + 1)]
        closes_20 = [c for c in closes_20 if c is not None]
        high20 = max(closes_20) if closes_20 else None
        low20 = min(closes_20) if closes_20 else None
        pct_from_high = (today_close / high20 - 1) if high20 else None
        pct_from_low = (today_close / low20 - 1) if low20 else None
        return {
            'today_chg': today_chg,
            'chg_3d': chg_3d,
            'chg_5d': chg_5d,
            'pct_from_high20': pct_from_high,
            'pct_from_low20': pct_from_low,
        }

    # Enrich consensus with leader_pct + price features
    enriched = []
    today_idx = idx
    for c in consensus:
        brs = stock_branches.get(c['code'], [])
        master_total = {}
        for br in brs:
            master_total[br['master']] = master_total.get(br['master'], 0) + br['net_amt']
        leader_amt = max(master_total.values()) if master_total else 0
        total = c['total_net_amt']
        leader_pct = (leader_amt / total) if total > 0 else 0
        price_feats = _price_features(c['code'], today_idx)
        enriched.append({
            'code': c['code'],
            'name': c['name'],
            'master_count': c['master_count'],
            'branch_count': c['branch_count'],
            'total_net_amt': total,
            'leader_pct': leader_pct,
            **price_feats,
        })

    # Q5 direction on this date
    th_entry = th_by_date.get(date)
    q5_dir = None
    if th_entry:
        try:
            md = infer_market_direction(th_entry.get('signals') or [])
            q5_dir = md.get('direction')
        except Exception:
            pass

    # For each pick, tally per combo
    picks_with_change = 0
    for pick in enriched:
        s_data = sh_stocks.get(pick['code'], {})
        nd = s_data.get('daily', {}).get(next_date, {})
        nxt_close = nd.get('close')
        nxt_chg = nd.get('change_pct')
        # v3.67.3 stale guard: next_close=None → skip
        if nxt_chg is None or nxt_close is None: continue
        picks_with_change += 1
        for combo_name, combo_def in COMBOS.items():
            if combo_def['filter'](pick, q5_dir):
                combo_changes[combo_name].append(nxt_chg)
                combo_q5_days[combo_name].add(date)

    per_day_log.append((date, next_date, len(enriched), picks_with_change, q5_dir))
    print(f"  {date} → {next_date}: {len(enriched):2d} 共識 ({picks_with_change} 有隔日) Q5={q5_dir}")

# Summary
print()
print('=' * 70)
print('組合表現 Summary (overall)')
print('=' * 70)
print(f"{'Combo':<25} {'n':>4} {'hit':>4} {'hit%':>6} {'mean%':>7} {'median%':>8} {'days':>5}")
summary = {}
for combo_name in COMBOS:
    changes = combo_changes[combo_name]
    days = len(combo_q5_days[combo_name])
    n = len(changes)
    if n == 0:
        summary[combo_name] = {
            'n': 0, 'hits': 0, 'hit_rate': 0,
            'mean_change': 0, 'median_change': 0,
            'days': days,
            'desc': COMBOS[combo_name]['desc'],
        }
        print(f"  {combo_name:<25} {n:>4} {'-':>4} {'-':>6} {'-':>7} {'-':>8} {days:>5}")
        continue
    hits = sum(1 for c in changes if c > 0)
    hit_rate = hits / n
    mean_chg = sum(changes) / n
    sorted_c = sorted(changes)
    median_chg = sorted_c[n // 2]
    summary[combo_name] = {
        'n': n, 'hits': hits, 'hit_rate': hit_rate,
        'mean_change': mean_chg, 'median_change': median_chg,
        'days': days,
        'desc': COMBOS[combo_name]['desc'],
    }
    print(f"  {combo_name:<25} {n:>4} {hits:>4} {hit_rate*100:>5.1f}% {mean_chg:>+6.2f}% {median_chg:>+7.2f}% {days:>5}")

# 找 best combo (hit > 60%)
print()
print('=== Best combo (hit ≥ 60%) ===')
best = [(k, v) for k, v in summary.items() if v['hit_rate'] >= 0.60 and v['n'] >= 10]
best.sort(key=lambda x: -x[1]['hit_rate'])
if best:
    for k, v in best:
        print(f"  ⭐ {k}: hit {v['hit_rate']*100:.1f}% (n={v['n']}) mean {v['mean_change']:+.2f}% — {v['desc']}")
else:
    print(f"  ⚠️ 無組合 hit ≥ 60%")

out = {
    'summary': summary,
    'best': [k for k, _ in best],
    'updated_at': datetime.now().isoformat(),
    'window_days': len(per_day_log),
}
out_path = ROOT / 'data' / 'combo_backtest.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\n✅ 寫入 {out_path}")
