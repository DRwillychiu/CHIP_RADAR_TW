"""
========================================================================
Module: margin.py  (v3.11 新增)
功能：融資融券資料整合

資料源：
  - TWSE 上市: https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN (1260 檔)
  - TPEx 上櫃: https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance (896 檔)

設計原則：
  - 失敗時優雅降級（融資資料是輔助，不影響主流程）
  - 欄位統一為英文 key（內部使用）
  - 每筆輸出包含計算後的衍生指標（使用率、資券變化）

輸出格式（每檔個股）：
  {
    "code": "2330",
    "name": "台積電",
    "market": "listed" | "otc",
    
    # 融資
    "margin_buy":        int,  # 今日融資買進（張）
    "margin_sell":       int,  # 今日融資賣出
    "margin_redeem":     int,  # 融資現金償還
    "margin_balance":    int,  # 融資今日餘額
    "margin_prev":       int,  # 融資前日餘額
    "margin_change":     int,  # 融資變化 (今日 - 前日)
    "margin_quota":      int,  # 融資限額
    "margin_usage":      float, # 融資使用率 (%)
    
    # 融券
    "short_buy":         int,  # 今日融券買進
    "short_sell":        int,  # 今日融券賣出
    "short_redeem":      int,  # 融券現券償還
    "short_balance":     int,  # 融券今日餘額
    "short_prev":        int,  # 融券前日餘額
    "short_change":      int,  # 融券變化
    "short_quota":       int,  # 融券限額
    "short_usage":       float, # 融券使用率
    
    # 資券互抵（當沖熱度）
    "offsetting":        int,  # 資券互抵（張）
    
    # 衍生指標
    "margin_short_ratio": float, # 券資比 = 融券/融資 (%)
  }
========================================================================
"""

import json
import time
import requests
from typing import Dict, Any, Optional


# ════════════════════════════════════════════════════════════════════
#  抓取 TWSE 上市融資融券
# ════════════════════════════════════════════════════════════════════

