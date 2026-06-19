"""
========================================================================
Module: short_lending_fetcher.py  (v3.46.0 後6 — Tier 2 Sprint 8)

抓 TWSE「當日融券賣出與借券賣出成交量值」— 反向力量觀察

資料源 (已實證):
  TWSE: https://www.twse.com.tw/exchangeReport/TWTASU?response=json
        標題: 「當日融券賣出與借券賣出成交量值」
        欄位 (groups): 證券名稱 | 融券賣出 (數量+金額) | 借券賣出 (數量+金額)
        1319 檔當日有資料

為什麼借券賣出重要 (跟融券一起看):
  融券 — 散戶級反向 (信用戶可借的券)
  借券 — 機構級反向 (大戶、外資、ETF 借券給投資人放空)
  借券量 >> 融券量 = 機構在押 (比融券更有 alpha)

輸出 data/short_lending.json:
  {
    fetched_at: ISO,
    applicable_date: YYYYMMDD,
    by_code: {
      '2330': {name, short_sell_lot, short_sell_amt,
                borrow_sell_lot, borrow_sell_amt}
    },
    top_borrow: [...]    # 借券賣出量 Top 30
  }

CLI: python short_lending_fetcher.py [--force]
========================================================================
"""
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

TW_TZ = timezone(timedelta(hours=8))

TWSE_TWTASU_URL = 'https://www.twse.com.tw/exchangeReport/TWTASU?response=json'
CACHE_FILE = 'short_lending.json'
DEFAULT_TTL_HOURS = 6


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


def _fetch_twse_twtasu() -> Optional[Dict[str, Any]]:
    try:
        from safe_fetch import safe_get
        r = safe_get(TWSE_TWTASU_URL, source_id='TWSE_TWTASU',
                      max_retries=2, timeout=20,
                      headers={'User-Agent': 'Mozilla/5.0'})
    except ImportError:
        import requests
        r = requests.get(TWSE_TWTASU_URL, timeout=20,
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


def parse_twtasu(twse_data: Dict[str, Any]) -> Dict[str, Any]:
    """解析 TWSE TWTASU JSON.

    row 格式: ['00400A   主動國泰動能高息', '112', '1,681,730', '506', '7,630,240']
             [name+code], 融券-數量, 融券-金額, 借券-數量, 借券-金額
    """
    rows = twse_data.get('data') or []
    by_code = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 5:
            continue
        # row[0] 形如 '00400A   主動國泰動能高息' — code + 空白 + name
        raw_name_col = str(row[0]).strip()
        m = re.match(r'^(\S+)\s+(.+)$', raw_name_col)
        if not m:
            continue
        code = m.group(1).strip()
        name = m.group(2).strip()
        try:
            short_lot = int(str(row[1]).replace(',', '').strip() or 0)
            short_amt = int(str(row[2]).replace(',', '').strip() or 0)
            borrow_lot = int(str(row[3]).replace(',', '').strip() or 0)
            borrow_amt = int(str(row[4]).replace(',', '').strip() or 0)
        except ValueError:
            continue
        # 過濾無實質賣出的 row (節省檔案大小)
        if short_lot == 0 and borrow_lot == 0:
            continue
        by_code[code] = {
            'name': name,
            'short_sell_lot': short_lot,
            'short_sell_amt': short_amt,
            'borrow_sell_lot': borrow_lot,
            'borrow_sell_amt': borrow_amt,
            'borrow_vs_short_ratio': round(borrow_lot / short_lot, 2) if short_lot > 0 else None,
        }

    # 從 title 取日期
    title = twse_data.get('title', '')
    m = re.search(r'(\d{2,3})年(\d{1,2})月(\d{1,2})日', title)
    applicable_date = None
    if m:
        roc_y, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        applicable_date = f'{roc_y + 1911:04d}{mm:02d}{dd:02d}'

    # Top 30 借券量
    top_borrow = sorted(by_code.items(),
                         key=lambda kv: -kv[1]['borrow_sell_lot'])[:30]
    top_borrow_list = [{'code': c, **info} for c, info in top_borrow]

    return {
        'applicable_date': applicable_date,
        'count_with_activity': len(by_code),
        'by_code': by_code,
        'top_borrow_sell': top_borrow_list,
    }


def get_short_lending_map(data_dir: str = 'data',
                           force_refresh: bool = False,
                           ttl_hours: int = DEFAULT_TTL_HOURS) -> Optional[Dict[str, Any]]:
    """主 API: cache → fetch → parse → save → return."""
    cache_path = Path(data_dir) / CACHE_FILE

    if not force_refresh and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            fetched_at = datetime.fromisoformat(cached['fetched_at'])
            now = datetime.now(fetched_at.tzinfo) if fetched_at.tzinfo else datetime.now()
            age_hours = (now - fetched_at).total_seconds() / 3600
            if age_hours < ttl_hours:
                return cached
        except Exception:
            pass

    twse = _fetch_twse_twtasu()
    if not twse:
        print("  ❌ TWSE TWTASU 抓取失敗")
        return None

    parsed = parse_twtasu(twse)
    parsed['fetched_at'] = now_tw().isoformat()
    parsed['source'] = TWSE_TWTASU_URL

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(parsed, ensure_ascii=False, indent=1),
                    encoding='utf-8')
    tmp.replace(cache_path)
    n = parsed['count_with_activity']
    top = parsed['top_borrow_sell'][0] if parsed['top_borrow_sell'] else None
    top_str = f"{top['code']} {top['name']} {top['borrow_sell_lot']:,} 張" if top else 'n/a'
    print(f"  [Short Lending] ✓ {n} 檔有融券/借券活動 (Top borrow: {top_str}) → {cache_path}")
    return parsed


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()
    r = get_short_lending_map(args.data_dir, args.force)
    if r:
        print(f"\nTop 10 借券賣出量:")
        for item in r.get('top_borrow_sell', [])[:10]:
            print(f"  {item['code']} {item['name']}: 借券 {item['borrow_sell_lot']:,} 張 / "
                  f"融券 {item['short_sell_lot']:,} 張 / 比 {item.get('borrow_vs_short_ratio')}")
    return 0 if r else 1


if __name__ == '__main__':
    sys.exit(main())
