"""v3.70.0 Phase 3.2: quad 命中股實戰 hit log.

每日 daily-full 跑完後自動更新.

寫入 data/quad_hit_log.json:
  {
    "trigger_days": [
      {
        "date": "20260520", "next_date": "20260521",
        "q5_direction": "偏多",
        "q5_confidence": 65.3,                # v3.70.3: 歸因用
        "taifex_change": -0.39,               # v3.70.3: 隔日 TAIEX 漲跌
        "vol_spike_masters": ["民哥"],
        "quad_picks": [
          {"code": "2330", "name": "台積電", "next_change_pct": 9.91, "hit": true,
           "matched_masters": ["民哥"],
           "leader_pct": 0.32,                 # v3.70.3: 領頭佔比 (>=0.5 = 假共識)
           "excess_return": 10.30,             # v3.70.3: 個股 - TAIEX (alpha)
           "failure_reasons": []               # v3.70.3: miss 才有
          },
          ...
        ],
        "n": 5, "hits": 5, "hit_rate": 1.0, "mean_change": 4.5
      },
      ...
    ],
    "rolling_30d": {"trigger_days": N, "n": X, "hits": Y, "hit_rate": Y/X, "mean_change": Z},
    "rolling_all": {"trigger_days": N, "n": X, "hits": Y, "hit_rate": Y/X, "mean_change": Z},
    "vs_expected": {"expected_hit_rate": 0.789, "actual_hit_rate": Y/X, "delta_pp": ...},
    "updated_at": "..."
  }

用途: 月底復盤實際 vs 預期 78.9%, Excel sub-banner 顯示滾動 30 天命中率.
"""
import json, sys, os, gzip, statistics
from pathlib import Path
from datetime import datetime
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipelines.crawler_output import decrypt_data
from src.exports.excel_report import _filter_tracked_branches, _compute_consensus_count
from src.analyzers.signal_engine import infer_market_direction

ANOMALY_SIGMA = 2.0
MIN_HISTORY_DAYS = 5
# v3.70.4: 78.9% → 85.7% (stale guard 2 移除 3 個 stale picks 後 — 真實 alpha)
EXPECTED_HIT_RATE = 0.857

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


# Load all daily files chronologically
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

# Per-master per-day total_buy (for vol_spike z-score)
master_total = defaultdict(dict)
for date, branches in all_data.items():
    for br in branches:
        m = br.get('master')
        co = br.get('co_masters') or []
        all_m = ([m] if m else []) + list(co)
        for mm in all_m:
            if not mm: continue
            for s in (br.get('buys') or []):
                amt = s.get('buy_amt', 0) or 0
                code = s.get('code')
                if amt > 0 and code and not code.startswith('00'):
                    master_total[mm][date] = master_total[mm].get(date, 0) + amt

sorted_dates = sorted(all_data.keys())


def vol_spike_masters(date_idx):
    if date_idx < MIN_HISTORY_DAYS: return set()
    date = sorted_dates[date_idx]
    past_dates = sorted_dates[:date_idx]
    spike = set()
    for m, by_date in master_total.items():
        today = by_date.get(date, 0)
        if today == 0: continue
        past_amts = [by_date[d] for d in past_dates if d in by_date and by_date[d] > 0]
        if len(past_amts) < MIN_HISTORY_DAYS: continue
        avg = statistics.mean(past_amts)
        std = statistics.stdev(past_amts) if len(past_amts) > 1 else avg * 0.3
        if std == 0: std = avg * 0.1
        z = (today - avg) / std
        if z > ANOMALY_SIGMA:
            spike.add(m)
    return spike


# Process each day, identify quad triggers
trigger_days = []

