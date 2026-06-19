"""
========================================================================
Module: attention_fetcher.py  (v3.46.0 後7 — Tier 2 Sprint 8)

抓 TWSE「注意有價證券」清單 — 比處置股更早期的警示

資料源 (已實證):
  TWSE: https://www.twse.com.tw/announcement/notice?response=json
        「公布注意有價證券資訊」
        含欄位: 編號 / 證券代號 / 證券名稱 / 累計次數 / 注意交易資訊 / 日期 / 收盤價 / 本益比

注意股 ≠ 處置股:
  注意股 = 早期警示 (一次符合條件就上榜)
  處置股 = 進階措施 (累計多次注意才會處置)
  本系統 disposal_fetcher 已抓處置 (chengwaye), 本模組補注意 (TWSE 官方)

輸出 data/attention_map.json:
  {
    fetched_at: ISO,
    applicable_date: 'YYYYMMDD',
    count: N,
    by_code: {
      '2330': {name, cumulative_count, info, date, close, pe}
    },
    all_codes: [code, ...]
  }

CLI: python attention_fetcher.py [--force]
========================================================================
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

TW_TZ = timezone(timedelta(hours=8))

TWSE_NOTICE_URL = 'https://www.twse.com.tw/announcement/notice?response=json'
CACHE_FILE = 'attention_map.json'
DEFAULT_TTL_DAYS = 1
STALE_FALLBACK_DAYS = 7   # chengwaye-style fallback


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


def _fetch_twse_notice() -> Optional[Dict[str, Any]]:
    """TWSE 注意股 JSON."""
    try:
        from safe_fetch import safe_get
        r = safe_get(TWSE_NOTICE_URL, source_id='TWSE_announcement_notice',
                      max_retries=2, timeout=20,
                      headers={'User-Agent': 'Mozilla/5.0'})
    except ImportError:
        import requests
        r = requests.get(TWSE_NOTICE_URL, timeout=20,
                          headers={'User-Agent': 'Mozilla/5.0'})
    if r.status_code != 200:
        return None
    try:
        d = r.json()
    except Exception:
        return None
    if d.get('stat') != 'OK':
        return None
    return d


def parse_notice(twse_data: Dict[str, Any]) -> Dict[str, Any]:
    """解析 TWSE 注意股 JSON → by_code dict.

    fields: ['編號', '證券代號', '證券名稱', '累計次數', '注意交易資訊', '日期', '收盤價', '本益比']
    """
    rows = twse_data.get('data') or []
    by_code = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            code = str(row[1]).strip()
            name = str(row[2]).strip()
            cumulative = int(str(row[3]).replace(',', '').strip() or 0)
            info = str(row[4]).strip()
            date = str(row[5]).strip()
            close = float(str(row[6]).replace(',', '').strip() or 0) if len(row) > 6 else None
            pe = str(row[7]).strip() if len(row) > 7 else None
        except (ValueError, IndexError):
            continue
        if not code:
            continue
        by_code[code] = {
            'name': name,
            'cumulative_count': cumulative,
            'info': info,
            'date': date,
            'close': close,
            'pe': pe,
        }
    # 從 title 抽日期
    title = twse_data.get('title', '')
    applicable_date = None
    import re
    m = re.search(r'(\d{2,3})年(\d{1,2})月(\d{1,2})日', title)
    if m:
        roc_y, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        applicable_date = f'{roc_y + 1911:04d}{mm:02d}{dd:02d}'
    return {
        'applicable_date': applicable_date,
        'count': len(by_code),
        'by_code': by_code,
        'all_codes': sorted(by_code.keys()),
    }


def get_attention_map(data_dir: str = 'data',
                       force_refresh: bool = False,
                       ttl_days: int = DEFAULT_TTL_DAYS,
                       stale_fallback_days: int = STALE_FALLBACK_DAYS) -> Optional[Dict[str, Any]]:
    """主 API: cache → fetch → parse → save → return.
    格式跟 disposal_fetcher 對齊 (stale fallback 機制)."""
    cache_path = Path(data_dir) / CACHE_FILE

    # 1. cache fresh 直接返
    cached_stale = None
    if not force_refresh and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            fetched_at = datetime.fromisoformat(cached['fetched_at'])
            now = datetime.now(fetched_at.tzinfo) if fetched_at.tzinfo else datetime.now()
            age_days = (now - fetched_at).total_seconds() / 86400
            if age_days < ttl_days:
                cached['stale'] = False
                cached['stale_days'] = round(age_days, 1)
                return cached
            elif age_days < stale_fallback_days:
                cached_stale = cached
                cached_stale['_age_days'] = round(age_days, 1)
        except Exception as e:
            print(f"  ⚠️ attention cache 讀取失敗 ({type(e).__name__}), 重抓")

    # 2. fetch + parse
    twse = _fetch_twse_notice()
    if not twse:
        print("  ❌ TWSE attention/notice 抓取失敗")
        if cached_stale:
            age = cached_stale.pop('_age_days', '?')
            print(f"  ⚠️ [後7 fallback] 用 {age} 天舊 cache 撐 (stale=True)")
            cached_stale['stale'] = True
            cached_stale['stale_days'] = age
            return cached_stale
        return None

    parsed = parse_notice(twse)
    parsed['fetched_at'] = now_tw().isoformat()
    parsed['source'] = TWSE_NOTICE_URL
    parsed['stale'] = False
    parsed['stale_days'] = 0

    # 3. save
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(parsed, ensure_ascii=False, indent=1),
                    encoding='utf-8')
    tmp.replace(cache_path)
    print(f"  [Attention] ✓ {parsed['count']} 檔注意股 (適用 {parsed.get('applicable_date', '?')}) → {cache_path}")
    return parsed


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()
    r = get_attention_map(args.data_dir, args.force)
    if r:
        print(f"\nTotal: {r['count']} 注意股")
        for code, info in list(r.get('by_code', {}).items())[:10]:
            print(f"  {code} {info['name']}: 累計 {info['cumulative_count']} 次 | {info['info'][:30]}")
    return 0 if r else 1


if __name__ == '__main__':
    sys.exit(main())
