"""
========================================================================
Module: futures.py  (v3.17 新增)
功能：抓取 TAIFEX 期貨 + 選擇權 + 大額交易人資料,計算 Max Pain

資料源：TAIFEX CSV 下載端點 (https://www.taifex.com.tw/cht/3/*)
  - 臺股期貨 (TXF)、小台 (MXF)、微台 (TMF)
  - 臺指選擇權 (TXO) — Call/Put 分開
  - 大額交易人期貨/選擇權

關鍵輸出欄位:
  外資期貨淨未平倉 = 多方未平倉口數 - 空方未平倉口數
    正值 = 外資看多, 負值 = 外資看空

  散戶小台淨部位 (自營商 - 散戶推算):
    小台主要是散戶,反指標用

  Put/Call Ratio = Put 未平倉口數 / Call 未平倉口數
    > 1.0 散戶看空 → 反指標偏多
    < 0.7 散戶看多 → 反指標偏空

  Max Pain = 選擇權結算時「賣方最痛點」
    最多買方在該價位會歸零,通常指數會靠近該點

========================================================================
"""

import io
import csv
import time
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

TW_TZ = timezone(timedelta(hours=8))

BASE_URL = 'https://www.taifex.com.tw/cht/3'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Referer': 'https://www.taifex.com.tw/cht/3/futContractsDate',
}


def _date_fmt(yyyymmdd: str) -> str:
    """YYYYMMDD → YYYY/MM/DD (TAIFEX 格式)"""
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def _post_csv(endpoint: str, data: Dict[str, str], max_retries: int = 3) -> Optional[str]:
    """POST 到 TAIFEX 取 CSV,含 retry 邏輯 (遵循 api-crawler-checklist)"""
    url = f"{BASE_URL}/{endpoint}"
    for attempt in range(max_retries):
        try:
            r = requests.post(url, data=data, headers=HEADERS, timeout=20)
            if r.status_code == 200 and len(r.text) > 100:
                r.encoding = 'big5'  # TAIFEX 用 Big5 編碼
                return r.text
            print(f"    ⚠️ TAIFEX {endpoint} 第 {attempt+1}/{max_retries} 次: HTTP {r.status_code}, size={len(r.text)}")
        except Exception as e:
            print(f"    ⚠️ TAIFEX {endpoint} 第 {attempt+1}/{max_retries} 次失敗: {e}")
        if attempt < max_retries - 1:
            time.sleep(10 + attempt * 5)  # 10s, 15s, 20s
    return None


def _parse_csv(text: str) -> List[Dict[str, str]]:
    """解析 TAIFEX CSV (header + rows)"""
    if not text:
        return []
    try:
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if len(rows) < 2:
            return []
        headers = [h.strip() for h in rows[0]]
        result = []
        for row in rows[1:]:
            if not row or not row[0].strip():
                continue
            row_dict = {}
            for i, val in enumerate(row):
                if i < len(headers):
                    row_dict[headers[i]] = val.strip()
            result.append(row_dict)
        return result
    except Exception as e:
        print(f"    ⚠️ CSV 解析失敗: {e}")
        return []


def _to_int(s: str) -> int:
    """CSV 字串轉 int (可能有逗號或空字串)"""
    if not s or not s.strip():
        return 0
    try:
        return int(s.replace(',', '').strip())
    except (ValueError, TypeError):
        return 0


# ════════════════════════════════════════════════════════════════════
#  🎯 1. 三大法人期貨未平倉 (最關鍵)
# ════════════════════════════════════════════════════════════════════
def fetch_institutional_futures(trade_date: str, commodity: str = 'TXF') -> Dict[str, Any]:
    """
    抓取三大法人 期貨 未平倉
    
    Args:
        trade_date: YYYYMMDD
        commodity: TXF (大台)、MXF (小台)、TMF (微台)
    
    Returns:
        {
            'commodity': 'TXF',
            'date': 'YYYY/MM/DD',
            'dealer':   {long_trade, short_trade, long_oi, short_oi, net_oi, ...},
            'trust':    {...},
            'foreign':  {long_trade, short_trade, long_oi, short_oi, net_oi, net_trade, ...},
        }
    """
    print(f"  [期貨三大法人] 抓取 {commodity}...")
    text = _post_csv('futContractsDateDown', {
        'queryStartDate': _date_fmt(trade_date),
        'queryEndDate': _date_fmt(trade_date),
        'commodityId': commodity,
    })
    if not text:
        return {}
    
    rows = _parse_csv(text)
    result = {'commodity': commodity, 'date': _date_fmt(trade_date), 'raw_rows': len(rows)}
    
    # CSV 欄位 (按 2026/04 測試確認):
    # 日期, 商品名稱, 身份別, 多方交易口數, 多方交易契約金額(千元), 空方交易口數, 空方交易契約金額(千元),
    # 多空交易口數淨額, 多空交易契約金額淨額(千元), 多方未平倉口數, 多方未平倉契約金額(千元),
    # 空方未平倉口數, 空方未平倉契約金額(千元), 多空未平倉口數淨額, 多空未平倉契約金額淨額(千元)
    identity_map = {
        '自營商': 'dealer', '投信': 'trust', 
        '外資': 'foreign', '外資及陸資': 'foreign'
    }
    
    for row in rows:
        identity = row.get('身份別', '').strip()
        key = identity_map.get(identity)
        if not key:
            continue
        result[key] = {
            'long_trade': _to_int(row.get('多方交易口數', '0')),
            'short_trade': _to_int(row.get('空方交易口數', '0')),
            'net_trade': _to_int(row.get('多空交易口數淨額', '0')),
            'long_oi': _to_int(row.get('多方未平倉口數', '0')),
            'short_oi': _to_int(row.get('空方未平倉口數', '0')),
            'net_oi': _to_int(row.get('多空未平倉口數淨額', '0')),
            'net_oi_amt_kilo': _to_int(row.get('多空未平倉契約金額淨額(千元)', '0')),
        }
    
    return result


