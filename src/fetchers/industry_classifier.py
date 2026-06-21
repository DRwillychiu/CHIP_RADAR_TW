"""
========================================================================
Module: industry_classifier.py  (v3.15.0 新增)
功能：抓取 TWSE + TPEx 公司基本資料,建立「個股代號 → 產業類別」對照表

資料源：
  1. TWSE OpenAPI: https://openapi.twse.com.tw/v1/opendata/t187ap03_L
     (1082 家上市公司, 欄位「產業別」為代碼 01-38,91)
  2. TPEx OpenAPI: https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O  
     (883 家上櫃公司, 欄位 SecuritiesIndustryCode)

快取策略：
  - 產業分類變動頻率極低(年度調整),快取 7 天
  - 檔案：data/industry_map.json
  - 每週一首次執行時更新

輸出格式：
  data/industry_map.json = {
    "updated_at": "2026-04-23T...",
    "version": "3.15.0",
    "count": 1965,
    "industries": {          # 產業 -> 個股列表
      "半導體業": ["2330", "2454", "5483", ...],
      ...
    },
    "stock_industry": {      # 個股 -> 產業 (反查快取)
      "2330": "半導體業",
      ...
    }
  }

使用：
  from industry_classifier import get_industry_map
  mapping = get_industry_map(data_dir)
  print(mapping['stock_industry']['2330'])  # "半導體業"
========================================================================
"""

import json
import time
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

TW_TZ = timezone(timedelta(hours=8))

# ════════════════════════════════════════════════════════════════════
#  TWSE 官方產業分類對照表 (2023/7/3 後 33 類 + DR 存託憑證)
# ════════════════════════════════════════════════════════════════════
INDUSTRY_CODE_MAP = {
    # 傳統產業
    '01': '水泥工業',
    '02': '食品工業',
    '03': '塑膠工業',
    '04': '紡織纖維',
    '05': '電機機械',
    '06': '電器電纜',
    '08': '玻璃陶瓷',
    '09': '造紙工業',
    '10': '鋼鐵工業',
    '11': '橡膠工業',
    '12': '汽車工業',
    # 建材/航運/觀光
    '14': '建材營造',
    '15': '航運業',
    '16': '觀光餐旅',
    # 金融/貿易
    '17': '金融保險業',
    '18': '貿易百貨',
    # 其他/化學/生技/油電
    '20': '其他',
    '21': '化學工業',
    '22': '生技醫療業',
    '23': '油電燃氣業',
    # 電子股 (24-31)
    '24': '半導體業',
    '25': '電腦及週邊設備業',
    '26': '光電業',
    '27': '通信網路業',
    '28': '電子零組件業',
    '29': '電子通路業',
    '30': '資訊服務業',
    '31': '其他電子業',
    # 2023/7 新增 4 類
    '35': '綠能環保',
    '36': '數位雲端',
    '37': '運動休閒',
    '38': '居家生活',
    # DR
    '91': '存託憑證',
    # TPEx 可能有的其他代碼
    '32': '文化創意業',
    '33': '農業科技業',  # TPEx 特有
    '34': '電子商務',    # TPEx 特有
}

# 大產業分組（方便前端摺疊/篩選）
INDUSTRY_GROUPS = {
    '電子股': ['半導體業', '電腦及週邊設備業', '光電業', '通信網路業',
               '電子零組件業', '電子通路業', '資訊服務業', '其他電子業'],
    '傳統產業': ['水泥工業', '食品工業', '塑膠工業', '紡織纖維', '電機機械',
                 '電器電纜', '玻璃陶瓷', '造紙工業', '鋼鐵工業', '橡膠工業',
                 '汽車工業', '化學工業'],
    '生技醫療': ['生技醫療業'],
    '金融股': ['金融保險業'],
    '營建/航運/觀光': ['建材營造', '航運業', '觀光餐旅', '貿易百貨'],
    '能源/公用': ['油電燃氣業', '綠能環保'],
    '新興產業': ['數位雲端', '運動休閒', '居家生活', '文化創意業', '農業科技業', '電子商務'],
    '其他': ['其他', '存託憑證'],
}

# 快取檔名
CACHE_FILE = 'industry_map.json'
CACHE_DAYS = 7  # 快取 7 天

