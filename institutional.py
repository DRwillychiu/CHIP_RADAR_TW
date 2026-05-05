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
                
                # 自營商 = 自行買賣 + 避險 (用合計 [11] 直接除避免整數除法 floor 誤差)
                dealer_net_self = _safe_int(row[14]) // 1000
                dealer_net_hedge = _safe_int(row[17]) // 1000
                # v3.21 修正: 用 [11] 合計直接除,避免負數 floor 誤差
                dealer_net = _safe_int(row[11]) // 1000
                
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
                time.sleep(10 + attempt * 5)  # v3.14.2: 10s → 15s → 20s
    
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
                time.sleep(10 + attempt * 5)  # v3.14.2: 10s → 15s → 20s
    
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
                time.sleep(10 + attempt * 5)  # v3.14.2: 10s → 15s → 20s
    
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
                time.sleep(10 + attempt * 5)  # v3.14.2: 10s → 15s → 20s
    
    return {}


# ════════════════════════════════════════════════════════════════════
#  整合介面（給 crawler.py 用）
# ════════════════════════════════════════════════════════════════════

def fetch_mis_fallback_quotes(missing_codes: list, batch_size=40, batch_delay=3) -> Dict[str, dict]:
    """
    v3.14.2: MIS API fallback 即時報價
    當 TWSE STOCK_DAY_ALL 失敗時，改用 mis.twse.com.tw 逐批查詢
    
    mis API 可一次查多檔：tse_2330.tw|tse_2317.tw|...
    速度快、限流少，但需要自己判斷 tse / otc 前綴
    
    Args:
        missing_codes: 要補抓的股票代號 list
        batch_size: 每批最多幾檔（太多會被截斷）
        batch_delay: 每批間隔秒數
    """
    if not missing_codes:
        return {}
    
    print(f"  [MIS Fallback] 補抓 {len(missing_codes)} 檔即時報價...")
    
    result = {}
    
    # MIS 需要分 tse_ (上市) / otc_ (上櫃)，但我們不知道每檔是上市上櫃
    # 策略：先當上市試，失敗的再當上櫃試
    
    def build_query(codes, prefix):
        return '|'.join(f"{prefix}_{c}.tw" for c in codes)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://mis.twse.com.tw/stock/index.jsp',
    }
    
    def parse_mis_batch(codes, prefix, attempt=0):
        """查一批資料並解析"""
        if not codes:
            return
        query = build_query(codes, prefix)
        url = f'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={query}&json=1&delay=0'
        try:
            r = requests.get(url, timeout=15, headers=headers)
            r.raise_for_status()
            data = r.json()
            for item in (data.get('msgArray') or []):
                code = item.get('c')
                if not code:
                    continue
                try:
                    # z = 最新成交價，但有時是 '-'（無成交）
                    close = float(item.get('z')) if item.get('z') not in ('-', '', None) else None
                    y = float(item.get('y')) if item.get('y') not in ('-', '', None) else None  # 昨收
                    if close is None and item.get('pz') not in ('-', '', None):
                        close = float(item.get('pz'))  # 買一價備援
                    open_ = float(item.get('o')) if item.get('o') not in ('-', '', None) else None
                    high = float(item.get('h')) if item.get('h') not in ('-', '', None) else None
                    low = float(item.get('l')) if item.get('l') not in ('-', '', None) else None
                    volume = int(item.get('v', 0) or 0)  # 累積成交量（張）
                    
                    change = (close - y) if (close and y) else 0.0
                    change_pct = (change / y * 100) if y else 0.0
                    
                    if close:
                        result[code] = {
                            "close": round(close, 2),
                            "open": round(open_, 2) if open_ else 0,
                            "high": round(high, 2) if high else 0,
                            "low": round(low, 2) if low else 0,
                            "volume_lot": volume,
                            "change": round(change, 2),
                            "change_pct": round(change_pct, 2),
                            "source": f"mis_{prefix}",  # 標記來源
                        }
                except (ValueError, TypeError):
                    continue
        except Exception as e:
            if attempt < 2:
                print(f"    ⚠️ MIS {prefix} 第 {attempt+1}/3 次失敗: {str(e)[:80]}")
                time.sleep(10 + attempt * 5)
                parse_mis_batch(codes, prefix, attempt + 1)
    
    # 先試上市
    for i in range(0, len(missing_codes), batch_size):
        batch = missing_codes[i:i+batch_size]
        parse_mis_batch(batch, 'tse')
        if i + batch_size < len(missing_codes):
            time.sleep(batch_delay)  # 批次間 delay
    
    # 沒抓到的再試上櫃
    still_missing = [c for c in missing_codes if c not in result]
    if still_missing:
        print(f"    → 上市抓到 {len(result)} 檔，剩 {len(still_missing)} 檔試上櫃")
        for i in range(0, len(still_missing), batch_size):
            batch = still_missing[i:i+batch_size]
            parse_mis_batch(batch, 'otc')
            if i + batch_size < len(still_missing):
                time.sleep(batch_delay)
    
    print(f"  [MIS Fallback] ✓ 成功補抓 {len(result)} 檔")
    return result


