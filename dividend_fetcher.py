"""
========================================================================
Module: dividend_fetcher.py  (v3.46.0 後8 — Tier 2 Sprint 8)

抓 TWSE 除權息預告表 — 8/10 月高峰前必看

資料源 (已實證):
  TWSE: https://www.twse.com.tw/exchangeReport/TWT48U?response=json
        289 檔上市公司除權息預告 (含日期)
  欄位:
    除權除息日期 / 股票代號 / 名稱 / 除權息 / 無償配股率 / 現金股利 / ...

輸出 data/dividend_calendar.json:
  {
    fetched_at: ISO,
    by_code: {
      '2330': {ex_date: '20260822', name: '台積電', type: '除息',
                cash_dividend: 4.0, stock_dividend_pct: 0}
    },
    upcoming_30d: [...],   # 未來 30 天內除權息
    by_date: {'20260815': [code, ...]}
  }

CLI: python dividend_fetcher.py [--force]
========================================================================
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

TW_TZ = timezone(timedelta(hours=8))

TWSE_TWT48U_URL = 'https://www.twse.com.tw/exchangeReport/TWT48U?response=json'
CACHE_FILE = 'dividend_calendar.json'
DEFAULT_TTL_DAYS = 1


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


def _roc_to_yyyymmdd(roc_date: str) -> Optional[str]:
    """ROC 民國年日期 → YYYYMMDD (e.g. '115/08/15' → '20260815')."""
    if not roc_date:
        return None
    # 多種格式: '115/08/15', '115年08月15日'
    import re
    s = roc_date.strip().replace('年', '/').replace('月', '/').replace('日', '')
    m = re.match(r'(\d+)/(\d{1,2})/(\d{1,2})', s)
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f'{y + 1911:04d}{mo:02d}{d:02d}'
    except ValueError:
        return None


def _to_float(s) -> Optional[float]:
    if s is None or s == '':
        return None
    try:
        return float(str(s).replace(',', '').strip())
    except ValueError:
        return None


def _fetch_twse_twt48u() -> Optional[Dict[str, Any]]:
    try:
        from safe_fetch import safe_get
        r = safe_get(TWSE_TWT48U_URL, source_id='TWSE_TWT48U',
                      max_retries=2, timeout=20,
                      headers={'User-Agent': 'Mozilla/5.0'})
    except ImportError:
        import requests
        r = requests.get(TWSE_TWT48U_URL, timeout=20,
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


def parse_twt48u(twse_data: Dict[str, Any]) -> Dict[str, Any]:
    """解析 TWSE 除權息預告 JSON."""
    rows = twse_data.get('data') or []
    fields = twse_data.get('fields') or []
    # 找欄位索引
    def _idx(name):
        for i, f in enumerate(fields):
            if name in f:
                return i
        return -1
    idx_date = _idx('除權除息日期')
    idx_code = _idx('股票代號')
    idx_name = _idx('名稱')
    idx_type = _idx('除權息')
    idx_stock_pct = _idx('無償配股率')
    idx_cash = _idx('現金股利')

    by_code = {}
    by_date = {}
    for row in rows:
        if not isinstance(row, list) or len(row) <= max(idx_code, idx_date):
            continue
        roc_date = str(row[idx_date]).strip() if idx_date >= 0 else ''
        ymd = _roc_to_yyyymmdd(roc_date)
        if not ymd:
            continue
        code = str(row[idx_code]).strip() if idx_code >= 0 else ''
        if not code:
            continue
        name = str(row[idx_name]).strip() if idx_name >= 0 else ''
        type_str = str(row[idx_type]).strip() if idx_type >= 0 else ''
        stock_pct = _to_float(row[idx_stock_pct]) if idx_stock_pct >= 0 else None
        cash = _to_float(row[idx_cash]) if idx_cash >= 0 else None
        entry = {
            'ex_date': ymd,
            'name': name,
            'type': type_str,
            'cash_dividend': cash,
            'stock_dividend_pct': stock_pct,
        }
        by_code[code] = entry
        by_date.setdefault(ymd, []).append(code)

    # 未來 30 天 upcoming
    today = now_tw().strftime('%Y%m%d')
    upcoming_cutoff = (now_tw() + timedelta(days=30)).strftime('%Y%m%d')
    upcoming = []
    for code, info in by_code.items():
        if today <= info['ex_date'] <= upcoming_cutoff:
            upcoming.append({'code': code, **info})
    upcoming.sort(key=lambda x: x['ex_date'])

    return {
        'count': len(by_code),
        'by_code': by_code,
        'by_date': by_date,
        'upcoming_30d': upcoming,
    }


def get_dividend_calendar(data_dir: str = 'data',
                            force_refresh: bool = False,
                            ttl_days: int = DEFAULT_TTL_DAYS) -> Optional[Dict[str, Any]]:
    cache_path = Path(data_dir) / CACHE_FILE

    if not force_refresh and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            fetched_at = datetime.fromisoformat(cached['fetched_at'])
            now = datetime.now(fetched_at.tzinfo) if fetched_at.tzinfo else datetime.now()
            age = (now - fetched_at).total_seconds() / 86400
            if age < ttl_days:
                return cached
        except Exception:
            pass

    twse = _fetch_twse_twt48u()
    if not twse:
        print("  ❌ TWSE TWT48U 抓取失敗")
        return None

    parsed = parse_twt48u(twse)
    parsed['fetched_at'] = now_tw().isoformat()
    parsed['source'] = TWSE_TWT48U_URL

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(parsed, ensure_ascii=False, indent=1),
                    encoding='utf-8')
    tmp.replace(cache_path)
    print(f"  [Dividend] ✓ {parsed['count']} 檔除權息預告 (未來 30 天 {len(parsed['upcoming_30d'])} 檔) → {cache_path}")
    return parsed


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()
    r = get_dividend_calendar(args.data_dir, args.force)
    if r:
        print(f"\n未來 30 天除權息 Top 10:")
        for item in r.get('upcoming_30d', [])[:10]:
            cash = item.get('cash_dividend')
            cash_str = f"現金 {cash:.2f}" if cash else ""
            print(f"  {item['ex_date']} {item['code']} {item['name']} ({item['type']}) {cash_str}")
    return 0 if r else 1


if __name__ == '__main__':
    sys.exit(main())
