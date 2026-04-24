"""
========================================================================
Module: history.py (v3.15.2 新增)
功能:維護 data/stock_history.json,累積每日個股/產業/大盤資料
      供前端畫三線比較圖

資料結構:
  {
    "updated_at": "2026-04-24T20:15:00+08:00",
    "max_days": 30,
    "dates": ["20260421", "20260422", ..., "20260424"],  # 升冪
    "stocks": {
      "2330": {
        "name": "台積電",
        "industry": "半導體業",
        "daily": {
          "20260422": { "close": 758.0, "change_pct": 1.88 },
          ...
        }
      },
      ...
    },
    "industry_avg": {
      "半導體業": {
        "20260422": { "avg_change_pct": 1.2, "count": 202 },
        ...
      }
    },
    "market": {
      "20260422": { "index": 22850.31, "change_pct": 0.85 },
      ...
    }
  }

使用:
  from history import update_history
  update_history(data_dir, trade_date, daily_quotes_map, industry_map)
========================================================================
"""

import json
import time
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

TW_TZ = timezone(timedelta(hours=8))

HISTORY_FILE = 'stock_history.json'
MAX_DAYS = 30  # 保留最近 30 天

# TWSE 大盤指數 API (FMTQIK 或 MI_INDEX)
TAIEX_URL = 'https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX'


