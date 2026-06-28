"""v3.71.18 L1 + L5 + L6: pinned master 多維度 alpha backtest.

對 PINNED_MASTERS 內每位 master, 從歷史 daily JSON + stock_history 算:
  L1 - 全部 picks alpha:
       過去 N 天每筆 master 買進 → t+1/t+3/t+5 hit + mean
  L5 - 新標的 alpha:
       master 「過去從未買過」 的股 → first day t+1/t+3/t+5 表現
  L6 - 連續囤貨 alpha:
       master 連續加碼 ≥ N 天 → 後續 t+N 表現

⚠️ 此 script 需要 CHIP_RADAR_PASSWORD env (解密 daily JSON).
若無, fallback 純讀 quad_hit_log + master_profiles 簡化版.

輸出: data/pinned_master_stats.json
{
  'updated_at': ISO,
  'pinned_masters': {
    'master_name': {
      'all_picks': {n, hit_1d, hit_3d, hit_5d, mean_1d, mean_3d, mean_5d},
      'new_stocks': {n, hit_1d, ...},
      'accumulation': {n, hit_1d, ...},
    }
  }
}
"""
import json, sys, os, gzip
from collections import defaultdict
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.exports.excel_report import PINNED_MASTERS

# Load stock_history (open, no password)
sh = json.loads((ROOT / 'data' / 'stock_history.json').read_text(encoding='utf-8'))
sh_stocks = sh.get('stocks', {})
sh_dates = sh.get('dates', [])

# Decrypt only if password available
password = os.environ.get('CHIP_RADAR_PASSWORD', '')
if password:
    from src.pipelines.crawler_output import decrypt_data
    print(f"=== with password: full backtest ===\n")
else:
    print(f"=== no password: simplified (only stock_history-based) ===\n")

ACC_MIN_DAYS = 3   # 連續加碼最少天數


def _read_daily(p):
    if not password: return None
    try:
        if str(p).endswith('.gz'):
            with gzip.open(p, 'rt', encoding='utf-8') as f: enc = json.load(f)
        else:
            with open(p, 'r', encoding='utf-8') as f: enc = json.load(f)
        plain = decrypt_data(enc['data'], password, iterations=enc.get('iterations'))
        return json.loads(plain)
    except Exception:
        return None


def _stock_returns_at(code, today_date):
    """算 t+1 / t+3 / t+5 return."""
    s_data = sh_stocks.get(code, {}).get('daily', {})
    today_close = (s_data.get(today_date) or {}).get('close')
    if not today_close: return {}
    if today_date not in sh_dates: return {}
    idx = sh_dates.index(today_date)
    out = {}
    for k in [1, 3, 5]:
        if idx + k >= len(sh_dates): out[f'r_{k}d'] = None; continue
        future_d = sh_dates[idx + k]
        fc = (s_data.get(future_d) or {}).get('close')
        if fc:
            out[f'r_{k}d'] = (fc / today_close - 1) * 100
        else:
            out[f'r_{k}d'] = None
    return out


def _summarize(picks_with_returns):
    """對 list of {r_1d, r_3d, r_5d} 算 hit rate + mean."""
    out = {'n': len(picks_with_returns)}
    for k in [1, 3, 5]:
        vals = [p[f'r_{k}d'] for p in picks_with_returns if p.get(f'r_{k}d') is not None]
        if not vals:
            out[f'hit_{k}d'] = None; out[f'mean_{k}d'] = None; continue
        hits = sum(1 for v in vals if v > 0)
        out[f'hit_{k}d'] = round(hits / len(vals), 3)
        out[f'mean_{k}d'] = round(sum(vals) / len(vals), 2)
        out[f'n_{k}d'] = len(vals)
    return out


