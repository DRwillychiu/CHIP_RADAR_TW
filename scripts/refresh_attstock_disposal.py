"""v3.71.7: 抓 attstock.tw 處置股清單寫 data/disposal_attstock.json.

整合到 Chip Radar 「今日避開」 section. 跟自己的 disposal_watch repo 同源
(attstock.tw 公開 API), 但 Chip Radar 只用「codes set + count」, 不重複
disposal_watch 的完整節錄功能.

執行: python scripts/refresh_attstock_disposal.py
寫入: data/disposal_attstock.json
  {
    "fetched_at": ISO,
    "count_in_disposal": int,    # 目前已處置
    "count_pending_1d": int,      # 1 天內即將處置 (minDaysToDisposal=1)
    "codes_in_disposal": [...],
    "codes_pending_1d": [...],
    "sample": [{code, name, type, days_to_disposal}, ...]   # 給 hover 用
  }
"""
import json, sys, time, requests, datetime
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'disposal_attstock.json'

URL = 'https://attstock.tw/api/stocks/risk'            # 風險股 → 明日恐處置 (minDaysToDisposal)
URL_DISPOSAL = 'https://attstock.tw/api/stocks/disposal'   # 處置中 (v3.80.14)
TW = datetime.timezone(datetime.timedelta(hours=8))
# v3.80.14: attstock 自 2026-08-24 起擋非瀏覽器 UA. 原本送 'Mozilla/5.0' → 403,
# 本檔從 2026-08-21 後再也沒更新成功 (步驟 continue-on-error, 沒人發現), Email
# 「明日恐處置」一直顯示 8/21 的清單. 標頭照抄 disposal-watch 已驗證的寫法
# (fetch_disposal.py: 完整 Chrome UA + Accept + Referer). 2026-10-06 本機實測 200.
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36'),
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-TW,zh;q=0.9',
    'Referer': 'https://attstock.tw/',
}


def fetch(url, retries=3):
    """403/429 = 被來源擋下, 不重試 (重打只會讓封鎖更久, 同 disposal-watch)."""
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, timeout=30, headers=HEADERS)
            if r.status_code in (403, 429):
                raise PermissionError(f"{url} HTTP {r.status_code} — attstock 擋下請求 (UA 過濾或 IP 限流), 不重試")
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list):
                raise ValueError(f"{url} unexpected response shape: {type(data).__name__}")
            return data
        except (PermissionError, ValueError):
            raise
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url} fetch failed after {retries} tries: {last}")


def summarize(risk, disposal, today):
    """today: 'YYYY-MM-DD' (台灣日期).
    處置中 = /disposal 中 起日 <= today <= 迄日. v3.80.14 以前用 /risk 的
    disposal_start_date 判斷, 但 /risk 只回 status=risk (2026-10-06 實測 139/139 皆空),
    「處置中」永遠是 0 檔.
    明日恐處置 = /risk 中 analysis.minDaysToDisposal == 1, 且不在處置中."""
    in_disposal, sample = [], []
    for s in disposal:
        code = s.get('code')
        ds, de = s.get('disposal_start_date') or '', s.get('disposal_end_date') or ''
        if code and ds and ds[:10] <= today and (not de or today <= de[:10]):
            in_disposal.append(code)
            sample.append({'code': code, 'name': s.get('name', '—'), 'status': 'in_disposal',
                           'start': ds[:10], 'end': de[:10] or None})
    pending_1d = []
    for s in risk:
        code = s.get('code')
        analysis = s.get('analysis') or {}
        if code and code not in in_disposal and analysis.get('minDaysToDisposal') == 1:
            pending_1d.append(code)
            sample.append({'code': code, 'name': s.get('name', '—'),
                           'type': analysis.get('disposalType') or '—',
                           'status': 'pending_1d', 'days_to_disposal': 1})
    return sorted(set(in_disposal)), sorted(set(pending_1d)), sample


def main():
    try:
        print(f"fetch {URL}")
        risk = fetch(URL)
        time.sleep(1.5)
        print(f"fetch {URL_DISPOSAL}")
        disposal = fetch(URL_DISPOSAL)
    except Exception as e:
        print(f"  ✗ fetch failed: {e}")
        # GitHub Actions 註記: 步驟是 continue-on-error, 不留註記就會像 8/21 起那樣沒人發現
        print(f"::warning title=attstock disposal::refresh failed — {e}; "
              f"data/disposal_attstock.json not updated (Excel/Email hide stale lists)")
        sys.exit(1)

    now = datetime.datetime.now(TW)
    in_disposal, pending_1d, sample = summarize(risk, disposal, now.strftime('%Y-%m-%d'))
    out = {
        'fetched_at': now.isoformat(timespec='seconds'),   # v3.80.14: 帶 +08:00
        'source': 'attstock.tw/api/stocks/risk + /api/stocks/disposal',
        'total_risk_count': len(risk),
        'total_disposal_rows': len(disposal),
        'count_in_disposal': len(in_disposal),
        'count_pending_1d': len(pending_1d),
        'codes_in_disposal': in_disposal,
        'codes_pending_1d': pending_1d,
        'sample': sample[:40],
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  ✓ {OUT}")
    print(f"    risk rows: {len(risk)} | disposal rows: {len(disposal)}")
    print(f"    in_disposal: {len(in_disposal)} → top 5: {in_disposal[:5]}")
    print(f"    pending_1d: {len(pending_1d)} → top 5: {pending_1d[:5]}")


if __name__ == '__main__':
    main()
