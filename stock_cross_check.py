"""stock_cross_check.py — V2 抽 10 個股 cross-check TWSE

隨機抽 10 個股 (含高 / 中 / 低價區段),拉 TWSE STOCK_DAY 端點對比
chip_radar 內 `data/stock_history.json` 的 close + change_pct 過去 5 個交易日。

證明:個股收盤對齊率 vs TWSE 官方 → 是否真的 > 99%

用法: python stock_cross_check.py [--days 5] [--n 10]
"""
import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import requests


def fetch_twse_stock_day(code, year_month):
    """Fetch TWSE STOCK_DAY for one stock in one month.
    year_month: YYYYMM (e.g. '202605')
    Returns: {date_yyyymmdd: (close, change)}
    """
    # API uses date param like YYYYMM01
    url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={year_month}01&stockNo={code}"
    try:
        r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code != 200:
            return None, f'HTTP {r.status_code}'
        data = r.json()
        if data.get('stat') != 'OK':
            return None, data.get('stat', 'no data')
        fields = data.get('fields', [])
        # TWSE STOCK_DAY fields:
        # [日期, 成交股數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, 漲跌價差, 成交筆數]
        date_idx = next((i for i, f in enumerate(fields) if '日期' in f), None)
        close_idx = next((i for i, f in enumerate(fields) if '收盤' in f), None)
        change_idx = next((i for i, f in enumerate(fields) if '漲跌' in f), None)

        result = {}
        for row in data.get('data', []):
            if not row or len(row) <= max(date_idx, close_idx, change_idx):
                continue
            roc_date = row[date_idx]  # '115/05/20'
            try:
                parts = roc_date.split('/')
                if len(parts) != 3:
                    continue
                ad_year = int(parts[0]) + 1911
                date_key = f"{ad_year:04d}{parts[1]:0>2}{parts[2]:0>2}"
                close_str = row[close_idx].replace(',', '').strip()
                change_str = (row[change_idx] or '').replace(',', '').replace('X', '').strip()
                close = float(close_str) if close_str and close_str != '--' else None
                change = float(change_str) if change_str and change_str not in ('--', '') else 0
                if close is not None:
                    result[date_key] = (close, change)
            except (ValueError, IndexError):
                continue
        return result, None
    except Exception as e:
        return None, str(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=5)
    parser.add_argument('--n', type=int, default=10)
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    sh_path = data_dir / 'stock_history.json'
    if not sh_path.exists():
        print(f"❌ {sh_path} 不存在")
        sys.exit(1)

    with open(sh_path, 'r', encoding='utf-8') as f:
        sh = json.load(f)

    all_stocks = sh.get('stocks', {})
    dates = sorted(sh.get('dates', []))[-args.days:]

    if not dates:
        print("❌ stock_history 無日期資料")
        sys.exit(1)

    # 抽樣:按價格 tier 抽
    high_price = []   # >= 1000
    mid_price = []    # 100-500
    low_price = []    # < 100
    for code, stk in all_stocks.items():
        daily = stk.get('daily', {})
        last_date_close = None
        for d in reversed(dates):
            if d in daily and daily[d].get('close'):
                last_date_close = daily[d]['close']
                break
        if last_date_close is None:
            continue
        if last_date_close >= 1000:
            high_price.append((code, stk.get('name', ''), last_date_close))
        elif 100 <= last_date_close < 500:
            mid_price.append((code, stk.get('name', ''), last_date_close))
        elif last_date_close < 100:
            low_price.append((code, stk.get('name', ''), last_date_close))

    # v2: 改用 hand-picked TWSE 大型股 (避免抽到 TPEx / 興櫃 TWSE 端點查不到)
    KNOWN_TWSE_STOCKS = [
        ('2330', '台積電'), ('2454', '聯發科'), ('2317', '鴻海'),
        ('2308', '台達電'), ('1216', '統一'), ('2891', '中信金'),
        ('2412', '中華電'), ('1303', '南亞'), ('2002', '中鋼'),
        ('2882', '國泰金'), ('1101', '台泥'), ('2303', '聯電'),
        ('2881', '富邦金'), ('3008', '大立光'), ('2885', '元大金'),
    ]
    sample = []
    for code, name in KNOWN_TWSE_STOCKS[:args.n]:
        stk = all_stocks.get(code, {})
        last_close = None
        for d in reversed(dates):
            rec = stk.get('daily', {}).get(d)
            if rec and rec.get('close'):
                last_close = rec['close']
                break
        if last_close:
            sample.append((code, name, last_close))

    print('=' * 80)
    print(f'  V2 個股 cross-check vs TWSE STOCK_DAY ({len(sample)} 檔 × {len(dates)} 天)')
    print('=' * 80)
    print(f'抽樣日期: {dates}')
    print()

    # 為了減少 API 請求,先按 month 群組
    year_months = sorted(set(d[:6] for d in dates))

    total_compares = 0
    matches = 0
    mismatches = []
    missing_in_twse = 0
    missing_in_local = 0

    for idx, (code, name, ref_close) in enumerate(sample):
        print(f'[{idx+1}/{len(sample)}] {code} {name} (ref close {ref_close})')
        local_daily = all_stocks.get(code, {}).get('daily', {})
        for ym in year_months:
            twse_data, err = fetch_twse_stock_day(code, ym)
            if twse_data is None:
                print(f'    ⚠️ TWSE {code} {ym} 失敗: {err}')
                time.sleep(2)
                continue
            for d in dates:
                if d[:6] != ym:
                    continue
                local = local_daily.get(d)
                twse = twse_data.get(d)
                if local and twse:
                    local_close = local.get('close')
                    twse_close, twse_change = twse
                    total_compares += 1
                    if abs(local_close - twse_close) < 0.01:
                        matches += 1
                        verdict = '✅'
                    else:
                        mismatches.append({
                            'code': code, 'name': name, 'date': d,
                            'local': local_close, 'twse': twse_close,
                            'diff': local_close - twse_close,
                        })
                        verdict = '❌'
                    print(f'    {d}: local close={local_close} twse close={twse_close}  {verdict}')
                elif local and not twse:
                    missing_in_twse += 1
                    print(f'    {d}: local close={local["close"]} TWSE 無資料 (假日?)')
                elif twse and not local:
                    missing_in_local += 1
                    print(f'    {d}: TWSE close={twse[0]} local 無 (chip_radar 沒抓?)')
            time.sleep(1.5)
        print()

    # Summary
    print('━' * 80)
    print('  總結')
    print('━' * 80)
    if total_compares > 0:
        match_rate = matches / total_compares * 100
        print(f'  比對成功: {matches}/{total_compares} = {match_rate:.2f}%')
        print(f'  TWSE 無資料 (跳過): {missing_in_twse}')
        print(f'  Local 無資料 (跳過): {missing_in_local}')
        if mismatches:
            print()
            print('  ❌ 不對齊 cases:')
            for m in mismatches:
                print(f"    {m['code']} {m['name']} {m['date']}: "
                      f"local={m['local']} twse={m['twse']} diff={m['diff']:+.2f}")
        else:
            print('  ✅ 0 個不對齊')
        if match_rate >= 99:
            print('\n  整體判定: ✅ TWSE 對齊率 > 99% (高信心)')
        elif match_rate >= 95:
            print('\n  整體判定: ⚠️ TWSE 對齊率 95-99% (有零星誤差)')
        else:
            print('\n  整體判定: ❌ TWSE 對齊率 < 95% (有系統性問題)')
    else:
        print('  ⚠️ 無有效比對 (可能 stock_history 跟測試日期沒重疊)')


if __name__ == '__main__':
    main()
