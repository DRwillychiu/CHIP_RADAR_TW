"""
========================================================================
Module: market_classifier.py
功能：股票市場類型分類（ETF / 上市 / 上櫃 / 興櫃 / KY / 特別股）

設計原則：
  - 優先用本地規則判定（離線可運作）
  - 必要時呼叫 TWSE/TPEx 公開 API 補資料
  - 分類結果快取避免重複請求
  - 處理「興櫃轉上櫃」「無法分類」等異常情況

8 種細緻分類:
  - listed       上市
  - listed_ky    上市-KY 外國第一上市
  - otc          上櫃
  - otc_ky       上櫃-KY
  - emerging     興櫃
  - etf          ETF（含 ETN/REITs）
  - etf_active   主動型 ETF
  - preferred    特別股
  - unknown      無法分類（新上市、已下市、創新版等）

5 種簡單分類 (前端顯示用):
  - listed (含 listed_ky)
  - otc (含 otc_ky)
  - emerging
  - etf (含 etf_active)
  - others (preferred + unknown)

3 種最簡分類:
  - stock (listed + otc + emerging + 各種 KY)
  - etf
  - others
========================================================================
"""

import re
import json
import requests
import time
from pathlib import Path

# ════════════════════════════════════════════════════════════════════
#  資料來源 API
# ════════════════════════════════════════════════════════════════════

TWSE_LISTED_API = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"   # 上市公司
TPEX_OTC_API = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"   # 上櫃公司
TPEX_EMERGING_API = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R"  # 興櫃公司

# ETF 名稱關鍵字（補強 00 開頭判定）
ETF_KEYWORDS = ['ETF', 'ETN', 'REITs', 'REIT', '指數', '正2', '反1', '槓桿', '反向']
ACTIVE_ETF_SUFFIXES = ['A']  # 主動型 ETF 代碼結尾


# ════════════════════════════════════════════════════════════════════
#  本地規則判定（不需網路）
# ════════════════════════════════════════════════════════════════════

def classify_by_rule(code: str, name: str = "") -> str:
    """
    純本地規則判定，回傳 8 種細緻分類之一
    若無法確定上市/上櫃，回傳 'unknown' 等待 API 補資料
    """
    if not code:
        return "unknown"
    
    code = code.strip()
    name = (name or "").strip()
    
    # ── 規則 1：00 開頭 → ETF 類 ──
    if code.startswith('00'):
        # 主動型 ETF（XXXXXA 結尾）
        if code.endswith('A') and len(code) == 6:
            return "etf_active"
        return "etf"
    
    # ── 規則 2：四位數字 + 字母 → 特別股 ──
    if len(code) == 5 and code[:4].isdigit() and code[4].isalpha():
        # 排除主動型 ETF 已在上面處理
        # 例: 2887I, 2883B
        return "preferred"
    
    # ── 規則 3：KY 外國企業（看名稱）──
    is_ky = "-KY" in name or name.endswith("KY")
    
    # ── 規則 4：四碼純數字 → 需查 API 才知上市/上櫃 ──
    if code.isdigit() and len(code) == 4:
        if is_ky:
            return "listed_ky"  # 預設 KY 是上市，後續 API 修正
        return "unknown"  # 等待 API 補
    
    # ── 規則 5：其他特殊情況 ──
    if name.endswith("*"):
        # 全額交割 / 特殊註記，視為一般股票（unknown 等 API）
        return "unknown"
    
    return "unknown"


# ════════════════════════════════════════════════════════════════════
#  從官方 API 抓取分類清單
# ════════════════════════════════════════════════════════════════════

