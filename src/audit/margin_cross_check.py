"""margin_cross_check.py — W1 融資融券 + 內部人 cross-check vs 官方來源

驗證 chip_radar 的融資/內部人資料是否對齊官方 (TWSE / MOPS).
因為 chip_radar production 資料是 AES-256 加密無法直接讀,
此工具策略:**拉官方原始數字印出**, 老闆/User 開 chip_radar 網站
對應 tab 視覺比對。

W1 涵蓋兩件事:
  A. TWSE MI_MARGN 全市場日融資融券彙總 (官方來源)
  B. MOPS 重大訊息近 N 天清單 (內部人公告來源)

用法:
  python margin_cross_check.py [--days 5]
"""
import argparse
import json
import sys
import time
from datetime import date, timedelta

import requests


def _roc_to_ad(roc_date):
    """115/05/20 → 20260520"""
    try:
        parts = roc_date.split('/')
        if len(parts) != 3:
            return None
        return f"{int(parts[0]) + 1911:04d}{parts[1]:0>2}{parts[2]:0>2}"
    except Exception:
        return None


def fetch_mi_margn(date_yyyymmdd):
    """抓 TWSE MI_MARGN: 個股當日融資融券明細."""
    url = f"https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date={date_yyyymmdd}&selectType=ALL"
    try:
        r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        data = r.json()
        if data.get('stat') != 'OK':
            return None, data.get('stat', 'no data')
        # 取最後 5 行通常是「合計」or 大盤統計
        rows = data.get('data', [])
        # 第 1 table 是個股, 第 2 table 是合計
        # 該端點通常回 [tables] 結構, 不同版本不同
        return data, None
    except Exception as e:
        return None, str(e)


def fetch_mops_t05st01_recent(days=5):
    """抓 MOPS 重大訊息近 N 天彙總 (近似)."""
    # MOPS t05st01 endpoint requires POST with co_id; 簡化版用 t05st02 (全市場最新)
    url = "https://mopsov.twse.com.tw/mops/web/ajax_t05st02"
    try:
        # 該端點不易簡單 GET, 改提示 user 手動驗
        return None, "MOPS t05st01 需 per-stock POST, 本工具暫不自動爬取"
    except Exception as e:
        return None, str(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=5)
    args = parser.parse_args()

    print('=' * 80)
    print(f'  W1 融資融券 + 內部人 cross-check vs 官方來源')
    print('=' * 80)
    print()

    # ── A. TWSE MI_MARGN 全市場日融資融券 ──
    print('━' * 80)
    print('  A. TWSE 官方融資融券 (MI_MARGN)')
    print('━' * 80)
    today = date.today() - timedelta(days=1)  # yesterday
    cursor = today
    found_days = 0
    while found_days < args.days and (today - cursor).days < 15:
        date_str = cursor.strftime('%Y%m%d')
        data, err = fetch_mi_margn(date_str)
        if data is not None:
            found_days += 1
            print(f'\n  [{date_str}] TWSE MI_MARGN:')
            # MI_MARGN 結構:可能有 'tables' 或直接 'data' + 'fields'
            tables = data.get('tables', [])
            if tables:
                for ti, t in enumerate(tables):
                    title = t.get('title', '')
                    print(f'    Table {ti}: {title}')
                    fields = t.get('fields', [])
                    rows = t.get('data', [])
                    if title and ('合計' in title or '總計' in title or 'Total' in title or '統計' in title):
                        # 印合計 row
                        for row in rows[-3:]:  # 末幾行通常是合計
                            print(f'      {row}')
                    elif rows:
                        print(f'      共 {len(rows)} rows (個股明細, 略)')
            else:
                # 舊版結構
                fields = data.get('fields', [])
                rows = data.get('data', [])
                if rows:
                    print(f'    共 {len(rows)} rows')
                    # 嘗試找融資餘額 column
                    for i, f in enumerate(fields[:8]):
                        print(f'      Field {i}: {f}')
        else:
            print(f'  [{date_str}] {err}')
        cursor = cursor - timedelta(days=1)
        time.sleep(2)

    print()
    print('━' * 80)
    print('  📝 老闆 / User 視覺驗證提示')
    print('━' * 80)
    print('  1. 打開 chip_radar 網站 → 融資融券 tab')
    print('  2. 對齊上面 TWSE MI_MARGN 印的「合計」row 數字')
    print('     - 全市場融資餘額 (萬元 / 張)')
    print('     - 融資增減 (今日 vs 昨日)')
    print('     - 融券餘額 / 增減')
    print('  3. 若 chip_radar 數字跟 TWSE 官方相同 → 融資資料源對齊 ✅')
    print('  4. 對個別個股可進階查:')
    print('     https://www.twse.com.tw/exchangeReport/MI_MARGN?response=html&stockNo=2330')

    # ── B. MOPS 內部人 cross-check (簡化版) ──
    print()
    print('━' * 80)
    print('  B. 內部人異動 cross-check (人工驗證指南)')
    print('━' * 80)
    print('  MOPS 公開資訊觀測站 → 公司治理 → 內部人持股餘額月申報')
    print('  https://mops.twse.com.tw/mops/web/t56sb01')
    print()
    print('  驗證流程:')
    print('  1. 打開 chip_radar 網站 → 內部人 tab')
    print('  2. 選擇 chip_radar 列出的「近期有內部人異動」的個股 (e.g. 2330, 2454)')
    print('  3. 同個股到 MOPS t56sb01 查近期內部人持股異動')
    print('  4. 對齊筆數 + 金額 + 異動方向')
    print()
    print('  💡 自動 cross-check 需 per-stock POST MOPS 端點 (本工具暫不爬, 押下版)')


if __name__ == '__main__':
    main()
