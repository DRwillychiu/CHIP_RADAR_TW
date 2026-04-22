"""
========================================================================
Module: institutional.py  (v3.7 新增)
功能：公開資訊觀測站資料整合
  - TWSE T86      上市三大法人買賣超（個股）
  - TPEx 3insti   上櫃三大法人買賣超（個股）
  - STOCK_DAY_ALL 上市每日收盤行情（量價、均價）
  - TPEx Daily    上櫃每日收盤行情

設計原則：
  - 純資料模組，不處理顯示邏輯
  - 失敗時優雅降級（只要分點爬蟲成功，法人資料失敗不影響主流程）
  - 回傳統一格式，供 crawler.py 整合

三大法人資料結構（回傳格式）：
    {
        "2330": {
            "foreign_buy_lot": 1200,       # 外資買張
            "foreign_sell_lot": 300,
            "foreign_net_lot": 900,
            "foreign_net_amt_wan": 18000.0, # 外資淨買萬（需配合收盤價計算）
            "trust_buy_lot": 50,
            "trust_sell_lot": 80,
            "trust_net_lot": -30,
            "dealer_net_lot": 80,
            "dealer_net_amt_wan": 1200.0,
            "total_net_lot": 950,          # 三大法人合計
        }
    }

收盤行情資料結構：
    {
        "2330": {
            "close": 2110.0,     # 今收
            "open": 2095.0,
            "high": 2115.0,
            "low": 2088.0,
            "volume_lot": 12500, # 成交張數
            "change": 15.0,      # 漲跌
            "change_pct": 0.72,  # 漲跌%
        }
    }
========================================================================
"""

import requests
import time
from typing import Dict, Optional

# ════════════════════════════════════════════════════════════════════
#  API Endpoints
# ════════════════════════════════════════════════════════════════════

TWSE_T86_URL = "https://www.twse.com.tw/fund/T86"
TPEX_3INSTI_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
TWSE_STOCK_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAILY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


# ════════════════════════════════════════════════════════════════════
#  輔助函數
# ════════════════════════════════════════════════════════════════════

def _safe_int(val, default=0):
    """將帶千分位的字串轉為 int"""
    if val is None or val == '':
        return default
    try:
        s = str(val).replace(',', '').replace(' ', '').strip()
        if s in ('--', '-', 'N/A', ''):
            return default
        return int(float(s))
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0):
    """將帶千分位的字串轉為 float"""
    if val is None or val == '':
        return default
    try:
        s = str(val).replace(',', '').replace(' ', '').strip()
        if s in ('--', '-', 'N/A', ''):
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


# ════════════════════════════════════════════════════════════════════
#  TWSE 上市三大法人（T86）
# ════════════════════════════════════════════════════════════════════

def fetch_twse_t86(trade_date: str, timeout=30, retries=3) -> Dict[str, dict]:
    """
    抓 TWSE 上市股票的三大法人買賣超日報
    
    Args:
        trade_date: "20260421" 格式
        
    Returns:
        {code: {foreign_buy_lot, foreign_net_lot, trust_net_lot, dealer_net_lot, total_net_lot}}
    """
    url = f"{TWSE_T86_URL}?response=json&date={trade_date}&selectType=ALL"
    
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout, headers=DEFAULT_HEADERS)
            r.raise_for_status()
            d = r.json()
            
            if d.get('stat') != 'OK':
                print(f"  ⚠️ TWSE T86 狀態非 OK: {d.get('stat', '未知')}")
                return {}
            
            data = d.get('data', [])
            fields = d.get('fields', [])
            
            # 欄位 index 參考（19 個欄位）
            # [0] 證券代號  [2] 外陸資買進股數(不含外資自營商)  [3] 外陸資賣出
            # [4] 外陸資買賣超  [5-7] 外資自營商  [8-10] 投信
            # [14] 自營商買賣超(自行買賣)  [17] 自營商買賣超(避險)
            # [18] 三大法人買賣超股數（合計）
            
            result = {}
            for row in data:
                if len(row) < 19:
                    continue
                code = str(row[0]).strip()
                if not code:
                    continue
                
                # 股數 → 張（除以 1000）
                foreign_buy = _safe_int(row[2]) // 1000       # 外陸資買張（主力）
                foreign_sell = _safe_int(row[3]) // 1000
                foreign_net = _safe_int(row[4]) // 1000        # 外陸資淨買張
                # 外資自營商（通常小，可忽略或合併）
                foreign_dealer_net = _safe_int(row[7]) // 1000
                
                trust_buy = _safe_int(row[8]) // 1000
                trust_sell = _safe_int(row[9]) // 1000
                trust_net = _safe_int(row[10]) // 1000
                
                # 自營商 = 自行買賣 + 避險
                dealer_net_self = _safe_int(row[14]) // 1000
                dealer_net_hedge = _safe_int(row[17]) // 1000
                dealer_net = dealer_net_self + dealer_net_hedge
                
                total_net = _safe_int(row[18]) // 1000
                
                # 外資合計（含自營商）
                foreign_total_net = foreign_net + foreign_dealer_net
                
                result[code] = {
                    "foreign_buy_lot": foreign_buy,
                    "foreign_sell_lot": foreign_sell,
                    "foreign_net_lot": foreign_total_net,
                    "trust_buy_lot": trust_buy,
                    "trust_sell_lot": trust_sell,
                    "trust_net_lot": trust_net,
                    "dealer_net_lot": dealer_net,
                    "total_net_lot": total_net,
                    "source": "twse",
                }
            
            return result
            
        except Exception as e:
            print(f"  ⚠️ TWSE T86 第 {attempt+1}/{retries} 次失敗: {e}")
            if attempt < retries - 1:
                time.sleep(3 + attempt * 2)
    
    return {}