# 找 daily files
daily_files = sorted(
    list((ROOT / 'data').glob('[0-9]' * 8 + '.json')) +
    list((ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json')) +
    list((ROOT / 'data' / 'archive').glob('[0-9]' * 8 + '.json.gz')),
    key=lambda p: p.name[:8]
)

# Per-master per-date buys 預 build (用 password)
master_daily_buys = defaultdict(lambda: defaultdict(set))   # m -> date -> codes set
master_all_picks_with_ret = defaultdict(list)
for p in daily_files:
    date = p.name[:8]
    data = _read_daily(p)
    if not data: continue
    for br in data.get('branches', []):
        m = br.get('master')
        if not m or m not in PINNED_MASTERS: continue
        for s in (br.get('buys') or []):
            code = s.get('code')
            if not code or code.startswith('00'): continue
            master_daily_buys[m][date].add(code)
            # 收集 picks + return
            rets = _stock_returns_at(code, date)
            if rets.get('r_1d') is not None:
                master_all_picks_with_ret[m].append({
                    'date': date, 'code': code, **rets,
                })

# Per-master 三維度 stats
out = {'pinned_masters': {}, 'updated_at': None}
import datetime
out['updated_at'] = datetime.datetime.now().isoformat()

for m in sorted(PINNED_MASTERS):
    print(f"\n=== {m} ===")
    if not password:
        print(f"  ⚠️ skip (需 password 解密 daily JSON)")
        out['pinned_masters'][m] = {'status': 'need_password'}
        continue

    # L1 all picks
    all_picks = master_all_picks_with_ret[m]
    all_stats = _summarize(all_picks)
    print(f"  L1 全部 picks: n={all_stats['n']}, "
          f"hit_1d={all_stats.get('hit_1d')}, mean_1d={all_stats.get('mean_1d')}, "
          f"hit_3d={all_stats.get('hit_3d')}, mean_3d={all_stats.get('mean_3d')}")

    # L5 new stocks: first time appearing
    daily_by_date = master_daily_buys[m]
    sorted_d = sorted(daily_by_date.keys())
    seen = set()
    new_picks_with_ret = []
    for d in sorted_d:
        codes_today = daily_by_date[d]
        new_today = codes_today - seen
        seen |= codes_today
        for c in new_today:
            rets = _stock_returns_at(c, d)
            if rets.get('r_1d') is not None:
                new_picks_with_ret.append({'date': d, 'code': c, **rets})
    new_stats = _summarize(new_picks_with_ret)
    print(f"  L5 新標的: n={new_stats['n']}, "
          f"hit_1d={new_stats.get('hit_1d')}, mean_1d={new_stats.get('mean_1d')}")

    # L6 accumulation: 連續加碼 ≥3 天的股 → 第 3 天當 entry point
    code_streaks = defaultdict(int)
    acc_picks_with_ret = []
    for d in sorted_d:
        codes_today = daily_by_date[d]
        for c in list(code_streaks.keys()):
            if c not in codes_today:
                code_streaks[c] = 0
        for c in codes_today:
            code_streaks[c] += 1
            if code_streaks[c] == ACC_MIN_DAYS:
                rets = _stock_returns_at(c, d)
                if rets.get('r_1d') is not None:
                    acc_picks_with_ret.append({'date': d, 'code': c, 'streak': ACC_MIN_DAYS, **rets})
    acc_stats = _summarize(acc_picks_with_ret)
    print(f"  L6 連續{ACC_MIN_DAYS}天加碼: n={acc_stats['n']}, "
          f"hit_1d={acc_stats.get('hit_1d')}, mean_1d={acc_stats.get('mean_1d')}, "
          f"hit_5d={acc_stats.get('hit_5d')}, mean_5d={acc_stats.get('mean_5d')}")

    out['pinned_masters'][m] = {
        'status': 'ok',
        'all_picks': all_stats,
        'new_stocks': new_stats,
        'accumulation': acc_stats,
        'accumulation_min_days': ACC_MIN_DAYS,
    }

# Write
op = ROOT / 'data' / 'pinned_master_stats.json'
op.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"\n✅ 寫入 {op}")