for date_idx, date in enumerate(sorted_dates):
    if date not in sh_dates: continue
    sh_idx = sh_dates.index(date)
    if sh_idx + 1 >= len(sh_dates): continue   # no next_date (today is last day)
    next_date = sh_dates[sh_idx + 1]

    # Check Q5 direction
    th_entry = th_by_date.get(date)
    q5_dir = None
    if th_entry:
        try:
            md = infer_market_direction(th_entry.get('signals') or [])
            q5_dir = md.get('direction')
        except Exception: pass

    if q5_dir != '偏多': continue

    # Check vol_spike
    vs = vol_spike_masters(date_idx)
    if not vs: continue

    # v3.70.3: Q5 confidence + TAIEX next-day change (歸因用)
    q5_confidence = 0.0
    try:
        md = infer_market_direction(th_entry.get('signals') or [])
        q5_confidence = md.get('confidence_pct') or 0.0
    except Exception:
        pass
    # TAIEX next-day from temp_history (taiex_index)
    taifex_change = None
    nxt_th = th_by_date.get(next_date)
    if nxt_th and th_entry and th_entry.get('taiex_index') and nxt_th.get('taiex_index'):
        t0 = th_entry['taiex_index']
        t1 = nxt_th['taiex_index']
        if t0 and t1 and t0 > 0 and t0 != t1:   # 防 stale
            taifex_change = round((t1 - t0) / t0 * 100, 2)

    # We have a quad trigger day. Compute consensus + quad picks
    branches = all_data[date]
    consensus = _compute_consensus_count(branches)
    if not consensus: continue

    # Build stock -> contributing masters + per-master amount (for leader_pct)
    stock_masters = {}
    stock_master_amt = {}   # {code: {master: net_amt}}
    for b in branches:
        m = b.get('master')
        if not m: continue
        for s in (b.get('buys') or []):
            code = s.get('code')
            if not code or code.startswith('00'): continue
            amt = s.get('buy_amt', 0) or 0
            if amt <= 0: continue
            stock_masters.setdefault(code, set()).add(m)
            sm = stock_master_amt.setdefault(code, {})
            sm[m] = sm.get(m, 0) + amt

    # Identify quad picks (consensus stocks with ≥1 vol_spike master)
    quad_picks = []
    for c in consensus:
        code = c['code']
        cmasters = stock_masters.get(code, set())
        matched = cmasters & vs
        if not matched: continue
        # Resolve hit (need next_date close in stock_history)
        nd = sh_stocks.get(code, {}).get('daily', {}).get(next_date, {})
        nxt_close = nd.get('close')
        nxt_chg = nd.get('change_pct')
        if nxt_chg is None or nxt_close is None: continue   # stale guard
        # v3.70.4 stale guard 2: TWSE API stale (next_close == today_close, change=0)
        today_close = sh_stocks.get(code, {}).get('daily', {}).get(date, {}).get('close')
        if (abs(nxt_chg) < 0.005 and today_close is not None
                and abs(nxt_close - today_close) < 0.001):
            continue   # stale: skip from hit log entirely
        # v3.70.3 歸因: leader_pct + excess_return + failure_reasons
        master_amts = stock_master_amt.get(code, {})
        total_amt = sum(master_amts.values()) or 1
        leader_amt = max(master_amts.values()) if master_amts else 0
        leader_pct = round(leader_amt / total_amt, 3)
        excess_return = round(nxt_chg - taifex_change, 2) if taifex_change is not None else None
        # 失效歸因 (miss 才填) — v3.70.3 嚴格分類
        failure_reasons = []
        if nxt_chg <= 0:
            # 1. 資料異常 — next_close 與 today_close 完全相同 (極可能停牌/資料 stale)
            if abs(nxt_chg) < 0.005:   # ~0.0%
                failure_reasons.append('資料異常 (next_close 未變動, 可能停牌/未交易)')
            # 2. TAIEX 整盤跌 (≥ -0.5% 大盤跌)
            if taifex_change is not None and taifex_change <= -0.5:
                failure_reasons.append('TAIEX 整盤跌')
            # 3. 假共識 (領頭佔比 ≥50%, 訊號被稀釋)
            if leader_pct >= 0.5:
                failure_reasons.append('假共識 (領頭獨佔 ≥50%)')
            # 4. 個股弱勢 (跑輸大盤 >2pp 顯著)
            if excess_return is not None and excess_return <= -2.0:
                failure_reasons.append('個股弱勢 (跑輸大盤 >2pp)')
            # 5. Q5 borderline (信心 <55% 預測弱)
            if q5_confidence > 0 and q5_confidence < 55:
                failure_reasons.append(f'Q5 borderline ({q5_confidence:.0f}%)')
            # 6. TAIEX 資料缺 (歸因不全)
            if taifex_change is None and not failure_reasons:
                failure_reasons.append('TAIEX 資料缺, 歸因不全')
            # 7. 其他 (沒有明確原因 → alpha noise)
            if not failure_reasons:
                failure_reasons.append('alpha noise (個股無系統性原因)')
        quad_picks.append({
            'code': code,
            'name': c['name'],
            'matched_masters': sorted(matched),
            'next_change_pct': round(nxt_chg, 2),
            'hit': nxt_chg > 0,
            'leader_pct': leader_pct,
            'excess_return': excess_return,
            'failure_reasons': failure_reasons,
        })

    if not quad_picks: continue

    hits = sum(1 for p in quad_picks if p['hit'])
    n = len(quad_picks)
    mean_chg = sum(p['next_change_pct'] for p in quad_picks) / n
    trigger_days.append({
        'date': date,
        'next_date': next_date,
        'q5_direction': q5_dir,
        'q5_confidence': round(q5_confidence, 1),
        'taifex_change': taifex_change,
        'vol_spike_masters': sorted(vs),
        'quad_picks': quad_picks,
        'n': n, 'hits': hits,
        'hit_rate': round(hits / n, 4),
        'mean_change': round(mean_chg, 2),
    })

