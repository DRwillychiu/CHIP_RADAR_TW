"""
========================================================================
Module: listing_fetcher.py  (v3.45.0 後3 — Tier 1 Sprint 7)

抓 TWSE + TPEx 上市櫃公司基本資料 (含上市日期) — 給 C8 universe_filter 用

資料源 (已實證):
  - TWSE: https://openapi.twse.com.tw/v1/opendata/t187ap03_L
          1090 檔上市公司, 「上市日期」欄位 (YYYYMMDD 西元)
  - TPEx: https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O
          890 檔上櫃公司, 「DateOfListing」欄位 (YYYYMMDD 西元)

輸出 data/listing_history.json:
  {
    'updated_at': ISO,
    'source_twse': URL,
    'source_tpex': URL,
    'listings': {
      '2330': {'first_listed': '19940209', 'market': 'TWSE', 'name': '台積電'},
      '6741': {'first_listed': '20210420', 'market': 'TPEx', 'name': '...'},
      ...
    },
    'count': {twse: 1090, tpex: 890, total: ...}
  }

注意:
  - 「終止上市」資料 TWSE OpenAPI 沒提供。本模組只給 first_listed。
  - delisted 欄位留接口給未來 (HTML scrape 或手動補)。

CLI: python listing_fetcher.py [--force]
========================================================================
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

TW_TZ = timezone(timedelta(hours=8))

TWSE_LISTING_URL = 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L'
TPEX_LISTING_URL = 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O'
CACHE_FILE = 'listing_history.json'

# Refresh TTL (上市櫃公司基本資料變動慢, 30 天足夠)
DEFAULT_TTL_DAYS = 30


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


def _fetch_twse_listings() -> Optional[Dict[str, Dict[str, Any]]]:
    """TWSE 1090 檔上市公司."""
    try:
        from safe_fetch import safe_get
        r = safe_get(TWSE_LISTING_URL, source_id='TWSE_listing_companies',
                      max_retries=2, timeout=20,
                      headers={'User-Agent': 'Mozilla/5.0'})
    except ImportError:
        import requests
        r = requests.get(TWSE_LISTING_URL, timeout=20,
                          headers={'User-Agent': 'Mozilla/5.0'})
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None

    result = {}
    for row in data:
        code = (row.get('公司代號') or '').strip()
        first_listed = (row.get('上市日期') or '').strip()
        name = (row.get('公司簡稱') or '').strip()
        industry = (row.get('產業別') or '').strip()
        if not code or not first_listed or len(first_listed) != 8:
            continue
        result[code] = {
            'first_listed': first_listed,
            'market': 'TWSE',
            'name': name,
            'industry': industry,
            'delisted': None,   # 接口預留 (TWSE OpenAPI 沒給)
        }
    return result


def _fetch_tpex_listings() -> Optional[Dict[str, Dict[str, Any]]]:
    """TPEx 890 檔上櫃公司."""
    try:
        from safe_fetch import safe_get
        r = safe_get(TPEX_LISTING_URL, source_id='TPEx_listing_companies',
                      max_retries=2, timeout=20,
                      headers={'User-Agent': 'Mozilla/5.0'})
    except ImportError:
        import requests
        r = requests.get(TPEX_LISTING_URL, timeout=20,
                          headers={'User-Agent': 'Mozilla/5.0'})
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None

    result = {}
    for row in data:
        code = (row.get('SecuritiesCompanyCode') or '').strip()
        first_listed = (row.get('DateOfListing') or '').strip()
        name = (row.get('CompanyAbbreviation') or '').strip()
        industry = (row.get('SecuritiesIndustryCode') or '').strip()
        if not code or not first_listed or len(first_listed) != 8:
            continue
        result[code] = {
            'first_listed': first_listed,
            'market': 'TPEx',
            'name': name,
            'industry': industry,
            'delisted': None,
        }
    return result


def fetch_listings(data_dir: str = 'data',
                    force_refresh: bool = False,
                    ttl_days: int = DEFAULT_TTL_DAYS) -> Optional[Dict[str, Any]]:
    """主 API: cache → fetch (TWSE + TPEx) → save → return."""
    cache_path = Path(data_dir) / CACHE_FILE

    # 1. cache 看
    if not force_refresh and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            fetched_at = datetime.fromisoformat(cached['updated_at'])
            now = datetime.now(fetched_at.tzinfo) if fetched_at.tzinfo else datetime.now()
            age_days = (now - fetched_at).total_seconds() / 86400
            if age_days < ttl_days:
                print(f"  [Listing] cache 命中 ({age_days:.1f} 天, < TTL {ttl_days})")
                return cached
        except Exception as e:
            print(f"  ⚠️ Listing cache 讀取失敗 ({type(e).__name__}), 重抓")

    # 2. fetch
    print(f"  [Listing] 抓 TWSE + TPEx 上市櫃公司基本資料...")
    twse = _fetch_twse_listings() or {}
    tpex = _fetch_tpex_listings() or {}

    # merge
    listings = {}
    listings.update(twse)
    listings.update(tpex)

    if not listings:
        print(f"  ❌ Listing 抓取完全失敗 (TWSE: {len(twse)}, TPEx: {len(tpex)})")
        # 若 cache 存在, fallback 用 (stale)
        if cache_path.exists():
            try:
                stale = json.loads(cache_path.read_text(encoding='utf-8'))
                stale['stale'] = True
                print(f"  ⚠️ [後3 fallback] 用舊 cache 撐 ({stale.get('count', {}).get('total', '?')} 檔, stale=True)")
                return stale
            except Exception:
                pass
        return None

    payload = {
        'updated_at': now_tw().isoformat(),
        'source_twse': TWSE_LISTING_URL,
        'source_tpex': TPEX_LISTING_URL,
        'listings': listings,
        'count': {
            'twse': len(twse), 'tpex': len(tpex), 'total': len(listings),
        },
        'stale': False,
    }

    # 3. save
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding='utf-8')
    tmp.replace(cache_path)
    print(f"  [Listing] ✓ TWSE {len(twse)} 檔 + TPEx {len(tpex)} 檔 = {len(listings)} 檔 → {cache_path}")
    return payload


def load_listings(data_dir: str = 'data') -> Optional[Dict[str, Dict[str, Any]]]:
    """讀本地 cache (不打網路) — 給 backtester / universe_filter 用."""
    cache_path = Path(data_dir) / CACHE_FILE
    if not cache_path.exists():
        return None
    try:
        d = json.loads(cache_path.read_text(encoding='utf-8'))
        return d.get('listings') or {}
    except Exception:
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()
    r = fetch_listings(args.data_dir, args.force)
    if not r:
        print("❌ fetch_listings 失敗")
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
