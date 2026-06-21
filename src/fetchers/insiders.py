"""
insiders.py — v3.20 MOPS 內部人籌碼信號 + 重大訊息

資料源:
  1. 董監持股餘額: https://mopsov.twse.com.tw/mops/web/ajax_stapap1
     - 職稱 / 姓名 / 選任時持股 / 目前持股 / 設質股數 / 設質比例
  
  2. 當日重大訊息: https://mopsov.twse.com.tw/mops/web/ajax_t05st01
     - 公司代號 / 名稱 / 發言日期時間 / 主旨

設計原則:
  • 限流防禦: time.sleep(5) 避免反爬
  • 民國年: 西元 - 1911
  • 編碼: utf-8
"""

import requests
import re
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://mopsov.twse.com.tw/mops/web/index',
}

MOPS_BASE = 'https://mopsov.twse.com.tw/mops/web'


def _to_roc(year: int) -> int:
    """西元 → 民國"""
    return year - 1911


def _parse_int(s: str) -> int:
    """安全轉 int (處理千分位逗號)"""
    if not s: return 0
    s = s.strip().replace(',', '').replace('\xa0', '').replace('&nbsp;', '')
    if s in ('', '-', '–'): return 0
    try: return int(s)
    except ValueError: return 0


def _parse_float(s: str) -> float:
    """安全轉 float"""
    if not s: return 0.0
    s = s.strip().replace(',', '').replace('%', '').replace('\xa0', '')
    if s in ('', '-', '–'): return 0.0
    try: return float(s)
    except ValueError: return 0.0


# ════════════════════════════════════════════════════════════════════
#  1. 董監持股餘額 (含設質)
# ════════════════════════════════════════════════════════════════════

def fetch_director_holdings(stock_code: str, year: int, month: int, retries: int = 3) -> Optional[Dict[str, Any]]:
    """
    抓單一公司的董監持股 (含設質股數/比例)
    
    Args:
        stock_code: 股票代號 (如 '2330')
        year: 西元年 (如 2026)
        month: 月份 (1-12)
    
    Returns:
        {
            'code': '2330',
            'year_roc': 115,
            'month': 4,
            'directors': [
                {
                    'title': '董事長',
                    'name': '魏哲家',
                    'init_shares': 1000000,    # 選任時持股
                    'current_shares': 1500000, # 目前持股
                    'pledged_shares': 0,       # 設質股數
                    'pledge_ratio': 0.0,       # 設質比例 (%)
                },
                ...
            ],
            'total_pledge_ratio': 12.3,        # 內部人合計設質比例
            'high_pledge_count': 2,            # 設質比例 > 30% 人數 (警報指標)
        }
        失敗回 None
    """
    roc_year = _to_roc(year)
    month_str = f'{month:02d}'
    
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(
                f'{MOPS_BASE}/ajax_stapap1',
                data={
                    'encodeURIComponent': '1',
                    'step': '1',
                    'firstin': '1',
                    'off': '1',
                    'isnew': 'true',  # true = 抓最新公告 (年月會被忽略)
                    'co_id': stock_code,
                    'year': str(roc_year),
                    'month': month_str,
                },
                headers=HEADERS,
                timeout=20,
            )
            
            if r.status_code != 200 or len(r.text) < 1000:
                last_err = f"HTTP {r.status_code}, {len(r.text)}b"
                if attempt < retries - 1:
                    time.sleep(10 + attempt * 5)
                continue
            
            r.encoding = 'utf-8'
            html = r.text
            
            # 解析:找含「目前持股」的 table (HTML tag 大小寫混用,需 IGNORECASE)
            tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
            
            directors = []
            valid_titles = {
                '董事長', '副董事長', '董事', '獨立董事', '監察人', 
                '總經理', '副總經理', '總裁', '副總裁', '財務主管', '會計主管',
                '發言人', '總公司或主要營業所負責人',
                # 變體 (本人/法人代表)
                '董事本人', '獨立董事本人', '監察人本人', '董事長本人',
                '法人董事代表人', '法人董事', '法人監察人',
            }
            
            for t in tables:
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.DOTALL | re.IGNORECASE)
                
                # 第一行 header 必須含「目前持股」+「設質」
                first_row_text = ''.join(rows[:3]) if rows else ''
                if '目前持股' not in first_row_text or '設質' not in first_row_text:
                    continue
                
                for row in rows:
                    tds = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL | re.IGNORECASE)
                    cleaned = [re.sub(r'<[^>]+>', '', x).strip().replace('\xa0','').replace('&nbsp;','') for x in tds]
                    if len(cleaned) < 6:
                        continue
                    
                    title = cleaned[0]
                    name = cleaned[1]
                    
                    # 用職稱白名單過濾 (避免抓到 header 行)
                    if title not in valid_titles:
                        continue
                    if not name or name in ('姓名', ''):
                        continue
                    
                    init_sh = _parse_int(cleaned[2])
                    curr_sh = _parse_int(cleaned[3])
                    pledged = _parse_int(cleaned[4])
                    ratio = _parse_float(cleaned[5])
                    
                    directors.append({
                        'title': title,
                        'name': name,
                        'init_shares': init_sh,
                        'current_shares': curr_sh,
                        'pledged_shares': pledged,
                        'pledge_ratio': ratio,
                    })
            
            if not directors:
                return None
            
            # 計算彙總指標
            total_current = sum(d['current_shares'] for d in directors)
            total_pledged = sum(d['pledged_shares'] for d in directors)
            high_pledge_count = sum(1 for d in directors if d['pledge_ratio'] > 30)
            
            return {
                'code': stock_code,
                'year_roc': roc_year,
                'month': month,
                'directors': directors,
                'total_current_shares': total_current,
                'total_pledged_shares': total_pledged,
                'total_pledge_ratio': round(total_pledged / total_current * 100, 2) if total_current > 0 else 0.0,
                'high_pledge_count': high_pledge_count,
                'directors_count': len(directors),
            }
        
        except Exception as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(10 + attempt * 5)
            continue
    
    print(f"  ⚠️ fetch_director_holdings({stock_code}, {year}/{month}) 失敗: {last_err}")
    return None