print(f"  found {len(trigger_days)} trigger days")

# Aggregate rolling stats
def aggregate(days_list):
    all_picks = [p for d in days_list for p in d['quad_picks']]
    n = len(all_picks)
    if n == 0:
        return {'trigger_days': len(days_list), 'n': 0, 'hits': 0,
                'hit_rate': 0, 'mean_change': 0}
    hits = sum(1 for p in all_picks if p['hit'])
    mean_chg = sum(p['next_change_pct'] for p in all_picks) / n
    return {
        'trigger_days': len(days_list),
        'n': n, 'hits': hits,
        'hit_rate': round(hits / n, 4),
        'mean_change': round(mean_chg, 2),
    }

# Last 30 calendar days (filter by date string)
from datetime import datetime as _dt, timedelta as _td
if sorted_dates:
    last_dt = _dt.strptime(sorted_dates[-1], '%Y%m%d')
    cutoff_30d = (last_dt - _td(days=30)).strftime('%Y%m%d')
    days_30d = [d for d in trigger_days if d['date'] >= cutoff_30d]
else:
    days_30d = trigger_days

rolling_30d = aggregate(days_30d)
rolling_all = aggregate(trigger_days)

# vs expected
actual_hr = rolling_all['hit_rate']
delta_pp = (actual_hr - EXPECTED_HIT_RATE) * 100

out = {
    'trigger_days': trigger_days,
    'rolling_30d': rolling_30d,
    'rolling_all': rolling_all,
    'vs_expected': {
        'expected_hit_rate': EXPECTED_HIT_RATE,
        'actual_hit_rate': actual_hr,
        'delta_pp': round(delta_pp, 1),
    },
    'updated_at': datetime.now().isoformat(),
}

out_path = ROOT / 'data' / 'quad_hit_log.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print()
print(f"=== Quad Hit Log Summary ===")
print(f"  Trigger days (all): {rolling_all['trigger_days']}")
print(f"  Total quad picks  : {rolling_all['n']}")
print(f"  Hits              : {rolling_all['hits']}")
print(f"  Actual hit rate   : {rolling_all['hit_rate']*100:.1f}%")
print(f"  Expected (Phase 3.2): {EXPECTED_HIT_RATE*100:.1f}%")
print(f"  Delta             : {delta_pp:+.1f}pp")
print(f"  Mean change       : {rolling_all['mean_change']:+.2f}%")
print()
print(f"=== Rolling 30d ===")
print(f"  Trigger days: {rolling_30d['trigger_days']}")
print(f"  Quad picks  : {rolling_30d['n']}")
print(f"  Hits        : {rolling_30d['hits']}")
print(f"  Hit rate    : {rolling_30d['hit_rate']*100:.1f}%")
print()
print(f"Wrote {out_path}")