def _fetch_taiex_index(max_retries: int = 2) -> Optional[Dict[str, float]]:
    """
    抓大盤加權指數 + 漲跌%
    TWSE OpenAPI MI_INDEX 每日更新當日各類股指數和大盤
    
    Returns: {"index": 22850.31, "change_pct": 0.85} 或 None
    """
    for attempt in range(max_retries):
        try:
            r = requests.get(TAIEX_URL, timeout=20, 
                           headers={'User-Agent': 'Mozilla/5.0'})
            if r.status_code != 200:
                print(f"    ⚠️ TAIEX 第 {attempt+1}/{max_retries} 次: HTTP {r.status_code}")
                if attempt < max_retries - 1:
                    time.sleep(5 + attempt * 3)
                continue
            
            r.encoding = 'utf-8'
            data = json.loads(r.text)
            
            # MI_INDEX 回傳格式:
            # [{"指數": "發行量加權股價指數", "收盤指數": "22,850.31", "漲跌": "+", "漲跌點數": "192.45", "漲跌百分比": "0.85"}, ...]
            for row in data:
                name = row.get('指數', '').strip()
                if name == '發行量加權股價指數' or '加權' in name:
                    close_str = row.get('收盤指數', '').replace(',', '').strip()
                    pct_str = row.get('漲跌百分比', '').strip()
                    sign = row.get('漲跌', '').strip()
                    try:
                        close = float(close_str) if close_str else 0
                        pct = float(pct_str) if pct_str else 0
                        if sign == '-':
                            pct = -pct
                        return {"index": close, "change_pct": round(pct, 2)}
                    except ValueError:
                        pass
        except Exception as e:
            print(f"    ⚠️ TAIEX 第 {attempt+1}/{max_retries} 次: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
    
    return None


def _load_history(history_path: Path) -> Dict[str, Any]:
    """讀取現有 history,不存在則回傳空結構"""
    if not history_path.exists():
        return {
            "updated_at": None,
            "max_days": MAX_DAYS,
            "dates": [],
            "stocks": {},
            "industry_avg": {},
            "market": {},
        }
    try:
        with open(history_path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠️ history 讀取失敗: {e}, 建立新檔")
        return {
            "updated_at": None,
            "max_days": MAX_DAYS,
            "dates": [],
            "stocks": {},
            "industry_avg": {},
            "market": {},
        }


def _prune_old_data(history: Dict[str, Any], max_days: int = MAX_DAYS) -> None:
    """清除超過 max_days 的舊資料"""
    dates = sorted(history.get("dates", []))
    if len(dates) <= max_days:
        return
    
    keep_dates = set(dates[-max_days:])
    removed = len(dates) - len(keep_dates)
    
    # 更新 dates
    history["dates"] = sorted(keep_dates)
    
    # 清每檔 stock 的 daily
    for code, stock in history.get("stocks", {}).items():
        stock["daily"] = {d: v for d, v in stock.get("daily", {}).items() if d in keep_dates}
    
    # 清 industry_avg
    for ind, avg_data in history.get("industry_avg", {}).items():
        history["industry_avg"][ind] = {d: v for d, v in avg_data.items() if d in keep_dates}
    
    # 清 market
    history["market"] = {d: v for d, v in history.get("market", {}).items() if d in keep_dates}
    
    print(f"  🗑️ 清除 {removed} 天舊資料")


def update_history(
    data_dir: Path,
    trade_date: str,
    daily_quotes_map: Dict[str, Dict[str, Any]],
    industry_map: Dict[str, Any],
    branches_results: Optional[list] = None,
) -> Dict[str, Any]:
    """
    更新歷史資料檔,注入當日個股收盤、產業平均、大盤指數
    
    Args:
        data_dir: 資料目錄
        trade_date: YYYYMMDD
        daily_quotes_map: {code: {close, change_pct, ...}}
        industry_map: industry_classifier 的對照表
        branches_results: 分點爬蟲結果 (拿 stock_name 用)
    
    Returns:
        更新後的 history 物件
    """
    print(f"\n[歷史累積] 更新 {trade_date} 歷史資料...")
    
    history_path = data_dir / HISTORY_FILE
    history = _load_history(history_path)
    
    # 1. 建立股票代號 → 名稱的 map (從 branches_results 或 quotes)
    name_map = {}
    if branches_results:
        for br in branches_results:
            for s in (br.get("buys", []) + br.get("sells", [])):
                code = s.get("code", "").strip()
                name = s.get("name", "").strip()
                if code and name:
                    name_map[code] = name
    
    # 2. 更新每檔個股的當日資料
    stock2ind = industry_map.get("stock_industry", {})
    added_stocks = 0
    for code, quote in daily_quotes_map.items():
        close = quote.get("close", 0)
        change_pct = quote.get("change_pct", 0)
        if not close:
            continue
        
        if code not in history["stocks"]:
            history["stocks"][code] = {
                "name": name_map.get(code, ""),
                "industry": stock2ind.get(code, ""),
                "daily": {},
            }
            added_stocks += 1
        
        # 補名稱(若之前沒有但這次有)
        if not history["stocks"][code].get("name") and name_map.get(code):
            history["stocks"][code]["name"] = name_map[code]
        # 補產業(若之前沒有但這次有)
        if not history["stocks"][code].get("industry") and stock2ind.get(code):
            history["stocks"][code]["industry"] = stock2ind[code]
        
        history["stocks"][code]["daily"][trade_date] = {
            "close": round(close, 2),
            "change_pct": round(change_pct, 2),
        }
    
    print(f"  ✓ 累積 {len(daily_quotes_map)} 檔個股 ({added_stocks} 檔新增)")
    
    # 3. 計算產業平均漲跌
    industry_stats = {}  # industry -> [change_pcts]
    for code, quote in daily_quotes_map.items():
        ind = stock2ind.get(code)
        if not ind or ind.startswith("未知"):
            continue
        change_pct = quote.get("change_pct", 0)
        industry_stats.setdefault(ind, []).append(change_pct)
    
    for ind, pcts in industry_stats.items():
        if len(pcts) < 3:
            continue
        avg = sum(pcts) / len(pcts)
        if ind not in history["industry_avg"]:
            history["industry_avg"][ind] = {}
        history["industry_avg"][ind][trade_date] = {
            "avg_change_pct": round(avg, 3),
            "count": len(pcts),
        }
    print(f"  ✓ 運算 {len(industry_stats)} 個產業平均")
    
    # 4. 抓大盤指數
    print(f"  [大盤] 抓取 TWSE 加權指數...")
    taiex = _fetch_taiex_index()
    if taiex:
        history["market"][trade_date] = taiex
        print(f"  ✓ 大盤 {taiex['index']} ({taiex['change_pct']:+.2f}%)")
    else:
        print(f"  ⚠️ 大盤指數抓取失敗,跳過本次")
    
    # 5. 更新 dates 清單
    if trade_date not in history["dates"]:
        history["dates"].append(trade_date)
        history["dates"].sort()
    
    # 6. 清除過舊資料
    _prune_old_data(history, MAX_DAYS)
    
    # 7. 寫回
    history["updated_at"] = datetime.now(TW_TZ).isoformat()
    history["max_days"] = MAX_DAYS
    
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)
    
    size_kb = history_path.stat().st_size / 1024
    print(f"  ✓ 寫入 {history_path.name} ({size_kb:.1f} KB, 保留 {len(history['dates'])} 天)")
    
    return history


# ════════════════════════════════════════════════════════════════════
#  CLI 測試
# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("🧪 history.py 獨立測試 - 僅測試大盤抓取")
    taiex = _fetch_taiex_index()
    if taiex:
        print(f"✅ 大盤指數: {taiex}")
    else:
        print("❌ 大盤指數抓取失敗")
