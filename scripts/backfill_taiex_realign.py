# -*- coding: utf-8 -*-
"""v3.76.0 大盤指數日期錯位修復 — 用 TWSE 官方 FMTQIK 重建 stock_history.market

背景 (2026-08-28 稽核):
  src/fetchers/history.py `_fetch_taiex_index` 的 stale guard 讀錯欄位名 —
  寫 data[0].get('Date'), 但 MI_INDEX 是中文欄位「日期」.
  → response_date 永遠 '', `and response_date` 短路 → guard 自 v3.27.3 起從未執行.
  → TWSE 尚未更新當日資料時 API 回前一交易日, 卻被寫入 history["market"][trade_date].

實測損害 (TWSE FMTQIK 逐日對照, 55 筆全部可解釋, 無例外):
  正確對齊當日     12 筆 (22%)
  等於前一交易日   43 筆 (78%)   ← 數值是真的官方值, 錯的是日期標籤
  兩者皆非          0 筆

連帶 temp_history.next_day_change_pct (Q5 命中判定依據) 60 筆:
  正確 (=隔日漲跌)                 6 筆
  錯位 (=訊號當日漲跌)            47 筆   ← 拿今天已發生的漲跌當明天的預測結果
  其他 / 無法比對                  7 筆

  用官方資料重算後 Q5 55.8% vs 無腦全多 55.8% (Δ +0.0pp),
  先前 67.3% vs 63.3% (+4.1pp) 的「優勢」是污染造成的假象.

未受影響 (已驗證):
  個股收盤價 — STOCK_DAY_ALL / TPEx daily 用的是英文 'Date', 寫法正確.
               實測 2330 / 2317 各 42 筆全部當日對齊, 零錯位.
               → 融資維持率 / 公司行動還原 (v3.74.x) 不受影響.
  Phase B 權重源 signal_history_official.json — 119 筆中 115 正確, 0 筆錯位.

本 script 做兩件事:
  1. 用 TWSE FMTQIK 官方資料重建 stock_history["market"] (index + change_pct)
  2. 依重建後的 market 重算 temp_history 每筆的 next_day_change_pct

用法:
  python scripts/backfill_taiex_realign.py --dry-run    # 只報告不寫入
  python scripts/backfill_taiex_realign.py              # 實際寫入 (自動備份)
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
TW_TZ = timezone(timedelta(hours=8))

FMTQIK = 'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={ym}01&response=json'
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'),
    'Accept-Language': 'zh-TW,zh;q=0.9',
}

DRY = '--dry-run' in sys.argv


def fetch_official(months: list[str]) -> dict[str, float]:
    """回傳 {YYYYMMDD: 收盤指數} — TWSE 官方發行量加權股價指數."""
    out: dict[str, float] = {}
    for ym in months:
        try:
            r = requests.get(FMTQIK.format(ym=ym), headers=HEADERS, timeout=25)
            j = r.json()
            if j.get('stat') != 'OK':
                print(f"  ! {ym} stat={j.get('stat')}")
                continue
            for row in (j.get('data') or []):
                p = row[0].split('/')
                d = f'{int(p[0]) + 1911}{p[1]}{p[2]}'
                out[d] = float(row[4].replace(',', ''))
        except Exception as e:
            print(f"  ! {ym} 抓取失敗: {type(e).__name__}")
        time.sleep(0.6)
    return out


def main() -> int:
    sh_path = DATA / 'stock_history.json'
    th_path = DATA / 'temp_history.json'
    if not sh_path.exists():
        print('X stock_history.json 不存在'); return 1

    sh = json.loads(sh_path.read_text(encoding='utf-8'))
    market = sh.get('market') or {}
    if not market:
        print('X stock_history.market 是空的'); return 1

    dates = sorted(market)
    months = sorted({d[:6] for d in dates})
    print(f'現有 market: {len(dates)} 筆, {dates[0]} ~ {dates[-1]}')
    print(f'抓取官方月份: {months}')
    off = fetch_official(months)
    print(f'官方取得 {len(off)} 個交易日\n')

    offd = sorted(off)

    # ── 1. 診斷 ──
    lag0 = lag1 = other = 0
    for d in dates:
        v = (market[d] or {}).get('index')
        if v is None or d not in off:
            continue
        if abs(v - off[d]) < 1:
            lag0 += 1
        else:
            i = offd.index(d)
            if i > 0 and abs(v - off[offd[i - 1]]) < 1:
                lag1 += 1
            else:
                other += 1
    print(f'[診斷] 對齊當日 {lag0} / 慢一天 {lag1} / 兩者皆非 {other}')

    # ── 2. 重建 market ──
    new_market: dict[str, dict] = {}
    for i, d in enumerate(offd):
        if d < dates[0] or d > dates[-1]:
            continue
        idx = off[d]
        prev = off[offd[i - 1]] if i > 0 else None
        chg = round((idx - prev) / prev * 100, 2) if prev else None
        rec = {
            'index': idx,
            'change_pct': chg,
            'quote_date': f'{int(d[:4]) - 1911}{d[4:]}',
            'change_pct_source': 'twse_fmtqik_official_v3.76.0',
        }
        new_market[d] = rec

    added = [d for d in new_market if d not in market]
    removed = [d for d in market if d not in new_market]
    changed = [d for d in new_market
               if d in market and abs((market[d] or {}).get('index', 0) - new_market[d]['index']) >= 1]
    print(f'[重建 market] 新增 {len(added)} / 修正 {len(changed)} / 移除 {len(removed)}')
    if added:
        print(f'   新增: {added}')
    if removed:
        print(f'   移除 (官方無此交易日): {removed}')

    # ── 3. 重算 temp_history.next_day_change_pct ──
    th = None
    th_fixed = th_same = th_null = 0
    if th_path.exists():
        th = json.loads(th_path.read_text(encoding='utf-8'))
        for e in (th.get('history') or []):
            d = e.get('date')
            if d not in off:
                continue
            i = offd.index(d)
            if i + 1 >= len(offd):
                new_nx = None            # 尚無隔日 → 不可判定
            else:
                nd = offd[i + 1]
                new_nx = round((off[nd] - off[d]) / off[d] * 100, 2)
            old_nx = e.get('next_day_change_pct')
            if new_nx is None:
                if old_nx is not None:
                    th_null += 1
                    e['next_day_change_pct'] = None
                    e['next_day_source'] = 'pending'
            elif old_nx is None or abs(old_nx - new_nx) >= 0.02:
                th_fixed += 1
                e['next_day_change_pct'] = new_nx
                e['next_day_source'] = 'twse_fmtqik_official_v3.76.0'
            else:
                th_same += 1
                e['next_day_source'] = 'twse_fmtqik_official_v3.76.0'
        print(f'[重算 temp_history] 修正 {th_fixed} / 本來就對 {th_same} / 清成 None {th_null}')

    if DRY:
        print('\n(--dry-run: 未寫入任何檔案)')
        return 0

    # ── 4. 備份 + 寫入 ──
    stamp = datetime.now(TW_TZ).strftime('%Y%m%d_%H%M%S')
    bak_dir = DATA / 'backup_v3760'
    bak_dir.mkdir(exist_ok=True)
    shutil.copy2(sh_path, bak_dir / f'stock_history_{stamp}.json')
    if th_path.exists():
        shutil.copy2(th_path, bak_dir / f'temp_history_{stamp}.json')
    print(f'\n備份 → {bak_dir}')

    sh['market'] = new_market
    sh['market_realigned_at'] = datetime.now(TW_TZ).strftime('%Y-%m-%dT%H:%M:%S+08:00')
    sh_path.write_text(json.dumps(sh, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'✅ 寫入 {sh_path.name}')

    if th is not None:
        th['next_day_realigned_at'] = sh['market_realigned_at']
        th_path.write_text(json.dumps(th, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'✅ 寫入 {th_path.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