def fetch_all_public_data(trade_date: str, priority_codes=None):
    """
    抓全部公開資訊：三大法人 + 收盤行情
    
    v3.14.2 升級:
      - 查詢間 delay 從 1.5s → 5s
      - TWSE/TPEx daily_quotes 失敗時，用 MIS API fallback 補抓
    
    Args:
        trade_date: 日期
        priority_codes: 優先補抓的個股代號 list（例如我的分點出現的股票）
    
    Returns:
        (institutional_map, daily_quotes_map)
    """
    print("[公開資訊] 抓取三大法人 + 收盤行情 (v3.14.2 增強版限流處理)...")
    
    # 三大法人
    print("  [1/4] TWSE 上市三大法人 (T86)...")
    twse_insti = fetch_twse_t86(trade_date)
    print(f"    ✓ {len(twse_insti)} 檔")
    time.sleep(5)   # v3.14.2: 1.5s → 5s
    
    print("  [2/4] TPEx 上櫃三大法人...")
    tpex_insti = fetch_tpex_3insti()
    print(f"    ✓ {len(tpex_insti)} 檔")
    time.sleep(5)
    
    # 收盤行情
    print("  [3/4] TWSE 上市收盤行情...")
    twse_quotes = fetch_twse_daily_quotes()
    print(f"    ✓ {len(twse_quotes)} 檔")
    time.sleep(5)
    
    print("  [4/4] TPEx 上櫃收盤行情...")
    tpex_quotes = fetch_tpex_daily_quotes()
    print(f"    ✓ {len(tpex_quotes)} 檔")
    
    # 合併（上櫃優先級較低，上市會覆蓋）
    institutional = {**tpex_insti, **twse_insti}
    quotes = {**tpex_quotes, **twse_quotes}
    
    # v3.14.2 Fallback：如果 quotes 太少 且有 priority_codes（我的分點出現的股票）
    # 用 MIS API 補抓
    fallback_count = 0
    if priority_codes:
        missing = [c for c in priority_codes if c not in quotes]
        if missing:
            # 只在主 API 大量失敗時 fallback（避免每次都打）
            total_expected = 2000  # TWSE + TPEx 合計應該 >2000 檔
            if len(quotes) < total_expected or len(missing) > 20:
                print(f"  [!] 主 API 取得 {len(quotes)} 檔 (預期 >{total_expected})")
                print(f"      我的分點股票中有 {len(missing)} 檔缺行情 → 啟動 MIS Fallback")
                time.sleep(5)
                mis_quotes = fetch_mis_fallback_quotes(missing)
                quotes.update(mis_quotes)
                fallback_count = len(mis_quotes)
    
    print(f"[公開資訊] ✓ 三大法人 {len(institutional)} 檔 / 收盤 {len(quotes)} 檔" +
          (f" (MIS fallback 補 {fallback_count} 檔)" if fallback_count else ""))
    
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