def fetch_twse_margin(timeout: int = 20, max_retries: int = 3) -> Dict[str, Dict[str, Any]]:
    """
    抓 TWSE 上市融資融券
    
    Returns: {code: {...融資融券資料...}}
    """
    url = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
    for attempt in range(max_retries):
        try:
            r = requests.get(
                url, 
                timeout=timeout,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            r.raise_for_status()
            raw_data = r.json()
            break
        except Exception as e:
            print(f"  ⚠️ TWSE Margin 第 {attempt+1}/{max_retries} 次失敗: {e}")
            if attempt == max_retries - 1:
                return {}
            time.sleep(10 + attempt * 5)  # v3.14.3: 10s → 15s → 20s
    
    result = {}
    for row in raw_data:
        code = row.get('股票代號', '').strip()
        if not code:
            continue
        
        try:
            margin_bal = _parse_int(row.get('融資今日餘額'))
            margin_prev = _parse_int(row.get('融資前日餘額'))
            margin_quota = _parse_int(row.get('融資限額'))
            short_bal = _parse_int(row.get('融券今日餘額'))
            short_prev = _parse_int(row.get('融券前日餘額'))
            short_quota = _parse_int(row.get('融券限額'))
            
            # 計算使用率
            margin_usage = (margin_bal / margin_quota * 100) if margin_quota > 0 else 0.0
            short_usage = (short_bal / short_quota * 100) if short_quota > 0 else 0.0
            # 券資比
            ms_ratio = (short_bal / margin_bal * 100) if margin_bal > 0 else 0.0
            
            result[code] = {
                'code': code,
                'name': row.get('股票名稱', '').strip(),
                'market': 'listed',
                
                'margin_buy': _parse_int(row.get('融資買進')),
                'margin_sell': _parse_int(row.get('融資賣出')),
                'margin_redeem': _parse_int(row.get('融資現金償還')),
                'margin_balance': margin_bal,
                'margin_prev': margin_prev,
                'margin_change': margin_bal - margin_prev,
                'margin_quota': margin_quota,
                'margin_usage': round(margin_usage, 2),
                
                'short_buy': _parse_int(row.get('融券買進')),
                'short_sell': _parse_int(row.get('融券賣出')),
                'short_redeem': _parse_int(row.get('融券現券償還')),
                'short_balance': short_bal,
                'short_prev': short_prev,
                'short_change': short_bal - short_prev,
                'short_quota': short_quota,
                'short_usage': round(short_usage, 2),
                
                'offsetting': _parse_int(row.get('資券互抵')),
                'margin_short_ratio': round(ms_ratio, 2),
            }
        except Exception as e:
            print(f"  ⚠️ 解析 TWSE {code} 失敗: {e}")
            continue
    
    return result


# ════════════════════════════════════════════════════════════════════
#  抓取 TPEx 上櫃融資融券
# ════════════════════════════════════════════════════════════════════

def fetch_tpex_margin(timeout: int = 20, max_retries: int = 3) -> Dict[str, Dict[str, Any]]:
    """
    抓 TPEx 上櫃融資融券
    """
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"
    for attempt in range(max_retries):
        try:
            r = requests.get(
                url,
                timeout=timeout,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            r.raise_for_status()
            raw_data = r.json()
            break
        except Exception as e:
            print(f"  ⚠️ TPEx Margin 第 {attempt+1}/{max_retries} 次失敗: {e}")
            if attempt == max_retries - 1:
                return {}
            time.sleep(10 + attempt * 5)  # v3.14.3: 10s → 15s → 20s
    
    result = {}
    for row in raw_data:
        code = row.get('SecuritiesCompanyCode', '').strip()
        if not code:
            continue
        
        try:
            margin_bal = _parse_int(row.get('MarginPurchaseBalance'))
            margin_prev = _parse_int(row.get('MarginPurchaseBalancePreviousDay'))
            margin_quota = _parse_int(row.get('MarginPurchaseQuota'))
            short_bal = _parse_int(row.get('ShortSaleBalance'))
            short_prev = _parse_int(row.get('ShortSaleBalancePreviousDay'))
            short_quota = _parse_int(row.get('ShortSaleQuota'))
            
            # TPEx 直接給使用率（但需轉換：0.27 應為 2.7%）
            margin_usage_raw = row.get('MarginPurchaseUtilizationRate')
            short_usage_raw = row.get('ShortSaleUtilizationRate')
            
            # 自己算比較可靠
            margin_usage = (margin_bal / margin_quota * 100) if margin_quota > 0 else 0.0
            short_usage = (short_bal / short_quota * 100) if short_quota > 0 else 0.0
            ms_ratio = (short_bal / margin_bal * 100) if margin_bal > 0 else 0.0
            
            result[code] = {
                'code': code,
                'name': row.get('CompanyName', '').strip(),
                'market': 'otc',
                
                'margin_buy': _parse_int(row.get('MarginPurchase')),
                'margin_sell': _parse_int(row.get('MarginSales')),
                'margin_redeem': _parse_int(row.get('CashRedemption')),
                'margin_balance': margin_bal,
                'margin_prev': margin_prev,
                'margin_change': margin_bal - margin_prev,
                'margin_quota': margin_quota,
                'margin_usage': round(margin_usage, 2),
                
                'short_buy': _parse_int(row.get('ShortSale')),
                'short_sell': _parse_int(row.get('ShortConvering')),  # TPEx 欄位名
                'short_redeem': _parse_int(row.get('StockRedemption')),
                'short_balance': short_bal,
                'short_prev': short_prev,
                'short_change': short_bal - short_prev,
                'short_quota': short_quota,
                'short_usage': round(short_usage, 2),
                
                'offsetting': _parse_int(row.get('Offsetting')),
                'margin_short_ratio': round(ms_ratio, 2),
            }
        except Exception as e:
            print(f"  ⚠️ 解析 TPEx {code} 失敗: {e}")
            continue
    
    return result


# ════════════════════════════════════════════════════════════════════
#  統一介面：一次抓完上市+上櫃
# ════════════════════════════════════════════════════════════════════

def fetch_all_margin() -> Dict[str, Dict[str, Any]]:
    """
    一次抓完上市 + 上櫃融資融券
    v3.14.3: 加入查詢間 5 秒 delay 避免限流
    
    Returns: 合併後的 {code: margin_data} 字典
    """
    print("  [1/2] TWSE 上市融資融券...")
    twse = fetch_twse_margin()
    print(f"    ✓ {len(twse)} 檔")
    
    time.sleep(5)  # v3.14.3: 查詢間 delay 避免 TPEx 被連續打到限流
    
    print("  [2/2] TPEx 上櫃融資融券...")
    tpex = fetch_tpex_margin()
    print(f"    ✓ {len(tpex)} 檔")
    
    # 合併（TWSE 優先，TPEx 補）
    merged = {**tpex, **twse}
    print(f"  [合計] 總共 {len(merged)} 檔融資融券資料")
    return merged


# ════════════════════════════════════════════════════════════════════
#  工具函數
# ════════════════════════════════════════════════════════════════════

def _parse_int(val) -> int:
    """容錯解析字串為整數"""
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    s = str(val).strip().replace(',', '')
    if not s or s == '-' or s == '.':
        return 0
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return 0


# ════════════════════════════════════════════════════════════════════
#  智慧混合策略：只存有價值的個股
# ════════════════════════════════════════════════════════════════════

def select_target_codes(all_margin: Dict[str, Dict[str, Any]],
                        my_branch_codes: set,
                        top_n: int = 100) -> set:
    """
    智慧混合策略：選出要存加密 JSON 的個股代號
    
    策略：
      1. 我的分點有交易的個股：全部存
      2. 融資變化 Top 100（絕對值最大）：散戶情緒熱點
      3. 融資使用率 Top 50（>50%）：過熱警示
      4. 券資比 Top 50：軋空潛力股
    
    Args:
        all_margin: fetch_all_margin() 的結果
        my_branch_codes: 我的分點今日有交易的個股代號集合
        top_n: Top N 融資變化（預設 100）
    
    Returns: 要保留的 code 集合
    """
    target = set(my_branch_codes)  # 我的分點個股永遠保留
    
    # Top N 融資變化（絕對值，代表最熱門的）
    if all_margin:
        sorted_by_margin_change = sorted(
            all_margin.values(),
            key=lambda x: abs(x.get('margin_change', 0)),
            reverse=True
        )
        for item in sorted_by_margin_change[:top_n]:
            target.add(item['code'])
        
        # 融資使用率 >= 50% 者（前 50 檔，代表散戶壓注集中）
        high_usage = [x for x in all_margin.values() 
                      if x.get('margin_usage', 0) >= 50]
        high_usage.sort(key=lambda x: -x.get('margin_usage', 0))
        for item in high_usage[:50]:
            target.add(item['code'])
        
        # 券資比 Top 50（軋空潛力）
        sorted_by_ms = sorted(
            all_margin.values(),
            key=lambda x: x.get('margin_short_ratio', 0),
            reverse=True
        )
        for item in sorted_by_ms[:50]:
            target.add(item['code'])
    
    return target


def filter_margin_data(all_margin: Dict[str, Dict[str, Any]],
                       target_codes: set) -> Dict[str, Dict[str, Any]]:
    """依 target_codes 過濾 margin 資料"""
    return {code: data for code, data in all_margin.items() if code in target_codes}


# ════════════════════════════════════════════════════════════════════
#  注入個股資料 + 產生全市場排行
# ════════════════════════════════════════════════════════════════════

def inject_margin_into_stocks(branches_data: list, 
                              all_margin: Dict[str, Dict[str, Any]]) -> int:
    """
    把融資融券資料注入每檔個股（在分點買賣超資料上）
    
    Returns: 注入成功的個股數
    """
    injected_count = 0
    seen_stocks = set()
    
    for br in branches_data:
        for s in (br.get('buys', []) + br.get('sells', [])):
            code = s.get('code', '').strip()
            if not code:
                continue
            
            margin_data = all_margin.get(code)
            if not margin_data:
                continue
            
            # 注入融資融券欄位（加 margin_ 前綴避免碰撞）
            s['margin_buy'] = margin_data['margin_buy']
            s['margin_sell'] = margin_data['margin_sell']
            s['margin_balance'] = margin_data['margin_balance']
            s['margin_change'] = margin_data['margin_change']
            s['margin_usage'] = margin_data['margin_usage']
            s['short_balance'] = margin_data['short_balance']
            s['short_change'] = margin_data['short_change']
            s['short_usage'] = margin_data['short_usage']
            s['offsetting'] = margin_data['offsetting']
            s['margin_short_ratio'] = margin_data['margin_short_ratio']
            
            # 智慧信號判定（v3.11 核心價值）
            s['margin_signal'] = compute_margin_signal(s, margin_data)
            
            if code not in seen_stocks:
                seen_stocks.add(code)
                injected_count += 1
    
    return injected_count


def compute_margin_signal(stock_with_inst: Dict[str, Any], 
                          margin: Dict[str, Any]) -> str:
    """
    綜合分點買賣 + 三大法人 + 融資融券的散戶情緒信號
    
    Returns: 信號字串
      - "smart_money_in"  : 外資/主力買 + 融資減 = 散戶下車，主力上車（最強買點）
      - "retail_fomo"     : 外資/主力買 + 融資增 = 散戶追漲（警告：可能被套）
      - "smart_money_out" : 外資/主力賣 + 融資增 = 散戶接刀（警告：下跌中）
      - "short_squeeze"   : 融券變化大 + 融資減 + 股價漲 = 軋空醞釀
      - "neutral"         : 無明顯信號
    """
    foreign_net = stock_with_inst.get('inst_foreign_net_lot', 0) or 0
    trust_net = stock_with_inst.get('inst_trust_net_lot', 0) or 0
    inst_total = foreign_net + trust_net
    
    margin_change = margin.get('margin_change', 0)
    short_change = margin.get('short_change', 0)
    change_pct = stock_with_inst.get('change_pct') or 0
    
    # 需要有三大法人資料才判斷
    if inst_total == 0 and margin_change == 0:
        return "neutral"
    
    # 主力強買 + 散戶下車 = 最佳
    if inst_total > 500 and margin_change < -100:
        return "smart_money_in"
    
    # 主力買 + 散戶跟風追漲
    if inst_total > 200 and margin_change > 500:
        return "retail_fomo"
    
    # 主力賣 + 散戶接刀
    if inst_total < -500 and margin_change > 100:
        return "smart_money_out"
    
    # 軋空潛力：融券暴增但股價還漲
    if short_change > 500 and change_pct > 0 and margin.get('margin_short_ratio', 0) > 10:
        return "short_squeeze"
    
    return "neutral"


# ════════════════════════════════════════════════════════════════════
#  全市場排行榜（給 UI 展示用）
# ════════════════════════════════════════════════════════════════════

def build_margin_rankings(all_margin: Dict[str, Dict[str, Any]], 
                          top_n: int = 30) -> Dict[str, Any]:
    """
    產生全市場融資融券排行榜
    
    Returns: 
      {
        "top_margin_buy":    [...],  # 融資買超 Top N
        "top_margin_sell":   [...],  # 融資賣超（減少）Top N
        "top_short_sell":    [...],  # 融券賣出 Top N
        "top_short_cover":   [...],  # 融券回補 Top N
        "top_offsetting":    [...],  # 當沖最熱 Top N
        "top_margin_usage":  [...],  # 融資使用率最高 Top N
        "top_margin_short_ratio": [...],  # 券資比最高 Top N（軋空潛力）
      }
    """
    items = list(all_margin.values())
    
    def sorted_top(key_fn, reverse=True):
        return sorted(items, key=key_fn, reverse=reverse)[:top_n]
    
    return {
        "top_margin_buy": sorted_top(lambda x: x.get('margin_change', 0)),
        "top_margin_sell": sorted_top(lambda x: x.get('margin_change', 0), reverse=False),
        "top_short_sell": sorted_top(lambda x: x.get('short_change', 0)),
        "top_short_cover": sorted_top(lambda x: x.get('short_change', 0), reverse=False),
        "top_offsetting": sorted_top(lambda x: x.get('offsetting', 0)),
        "top_margin_usage": sorted_top(lambda x: x.get('margin_usage', 0)),
        "top_margin_short_ratio": sorted_top(lambda x: x.get('margin_short_ratio', 0)),
    }