def detect_insider_changes(curr: Dict[str, Any], prev: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    偵測異動 (curr vs prev)
    
    Returns:
        [
            {
                'type': 'sell' | 'pledge_up' | 'high_pledge',
                'severity': 'high' | 'medium' | 'low',
                'name': '魏哲家',
                'title': '董事長',
                'message': '...',
                ...
            }
        ]
    """
    alerts = []
    if not curr or not curr.get('directors'):
        return alerts
    
    # 1. 高設質警報 (>30%)
    for d in curr['directors']:
        if d['pledge_ratio'] > 30:
            alerts.append({
                'type': 'high_pledge',
                'severity': 'medium' if d['pledge_ratio'] < 50 else 'high',
                'name': d['name'],
                'title': d['title'],
                'pledge_ratio': d['pledge_ratio'],
                'message': f"{d['title']} {d['name']} 設質 {d['pledge_ratio']:.1f}%",
            })
    
    # 2. 跟前期比對 (申讓偵測)
    if prev and prev.get('directors'):
        prev_map = {(d['title'], d['name']): d for d in prev['directors']}
        
        for d in curr['directors']:
            key = (d['title'], d['name'])
            prev_d = prev_map.get(key)
            if not prev_d:
                continue
            
            # 持股減少 ≥ 1,000 張 (1 張 = 1,000 股)
            shares_change = d['current_shares'] - prev_d['current_shares']
            if shares_change <= -1_000_000:  # -1000 張
                alerts.append({
                    'type': 'sell',
                    'severity': 'high' if shares_change <= -5_000_000 else 'medium',
                    'name': d['name'],
                    'title': d['title'],
                    'shares_change': shares_change,
                    'lots_change': shares_change // 1000,
                    'message': f"{d['title']} {d['name']} 申讓 {abs(shares_change // 1000):,} 張",
                })
            
            # 設質比例增加 ≥ 10%
            ratio_change = d['pledge_ratio'] - prev_d['pledge_ratio']
            if ratio_change >= 10:
                alerts.append({
                    'type': 'pledge_up',
                    'severity': 'medium',
                    'name': d['name'],
                    'title': d['title'],
                    'ratio_change': ratio_change,
                    'message': f"{d['title']} {d['name']} 設質比例 +{ratio_change:.1f}%",
                })
    
    return alerts


# ════════════════════════════════════════════════════════════════════
#  2. 當日重大訊息
# ════════════════════════════════════════════════════════════════════

def fetch_daily_announcements(year: int, month: int, day: int, market: str = 'sii', retries: int = 3) -> List[Dict[str, Any]]:
    """
    抓當日重大訊息
    
    Args:
        year: 西元年
        month: 月 (1-12)
        day: 日 (1-31)
        market: 'sii' 上市 / 'otc' 上櫃
    
    Returns:
        [
            {
                'code': '2330',
                'name': '台積電',
                'date': '115/05/01',
                'time': '15:43:23',
                'subject': '...',
            }
        ]
    """
    roc_year = _to_roc(year)
    month_str = f'{month:02d}'
    day_str = f'{day:02d}'
    
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(
                f'{MOPS_BASE}/ajax_t05st01',
                data={
                    'encodeURIComponent': '1',
                    'step': '1',
                    'firstin': '1',
                    'off': '1',
                    'TYPEK': market,
                    'year': str(roc_year),
                    'month': month_str,
                    'b_date': day_str,
                    'e_date': day_str,
                },
                headers=HEADERS,
                timeout=20,
            )
            
            if r.status_code != 200 or len(r.text) < 1000:
                last_err = f"HTTP {r.status_code}, {len(r.text)}b"
                if attempt < retries - 1:
                    time.sleep(10 + attempt * 5)
                continue
            
            r.encoding = 'utf-8'
            tables = re.findall(r'<table[^>]*>(.*?)</table>', r.text, re.DOTALL)
            
            announcements = []
            for t in tables:
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.DOTALL)
                # 第一行 header 必須有「公司代號」+「主旨」
                first_text = rows[0] if rows else ''
                if '公司代號' not in first_text or '主旨' not in first_text:
                    continue
                
                for row in rows[1:]:
                    tds = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL)
                    cleaned = [re.sub(r'<[^>]+>', '', x).strip().replace('\xa0','').replace('&nbsp;','') for x in tds]
                    if len(cleaned) < 5:
                        continue
                    
                    code = cleaned[0]
                    name = cleaned[1]
                    date = cleaned[2]
                    time_s = cleaned[3]
                    subject = cleaned[4].replace('\r\n', ' ').replace('\n', ' ').strip()
                    
                    if not code or not subject:
                        continue
                    
                    announcements.append({
                        'code': code,
                        'name': name,
                        'date': date,
                        'time': time_s,
                        'subject': subject,
                    })
            
            return announcements
        
        except Exception as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(10 + attempt * 5)
            continue
    
    print(f"  ⚠️ fetch_daily_announcements({year}/{month}/{day}, {market}) 失敗: {last_err}")
    return []


def classify_announcement(subject: str) -> Dict[str, Any]:
    """
    分類重大訊息類型 + 籌碼影響度
    
    Returns:
        {
            'category': '法說會' | '財報' | '購併' | '增減資' | '股利' | '其他',
            'impact': 'high' | 'medium' | 'low',
            'tags': ['關鍵詞', ...],
        }
    """
    subj = subject or ''
    
    # 高影響籌碼相關
    if any(k in subj for k in ['財務報告', '財報', '營收', 'EPS']):
        return {'category': '財報', 'impact': 'high', 'tags': ['財報']}
    if any(k in subj for k in ['購併', '合併', '收購', '併購']):
        return {'category': '購併', 'impact': 'high', 'tags': ['購併']}
    if any(k in subj for k in ['庫藏股', '買回']):
        return {'category': '庫藏股', 'impact': 'high', 'tags': ['庫藏股']}
    if any(k in subj for k in ['減資', '增資', '私募', '可轉債']):
        return {'category': '增減資', 'impact': 'high', 'tags': ['股本變動']}
    
    # 中等影響
    if any(k in subj for k in ['股利', '配息', '除權', '除息']):
        return {'category': '股利', 'impact': 'medium', 'tags': ['股利']}
    if any(k in subj for k in ['法說會', '說明會', '法人說明']):
        return {'category': '法說會', 'impact': 'medium', 'tags': ['法說會']}
    if any(k in subj for k in ['董事會', '股東會', '股東常會']):
        return {'category': '會議', 'impact': 'medium', 'tags': ['會議']}
    
    # 低影響 (人事/異動)
    if any(k in subj for k in ['異動', '更名', '變更']):
        return {'category': '異動', 'impact': 'low', 'tags': ['異動']}
    
    return {'category': '其他', 'impact': 'low', 'tags': []}


# ════════════════════════════════════════════════════════════════════
#  CLI 測試
# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import json
    print("═══ 1. 台積電 2330 董監持股 (2026/04) ═══")
    data = fetch_director_holdings('2330', 2026, 4)
    if data:
        print(f"董監人數: {data['directors_count']}")
        print(f"合計設質比例: {data['total_pledge_ratio']}%")
        print(f"高設質人數 (>30%): {data['high_pledge_count']}")
        print(f"\n前 3 筆:")
        for d in data['directors'][:3]:
            print(f"  {d['title']} {d['name']}: 持股={d['current_shares']:,}, 設質={d['pledge_ratio']}%")
    
    print("\n═══ 2. 5/1 重大訊息 ═══")
    anns = fetch_daily_announcements(2026, 5, 1, 'sii')
    print(f"總計 {len(anns)} 則")
    for a in anns[:5]:
        c = classify_announcement(a['subject'])
        print(f"  [{c['impact'].upper()}] {a['code']} {a['name']}: {a['subject'][:60]}")
