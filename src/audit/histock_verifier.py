"""
========================================================================
Module: histock_verifier.py  (v3.14.4 新增)
功能：透過 HiStock 驗證 TWSE OpenAPI 融資融券資料的實際日期

背景：
  TWSE OpenAPI 的 MI_MARGN 不提供資料日期欄位，只給「今日餘額」「前日餘額」。
  若爬蟲執行時 TWSE 還未公告當日資料(通常 21:30 後才公告)，
  會抓到 T-1 的資料但無從得知。

解法：
  拿 3 檔大型股 (2330, 2317, 2454) 的融資餘額，去 HiStock 比對。
  HiStock 網站明確顯示每一行資料的日期 (MM/DD)。
  若 TWSE 的數字跟 HiStock 某一天吻合 → 就知道資料的真實日期。

輸出：
  {
    "verified": True/False,
    "data_date": "20260422",  # YYYYMMDD 格式
    "confidence": "high/medium/low",
    "samples": [
      {"code": "2330", "twse_balance": 25255, "histock_date": "04/22", "histock_balance": 25255, "match": True},
      ...
    ]
  }

使用：
  from histock_verifier import verify_margin_date
  result = verify_margin_date(twse_margin_data)
========================================================================
"""

import re
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# 驗證用的 3 檔代表股 (選流動性大的,HiStock 一定有資料)
VERIFY_STOCKS = [
    ('2330', '台積電'),
    ('2317', '鴻海'),
    ('2454', '聯發科'),
]

HISTOCK_URL_TEMPLATE = "https://histock.tw/stock/chips.aspx?no={code}&m=mg"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
}