# ════════════════════════════════════════════════════════════════════
#  🎯 2. 臺指選擇權 Call/Put 三大法人未平倉
# ════════════════════════════════════════════════════════════════════
def fetch_institutional_options(trade_date: str, commodity: str = 'TXO') -> Dict[str, Any]:
    """
    抓取 TXO (臺指選擇權) Call/Put 三大法人未平倉
    
    Returns:
        {
            'commodity': 'TXO',
            'date': 'YYYY/MM/DD',
            'call': {
                'dealer':  {long_oi, short_oi, net_oi, ...},
                'trust':   {...},
                'foreign': {...},
            },
            'put': {
                'dealer':  {...},
                ...
            }
        }
    """
    print(f"  [選擇權三大法人] 抓取 {commodity}...")
    text = _post_csv('callsAndPutsDateDown', {
        'queryStartDate': _date_fmt(trade_date),
        'queryEndDate': _date_fmt(trade_date),
        'commodityId': commodity,
    })
    if not text:
        return {}
    
    rows = _parse_csv(text)
    result = {
        'commodity': commodity,
        'date': _date_fmt(trade_date),
        'call': {},
        'put': {},
    }
    
    # CSV 欄位: 日期, 商品名稱, 買賣權別, 身份別, 多方交易口數, ..., 多空未平倉口數淨額, ...
    identity_map = {
        '自營商': 'dealer', '投信': 'trust',
        '外資': 'foreign', '外資及陸資': 'foreign'
    }
    cp_map = {'CALL': 'call', 'PUT': 'put', 'Call': 'call', 'Put': 'put', '買權': 'call', '賣權': 'put'}
    
    for row in rows:
        cp_raw = row.get('買賣權別', '').strip()
        identity = row.get('身份別', '').strip()
        cp_key = cp_map.get(cp_raw)
        id_key = identity_map.get(identity)
        if not cp_key or not id_key:
            continue
        # 選擇權欄位用「買方/賣方」而非「多方/空方」
        result[cp_key][id_key] = {
            'long_trade': _to_int(row.get('買方交易口數', '0')),
            'short_trade': _to_int(row.get('賣方交易口數', '0')),
            'net_trade': _to_int(row.get('交易口數買賣淨額', '0')),
            'long_oi': _to_int(row.get('買方未平倉口數', '0')),
            'short_oi': _to_int(row.get('賣方未平倉口數', '0')),
            'net_oi': _to_int(row.get('未平倉口數買賣淨額', '0')),
        }
    
    return result