# TWSE/TPEx API URLs
TWSE_API_URL = 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L'
TPEX_API_URL = 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; ChipRadar/3.15.0)',
    'Accept': 'application/json',
}


def _fetch_twse_companies(max_retries: int = 2) -> list:
    """抓取上市公司基本資料"""
    for attempt in range(max_retries):
        try:
            r = requests.get(TWSE_API_URL, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                r.encoding = 'utf-8'
                return json.loads(r.text)
            else:
                print(f"    ⚠️ TWSE 公司資料第 {attempt+1}/{max_retries} 次: HTTP {r.status_code}")
        except Exception as e:
            print(f"    ⚠️ TWSE 公司資料第 {attempt+1}/{max_retries} 次失敗: {e}")
        if attempt < max_retries - 1:
            time.sleep(10 + attempt * 5)
    return []


def _fetch_tpex_companies(max_retries: int = 2) -> list:
    """抓取上櫃公司基本資料"""
    for attempt in range(max_retries):
        try:
            r = requests.get(TPEX_API_URL, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
            else:
                print(f"    ⚠️ TPEx 公司資料第 {attempt+1}/{max_retries} 次: HTTP {r.status_code}")
        except Exception as e:
            print(f"    ⚠️ TPEx 公司資料第 {attempt+1}/{max_retries} 次失敗: {e}")
        if attempt < max_retries - 1:
            time.sleep(10 + attempt * 5)
    return []


def _build_mapping() -> Dict[str, Any]:
    """從 API 建立完整的產業對照表"""
    print("  [1/2] 抓取 TWSE 上市公司基本資料...")
    twse = _fetch_twse_companies()
    print(f"    ✓ {len(twse)} 家上市公司")
    
    time.sleep(5)  # API 間隔避免限流
    
    print("  [2/2] 抓取 TPEx 上櫃公司基本資料...")
    tpex = _fetch_tpex_companies()
    print(f"    ✓ {len(tpex)} 家上櫃公司")
    
    # 建立對照表
    stock_industry = {}  # code -> industry_name
    industries = {}      # industry_name -> [codes]
    unknown_codes = set()
    
    # 處理 TWSE
    for r in twse:
        code = (r.get('公司代號') or '').strip()
        ind_code = (r.get('產業別') or '').strip()
        if not code or not ind_code:
            continue
        ind_name = INDUSTRY_CODE_MAP.get(ind_code)
        if not ind_name:
            unknown_codes.add(ind_code)
            ind_name = f'未知({ind_code})'
        stock_industry[code] = ind_name
        industries.setdefault(ind_name, []).append(code)
    
    # 處理 TPEx
    for r in tpex:
        code = (r.get('SecuritiesCompanyCode') or '').strip()
        ind_code = (r.get('SecuritiesIndustryCode') or '').strip()
        if not code or not ind_code:
            continue
        # TPEx 代碼可能是 2 位或 1 位
        if len(ind_code) == 1:
            ind_code = '0' + ind_code
        ind_name = INDUSTRY_CODE_MAP.get(ind_code)
        if not ind_name:
            unknown_codes.add(ind_code)
            ind_name = f'未知({ind_code})'
        stock_industry[code] = ind_name
        industries.setdefault(ind_name, []).append(code)
    
    if unknown_codes:
        print(f"    ⚠️ 發現未知產業代碼: {sorted(unknown_codes)}")
    
    # 每個產業的個股按代號排序
    for ind in industries:
        industries[ind] = sorted(set(industries[ind]))
    
    print(f"\n  [合計] {len(stock_industry)} 檔個股, {len(industries)} 個產業")
    
    # 加上大分組資訊
    for group_name, ind_list in INDUSTRY_GROUPS.items():
        existing = [ind for ind in ind_list if ind in industries]
        if existing:
            total_stocks = sum(len(industries[i]) for i in existing)
            print(f"    {group_name}: {len(existing)} 個產業, {total_stocks} 檔")
    
    return {
        'updated_at': datetime.now(TW_TZ).isoformat(),
        'version': '3.15.0',
        'count': len(stock_industry),
        'industries': industries,
        'stock_industry': stock_industry,
        'industry_groups': INDUSTRY_GROUPS,
        'unknown_codes': sorted(unknown_codes),
    }


def _load_cache(cache_path: Path) -> Optional[Dict[str, Any]]:
    """讀取快取,若過期則回傳 None"""
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, encoding='utf-8') as f:
            cache = json.load(f)
        # 檢查快取過期
        updated_at = datetime.fromisoformat(cache['updated_at'])
        age_days = (datetime.now(TW_TZ) - updated_at).days
        if age_days > CACHE_DAYS:
            print(f"  產業分類快取已過期 ({age_days} 天), 需重抓")
            return None
        print(f"  ✓ 使用產業分類快取 (更新於 {age_days} 天前, {cache.get('count', '?')} 檔)")
        return cache
    except Exception as e:
        print(f"  ⚠️ 快取讀取失敗: {e}, 重抓")
        return None


def get_industry_map(data_dir: Path, force_refresh: bool = False) -> Dict[str, Any]:
    """
    取得完整產業對照表 (帶快取)
    
    Args:
        data_dir: 資料目錄 (Path 物件)
        force_refresh: 強制重抓 (忽略快取)
    
    Returns:
        {
            'updated_at': ISO string,
            'count': int,
            'industries': {ind_name: [codes]},
            'stock_industry': {code: ind_name},
            'industry_groups': {group_name: [ind_names]},
            'unknown_codes': [unknown_codes],
        }
    """
    cache_path = data_dir / CACHE_FILE
    
    # 嘗試讀取快取
    if not force_refresh:
        cache = _load_cache(cache_path)
        if cache:
            return cache
    
    # 快取無效,重抓
    print("\n[產業分類] 建立新的產業對照表...")
    mapping = _build_mapping()
    
    # 存檔
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 快取存於 {cache_path}")
    
    return mapping


def inject_industry_into_stocks(results: list, industry_map: Dict[str, Any]) -> int:
    """
    把產業資訊注入到 results (分點結果) 的每個個股
    
    Args:
        results: [{code, buys:[{code, name, ...}], sells:[...]}, ...]
        industry_map: get_industry_map 回傳的對照表
    
    Returns: 注入成功的個股數
    """
    stock_industry = industry_map.get('stock_industry', {})
    count = 0
    
    for br in results:
        for s in (br.get('buys', []) + br.get('sells', [])):
            code = s.get('code', '').strip()
            if code and code in stock_industry:
                s['industry'] = stock_industry[code]
                count += 1
    
    return count


# ════════════════════════════════════════════════════════════════════
#  CLI 測試
# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import sys
    from pathlib import Path
    
    print("=" * 65)
    print("🧪 industry_classifier 獨立測試")
    print("=" * 65)
    
    # 測試用暫存目錄
    test_data_dir = Path('/tmp/test_industry')
    test_data_dir.mkdir(exist_ok=True)
    
    mapping = get_industry_map(test_data_dir, force_refresh=True)
    
    print("\n" + "=" * 65)
    print("📊 驗證結果")
    print("=" * 65)
    print(f"總個股數: {mapping['count']}")
    print(f"產業數: {len(mapping['industries'])}")
    
    print(f"\n=== 產業分佈 Top 10 ===")
    sorted_inds = sorted(mapping['industries'].items(), 
                        key=lambda x: -len(x[1]))
    for ind, codes in sorted_inds[:10]:
        print(f"  {ind}: {len(codes)} 檔 (樣本: {codes[:3]})")
    
    print(f"\n=== 重要個股驗證 ===")
    test_stocks = [
        ('2330', '台積電', '半導體業'),
        ('2317', '鴻海', '其他電子業'),
        ('2454', '聯發科', '半導體業'),
        ('2603', '長榮', '航運業'),
        ('2882', '國泰金', '金融保險業'),
        ('3008', '大立光', '光電業'),
        ('2412', '中華電', '通信網路業'),
        ('1301', '台塑', '塑膠工業'),
    ]
    for code, name, expected in test_stocks:
        actual = mapping['stock_industry'].get(code, '❌ 找不到')
        match = '✅' if actual == expected else '❌'
        print(f"  {match} {code} {name}: {actual} (預期: {expected})")
    
    print(f"\n快取存於: {test_data_dir / CACHE_FILE}")
