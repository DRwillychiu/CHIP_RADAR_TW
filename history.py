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
MAX_DAYS = 60  # v3.44.0: 30 → 60 配合 master_profile B3 時間衰減 60 天視窗 + 給 margin_maintenance 60 日均價選項

# TWSE 大盤指數 API (FMTQIK 或 MI_INDEX)
TAIEX_URL = 'https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX'


def _yyyymmdd_to_roc(yyyymmdd: str) -> str:
    """v3.27.3: 西元 → 民國 (TWSE OpenAPI 日期格式)"""
    if not yyyymmdd or len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return ""
    y = int(yyyymmdd[:4]) - 1911
    return f"{y:03d}{yyyymmdd[4:]}"


def _fetch_taiex_index(expected_trade_date: str = None,
                       max_retries: int = 2) -> Optional[Dict[str, float]]:
    """
    抓大盤加權指數 + 漲跌%
    TWSE OpenAPI MI_INDEX 每日更新當日各類股指數和大盤

    v3.27.3: 加 expected_trade_date 偵測 stale 資料。MI_INDEX 也屬於 TWSE OpenAPI
    家族,跟 STOCK_DAY_ALL 一樣在 2026-05-11 21:30 觀察到 publish 5/8 舊資料。

    Returns: {"index": 22850.31, "change_pct": 0.85, "quote_date": "1150511"} 或 None
    """
    expected_roc = _yyyymmdd_to_roc(expected_trade_date) if expected_trade_date else ""

    # v3.44.0 後1: safe_fetch + backoff + quota log
    try:
        from safe_fetch import safe_get, RateLimitedError, ResponseTooLargeError
        _has_safe_fetch = True
    except ImportError:
        _has_safe_fetch = False

    for attempt in range(max_retries):
        try:
            if _has_safe_fetch:
                r = safe_get(TAIEX_URL, source_id='TWSE_MI_INDEX',
                              max_retries=2, timeout=20,
                              headers={'User-Agent': 'Mozilla/5.0'})
            else:
                r = requests.get(TAIEX_URL, timeout=20,
                               headers={'User-Agent': 'Mozilla/5.0'})
            if r.status_code != 200:
                print(f"    ⚠️ TAIEX 第 {attempt+1}/{max_retries} 次: HTTP {r.status_code}")
                if attempt < max_retries - 1:
                    time.sleep(5 + attempt * 3)
                continue

            r.encoding = 'utf-8'
            data = json.loads(r.text)

            # v3.27.3: 檢查回傳資料的 Date (MI_INDEX 每筆都有 Date 欄位)
            response_date = ""
            if isinstance(data, list) and data:
                response_date = (data[0].get('Date') or '').strip()
            if expected_roc and response_date and response_date != expected_roc:
                print(f"    ⚠️ TAIEX MI_INDEX stale: 回傳 Date={response_date} ≠ 預期 {expected_roc} "
                      f"(today {expected_trade_date}) → 跳過本次更新,維持上次資料")
                return None

            # MI_INDEX 回傳格式:
            # [{"Date": "1150511", "指數": "發行量加權股價指數", "收盤指數": "...", ...}, ...]
            #
            # v3.43.0 fix: TWSE OpenAPI「漲跌百分比」一律是絕對值, 由「漲跌」
            # ('+' / '-') 決定符號。但歷史觀察到 sign 欄位偶爾空白或非預期值
            # → 30 天 stock_history.market 全部為正 (5/14 index 下跌 524 點卻
            #   stored chg_pct=+1.25%) → C2 backtest 撞 strong_bull false regime
            # 改: 不信 sign 欄位, 回傳 raw_pct + raw_sign, 由 update_history
            #     拿前日 index 自己算 signed pct (index diff 是事實)
            for row in data:
                name = row.get('指數', '').strip()
                if name == '發行量加權股價指數' or '加權' in name:
                    close_str = row.get('收盤指數', '').replace(',', '').strip()
                    pct_str = row.get('漲跌百分比', '').strip()
                    sign = row.get('漲跌', '').strip()
                    try:
                        close = float(close_str) if close_str else 0
                        raw_pct = float(pct_str) if pct_str else 0
                        # raw 不應用 sign (保留供 fallback)
                        # 真正的 signed pct 留給 update_history 從 index diff 算
                        signed_pct_from_api = raw_pct if sign != '-' else -raw_pct
                        return {
                            "index": close,
                            "change_pct": round(signed_pct_from_api, 2),  # API fallback
                            "raw_pct_abs": round(raw_pct, 2),              # 絕對值 (供查證)
                            "raw_sign": sign,                              # 原始 sign
                            "quote_date": response_date,  # v3.27.3
                        }
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
            "futures": {},  # v3.17.1: 期貨歷史累積
        }
    try:
        with open(history_path, encoding='utf-8') as f:
            h = json.load(f)
            # 向後相容: 沒 futures 欄位則加上
            if "futures" not in h:
                h["futures"] = {}
            return h
    except Exception as e:
        print(f"  ⚠️ history 讀取失敗: {e}, 建立新檔")
        return {
            "updated_at": None,
            "max_days": MAX_DAYS,
            "dates": [],
            "stocks": {},
            "industry_avg": {},
            "market": {},
            "futures": {},
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
    
    # v3.17.1: 清 futures
    if "futures" in history:
        history["futures"] = {d: v for d, v in history["futures"].items() if d in keep_dates}
    
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
    
    # 4. 抓大盤指數 (v3.27.3: 傳 trade_date 偵測 stale)
    print(f"  [大盤] 抓取 TWSE 加權指數...")
    taiex = _fetch_taiex_index(expected_trade_date=trade_date)
    if taiex:
        # v3.43.0 fix: 用前日 index 自己算 signed change_pct (絕對事實)
        # 避免 API sign 偶爾空白導致負日子也存成正值 (5/14 index 41898→41374
        # 跌 1.25% 卻 stored +1.25%)
        prev_dates = sorted(d for d in history.get("market", {}) if d < trade_date)
        api_pct = taiex.get('change_pct', 0)
        verified_pct = None
        if prev_dates:
            prev_date = prev_dates[-1]
            prev_index = (history["market"].get(prev_date) or {}).get('index')
            cur_index = taiex.get('index')
            if prev_index and cur_index and prev_index > 0:
                # 真實 signed change_pct = (today - yesterday) / yesterday × 100
                verified_pct = round((cur_index - prev_index) / prev_index * 100, 2)
                # 若 API sign 跟事實不符, 用 verified 取代
                if abs(verified_pct - api_pct) > 0.05:   # 0.05% 容差
                    print(f"  ⚠️ [v3.43.0 fix] TAIEX API change_pct={api_pct:+.2f}% "
                          f"vs index-diff verified={verified_pct:+.2f}% "
                          f"(prev_idx={prev_index} cur_idx={cur_index}) → 採用 verified")
                    taiex['change_pct'] = verified_pct
                    taiex['change_pct_source'] = 'index_diff_verified'
                    taiex['change_pct_api_original'] = api_pct
                else:
                    taiex['change_pct_source'] = 'api_confirmed'
        if 'change_pct_source' not in taiex:
            taiex['change_pct_source'] = 'api_only'   # 無前日可比 (首日)
        history["market"][trade_date] = taiex
        print(f"  ✓ 大盤 {taiex['index']} ({taiex['change_pct']:+.2f}%) "
              f"[source={taiex['change_pct_source']}]")
    else:
        print(f"  ⚠️ 大盤指數抓取失敗或 stale,跳過本次 (保留前次資料)")
    
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


def update_futures_history(
    data_dir: Path,
    trade_date: str,
    futures_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    v3.17.1: 累積期貨歷史資料 (給前端 Modal 圖表用)
    """
    if not futures_data or not futures_data.get('summary'):
        print(f"  ⚠️ 期貨資料為空,跳過歷史累積")
        return None
    
    print(f"\n[期貨歷史] 累積 {trade_date} 期貨指標...")
    
    history_path = data_dir / HISTORY_FILE
    history = _load_history(history_path)
    
    s = futures_data.get('summary', {})
    f = futures_data.get('futures', {})
    
    # 抽取關鍵指標
    futures_snapshot = {
        # 外資期貨
        'foreign_txf_net_oi': s.get('foreign_txf_net_oi', 0),
        'foreign_mxf_net_oi': s.get('foreign_mxf_net_oi', 0),
        'foreign_equivalent_net_oi': s.get('foreign_equivalent_net_oi', 0),
        # 散戶
        'retail_mxf_net_oi': s.get('retail_mxf_net_oi', 0),
        # 選擇權
        'pc_ratio_oi': s.get('pc_ratio_oi'),
        'foreign_call_net_oi': s.get('foreign_call_net_oi', 0),
        'foreign_put_net_oi': s.get('foreign_put_net_oi', 0),
        'foreign_option_sentiment': s.get('foreign_option_sentiment', 0),
        # 十大交易人
        'top10_long_ratio': s.get('top10_long_ratio'),
        'top10_short_ratio': s.get('top10_short_ratio'),
        'top10_net_oi': s.get('top10_net_oi', 0),
        # 三大商品 三法人淨 OI
        'txf_dealer_net': f.get('TXF', {}).get('dealer', {}).get('net_oi', 0),
        'txf_trust_net': f.get('TXF', {}).get('trust', {}).get('net_oi', 0),
        'mxf_dealer_net': f.get('MXF', {}).get('dealer', {}).get('net_oi', 0),
        'mxf_trust_net': f.get('MXF', {}).get('trust', {}).get('net_oi', 0),
        # TMF 微型台指 (v3.17.1)
        'tmf_dealer_net': f.get('TMF', {}).get('dealer', {}).get('net_oi', 0),
        'tmf_trust_net': f.get('TMF', {}).get('trust', {}).get('net_oi', 0),
        'tmf_foreign_net': f.get('TMF', {}).get('foreign', {}).get('net_oi', 0),
    }
    
    history.setdefault("futures", {})[trade_date] = futures_snapshot
    
    if trade_date not in history["dates"]:
        history["dates"].append(trade_date)
        history["dates"].sort()
    
    _prune_old_data(history, MAX_DAYS)
    
    history["updated_at"] = datetime.now(TW_TZ).isoformat()
    
    with open(history_path, "w", encoding="utf-8") as f_out:
        json.dump(history, f_out, ensure_ascii=False, indent=1)
    
    fut_days = len(history.get("futures", {}))
    print(f"  ✓ 期貨歷史累積 {fut_days} 天 (最近 30 天)")
    print(f"     外資等效大台: {futures_snapshot['foreign_equivalent_net_oi']:+,} 口")
    pc = futures_snapshot.get('pc_ratio_oi')
    print(f"     P/C Ratio: {pc if pc is not None else '—'}")
    
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