def fetch_twse_listed(timeout=30):
    """抓上市公司清單"""
    try:
        r = requests.get(TWSE_LISTED_API, timeout=timeout, 
                         headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        data = r.json()
        result = {}
        for item in data:
            code = (item.get('公司代號') or '').strip()
            if code:
                result[code] = {
                    'category': 'listed',
                    'name': (item.get('公司簡稱') or item.get('公司名稱') or '').strip(),
                    'industry': (item.get('產業別') or '').strip(),
                    'foreign': (item.get('外國企業註冊地國') or '').strip(),
                }
        return result
    except Exception as e:
        print(f"  ⚠️ TWSE 上市清單抓取失敗: {e}")
        return {}


def fetch_tpex_otc(timeout=30):
    """抓上櫃公司清單"""
    try:
        r = requests.get(TPEX_OTC_API, timeout=timeout,
                         headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        data = r.json()
        result = {}
        for item in data:
            code = (item.get('SecuritiesCompanyCode') or '').strip()
            if code:
                result[code] = {
                    'category': 'otc',
                    'name': (item.get('CompanyAbbreviation') or item.get('CompanyName') or '').strip(),
                    'industry': (item.get('SecuritiesIndustryCode') or '').strip(),
                    'foreign': '',
                }
        return result
    except Exception as e:
        print(f"  ⚠️ TPEx 上櫃清單抓取失敗: {e}")
        return {}


def fetch_tpex_emerging(timeout=30):
    """抓興櫃公司清單"""
    try:
        r = requests.get(TPEX_EMERGING_API, timeout=timeout,
                         headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        data = r.json()
        result = {}
        for item in data:
            code = (item.get('SecuritiesCompanyCode') or '').strip()
            if code:
                result[code] = {
                    'category': 'emerging',
                    'name': (item.get('CompanyAbbreviation') or item.get('CompanyName') or '').strip(),
                    'industry': (item.get('SecuritiesIndustryCode') or '').strip(),
                    'foreign': '',
                }
        return result
    except Exception as e:
        print(f"  ⚠️ TPEx 興櫃清單抓取失敗: {e}")
        return {}


def fetch_all_classifications():
    """
    抓取全部分類清單
    回傳: {code: {category, name, industry, foreign}}
    
    注意處理優先順序：
    1. 興櫃 → 上櫃 → 上市（避免「興櫃轉上櫃」時兩邊都有，以最新狀態為準）
    """
    print("[市場分類] 從 TWSE/TPEx 抓取最新清單...")
    classifications = {}
    
    # 先抓興櫃（最舊狀態）
    emerging = fetch_tpex_emerging()
    classifications.update(emerging)
    print(f"  ✓ 興櫃 {len(emerging)} 家")
    
    time.sleep(1)
    
    # 再抓上櫃（覆蓋興櫃，因為興櫃轉上櫃後就是上櫃）
    otc = fetch_tpex_otc()
    classifications.update(otc)
    print(f"  ✓ 上櫃 {len(otc)} 家")
    
    time.sleep(1)
    
    # 最後抓上市（覆蓋上櫃，因為上櫃轉上市後就是上市）
    listed = fetch_twse_listed()
    classifications.update(listed)
    print(f"  ✓ 上市 {len(listed)} 家")
    
    return classifications


# ════════════════════════════════════════════════════════════════════
#  整合判定（規則 + API）
# ════════════════════════════════════════════════════════════════════

def classify_stock(code: str, name: str, api_data: dict = None) -> dict:
    """
    完整判定一檔股票的分類資訊
    
    Args:
        code: 股票代碼
        name: 股票名稱
        api_data: 從 fetch_all_classifications 拿到的對照表（可為空）
    
    Returns:
        {
            "category": "listed/otc/emerging/etf/...",
            "category_simple": "listed/otc/emerging/etf/others",  # 5 類
            "category_basic": "stock/etf/others",                  # 3 類
            "industry": "...",
            "is_ky": bool,
            "source": "rule" or "api",
        }
    """
    # 第一步：本地規則
    cat = classify_by_rule(code, name)
    industry = ""
    source = "rule"
    is_ky = "-KY" in name or name.endswith("KY")
    
    # 第二步：若是 unknown 且有 API 資料，補查
    if cat == "unknown" and api_data and code in api_data:
        info = api_data[code]
        cat = info.get('category', 'unknown')
        industry = info.get('industry', '')
        source = "api"
        # 如果是 KY 股，調整成 KY 變體
        if is_ky:
            if cat == "listed":
                cat = "listed_ky"
            elif cat == "otc":
                cat = "otc_ky"
    
    # 第三步：即使本地判到了 listed_ky/etf 等，仍嘗試補上 industry
    if cat != "unknown" and api_data and code in api_data:
        api_info = api_data[code]
        if not industry:
            industry = api_info.get('industry', '')
    
    return {
        "category": cat,
        "category_simple": _to_simple(cat),
        "category_basic": _to_basic(cat),
        "industry": industry,
        "is_ky": is_ky,
        "source": source,
    }


def _to_simple(category: str) -> str:
    """8 類 → 5 類"""
    mapping = {
        "listed": "listed", "listed_ky": "listed",
        "otc": "otc", "otc_ky": "otc",
        "emerging": "emerging",
        "etf": "etf", "etf_active": "etf",
        "preferred": "others", "unknown": "others",
    }
    return mapping.get(category, "others")


def _to_basic(category: str) -> str:
    """8 類 → 3 類"""
    mapping = {
        "listed": "stock", "listed_ky": "stock",
        "otc": "stock", "otc_ky": "stock",
        "emerging": "stock",
        "etf": "etf", "etf_active": "etf",
        "preferred": "others", "unknown": "others",
    }
    return mapping.get(category, "others")


# ════════════════════════════════════════════════════════════════════
#  快取管理
# ════════════════════════════════════════════════════════════════════

def load_cache(cache_file: Path):
    """載入分類快取"""
    if not cache_file.exists():
        return None, None
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('classifications', {}), data.get('updated_date', '')
    except Exception:
        return None, None


def save_cache(cache_file: Path, classifications: dict, updated_date: str):
    """儲存分類快取（明文，因為都是公開資訊）"""
    cache_file.parent.mkdir(exist_ok=True)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump({
            'updated_date': updated_date,
            'count': len(classifications),
            'classifications': classifications,
        }, f, ensure_ascii=False, indent=2)


def should_refresh_cache(updated_date: str, today: str, max_age_days: int = 7) -> bool:
    """
    判斷是否該重新抓 API
    預設每 7 天更新一次（週一更新較合適）
    """
    if not updated_date:
        return True
    try:
        from datetime import datetime
        last = datetime.strptime(updated_date, "%Y%m%d")
        now = datetime.strptime(today, "%Y%m%d")
        return (now - last).days >= max_age_days
    except Exception:
        return True


# ════════════════════════════════════════════════════════════════════
#  公開介面（給 crawler.py 用）
# ════════════════════════════════════════════════════════════════════

def get_classifier(data_dir: Path, today: str, force_refresh: bool = False):
    """
    取得分類器（自動處理快取）
    
    Returns: 一個函數 `classify(code, name) -> dict`
    """
    cache_file = data_dir / "stock_categories.json"
    api_data, last_update = load_cache(cache_file)
    
    if force_refresh or should_refresh_cache(last_update, today):
        print(f"[市場分類] 快取過期或不存在（last={last_update}），更新中...")
        api_data = fetch_all_classifications()
        if api_data:
            save_cache(cache_file, api_data, today)
            print(f"[市場分類] ✓ 已快取 {len(api_data)} 檔")
        else:
            print("[市場分類] ⚠️ API 全部失敗，仍可用本地規則判定")
            api_data = api_data or {}
    else:
        print(f"[市場分類] 使用快取（{last_update}, 共 {len(api_data)} 檔）")
    
    def classify(code: str, name: str = "") -> dict:
        return classify_stock(code, name, api_data)
    
    return classify, api_data


# ════════════════════════════════════════════════════════════════════
#  分類標籤的中文名稱（給前端用）
# ════════════════════════════════════════════════════════════════════

CATEGORY_LABELS = {
    "listed":     "上市",
    "listed_ky":  "上市-KY",
    "otc":        "上櫃",
    "otc_ky":     "上櫃-KY",
    "emerging":   "興櫃",
    "etf":        "ETF",
    "etf_active": "主動型ETF",
    "preferred":  "特別股",
    "unknown":    "未分類",
}

CATEGORY_LABELS_SIMPLE = {
    "listed":   "上市",
    "otc":      "上櫃",
    "emerging": "興櫃",
    "etf":      "ETF",
    "others":   "其他",
}
