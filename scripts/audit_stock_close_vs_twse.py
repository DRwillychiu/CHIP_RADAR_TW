"""v3.70.5 個股 close 抽樣 vs TWSE 官方 API.

抽樣個股 + 最近 7 個交易日 close, 對 TWSE STOCK_DAY API 驗證:
  - 差異 > 1% → 嚴重錯誤 (數字級錯誤)
  - 差異 > 0.05% → 警告 (rounding 差異)

通過 → 證明 stock_history.json close 與 TWSE 一致.
"""
import json, sys, time
import requests
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]

with open(ROOT / 'data' / 'stock_history.json', 'r', encoding='utf-8') as f:
    sh = json.load(f)
sh_stocks = sh['stocks']
sh_dates = sh['dates']

# 抽樣 8 個常見大型股 (TWSE 100% 涵蓋)
samples = [
    ('2330', '台積電'),
    ('2317', '鴻海'),
    ('2308', '台達電'),
    ('2454', '聯發科'),
    ('2603', '長榮'),
    ('2882', '國泰金'),
    ('1301', '台塑'),
    ('1216', '統一'),
]

# 最近 7 個交易日 (從 sh_dates 末端取)
recent_dates = sh_dates[-7:]
print(f"Checking {len(samples)} stocks x {len(recent_dates)} days = {len(samples)*len(recent_dates)} cells")
print(f"Recent dates: {recent_dates}")
print()

errors = []
warnings = []
ok_count = 0

for code, name in samples:
    print(f"  {name}({code}):")
    # 1 API call per stock gets the whole month
    # Use the month of the FIRST recent date
    first_date = recent_dates[0]
    month_str = first_date[:6] + '01'
    url = (f'https://www.twse.com.tw/rwd/zh/afterTrading/'
           f'STOCK_DAY?date={month_str}&stockNo={code}&response=json')
    try:
        r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        data = r.json()
        if data.get('stat') != 'OK':
            print(f"    ! TWSE returned: {data.get('stat')}")
            continue
        # Build {YYYYMMDD: close} from TWSE response
        twse_closes = {}
        for row in data.get('data', []):
            roc_date = row[0]
            # ROC date like "115/06/22" → 2026/06/22
            y, m, d = roc_date.split('/')
            yyyymmdd = f'{int(y)+1911}{m}{d}'
            try:
                close_str = row[6].replace(',', '')
                twse_closes[yyyymmdd] = float(close_str)
            except (ValueError, IndexError):
                pass
        # Compare
        for d in recent_dates:
            twse_close = twse_closes.get(d)
            my_close = sh_stocks.get(code, {}).get('daily', {}).get(d, {}).get('close')
            if twse_close is None:
                # date not in TWSE month range — likely needs different month
                # Try second month if needed (already fetched for that month from main page)
                month_2 = d[:6] + '01'
                if month_2 != month_str:
                    url2 = (f'https://www.twse.com.tw/rwd/zh/afterTrading/'
                           f'STOCK_DAY?date={month_2}&stockNo={code}&response=json')
                    r2 = requests.get(url2, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
                    data2 = r2.json()
                    for row in data2.get('data', []):
                        roc_date2 = row[0]
                        y2, m2, dd2 = roc_date2.split('/')
                        yyyymmdd2 = f'{int(y2)+1911}{m2}{dd2}'
                        if yyyymmdd2 == d:
                            try:
                                twse_close = float(row[6].replace(',', ''))
                                break
                            except: pass
                    time.sleep(1)
            if twse_close is None:
                print(f"    {d}: (TWSE no data)")
                continue
            if my_close is None:
                print(f"    {d}: (我方 no close), TWSE={twse_close}")
                errors.append((code, name, d, twse_close, my_close,
                              'my close missing'))
                continue
            diff_pct = abs(my_close - twse_close) / max(abs(twse_close), 0.01) * 100
            status = '✓' if diff_pct < 0.05 else ('⚠️' if diff_pct < 1.0 else '✗')
            if diff_pct >= 1.0:
                errors.append((code, name, d, twse_close, my_close,
                              f'diff {diff_pct:.2f}%'))
            elif diff_pct >= 0.05:
                warnings.append((code, name, d, twse_close, my_close,
                               f'diff {diff_pct:.2f}%'))
            else:
                ok_count += 1
            print(f"    {d}: my={my_close} TWSE={twse_close} {status} (diff {diff_pct:.3f}%)")
        time.sleep(2)   # 防 rate limit
    except Exception as e:
        print(f"    ! exception: {e}")

print()
print("=" * 70)
print(f"OK: {ok_count}")
print(f"Warnings: {len(warnings)}")
if warnings:
    for w in warnings: print(f"  {w}")
print(f"Errors: {len(errors)}")
if errors:
    for e in errors: print(f"  {e}")
print()
if errors:
    print("❌ FAIL: 個股 close 與 TWSE 不一致")
    sys.exit(1)
else:
    print("✅ PASS: 個股 close 與 TWSE 一致 (差異 < 1%)")