# ════════════════════════════════════════════════════════════════════
#  TPEx 上櫃三大法人
# ════════════════════════════════════════════════════════════════════

def fetch_tpex_3insti(timeout=30, retries=3) -> Dict[str, dict]:
    """
    抓 TPEx 上櫃股票的三大法人買賣超
    Returns: 與 fetch_twse_t86 相同結構（單位：張）
    
    注意：TPEx API 原始欄位含不規則空白與拼寫，以下欄位是實測可用的。
    """
    for attempt in range(retries):
        try:
            r = requests.get(TPEX_3INSTI_URL, timeout=timeout, headers=DEFAULT_HEADERS)
            r.raise_for_status()
            data = r.json()
            
            result = {}
            for item in data:
                code = (item.get('SecuritiesCompanyCode') or '').strip()
                if not code:
                    continue
                
                # 外資（含陸資，不含外資自營商）
                foreign_buy = _safe_int(item.get(
                    'Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy')) // 1000
                foreign_sell = _safe_int(item.get(
                    ' Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell')) // 1000
                foreign_net = _safe_int(item.get(
                    'Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference')) // 1000
                
                # 外資自營商
                foreign_dealer_net = _safe_int(item.get('ForeignDealers-Difference')) // 1000
                
                # 投信（實測欄位名是 SecuritiesInvestmentTrustCompanies）
                trust_buy = _safe_int(item.get('SecuritiesInvestmentTrustCompanies-TotalBuy')) // 1000
                trust_sell = _safe_int(item.get('SecuritiesInvestmentTrustCompanies-TotalSell')) // 1000
                trust_net = _safe_int(item.get('SecuritiesInvestmentTrustCompanies-Difference')) // 1000
                
                # 自營商（TPEx 合計不細分自行/避險）
                dealer_net = _safe_int(item.get('Dealers-Difference')) // 1000
                
                total_net = _safe_int(item.get('TotalDifference')) // 1000
                
                result[code] = {
                    "foreign_buy_lot": foreign_buy,
                    "foreign_sell_lot": foreign_sell,
                    "foreign_net_lot": foreign_net + foreign_dealer_net,
                    "trust_buy_lot": trust_buy,
                    "trust_sell_lot": trust_sell,
                    "trust_net_lot": trust_net,
                    "dealer_net_lot": dealer_net,
                    "total_net_lot": total_net,
                    "source": "tpex",
                }
            
            return result
            
        except Exception as e:
            print(f"  ⚠️ TPEx 3insti 第 {attempt+1}/{retries} 次失敗: {e}")
            if attempt < retries - 1:
                time.sleep(3 + attempt * 2)
    
    return {}


# ════════════════════════════════════════════════════════════════════
#  TWSE 上市收盤行情
# ════════════════════════════════════════════════════════════════════

def fetch_twse_daily_quotes(timeout=30, retries=3) -> Dict[str, dict]:
    """
    抓 TWSE 上市股票當日收盤行情
    
    Returns:
        {code: {close, open, high, low, volume_lot, change, change_pct}}
    """
    for attempt in range(retries):
        try:
            r = requests.get(TWSE_STOCK_DAY_ALL_URL, timeout=timeout, headers=DEFAULT_HEADERS)
            r.raise_for_status()
            data = r.json()
            
            result = {}
            for item in data:
                code = (item.get('Code') or '').strip()
                if not code:
                    continue
                
                close = _safe_float(item.get('ClosingPrice'))
                open_ = _safe_float(item.get('OpeningPrice'))
                high = _safe_float(item.get('HighestPrice'))
                low = _safe_float(item.get('LowestPrice'))
                volume = _safe_int(item.get('TradeVolume'))  # 股數
                change = _safe_float(item.get('Change'))
                
                prev_close = close - change if change else close
                change_pct = (change / prev_close * 100) if prev_close else 0.0
                
                result[code] = {
                    "close": close,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "volume_lot": volume // 1000,
                    "change": change,
                    "change_pct": round(change_pct, 2),
                    "source": "twse",
                }
            
            return result
            
        except Exception as e:
            print(f"  ⚠️ TWSE daily quotes 第 {attempt+1}/{retries} 次失敗: {e}")
            if attempt < retries - 1:
                time.sleep(3 + attempt * 2)
    
    return {}