def _fetch_histock_margin(code: str, timeout: int = 15, max_retries: int = 2) -> Optional[List[Dict[str, Any]]]:
    """
    抓取 HiStock 個股融資融券頁面，解析出近期每一天的資料
    v3.14.4: 加 retry 機制,避免偶發 503
    
    Returns: [{"date": "04/22", "balance": 25255, "change": 148}, ...]
             或 None (失敗)
    """
    url = HISTOCK_URL_TEMPLATE.format(code=code)
    
    html = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            if resp.status_code == 200:
                html = resp.text
                break
            else:
                print(f"    ⚠️ HiStock {code} 第 {attempt+1}/{max_retries} 次: HTTP {resp.status_code}")
                if attempt < max_retries - 1:
                    time.sleep(5 + attempt * 3)  # 5s, 8s
        except Exception as e:
            print(f"    ⚠️ HiStock {code} 第 {attempt+1}/{max_retries} 次失敗: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
    
    if html is None:
        return None
    
    # 解析 HTML：
    # <td class="date"><span>04/22</span></td>
    # <td class=""><span class="clr-rd">148</span></td>    (融資增加)
    # <td class="b-b"><span>25,255</span></td>              (融資餘額)
    pattern = re.compile(
        r'<td class="date"><span>(\d{2}/\d{2})</span></td>'
        r'<td[^>]*><span[^>]*>(-?[\d,]+)</span></td>'
        r'<td[^>]*><span[^>]*>([\d,]+)</span></td>',
        re.DOTALL
    )
    
    matches = pattern.findall(html)
    if not matches:
        print(f"    ⚠️ HiStock {code}: HTML 結構無法解析")
        return None
    
    result = []
    for date, change, balance in matches[:10]:  # 只取近 10 天
        try:
            result.append({
                'date': date,                                    # "04/22"
                'balance': int(balance.replace(',', '')),        # 融資餘額
                'change': int(change.replace(',', '')),          # 融資增減
            })
        except ValueError:
            continue
    
    return result if result else None


def _parse_histock_date(mm_dd: str) -> Optional[str]:
    """
    把 HiStock 的 "04/22" 轉成 "20260422" (YYYYMMDD)
    
    智能判斷年份：
      - 如果 MM/DD 是未來日期 (大於今天) → 視為去年
      - 否則視為今年
    """
    try:
        mm, dd = mm_dd.split('/')
        today = datetime.now()
        year = today.year
        
        try:
            d = datetime(year, int(mm), int(dd))
        except ValueError:
            return None
        
        # 如果這個日期比今天還晚,一定是去年
        if d > today + timedelta(days=1):
            d = datetime(year - 1, int(mm), int(dd))
        
        return d.strftime('%Y%m%d')
    except Exception:
        return None


def verify_margin_date(twse_margin: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    主驗證函數：比對 TWSE 融資餘額跟 HiStock，推斷資料日期
    
    Args:
        twse_margin: TWSE 的融資融券資料字典 {code: {margin_balance, ...}}
    
    Returns:
        {
            "verified": bool,              # 是否成功驗證
            "data_date": str,              # 推斷的資料日期 (YYYYMMDD)
            "confidence": str,             # "high"/"medium"/"low"
            "samples": list,               # 驗證樣本明細
            "message": str,                # 人類可讀的訊息
            "checked_at": str,             # 驗證時間 (ISO)
        }
    """
    print("\n  🔍 HiStock 驗證融資融券資料日期...")
    
    samples = []
    matched_dates = []
    
    for i, (code, name) in enumerate(VERIFY_STOCKS):
        if i > 0:
            time.sleep(3)  # HiStock 間距 3 秒,避免過快
        
        # 從 TWSE 取得該檔的融資餘額
        twse_record = twse_margin.get(code)
        if not twse_record:
            print(f"    ⚠️ TWSE 沒有 {code} {name} 的資料")
            continue
        
        twse_balance = twse_record.get('margin_balance', 0)
        
        # 爬 HiStock
        print(f"    [{i+1}/3] 驗證 {code} {name}... (TWSE 餘額: {twse_balance:,})")
        histock_data = _fetch_histock_margin(code)
        
        if not histock_data:
            samples.append({
                'code': code,
                'name': name,
                'twse_balance': twse_balance,
                'match': False,
                'reason': 'HiStock 抓取失敗',
            })
            continue
        
        # 在 HiStock 近 10 天資料中找餘額吻合的日期
        matched_date = None
        for day in histock_data:
            if day['balance'] == twse_balance:
                matched_date = day['date']
                break
        
        if matched_date:
            yyyymmdd = _parse_histock_date(matched_date)
            samples.append({
                'code': code,
                'name': name,
                'twse_balance': twse_balance,
                'histock_date': matched_date,
                'histock_balance': twse_balance,
                'data_date': yyyymmdd,
                'match': True,
            })
            matched_dates.append(yyyymmdd)
            print(f"        ✅ 匹配 HiStock {matched_date} ({yyyymmdd})")
        else:
            # 沒找到 → TWSE 資料可能很舊
            samples.append({
                'code': code,
                'name': name,
                'twse_balance': twse_balance,
                'histock_recent': [d['date'] for d in histock_data[:3]],
                'match': False,
                'reason': 'TWSE 餘額在 HiStock 近 10 天找不到對應',
            })
            print(f"        ❌ 無吻合 (HiStock 近期: {[d['date'] for d in histock_data[:3]]})")
    
    # 綜合判斷
    total_checked = len([s for s in samples if s.get('match') is True or 
                         (s.get('reason') == 'HiStock 抓取失敗') is False])
    total_matched = len(matched_dates)
    
    if not matched_dates:
        return {
            'verified': False,
            'data_date': None,
            'confidence': 'low',
            'samples': samples,
            'message': '❌ HiStock 驗證失敗: 無法確認 TWSE 資料日期 (全部抓取失敗)',
            'checked_at': datetime.now().isoformat(),
        }
    
    # 如果都匹配到同一天
    unique_dates = set(matched_dates)
    
    if len(unique_dates) == 1:
        data_date = matched_dates[0]
        # 根據成功驗證的樣本數決定 confidence
        if total_matched >= 3:
            confidence = 'high'
            message = f'✅ HiStock 驗證通過 (3/3): TWSE 資料為 {data_date}'
        elif total_matched == 2:
            confidence = 'high'
            message = f'✅ HiStock 驗證通過 (2/2 致): TWSE 資料為 {data_date}'
        else:
            # 只有 1 個成功但吻合 → medium 信心
            confidence = 'medium'
            message = f'⚠️ HiStock 部分驗證 (僅 1/3 成功抓取，餘額吻合): TWSE 資料為 {data_date}'
    else:
        # 結果分歧 (例: 2330 指到 04/22, 2317 指到 04/21) → 有問題
        from collections import Counter
        most_common = Counter(matched_dates).most_common(1)[0]
        data_date = most_common[0]
        confidence = 'low'
        message = f'⚠️ HiStock 驗證結果分歧 {matched_dates}, 取多數 {data_date}'
    
    return {
        'verified': True,
        'data_date': data_date,
        'confidence': confidence,
        'samples': samples,
        'message': message,
        'checked_at': datetime.now().isoformat(),
    }


# ════════════════════════════════════════════════════════════════════
#  CLI 測試
# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import json
    import sys
    
    # 測試模式：從 TWSE OpenAPI 抓一份當下資料來驗證
    print("=" * 60)
    print("🧪 HiStock 驗證器獨立測試")
    print("=" * 60)
    
    # 抓 TWSE 當下資料
    print("\n[1/2] 抓 TWSE OpenAPI 融資融券...")
    try:
        resp = requests.get(
            'https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN',
            timeout=30
        )
        twse_raw = resp.json()
        print(f"    ✓ TWSE 抓到 {len(twse_raw)} 筆")
    except Exception as e:
        print(f"    ❌ TWSE 抓取失敗: {e}")
        sys.exit(1)
    
    # 轉成 margin.py 用的格式
    twse_dict = {}
    for r in twse_raw:
        code = r.get('股票代號', '').strip()
        if code:
            try:
                twse_dict[code] = {
                    'margin_balance': int(str(r.get('融資今日餘額', 0)).replace(',', '').strip() or 0),
                }
            except ValueError:
                continue
    
    # 跑驗證
    print(f"\n[2/2] 執行 HiStock 驗證...")
    result = verify_margin_date(twse_dict)
    
    print("\n" + "=" * 60)
    print("📊 驗證結果")
    print("=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))
