"""insider_cross_check.py — U1 內部人 cross-check vs MOPS 官方

直接呼叫 chip_radar 既有 `insiders.fetch_director_holdings()` 拉 MOPS 同源資料,
印結構化表格供 user 開 chip_radar 網站 內部人 tab 視覺對齊驗證.

驗證邏輯:
  fetch_director_holdings(stock_code, year, month) 從 MOPS ajax_stapap1 拉:
    - 董事長 / 董事 / 監察人 / 總經理 等內部人
    - 目前持股 / 設質股數 / 設質比例
  → 印每檔個股的董監名單 + 設質比例 + 高設質警報數
  → User 開 chip_radar 內部人 tab 對應個股看是否一致

抽樣個股 (台股代表性):
  2330 台積電
  2454 聯發科
  2317 鴻海
  3008 大立光
  2412 中華電
  1216 統一

用法: python insider_cross_check.py [--year 2026] [--month 5]
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from insiders import fetch_director_holdings


SAMPLE_STOCKS = [
    ('2330', '台積電'),
    ('2454', '聯發科'),
    ('2317', '鴻海'),
    ('3008', '大立光'),
    ('2412', '中華電'),
    ('1216', '統一'),
]


def main():
    parser = argparse.ArgumentParser()
    today = date.today()
    parser.add_argument('--year', type=int, default=today.year)
    parser.add_argument('--month', type=int, default=today.month)
    parser.add_argument('--n', type=int, default=len(SAMPLE_STOCKS))
    args = parser.parse_args()

    print('=' * 80)
    print(f'  U1 內部人 cross-check vs MOPS 官方 ({args.year}/{args.month:02d})')
    print('=' * 80)
    print()
    print(f'抽樣: {len(SAMPLE_STOCKS[:args.n])} 個 TWSE 大型股')
    print(f'資料源: MOPS ajax_stapap1 (chip_radar 主流程同源)')
    print()

    summary_rows = []

    for idx, (code, name) in enumerate(SAMPLE_STOCKS[:args.n]):
        print('─' * 80)
        print(f'  [{idx + 1}/{args.n}] {code} {name}')
        print('─' * 80)

        data = fetch_director_holdings(code, args.year, args.month)

        if data is None:
            print(f'  ❌ MOPS 抓取失敗')
            summary_rows.append({
                'code': code, 'name': name, 'status': 'FAIL',
                'directors_count': None, 'total_pledge_ratio': None, 'high_pledge': None,
            })
            continue

        directors = data.get('directors', [])
        total_pledge = data.get('total_pledge_ratio', 0)
        high_pledge = data.get('high_pledge_count', 0)

        print(f'  董監人數: {len(directors)}')
        print(f'  總設質比例: {total_pledge}%')
        print(f'  高設質警報 (>30%): {high_pledge} 人')

        # 印前 5 名董監
        print()
        print(f'  董監清單 (前 {min(5, len(directors))} 位):')
        print(f"    {'職稱':<10} {'姓名':<14} {'目前持股':>14} {'設質':>10} {'設質%':>7}")
        for d in directors[:5]:
            curr = f"{d.get('current_shares', 0):,}"
            pledged = f"{d.get('pledged_shares', 0):,}"
            ratio = f"{d.get('pledge_ratio', 0):.2f}%"
            print(f"    {d.get('title', ''):<10} {d.get('name', ''):<14} {curr:>14} {pledged:>10} {ratio:>7}")

        summary_rows.append({
            'code': code, 'name': name, 'status': 'OK',
            'directors_count': len(directors),
            'total_pledge_ratio': total_pledge,
            'high_pledge': high_pledge,
        })
        print()

    # ── Summary table ──
    print('━' * 80)
    print('  📊 摘要 (請開 chip_radar 內部人 tab 逐項對齊)')
    print('━' * 80)
    print(f"  {'代號':<6} {'名稱':<10} {'狀態':<6} {'董監人數':>6} {'總設質%':>10} {'高設質':>6}")
    for r in summary_rows:
        s = r['status']
        dc = r['directors_count'] if r['directors_count'] is not None else '-'
        tp = f"{r['total_pledge_ratio']:.2f}%" if r['total_pledge_ratio'] is not None else '-'
        hp = r['high_pledge'] if r['high_pledge'] is not None else '-'
        print(f"  {r['code']:<6} {r['name']:<10} {s:<6} {dc:>6} {tp:>10} {hp:>6}")

    print()
    print('━' * 80)
    print('  📝 視覺驗證流程')
    print('━' * 80)
    print('  1. 打開 chip_radar 網站 → 內部人 tab')
    print('  2. 找上面 6 檔個股各自的內部人資料')
    print('  3. 對齊「董監人數 / 總設質比例 / 高設質警報」3 個數字')
    print('  4. 若 3/6 以上吻合 → 內部人資料源對齊 ✅ (>50% 為可信閾值)')
    print('  5. 若有差異 → 可能 chip_radar 抓的月份跟本工具不同 (預設今月,可改 --month)')
    print()
    print('  💡 進階手動 cross-check:')
    print(f'     MOPS 直接查: https://mops.twse.com.tw/mops/web/t56sb01')
    print('     輸入 stock code 看官方原表')


if __name__ == '__main__':
    main()