# ════════════════════════════════════════════════════════════════════
#  TPEx 上櫃收盤行情
# ════════════════════════════════════════════════════════════════════

def fetch_tpex_daily_quotes(timeout=30, retries=3) -> Dict[str, dict]:
    """抓 TPEx 上櫃股票當日收盤行情"""
    for attempt in range(retries):
        try:
            r = requests.get(TPEX_DAILY_URL, timeout=timeout, headers=DEFAULT_HEADERS)
            r.raise_for_status()
            data = r.json()
            
            result = {}
            for item in data:
                code = (item.get('SecuritiesCompanyCode') or '').strip()
                if not code:
                    continue
                
                close = _safe_float(item.get('Close'))
                open_ = _safe_float(item.get('Open'))
                high = _safe_float(item.get('High'))
                low = _safe_float(item.get('Low'))
                volume = _safe_int(item.get('TradingShares'))
                change = _safe_float(item.get('Change'))
                
                prev_close = close - change if change else close
                change_pct = (change / prev_close * 100) if prev_close else 0.0
                
                result[code] = {
                    "close": close,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "volume_lot": volume // 1000,
                    "change": change,
                    "change_pct": round(change_pct, 2),
                    "source": "tpex",
                }
            
            return result
            
        except Exception as e:
            print(f"  ⚠️ TPEx daily quotes 第 {attempt+1}/{retries} 次失敗: {e}")
            if attempt < retries - 1:
                time.sleep(3 + attempt * 2)
    
    return {}


# ════════════════════════════════════════════════════════════════════
#  整合介面（給 crawler.py 用）
# ════════════════════════════════════════════════════════════════════

def fetch_all_public_data(trade_date: str):
    """
    抓全部公開資訊：三大法人 + 收盤行情
    
    Returns:
        (institutional_map, daily_quotes_map)
        institutional_map: {code: 三大法人資料}
        daily_quotes_map:  {code: 收盤行情資料}
    """
    print("[公開資訊] 抓取三大法人 + 收盤行情...")
    
    # 三大法人
    print("  [1/4] TWSE 上市三大法人 (T86)...")
    twse_insti = fetch_twse_t86(trade_date)
    print(f"    ✓ {len(twse_insti)} 檔")
    time.sleep(1.5)
    
    print("  [2/4] TPEx 上櫃三大法人...")
    tpex_insti = fetch_tpex_3insti()
    print(f"    ✓ {len(tpex_insti)} 檔")
    time.sleep(1.5)
    
    # 收盤行情
    print("  [3/4] TWSE 上市收盤行情...")
    twse_quotes = fetch_twse_daily_quotes()
    print(f"    ✓ {len(twse_quotes)} 檔")
    time.sleep(1.5)
    
    print("  [4/4] TPEx 上櫃收盤行情...")
    tpex_quotes = fetch_tpex_daily_quotes()
    print(f"    ✓ {len(tpex_quotes)} 檔")
    
    # 合併（上櫃優先級較低，上市會覆蓋）
    institutional = {**tpex_insti, **twse_insti}
    quotes = {**tpex_quotes, **twse_quotes}
    
    print(f"[公開資訊] ✓ 三大法人 {len(institutional)} 檔 / 收盤 {len(quotes)} 檔")
    
    return institutional, quotes


# ════════════════════════════════════════════════════════════════════
#  針對某檔計算各種有用的衍生資訊
# ════════════════════════════════════════════════════════════════════

def compute_alignment(branch_net_lot: int, foreign_net_lot: int) -> str:
    """
    判斷分點 vs 外資同向/反向
    
    Returns:
        "aligned"   → 同向（都買或都賣）
        "opposing"  → 反向
        "neutral"   → 一方資料不足
    """
    if abs(branch_net_lot) < 1 or abs(foreign_net_lot) < 1:
        return "neutral"
    if (branch_net_lot > 0 and foreign_net_lot > 0) or \
       (branch_net_lot < 0 and foreign_net_lot < 0):
        return "aligned"
    return "opposing"


def compute_floating_pnl_pct(buy_avg: float, current_close: float) -> float:
    """計算浮盈百分比"""
    if not buy_avg or not current_close:
        return 0.0
    return round((current_close - buy_avg) / buy_avg * 100, 2)
