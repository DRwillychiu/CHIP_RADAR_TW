"""v3.71.4: TAIEX 歷史汙染 backfill.

修補 v3.43.0 已修「兜底重複日 bug」殘留的 6/2-6/8 歷史汙染:
  6/2, 6/3, 6/4, 6/5, 6/8 共 5 天 stock_history.market[d] 全是
  index=45070.94 chg=0.0 (5/29 收盤值反覆寫入)

從 TWSE MI_5MINS_HIST endpoint 抓歷史月份大盤 OHLC, parse close + 跟前一日算 chg,
更新 data/stock_history.json['market'][d] + 同步 temp_history.next_day_change_pct.

執行: python scripts/backfill_taiex_history.py
"""
import json, sys, requests, time
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
SH_PATH = ROOT / 'data' / 'stock_history.json'
TH_PATH = ROOT / 'data' / 'temp_history.json'

# TWSE 歷史單日大盤指數: 給定 date 回該日所有類股指數 (含 TAIEX 發行量加權股價指數)
TWSE_HIST_URL = 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&date={date}&type=IND'


def fetch_day_taiex(yyyymmdd: str):
    """抓單日 TAIEX close + chg。
    Returns: {'close': float, 'change_pct': float, 'change_pts': float} 或 None
    """
    url = TWSE_HIST_URL.format(date=yyyymmdd)
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        data = json.loads(r.text)
    except Exception as e:
        print(f"    ✗ {yyyymmdd}: {e}")
        return None

    for tbl in data.get('tables', []):
        for row in tbl.get('data', []):
            if not row or len(row) < 5: continue
            name = row[0]
            if '發行量加權' not in name: continue
            close_str = row[1].replace(',', '')
            pct_str = row[4].replace(',', '')
            try:
                close = float(close_str)
                # TWSE row[4] 本身已含 sign (e.g. '-3.48' / '+1.98'), 直接用
                pct = float(pct_str)
                return {'close': close, 'change_pct': round(pct, 2)}
            except ValueError:
                continue
    print(f"    ⚠️ {yyyymmdd}: 找不到「發行量加權股價指數」row")
    return None


def main():
    sh = json.loads(SH_PATH.read_text(encoding='utf-8'))
    market = sh.get('market', {})

    # 找汙染 entry: chg=0 但 index 跟前一日相同
    sorted_dates = sorted(market.keys())
    contaminated = []
    for i, d in enumerate(sorted_dates):
        if i == 0: continue
        m = market[d]
        prev_m = market[sorted_dates[i-1]]
        if (m.get('change_pct') == 0.0 and
            m.get('index') == prev_m.get('index')):
            contaminated.append(d)
    print(f"\n發現 {len(contaminated)} 個汙染日: {contaminated}")
    if not contaminated:
        print("  ✓ 無汙染, 不需 backfill")
        return

    # 一個個抓 (TWSE rate limit 友善)
    print(f"\n抓 {len(contaminated)} 個歷史日 TAIEX:")
    fixed = 0
    for d in contaminated:
        twse = fetch_day_taiex(d)
        time.sleep(1.5)   # 禮貌 rate limit
        if not twse:
            print(f"  ⚠️ {d}: 跳過")
            continue
        new_close = twse['close']
        new_chg = twse['change_pct']    # TWSE 提供 official chg
        old_idx = market[d].get('index')
        old_chg = market[d].get('change_pct')
        market[d] = {
            'index': new_close,
            'change_pct': new_chg,
            'quote_date': '',
            'change_pct_source': 'backfill_v3.71.4_twse_mi_index_hist',
        }
        print(f"  ✓ {d}: {old_idx}({old_chg:+.2f}%) → {new_close}({new_chg:+.2f}%)")
        fixed += 1

    if fixed == 0:
        print("\n⚠️ 0 個修補, abort")
        return

    # 寫回 stock_history
    print(f"\n寫回 stock_history.json...")
    tmp = SH_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(sh, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(SH_PATH)
    print(f"  ✓ {fixed} entries 更新")

    # 同步 temp_history.next_day_change_pct
    if TH_PATH.exists():
        th = json.loads(TH_PATH.read_text(encoding='utf-8'))
        history = th.get('history', []) or []
        # 排序確認
        th_dates = sorted([h['date'] for h in history if h.get('date')])
        idx_map = {h['date']: h for h in history if h.get('date')}
        updated = 0
        for d in th_dates:
            h = idx_map[d]
            # 找 stock_history.market 內 d 之後最近的交易日
            next_dates = [dd for dd in sorted_dates if dd > d]
            if not next_dates: continue
            next_d = next_dates[0]
            next_chg = market[next_d].get('change_pct')
            if next_chg is not None and h.get('next_day_change_pct') != next_chg:
                old = h.get('next_day_change_pct')
                h['next_day_change_pct'] = next_chg
                # 也填 next_day_close (給 stale guard 用)
                h['next_day_close'] = market[next_d].get('index')
                h['next_date'] = next_d
                updated += 1
                print(f"  temp_history[{d}].next_day_change_pct: {old} → {next_chg}")
        if updated > 0:
            tmp = TH_PATH.with_suffix('.tmp')
            tmp.write_text(json.dumps(th, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(TH_PATH)
            print(f"  ✓ temp_history.next_day_change_pct 修 {updated} 筆")

    print(f"\n✅ backfill 完成. 建議下一步:")
    print(f"  1. 重跑 bootstrap_phase32_e_anomaly.py 更新真實 baseline / quad hit rate")
    print(f"  2. 重跑 bootstrap_combo_backtest.py 更新 combo backtest")


if __name__ == '__main__':
    main()