# ════════════════════════════════════════════════════════════════════
#  🎯 3. 大額交易人期貨 (前十大 / 前五大)
# ════════════════════════════════════════════════════════════════════
def fetch_top_traders_futures(trade_date: str, contract: str = 'TXF') -> Dict[str, Any]:
    """
    抓取大額交易人 期貨 未平倉 (當月份合約)
    
    CSV 欄位 (2026/04 確認):
      日期, 商品(契約), 商品名稱(契約名稱), 到期月份(週別), 交易人類別,
      前五大交易人買方, 前五大交易人賣方,
      前十大交易人買方, 前十大交易人賣方,
      全市場未沖銷部位數
    
    交易人類別: 0=全市場, 1=特定法人
    
    Returns:
        {
            'commodity': 'TXF',
            'date': 'YYYY/MM/DD',
            'nearest_month': {
                'top5_long_all': int, 'top5_short_all': int,
                'top10_long_all': int, 'top10_short_all': int,
                'top5_long_institutional': int, 'top5_short_institutional': int,
                'top10_long_institutional': int, 'top10_short_institutional': int,
                'total_oi': int,  # 全市場未沖銷
            },
            'nearest_month_label': '202605'
        }
    """
    print(f"  [大額交易人期貨] 抓取 {contract}...")
    text = _post_csv('largeTraderFutDown', {
        'queryStartDate': _date_fmt(trade_date),
        'queryEndDate': _date_fmt(trade_date),
        'contractId': contract,
    })
    if not text:
        return {}
    
    rows = _parse_csv(text)
    result = {'commodity': contract, 'date': _date_fmt(trade_date), 'by_month': {}}
    
    # 欄位名可能有空格,用 get 精確比對
    for row in rows:
        # 商品代碼可能有空格 (e.g. "TXF    ")
        code_raw = row.get('商品(契約)', '') or row.get('商品 (契約)', '')
        code = code_raw.strip()
        if code != contract:
            continue
        
        month_raw = row.get('到期月份(週別)', '') or row.get('到期月份 (週別)', '')
        month = month_raw.strip()
        if not month:
            continue
        
        # 交易人類別: 0=全市場, 1=特定法人 (institutional)
        trader_type = row.get('交易人類別', '').strip()
        
        top5_long = _to_int(row.get('前五大交易人買方', '0'))
        top5_short = _to_int(row.get('前五大交易人賣方', '0'))
        top10_long = _to_int(row.get('前十大交易人買方', '0'))
        top10_short = _to_int(row.get('前十大交易人賣方', '0'))
        total_oi = _to_int(row.get('全市場未沖銷部位數', '0'))
        
        if month not in result['by_month']:
            result['by_month'][month] = {}
        
        if trader_type == '0':
            # 全市場前 5/10 大
            result['by_month'][month]['top5_long_all'] = top5_long
            result['by_month'][month]['top5_short_all'] = top5_short
            result['by_month'][month]['top10_long_all'] = top10_long
            result['by_month'][month]['top10_short_all'] = top10_short
            result['by_month'][month]['total_oi'] = total_oi
        elif trader_type == '1':
            # 前 5/10 大特定法人
            result['by_month'][month]['top5_long_institutional'] = top5_long
            result['by_month'][month]['top5_short_institutional'] = top5_short
            result['by_month'][month]['top10_long_institutional'] = top10_long
            result['by_month'][month]['top10_short_institutional'] = top10_short
    
    # 取參考月份 (v3.17.5 修正: 改用 999999 全部月份對齊 TAIFEX 官網標準)
    if result['by_month']:
        months = sorted(result['by_month'].keys())
        # 999999 = 不分月份合計 (TAIFEX 官網預設顯示這個)
        if '999999' in result['by_month']:
            result['nearest_month'] = result['by_month']['999999']
            result['nearest_month_label'] = '全部月份'
            # 同時保留當月供參考
            current_months = [m for m in months if m not in ('999999', '666666')]
            if current_months:
                result['current_month'] = result['by_month'][current_months[0]]
                result['current_month_label'] = current_months[0]
        else:
            # 退化:若沒 999999 則取最近月份
            current_months = [m for m in months if m not in ('999999', '666666')]
            nearest = current_months[0] if current_months else months[0]
            result['nearest_month'] = result['by_month'][nearest]
            result['nearest_month_label'] = nearest
    
    return result


# ════════════════════════════════════════════════════════════════════
#  🎯 4. 大額交易人 選擇權 (for Max Pain 參考)
# ════════════════════════════════════════════════════════════════════
def fetch_top_traders_options(trade_date: str, contract: str = 'TXO') -> Dict[str, Any]:
    """
    抓取大額交易人 選擇權 未平倉 (TXO 各履約價)
    此函數資料量大,for Max Pain 計算使用
    """
    print(f"  [大額交易人選擇權] 抓取 {contract}...")
    text = _post_csv('largeTraderOptDown', {
        'queryStartDate': _date_fmt(trade_date),
        'queryEndDate': _date_fmt(trade_date),
        'contractId': contract,
    })
    if not text:
        return {}
    
    rows = _parse_csv(text)
    return {
        'commodity': contract,
        'date': _date_fmt(trade_date),
        'row_count': len(rows),
        'rows': rows[:50],  # 只保留前 50 行 (避免 JSON 太大)
    }


