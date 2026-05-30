"""
========================================================================
Module: disposal_fetcher.py  (v3.30.13 新增)
功能: 抓 chengwaye 處置股 forecast 清單, 給 master_profile 算「處置股獵手」標籤

背景 (5/30 使用者選擇 B):
  TWSE 處置股無公開 JSON API (試 9 個 endpoint 全 404 / 空殼 SPA)。
  chengwaye 整合 TWSE 處置公告 + robots.txt 允許 + 全免費 + 使用者自用,
  繞第三方取「整合版」處置股清單。

風險揭露 (誠實):
  - chengwaye 改 HTML → 我們 break
  - chengwaye 關站/改授權 → 我們無資料
  - 處置股原始源仍是 TWSE 公告, chengwaye 等於我們的中介
  - 容錯: fetch 失敗 → 回傳 None, master_profile 跳過處置股 metric

URL: https://chengwaye.com/disposal-forecast.html (每日 19:30 更新)

3 區分類:
  - imminent_1: 差 1 次違規就處置 (最高風險)
  - imminent_2: 差 2 次違規就處置
  - active:     目前處置中

cache: data/disposal_map.json (TTL 1 天)

API:
  get_disposal_map(data_dir, force_refresh=False, ttl_days=1) -> dict 或 None
    {
      'fetched_at': isoformat,
      'applicable_date': 'MM/DD',
      'count': 92,
      'sets': {'imminent_1': [...], 'imminent_2': [...], 'active': [...]},
      'all_risky': [union of 3 sets] (master_profile 用這個)
    }
========================================================================
"""
import re
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import requests

TW_TZ = timezone(timedelta(hours=8))

CHENGWAYE_URL = 'https://chengwaye.com/disposal-forecast.html'
CACHE_FILE = 'disposal_map.json'

# 台股代號 pattern: 4-6 字數字 (首位非 0), 可選後綴字母 (B/L/U 之類 ETF)
# 1000-99999X 涵蓋多數: 上市 4 字 (1xxx-9xxx), ETF 5 字 (00xxx → 跳過, 因首位 0)
# 注意: 處置股不太可能是 ETF, 所以首位非 0 過濾掉「10000 / 111118 / 141422」這種雜訊
CODE_PATTERN = re.compile(r'\b([1-9]\d{3,5}[A-Z]?)\b')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
}


def _fetch_disposal_html(timeout: int = 15, max_retries: int = 2) -> Optional[str]:
    """抓 chengwaye disposal-forecast.html, 失敗回 None。"""
    for attempt in range(max_retries):
        try:
            r = requests.get(CHENGWAYE_URL, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                r.encoding = 'utf-8'
                return r.text
            else:
                print(f"  ⚠️ chengwaye disposal {r.status_code}, retry {attempt+1}/{max_retries}")
        except Exception as e:
            print(f"  ⚠️ chengwaye disposal {type(e).__name__}, retry {attempt+1}/{max_retries}")
        time.sleep(3 + attempt * 3)
    return None


def parse_disposal_html(html: str) -> Dict[str, Any]:
    """Parse 3 個 sortable table → 3 sets of codes + applicable_date。"""
    sets: Dict[str, set] = {'imminent_1': set(), 'imminent_2': set(), 'active': set()}

    # 適用日期 (例: "適用 06/01 交易日")
    date_m = re.search(r'適用\s*(\d{2}/\d{2})', html)
    applicable_date = date_m.group(1) if date_m else None

    # 抓 3 個 sortable table (對應 3 區, 順序: 差1 / 差2 / 處置中)
    tables = re.findall(
        r'<table[^>]*class="[^"]*sortable[^"]*"[^>]*>(.*?)</table>',
        html, re.DOTALL,
    )
    section_keys = ['imminent_1', 'imminent_2', 'active']
    for i, table_html in enumerate(tables[:3]):
        key = section_keys[i]
        # 對每 tr 抽前 3 個 td (代號通常在第 2 個 td, 第 1 個是「所」上市/上櫃)
        trs = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)
        for tr in trs:
            tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
            if not tds:
                continue
            # 嘗試前 3 個 td 找代號 (避開非代號欄)
            for td in tds[:3]:
                txt = re.sub(r'<[^>]+>', '', td).strip()
                m = CODE_PATTERN.search(txt)
                if m:
                    sets[key].add(m.group(1))
                    break

    all_risky = sets['imminent_1'] | sets['imminent_2'] | sets['active']
    return {
        'applicable_date': applicable_date,
        'sets': sets,
        'all_risky': all_risky,
    }


def get_disposal_map(data_dir: str = 'data',
                      force_refresh: bool = False,
                      ttl_days: int = 1) -> Optional[Dict[str, Any]]:
    """主 API: cache (TTL 1 天) → fetch → parse → save → return.
    回傳 None 表示無法取得 (網路失敗或 parse 失敗); 呼叫者應跳過處置股 metric."""
    cache_path = Path(data_dir) / CACHE_FILE

    # 1. 看 cache
    if not force_refresh and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            fetched_at = datetime.fromisoformat(cached['fetched_at'])
            now = datetime.now(fetched_at.tzinfo) if fetched_at.tzinfo else datetime.now()
            age = (now - fetched_at).total_seconds() / 86400
            if age < ttl_days:
                # 轉回 set (給呼叫者直接用)
                cached['sets'] = {k: set(v) for k, v in cached['sets'].items()}
                cached['all_risky'] = set(cached['all_risky'])
                return cached
        except Exception as e:
            print(f"  ⚠️ disposal cache 讀取失敗 ({type(e).__name__}), 重抓")

    # 2. fetch + parse
    html = _fetch_disposal_html()
    if not html:
        print("  ❌ chengwaye disposal-forecast 抓取失敗")
        return None

    parsed = parse_disposal_html(html)
    parsed['fetched_at'] = datetime.now(TW_TZ).isoformat()
    parsed['count'] = len(parsed['all_risky'])

    if parsed['count'] == 0:
        print("  ⚠️ disposal parse 0 筆, 結構可能變動")
        return None

    # 3. save (set → sorted list 給 JSON)
    to_save = {
        'fetched_at': parsed['fetched_at'],
        'applicable_date': parsed['applicable_date'],
        'count': parsed['count'],
        'sets': {k: sorted(v) for k, v in parsed['sets'].items()},
        'all_risky': sorted(parsed['all_risky']),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(to_save, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  [Disposal] 抓到 {parsed['count']} 檔處置股 "
          f"(差1次 {len(parsed['sets']['imminent_1'])}, "
          f"差2次 {len(parsed['sets']['imminent_2'])}, "
          f"處置中 {len(parsed['sets']['active'])}, "
          f"適用 {parsed['applicable_date']})")
    return parsed


if __name__ == '__main__':
    import sys
    m = get_disposal_map(force_refresh='--refresh' in sys.argv)
    if m:
        print(f"\n✅ 處置股清單 ({m['count']} 檔)")
        for k, codes in m['sets'].items():
            sample = list(sorted(codes))[:10]
            print(f"  {k}: {len(codes)} 檔, 樣本 {sample}")
    else:
        print("❌ 取得失敗")
        sys.exit(1)