# ════════════════════════════════════════════════════════════════════
#  🎯 5. 計算 Max Pain (最大痛點)
# ════════════════════════════════════════════════════════════════════
def compute_max_pain(option_oi_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    從選擇權各履約價未平倉資料計算 Max Pain
    
    Max Pain 邏輯:
      對每一個可能的結算價 K,計算:
        Call 買方損失 = Σ (K > strike) × (K - strike) × Call_OI
        Put 買方損失 = Σ (strike > K) × (strike - K) × Put_OI
      Max Pain = 使總損失最大的 K (賣方最痛,但實際上多數時候指數會靠近這點)
    
    由於 TAIFEX 大額交易人選擇權端點資料結構複雜 (按前5大/前10大拆分),
    此函數為簡化版:若有明確 Call/Put 的各履約價 OI 才計算,否則回傳 None
    
    真實 Max Pain 需要的是全市場各履約價 OI 資料,
    這個 API 端點目前可能不提供,需要日後用其他資料源補上
    """
    return None  # v3.17.0 先回傳 None, v3.17.1 版本補上完整 Max Pain


# ════════════════════════════════════════════════════════════════════
#  🎯 6. 綜合抓取 + 計算 (主入口)
# ════════════════════════════════════════════════════════════════════
def fetch_futures_market_data(trade_date: str) -> Optional[Dict[str, Any]]:
    """
    v3.18: 抓 TAIFEX 期貨每日交易行情 (TX 各月份開高低收 + 跨月價差)
    
    端點: https://www.taifex.com.tw/cht/3/dlFutDataDown
    
    回傳:
        {
            'date': '2026/04/29',
            'months': [
                {
                    'month': '202605',          # 月份代碼
                    'session': '一般',           # 一般 / 盤後
                    'open': 39698,
                    'high': 39790,
                    'low': 39123,
                    'close': 39490,
                    'change': -243,
                    'change_pct': -0.61,
                    'volume': 59705,
                    'settlement': 39479,        # 結算價
                    'open_interest': 79818,     # 未沖銷契約
                    'historical_high': 40458,
                    'historical_low': 31357,
                },
                ...
            ],
            'spreads': [                         # 跨月價差
                {
                    'pair': '202605/202606',
                    'session': '一般',
                    'spread': 92,
                    'volume': 415,
                },
                ...
            ],
            'summary': {
                'near_month': '202605',           # 近月
                'near_close': 39490,              # 近月收盤
                'near_change': -243,              # 近月漲跌
                'near_change_pct': -0.61,         # 近月漲跌%
                'near_volume': 59705,             # 近月成交量
                'next_month': '202606',           # 次月
                'spread_near_next': 60,           # 近月-次月價差 (反映預期)
                'after_hours_near_close': 39461,  # 近月夜盤收盤 (如有)
            }
        }
    """
    import re
    
    try:
        r = requests.post(
            'https://www.taifex.com.tw/cht/3/dlFutDataDown',
            data={
                'down_type': '1',
                'commodity_id': 'TX',
                'queryStartDate': _date_fmt(trade_date),
                'queryEndDate': _date_fmt(trade_date),
                'commodity_idt': 'TX',
                'MarketCode': '',
            },
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code != 200 or len(r.text) < 500:
            return None
        
        r.encoding = 'big5'
        lines = [l.strip() for l in r.text.split('\n') if l.strip()]
        
        if len(lines) < 2:
            return None
        
        # 解析每一行
        months = []
        spreads = []
        target_date = None
        
        for line in lines[1:]:  # 跳過 header
            cols = [c.strip() for c in line.split(',')]
            if len(cols) < 16:
                continue
            
            date = cols[0]
            commodity = cols[1]
            month_str = cols[2].strip()
            session = cols[17] if len(cols) > 17 else '一般'
            
            if commodity != 'TX':
                continue
            
            target_date = date
            
            # 跨月價差會有 / 符號
            if '/' in month_str:
                # 例如 "202605/202606"
                try:
                    spread_val = cols[3]  # 開盤價當作價差參考
                    spread_volume = int(cols[9]) if cols[9] not in ('-', '') else 0
                    
                    # 用收盤價當價差 (若有)
                    close = cols[6]
                    spread = None
                    if close not in ('-', ''):
                        try:
                            spread = int(close)
                        except ValueError:
                            spread = None
                    
                    spreads.append({
                        'pair': month_str.replace(' ', ''),
                        'session': session,
                        'spread': spread,
                        'volume': spread_volume,
                    })
                except (ValueError, IndexError):
                    continue
            else:
                # 單月行情
                try:
                    def safe_int(v):
                        if v in ('-', ''): return None
                        try: return int(v)
                        except ValueError: return None
                    
                    def safe_float(v):
                        if v in ('-', ''): return None
                        try: return float(v.replace('%', ''))
                        except ValueError: return None
                    
                    months.append({
                        'month': month_str.strip(),
                        'session': session,
                        'open': safe_int(cols[3]),
                        'high': safe_int(cols[4]),
                        'low': safe_int(cols[5]),
                        'close': safe_int(cols[6]),
                        'change': safe_int(cols[7]),
                        'change_pct': safe_float(cols[8]),
                        'volume': safe_int(cols[9]) or 0,
                        'settlement': safe_int(cols[10]),
                        'open_interest': safe_int(cols[11]),
                        'historical_high': safe_int(cols[14]),
                        'historical_low': safe_int(cols[15]),
                    })
                except (ValueError, IndexError):
                    continue
        
        if not months:
            return None
        
        # 計算 summary
        # 一般時段月份排序 (近月通常排第 1)
        regular_months = [m for m in months if m['session'] == '一般']
        ah_months = [m for m in months if m['session'] == '盤後']
        
        regular_months.sort(key=lambda x: x['month'])
        
        summary = {}
        if regular_months:
            near = regular_months[0]
            summary['near_month'] = near['month']
            summary['near_close'] = near['close']
            summary['near_change'] = near['change']
            summary['near_change_pct'] = near['change_pct']
            summary['near_volume'] = near['volume']
            summary['near_open'] = near['open']
            summary['near_high'] = near['high']
            summary['near_low'] = near['low']
            summary['near_settlement'] = near['settlement']
            summary['near_oi'] = near['open_interest']
            
            if len(regular_months) >= 2:
                next_m = regular_months[1]
                summary['next_month'] = next_m['month']
                summary['next_close'] = next_m['close']
                if near['close'] is not None and next_m['close'] is not None:
                    summary['spread_near_next'] = next_m['close'] - near['close']
        
        # 夜盤近月收盤
        if ah_months:
            ah_regular = sorted([m for m in ah_months], key=lambda x: x['month'])
            if ah_regular:
                summary['after_hours_near_month'] = ah_regular[0]['month']
                summary['after_hours_near_close'] = ah_regular[0]['close']
                summary['after_hours_near_change'] = ah_regular[0]['change']
                summary['after_hours_near_change_pct'] = ah_regular[0]['change_pct']
        
        return {
            'date': target_date,
            'months': months,
            'spreads': spreads,
            'summary': summary,
        }
    
    except Exception as e:
        print(f"  ⚠️ fetch_futures_market_data 失敗: {e}")
        return None


def fetch_after_hours_futures(trade_date: str) -> Optional[Dict[str, Any]]:
    """
    v3.18: 抓夜盤三大法人 (futContractsDateAhDown)
    
    夜盤交易時段: 15:00 (前一日) 至 05:00 (當日)
    反映美股後台股期貨開盤前反應
    
    ⚠️ 夜盤資料只有「交易量」沒有「未平倉」(因為夜盤不結算)
    
    回傳:
        {
            'date': '2026/04/29',
            'futures': {
                'TXF': {
                    'dealer':  {'long_trade', 'short_trade', 'net_trade'},
                    'trust':   {...},
                    'foreign': {...},
                },
                'MXF': {...},
                'TMF': {...},
            }
        }
    """
    try:
        r = requests.post(
            'https://www.taifex.com.tw/cht/3/futContractsDateAhDown',
            data={
                'queryStartDate': _date_fmt(trade_date),
                'queryEndDate': _date_fmt(trade_date),
                'commodityId': '',
            },
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code != 200 or len(r.text) < 500:
            return None
        
        r.encoding = 'big5'
        lines = [l.strip() for l in r.text.split('\n') if l.strip()]
        if len(lines) < 2:
            return None
        
        result = {'date': None, 'futures': {'TXF': {}, 'MXF': {}, 'TMF': {}}}
        COMMODITY_MAP = {'臺股期貨': 'TXF', '小型臺指期貨': 'MXF', '微型臺指期貨': 'TMF'}
        ROLE_MAP = {'自營商': 'dealer', '投信': 'trust', '外資及陸資': 'foreign'}
        
        for line in lines[1:]:
            cols = [c.strip() for c in line.split(',')]
            if len(cols) < 9:
                continue
            
            commodity_zh = cols[1]
            role_zh = cols[2]
            
            if commodity_zh not in COMMODITY_MAP:
                continue
            if role_zh not in ROLE_MAP:
                continue
            
            com_key = COMMODITY_MAP[commodity_zh]
            role_key = ROLE_MAP[role_zh]
            
            try:
                result['date'] = cols[0]
                # 夜盤 CSV 9 欄: 日期,商品,身份,多方交易口數,多方金額,空方口數,空方金額,多空淨額,金額淨額
                result['futures'][com_key][role_key] = {
                    'long_trade': int(cols[3]),
                    'short_trade': int(cols[5]),
                    'net_trade': int(cols[7]),
                }
            except (ValueError, IndexError):
                continue
        
        # 計算夜盤外資等效大台 (用 net_trade 而非 net_oi)
        try:
            txf_foreign = result['futures'].get('TXF', {}).get('foreign', {}).get('net_trade', 0)
            mxf_foreign = result['futures'].get('MXF', {}).get('foreign', {}).get('net_trade', 0)
            tmf_foreign = result['futures'].get('TMF', {}).get('foreign', {}).get('net_trade', 0)
            
            equivalent = txf_foreign + (mxf_foreign / 4) + (tmf_foreign / 20)
            result['summary'] = {
                'foreign_equivalent_net_trade_ah': round(equivalent),
                'foreign_txf_net_trade_ah': txf_foreign,
                'foreign_mxf_net_trade_ah': mxf_foreign,
                'foreign_tmf_net_trade_ah': tmf_foreign,
            }
        except (TypeError, ValueError):
            result['summary'] = {}
        
        return result
    
    except Exception as e:
        print(f"  ⚠️ fetch_after_hours_futures 失敗: {e}")
        return None


def fetch_official_pcr(trade_date: str) -> Optional[Dict[str, Any]]:
    """
    v3.17.5: 直接從 TAIFEX 官方 pcRatio 端點抓真實 PCR
    
    端點: https://www.taifex.com.tw/cht/3/pcRatio (HTML 頁面)
    回傳最近 21 個交易日的 PCR 表格
    
    Args:
        trade_date: YYYYMMDD (e.g. 20260429)
    
    Returns:
        {
            'pcr_oi': float,         # 買賣權未平倉量比 (例: 1.7112)
            'pcr_volume': float,     # 買賣權成交量比 (例: 0.9592)  
            'put_oi': int,           # 賣權未平倉量
            'call_oi': int,          # 買權未平倉量
            'put_volume': int,       # 賣權成交量
            'call_volume': int,      # 買權成交量
            'date': str,             # YYYY/M/D
        }
        失敗回 None
    """
    import re
    
    # YYYYMMDD → YYYY/M/D (TAIFEX 表格用無前導零格式)
    yyyy = trade_date[:4]
    mm = str(int(trade_date[4:6]))  # 去掉前導 0
    dd = str(int(trade_date[6:8]))
    target_date = f"{yyyy}/{mm}/{dd}"
    
    try:
        r = requests.get(
            'https://www.taifex.com.tw/cht/3/pcRatio',
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code != 200 or len(r.text) < 5000:
            return None
        
        html = r.text
        # 解析所有 <tr>
        trs = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        
        for tr in trs:
            if target_date not in tr:
                continue
            tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
            cleaned = [re.sub(r'<[^>]+>', '', t).strip().replace(',', '').replace('&nbsp;', '') for t in tds]
            if len(cleaned) < 7:
                continue
            
            try:
                date, put_vol, call_vol, vol_ratio, put_oi, call_oi, oi_ratio = cleaned[:7]
                if date != target_date:
                    continue
                return {
                    'pcr_oi': round(float(oi_ratio) / 100, 4),         # 171.12 → 1.7112
                    'pcr_volume': round(float(vol_ratio) / 100, 4),    # 95.92 → 0.9592
                    'put_oi': int(put_oi),
                    'call_oi': int(call_oi),
                    'put_volume': int(put_vol),
                    'call_volume': int(call_vol),
                    'date': date,
                }
            except (ValueError, IndexError):
                continue
        
        return None
    except Exception as e:
        print(f"  ⚠️ fetch_official_pcr 失敗: {e}")
        return None


def fetch_all_futures_data(trade_date: str) -> Dict[str, Any]:
    """
    一次抓取所有期貨相關資料 (for crawler.py 主流程)
    
    Returns:
        {
            'date': 'YYYY/MM/DD',
            'crawled_at': ISO,
            'futures': {
                'TXF': {dealer, trust, foreign},  # 大台
                'MXF': {...},                      # 小台
                'TMF': {...},                      # 微台
            },
            'options': {
                'TXO': {call: {...}, put: {...}},
            },
            'top_traders': {
                'TXF': {by_month, nearest_month, nearest_month_label},
            },
            'summary': {
                'foreign_futures_net_oi': int,      # 外資大台+小台合計
                'foreign_futures_mxf_tx_ratio': float,
                'retail_mxf_net_oi': int,           # 散戶小台推算
                'pc_ratio_oi': float,               # Put/Call 未平倉比
                'pc_ratio_trade': float,            # Put/Call 當日交易比
            }
        }
    """
    result = {
        'date': _date_fmt(trade_date),
        'crawled_at': datetime.now(TW_TZ).isoformat(),
        'futures': {},
        'options': {},
        'top_traders': {},
        'summary': {},
    }
    
    # 1. 三大法人期貨 (TXF, MXF, TMF)
    for commodity in ['TXF', 'MXF', 'TMF']:
        try:
            result['futures'][commodity] = fetch_institutional_futures(trade_date, commodity)
            time.sleep(3)  # TAIFEX 也有限流,保守點
        except Exception as e:
            print(f"    ⚠️ {commodity} 期貨抓取失敗: {e}")
    
    # 2. 臺指選擇權 TXO
    try:
        result['options']['TXO'] = fetch_institutional_options(trade_date, 'TXO')
        time.sleep(3)
    except Exception as e:
        print(f"    ⚠️ TXO 選擇權抓取失敗: {e}")
    
    # 3. 大額交易人 TX (注意:大額交易人用 TX 不是 TXF,且是等效大台合併)
    try:
        result['top_traders']['TX'] = fetch_top_traders_futures(trade_date, 'TX')
        time.sleep(3)
    except Exception as e:
        print(f"    ⚠️ TX 大額交易人抓取失敗: {e}")
    
    # 4. 計算 summary 關鍵指標
    summary = result['summary']
    
    # 4-a. 外資期貨淨未平倉 (大台 + 小台折算)
    # 小台合約值是大台的 1/4,所以等效大台 = 大台 OI + 小台 OI / 4
    txf_foreign = result['futures'].get('TXF', {}).get('foreign', {})
    mxf_foreign = result['futures'].get('MXF', {}).get('foreign', {})
    txf_foreign_net = txf_foreign.get('net_oi', 0)
    mxf_foreign_net = mxf_foreign.get('net_oi', 0)
    
    summary['foreign_txf_net_oi'] = txf_foreign_net
    summary['foreign_mxf_net_oi'] = mxf_foreign_net
    # 等效大台合約 (大台 1 口 = 小台 4 口 合約值)
    summary['foreign_equivalent_net_oi'] = txf_foreign_net + mxf_foreign_net // 4
    
    # 4-b. 散戶小台 (自營商 + 投信通常不會在小台大量,所以小台的反向 ≈ 散戶)
    # 散戶小台淨 = -(自營 + 投信 + 外資 的小台淨)
    mxf_dealer_net = result['futures'].get('MXF', {}).get('dealer', {}).get('net_oi', 0)
    mxf_trust_net = result['futures'].get('MXF', {}).get('trust', {}).get('net_oi', 0)
    summary['retail_mxf_net_oi'] = -(mxf_dealer_net + mxf_trust_net + mxf_foreign_net)
    
    # 4-c. Put/Call Ratio (全市場未平倉)
    # ⚠️ v3.17.5 修正: 改抓 TAIFEX 官方 pcRatio 端點 (全市場 OI)
    # 之前用三大法人多方 OI 計算是錯誤的 (差異約 8-10%)
    call_data = result['options'].get('TXO', {}).get('call', {})
    put_data = result['options'].get('TXO', {}).get('put', {})
    
    # 嘗試從官方端點取真實 PCR
    pcr_official = fetch_official_pcr(trade_date)
    if pcr_official:
        summary['pc_ratio_oi'] = pcr_official['pcr_oi']
        summary['pc_ratio_volume'] = pcr_official.get('pcr_volume')
        summary['put_oi_total'] = pcr_official.get('put_oi')
        summary['call_oi_total'] = pcr_official.get('call_oi')
        summary['pcr_source'] = 'TAIFEX 官方'
    else:
        # 退化:用三大法人計算 (僅作備援,標記為估算)
        total_call_long_oi = sum(
            (call_data.get(k, {}).get('long_oi', 0)) for k in ['dealer', 'trust', 'foreign']
        )
        total_put_long_oi = sum(
            (put_data.get(k, {}).get('long_oi', 0)) for k in ['dealer', 'trust', 'foreign']
        )
        if total_call_long_oi > 0:
            summary['pc_ratio_oi'] = round(total_put_long_oi / total_call_long_oi, 3)
            summary['pcr_source'] = '三法人估算 (備援)'
        else:
            summary['pc_ratio_oi'] = None
            summary['pcr_source'] = None
    
    # 4-d. 外資選擇權 Call 和 Put 的淨 OI (多方 - 空方)
    foreign_call = call_data.get('foreign', {})
    foreign_put = put_data.get('foreign', {})
    summary['foreign_call_net_oi'] = foreign_call.get('net_oi', 0)
    summary['foreign_put_net_oi'] = foreign_put.get('net_oi', 0)
    # 外資選擇權傾向: 買 Call 看多 + 賣 Put 看多
    # 這個指標直接取 Call 淨 OI - Put 淨 OI 做簡化
    summary['foreign_option_sentiment'] = summary['foreign_call_net_oi'] - summary['foreign_put_net_oi']
    
    # 4-e. 十大交易人集中度 (TX = 等效大台合併)
    # 有多個月份,取當月份 (排除 999999 全部和 666666 當月合約標記)
    top_t_data = result['top_traders'].get('TX', {})
    nearest_month = top_t_data.get('nearest_month', {})
    # 如果 nearest 是 666666/999999 代碼,改取實際月份
    nearest_label = top_t_data.get('nearest_month_label', '')
    if nearest_label in ('666666', '999999'):
        # 找實際月份 (6 digit YYYYMM)
        by_month = top_t_data.get('by_month', {})
        real_months = [m for m in by_month.keys() if m.isdigit() and len(m) == 6 and m not in ('666666', '999999')]
        if real_months:
            month = sorted(real_months)[0]
            nearest_month = by_month[month]
            summary['top_traders_month'] = month
    else:
        summary['top_traders_month'] = nearest_label
    
    if nearest_month:
        t10_long = nearest_month.get('top10_long_all', 0)
        t10_short = nearest_month.get('top10_short_all', 0)
        total = nearest_month.get('total_oi', 0) or 1
        summary['top10_long_ratio'] = round(t10_long / total, 3) if total > 0 else None
        summary['top10_short_ratio'] = round(t10_short / total, 3) if total > 0 else None
        summary['top10_net_oi'] = t10_long - t10_short
        summary['top10_long'] = t10_long
        summary['top10_short'] = t10_short
        summary['market_total_oi'] = total
    
    # 5. v3.18 NEW: 期貨各月份行情 (TX 開高低收 + 跨月價差)
    print("  [期貨行情] 抓取 TX 各月份開高低收...")
    market_data = fetch_futures_market_data(trade_date)
    if market_data:
        result['market_data'] = market_data
        # 把關鍵指標放到 summary
        ms = market_data.get('summary', {})
        summary['near_month_close'] = ms.get('near_close')
        summary['near_month_change'] = ms.get('near_change')
        summary['near_month_change_pct'] = ms.get('near_change_pct')
        summary['near_month_volume'] = ms.get('near_volume')
        summary['near_month_settlement'] = ms.get('near_settlement')
        summary['spread_near_next'] = ms.get('spread_near_next')
        summary['after_hours_near_close'] = ms.get('after_hours_near_close')
        summary['after_hours_near_change_pct'] = ms.get('after_hours_near_change_pct')
    
    # 6. v3.18 NEW: 夜盤三大法人
    print("  [夜盤] 抓取夜盤三大法人...")
    ah_data = fetch_after_hours_futures(trade_date)
    if ah_data:
        result['after_hours'] = ah_data
        # 把關鍵指標放到 summary
        ahs = ah_data.get('summary', {})
        summary['ah_foreign_txf_net_trade'] = ahs.get('foreign_txf_net_trade_ah')
        summary['ah_foreign_mxf_net_trade'] = ahs.get('foreign_mxf_net_trade_ah')
        summary['ah_foreign_tmf_net_trade'] = ahs.get('foreign_tmf_net_trade_ah')
        summary['ah_foreign_equivalent_net_trade'] = ahs.get('foreign_equivalent_net_trade_ah')
    
    return result


# ════════════════════════════════════════════════════════════════════
#  CLI 測試
# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import json
    from datetime import date
    
    # 測試 2026/04/23 (最新交易日)
    test_date = '20260423'
    print(f"🧪 futures.py 獨立測試 - {test_date}")
    print("=" * 65)
    
    data = fetch_all_futures_data(test_date)
    
    print("\n" + "=" * 65)
    print("📊 驗證結果")
    print("=" * 65)
    
    print(f"\n=== 外資期貨籌碼 ===")
    txf_f = data['futures'].get('TXF', {}).get('foreign', {})
    mxf_f = data['futures'].get('MXF', {}).get('foreign', {})
    print(f"  外資 TXF 淨 OI: {txf_f.get('net_oi', 0):,} 口 "
          f"(多 {txf_f.get('long_oi', 0):,} / 空 {txf_f.get('short_oi', 0):,})")
    print(f"  外資 MXF 淨 OI: {mxf_f.get('net_oi', 0):,} 口 "
          f"(多 {mxf_f.get('long_oi', 0):,} / 空 {mxf_f.get('short_oi', 0):,})")
    print(f"  外資等效大台: {data['summary'].get('foreign_equivalent_net_oi', 0):,} 口")
    
    print(f"\n=== 散戶小台反指標 ===")
    print(f"  散戶 MXF 淨 OI (推算): {data['summary'].get('retail_mxf_net_oi', 0):,} 口")
    
    print(f"\n=== 選擇權情緒 ===")
    pc = data['summary'].get('pc_ratio_oi')
    if pc is not None:
        interpret = "看空偏多 (反指標)" if pc > 1 else ("看多偏空 (反指標)" if pc < 0.7 else "中性")
        print(f"  Put/Call Ratio: {pc} ({interpret})")
    print(f"  外資 Call 淨 OI: {data['summary'].get('foreign_call_net_oi', 0):,}")
    print(f"  外資 Put 淨 OI: {data['summary'].get('foreign_put_net_oi', 0):,}")
    print(f"  外資選擇權傾向: {data['summary'].get('foreign_option_sentiment', 0):,}")
    
    print(f"\n=== 十大交易人 ===")
    top10_long = data['summary'].get('top10_long_ratio')
    if top10_long is not None:
        print(f"  十大買方集中度: {top10_long*100:.1f}%")
        print(f"  十大賣方集中度: {data['summary'].get('top10_short_ratio', 0)*100:.1f}%")
        print(f"  十大淨 OI: {data['summary'].get('top10_net_oi', 0):,} 口")
