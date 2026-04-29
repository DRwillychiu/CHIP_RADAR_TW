"""
分點籌碼觀察站 - 完整版爬蟲 (v3.6)
功能：
  1. 爬取每個分點的「金額 (c=B)」和「張數 (c=E)」雙模式資料
  2. FIFO 部位追蹤，累積已實現損益（基準日 2026/4/21 起算）
  3. 資料 AES-256-GCM 加密
  4. 自動更新 positions.json 累積部位狀態
  5. 自動分類股票市場類型 (上市/上櫃/興櫃/ETF/KY/特別股)
  6. 整合個人標記 + 市場公認標記

模組架構：
  - branches.py        分點清單 + 個人/市場標記
  - market_classifier.py  股票市場分類
  - styles.py (內建)    交易風格判定
  - crawler.py (本檔)   爬蟲主流程
"""
import requests
import re
import json
import time
import os
import sys
import random
import base64
from pathlib import Path
from collections import deque
from datetime import datetime, timezone, timedelta
from copy import deepcopy

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ========== 模組化 import ==========
from branches import (
    WATCHED_BRANCHES, get_unique_branches,
    MASTER_STYLES, STYLE_LABELS, LIMIT_UP_THRESHOLD, NEAR_LIMIT_UP_THRESHOLD,
    get_master_styles, get_masters_of_style,
)
from market_classifier import get_classifier, CATEGORY_LABELS, CATEGORY_LABELS_SIMPLE
from institutional import (
    fetch_all_public_data, compute_alignment, compute_floating_pnl_pct
)
import reports  # v3.9 週報/月報生成
import margin   # v3.11 融資融券
import industry_classifier  # v3.15.0 產業分類
import history  # v3.15.2 歷史資料累積
import futures  # v3.17 期貨選擇權籌碼

TW_TZ = timezone(timedelta(hours=8))

def now_tw():
    return datetime.now(TW_TZ)

# ========== 爬蟲參數 ==========

TOP_N = 30                # 每個分點保留的買/賣超前 N 檔
DELAY_MIN = 2.0           # 請求間隔最小秒
DELAY_MAX = 4.0           # 請求間隔最大秒
COOL_DOWN_EVERY = 10      # 每 N 個分點後長休息
COOL_DOWN_SECONDS = 8
BASELINE_DATE = "20260421"  # 累積損益基準日（不納入此日之前資料）

URL_TPL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb0.djhtm?a={code}&b={code}&c={mode}&d=1"
HOME_URL = "https://fubon-ebrokerdj.fbs.com.tw/"

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

ROW_PATTERN = re.compile(
    r"<tr>\s*<td[^>]*id=\"oAddCheckbox\"[^>]*>\s*"
    r"(?:"
    r"<SCRIPT[^>]*>\s*<!--\s*GenLink2stk\('(?:AS)?(\w+)',\s*'([^']+)'\)"
    r"|"
    r"<a[^>]*>([0-9A-Z]+)([^<]+)</a>"
    r")"
    r".*?"
    r"<td[^>]*>([\d,]+)</td>\s*"
    r"<td[^>]*>([\d,]+)</td>\s*"
    r"<td[^>]*>(-?[\d,]+)</td>",
    re.DOTALL,
)

# ========== 加密 ==========

PBKDF2_ITERATIONS = 100000

def encrypt_data(plaintext: str, password: str) -> str:
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    key = kdf.derive(password.encode("utf-8"))
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    return base64.b64encode(salt + iv + ct).decode("ascii")


def decrypt_data(token: str, password: str) -> str:
    raw = base64.b64decode(token)
    salt, iv, ct = raw[:16], raw[16:28], raw[28:]
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    key = kdf.derive(password.encode("utf-8"))
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ct, None).decode("utf-8")


# ========== 爬蟲主邏輯 ==========

def parse_region(html):
    """解析買超或賣超表格區塊"""
    rows = []
    for m in ROW_PATTERN.finditer(html):
        code = m.group(1) or m.group(3)
        name = (m.group(2) or m.group(4) or "").strip()
        try:
            v1 = int(m.group(5).replace(",", ""))
            v2 = int(m.group(6).replace(",", ""))
            v3 = int(m.group(7).replace(",", ""))
        except ValueError:
            continue
        rows.append({"code": code, "name": name, "v1": v1, "v2": v2, "v3": v3})
    return rows


def fetch_branch_mode(branch_code, mode, max_retries=3):
    """爬取指定分點的指定模式 (mode='B' 金額, mode='E' 張數)"""
    url = URL_TPL.format(code=branch_code, mode=mode)
    last_err = None
    for attempt in range(max_retries):
        try:
            s = requests.Session()
            s.headers.update({
                "User-Agent": random.choice(UA_POOL),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Referer": HOME_URL,
                "Connection": "keep-alive",
            })
            r = s.get(url, timeout=20)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                time.sleep(3 + attempt * 3)
                continue
            html = r.content.decode("big5", errors="replace")
            if len(html) < 5000:
                last_err = f"頁面過小 ({len(html)}b)"
                time.sleep(5 + attempt * 3)
                continue
            
            date_m = re.search(r"資料日期：(\d{8})", html)
            date = date_m.group(1) if date_m else None
            
            buy_idx = html.find("買超</td>")
            sell_idx = html.find("賣超</td>")
            if buy_idx < 0 or sell_idx < 0:
                return {"date": date, "buys": [], "sells": [], "error": None}
            
            buys = parse_region(html[buy_idx:sell_idx])[:TOP_N]
            sells = parse_region(html[sell_idx:])[:TOP_N]
            return {"date": date, "buys": buys, "sells": sells, "error": None}
        except Exception as e:
            last_err = str(e)
            time.sleep(3 + attempt * 3)
    return {"date": None, "buys": [], "sells": [], "error": last_err}


def fetch_branch_combined(branch_code):
    """
    爬取金額+張數雙模式，合併為完整資料
    回傳結構:
    {
        "date": "20260421",
        "buys": [{
            "code": "2454", "name": "聯發科",
            "buy_amt": 213521, "sell_amt": 51477, "net_amt": 162044,  # 仟元
            "buy_lot": 102, "sell_lot": 25, "net_lot": 77,             # 張
            "buy_avg": 2093.34, "sell_avg": 2059.08,                    # 元/股
            "pnl_intraday": -85.66                                       # 萬元 (當日沖銷)
        }, ...],
        "sells": [...],
        "error": None
    }
    """
    # 爬金額模式
    amt_result = fetch_branch_mode(branch_code, "B")
    if amt_result["error"]:
        return {"date": None, "buys": [], "sells": [], "error": amt_result["error"]}
    
    time.sleep(random.uniform(1.5, 2.5))  # 兩次請求之間的小停頓
    
    # 爬張數模式
    lot_result = fetch_branch_mode(branch_code, "E")
    if lot_result["error"]:
        # 張數爬失敗也可以繼續，只是沒有張數資料
        lot_result = {"date": None, "buys": [], "sells": [], "error": None}
    
    # 合併策略：聯集（不論在哪個排行）→ 最完整的當日交易紀錄
    # - 只在金額排行的 → 有 amt，lot 為 0（可能是高價股，張數少沒上榜）
    # - 只在張數排行的 → 有 lot，amt 為 0（可能是低價股，金額少沒上榜）
    # - 兩邊都有的 → amt + lot 都完整（可計算 FIFO 損益）
    def merge_rows(amt_rows, lot_rows):
        amt_map = {r["code"]: r for r in amt_rows}
        lot_map = {r["code"]: r for r in lot_rows}
        all_codes = list({r["code"]: None for r in amt_rows + lot_rows}.keys())  # 保持順序（優先依金額排行）
        
        merged = []
        for code in all_codes:
            ar = amt_map.get(code)
            lr = lot_map.get(code)
            # 名稱以任一為主（一致的）
            name = (ar or lr)["name"]
            
            buy_amt = ar["v1"] if ar else 0
            sell_amt = ar["v2"] if ar else 0
            net_amt = ar["v3"] if ar else 0
            buy_lot = lr["v1"] if lr else 0
            sell_lot = lr["v2"] if lr else 0
            net_lot = lr["v3"] if lr else 0
            
            # 只有張數沒金額時，嘗試用 TWSE 當日成交補金額（未來可擴充）
            # 目前：只有張數沒金額 → 金額=0（暫時），資料標記為 lot_only
            has_amt = ar is not None
            has_lot = lr is not None
            
            # 均價（元/股）= 金額(仟元) / 張數（兩個都有才能算）
            buy_avg = round(buy_amt * 1.0 / buy_lot, 2) if buy_lot > 0 and buy_amt > 0 else 0.0
            sell_avg = round(sell_amt * 1.0 / sell_lot, 2) if sell_lot > 0 and sell_amt > 0 else 0.0
            
            # 當日沖銷損益（只有買均和賣均都有才能算）
            realized_lots = min(buy_lot, sell_lot)
            if realized_lots > 0 and buy_avg > 0 and sell_avg > 0:
                pnl_intraday = round((sell_avg - buy_avg) * realized_lots * 1000 / 10000, 2)
            else:
                pnl_intraday = 0.0
            
            # 交易風格判定 (per stock)
            #   daytrade_ratio = min(買張, 賣張) / max(買張, 賣張)
            #     > 0.7  → daytrade (當沖)
            #     0.3-0.7 → partial (部分當沖+留倉)
            #     < 0.3   → overnight (主要留倉/建倉)
            trade_style = "unknown"
            daytrade_ratio = 0.0
            overnight_lots = 0  # 今日留倉張數（淨買正值代表新留倉）
            overnight_cost_wan = 0.0  # 留倉成本（萬元）
            
            if buy_lot > 0 or sell_lot > 0:
                max_lot = max(buy_lot, sell_lot)
                min_lot = min(buy_lot, sell_lot)
                if max_lot > 0:
                    daytrade_ratio = round(min_lot / max_lot, 3)
                
                if daytrade_ratio >= 0.7:
                    trade_style = "daytrade"
                elif daytrade_ratio >= 0.3:
                    trade_style = "partial"
                else:
                    trade_style = "overnight"
                
                # 今日淨建倉
                if buy_lot > sell_lot:
                    overnight_lots = buy_lot - sell_lot
                    if buy_avg > 0:
                        overnight_cost_wan = round(overnight_lots * buy_avg * 1000 / 10000, 2)
            elif buy_amt > 0 or sell_amt > 0:
                # 只有金額沒有張數（高價股），用金額估算風格
                max_amt = max(buy_amt, sell_amt)
                min_amt = min(buy_amt, sell_amt)
                if max_amt > 0:
                    daytrade_ratio = round(min_amt / max_amt, 3)
                
                if daytrade_ratio >= 0.7:
                    trade_style = "daytrade"
                elif daytrade_ratio >= 0.3:
                    trade_style = "partial"
                else:
                    trade_style = "overnight"
            
            merged.append({
                "code": code, "name": name,
                "buy_amt": buy_amt, "sell_amt": sell_amt, "net_amt": net_amt,
                "buy_lot": buy_lot, "sell_lot": sell_lot, "net_lot": net_lot,
                "buy_avg": buy_avg, "sell_avg": sell_avg,
                "pnl_intraday": pnl_intraday,
                "data_complete": has_amt and has_lot,  # 兩邊都有才能 FIFO
                "trade_style": trade_style,
                "daytrade_ratio": daytrade_ratio,
                "overnight_lots": overnight_lots,
                "overnight_cost_wan": overnight_cost_wan,
            })
        return merged
    
    return {
        "date": amt_result["date"] or lot_result["date"],
        "buys": merge_rows(amt_result["buys"], lot_result["buys"]),
        "sells": merge_rows(amt_result["sells"], lot_result["sells"]),
        "error": None,
    }


# ========== FIFO 部位追蹤 ==========

def load_positions(data_dir: Path, password: str):
    """載入 positions.json 的加密內容；若不存在則回傳空結構"""
    positions_file = data_dir / "positions.json"
    if not positions_file.exists():
        return {"branches": {}, "baseline_date": BASELINE_DATE, "last_update_date": None}
    try:
        with open(positions_file, "r", encoding="utf-8") as f:
            enc = json.load(f)
        if enc.get("encrypted"):
            plain = decrypt_data(enc["data"], password)
            return json.loads(plain)
        else:
            return enc
    except Exception as e:
        print(f"⚠️  載入 positions.json 失敗 ({e})，從頭開始")
        return {"branches": {}, "baseline_date": BASELINE_DATE, "last_update_date": None}


def save_positions(positions: dict, data_dir: Path, password: str):
    """加密儲存 positions.json"""
    plaintext = json.dumps(positions, ensure_ascii=False)
    encrypted_token = encrypt_data(plaintext, password)
    output = {
        "encrypted": True,
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "updated_at": now_tw().isoformat(),
        "baseline_date": positions.get("baseline_date", BASELINE_DATE),
        "data": encrypted_token,
    }
    with open(data_dir / "positions.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


def _rollback_day(positions: dict, trade_date: str) -> int:
    """
    回滾指定日期的 FIFO 變化（用於重跑同一天的覆蓋邏輯）
    
    操作：
      1. 從每個 stock.open_lots 移除該日新建立的 lot 項目
      2. 從每個 stock.realized_history 移除該日記錄
      3. 重算 total_realized_wan
    
    注意：FIFO 中已被 sell 消耗的 lot 無法精確還原（只能近似）
    所以這個機制只適合「同日內快速重跑」，不適合追溯
    
    Returns: 受影響的 (branch, stock) 組合數
    """
    affected = 0
    for br_code, br in positions.get("branches", {}).items():
        for stock_code, stock in br.get("stocks", {}).items():
            changed = False
            
            # 1) 移除該日新建立的 open_lots
            new_open_lots = [lot for lot in stock.get("open_lots", []) 
                             if lot.get("date") != trade_date]
            if len(new_open_lots) != len(stock.get("open_lots", [])):
                stock["open_lots"] = new_open_lots
                changed = True
            
            # 2) 移除該日的 realized_history
            new_history = [rec for rec in stock.get("realized_history", []) 
                           if rec.get("date") != trade_date]
            if len(new_history) != len(stock.get("realized_history", [])):
                # 重算 total
                rolled_pnl = sum(rec["pnl_wan"] for rec in stock.get("realized_history", [])
                                  if rec.get("date") == trade_date)
                stock["realized_history"] = new_history
                stock["total_realized_wan"] = round(
                    stock.get("total_realized_wan", 0.0) - rolled_pnl, 2)
                changed = True
            
            if changed:
                affected += 1
    
    # 把 last_update_date 設為前一個有資料的日期（從歷史推算）
    all_dates = set()
    for br in positions.get("branches", {}).values():
        for st in br.get("stocks", {}).values():
            for rec in st.get("realized_history", []):
                all_dates.add(rec.get("date"))
    
    prior_dates = sorted([d for d in all_dates if d and d < trade_date], reverse=True)
    positions["last_update_date"] = prior_dates[0] if prior_dates else None
    
    return affected


def apply_day_to_positions(positions: dict, trade_date: str, branches_data: list):
    """
    用當日交易資料更新累積部位（FIFO 演算法）
    
    positions["branches"][branch_code]["stocks"][stock_code] = {
        "stock_name": "聯發科",
        "open_lots": [  # FIFO 佇列
            {"date": "20260421", "lots": 402, "avg_price": 2039.38}
        ],
        "realized_history": [
            {"date": "20260421", "pnl_wan": 6.3, "lots_closed": 9}
        ],
        "total_realized_wan": 6.3
    }
    """
    baseline = positions.get("baseline_date", BASELINE_DATE)
    if trade_date < baseline:
        print(f"  (跳過累積損益更新，{trade_date} 早於基準日 {baseline})")
        return
    
    # ════════════════════════════════════════════════════════════════
    # 重複跑同一天的處理（例如 18:30 第一次 + 20:00 第二次）
    # ════════════════════════════════════════════════════════════════
    # 策略：
    #   - 若 trade_date < last_update_date，跳過（避免回頭爬舊日期）
    #   - 若 trade_date == last_update_date，回滾當日的 FIFO 變化後重做
    #     這樣第二次跑就能用更完整的資料覆蓋第一次
    
    last_date = positions.get("last_update_date")
    
    if last_date and trade_date < last_date:
        print(f"  (跳過：{trade_date} 早於 last_update_date={last_date})")
        return
    
    if last_date and trade_date == last_date:
        print(f"  (重新跑同一天 {trade_date}：先回滾當日 FIFO 變化...)")
        rolled_back_count = _rollback_day(positions, trade_date)
        print(f"  → 回滾完成，影響 {rolled_back_count} 個 branch×stock 組合")
    
    branches_store = positions.setdefault("branches", {})
    
    for br in branches_data:
        branch_code = br["code"]
        if not br.get("buys"):
            continue
        
        br_store = branches_store.setdefault(branch_code, {
            "branch_name": br["name"],
            "master": br["master"],
            "stocks": {},
        })
        # 更新分點名（可能有改）
        br_store["branch_name"] = br["name"]
        br_store["master"] = br["master"]
        stocks_store = br_store["stocks"]
        
        # 把 buys + sells 合併成「股票級」的進出記錄
        # buys 裡面的 buy_lot/buy_amt 是當天買了多少
        # buys 和 sells 可能會列出同一檔股票（從不同排序看）
        # 以 buys 為主，因為資料最完整
        seen_codes = set()
        
        for s in br["buys"]:
            stock_code = s["code"]
            if stock_code in seen_codes:
                continue
            seen_codes.add(stock_code)
            
            # 只對「資料完整」（金額+張數都有）的股票做 FIFO
            if not s.get("data_complete", False):
                continue
            
            # 取得當日該分點對該股票的完整進出
            buy_lot = s.get("buy_lot", 0)
            sell_lot = s.get("sell_lot", 0)
            buy_avg = s.get("buy_avg", 0.0)
            sell_avg = s.get("sell_avg", 0.0)
            
            if buy_lot == 0 and sell_lot == 0:
                continue
            
            # 取出或新建該股票部位
            stock_store = stocks_store.setdefault(stock_code, {
                "stock_name": s["name"],
                "open_lots": [],  # FIFO: [{date, lots, avg_price}, ...]
                "realized_history": [],
                "total_realized_wan": 0.0,
            })
            stock_store["stock_name"] = s["name"]
            
            # Step 1: 先建倉（把買進的量加入 FIFO 佇列末尾）
            if buy_lot > 0:
                stock_store["open_lots"].append({
                    "date": trade_date,
                    "lots": buy_lot,
                    "avg_price": buy_avg,
                })
            
            # Step 2: 平倉（從 FIFO 佇列頭部開始扣）
            day_pnl_wan = 0.0
            lots_closed_today = 0
            
            if sell_lot > 0:
                remaining = sell_lot
                queue = stock_store["open_lots"]
                
                while remaining > 0 and queue:
                    head = queue[0]
                    if head["lots"] <= remaining:
                        # 整筆出清
                        closed = head["lots"]
                        pnl = (sell_avg - head["avg_price"]) * closed * 1000 / 10000  # 萬元
                        day_pnl_wan += pnl
                        lots_closed_today += closed
                        remaining -= closed
                        queue.pop(0)
                    else:
                        # 部分出清
                        closed = remaining
                        pnl = (sell_avg - head["avg_price"]) * closed * 1000 / 10000
                        day_pnl_wan += pnl
                        lots_closed_today += closed
                        head["lots"] -= closed
                        remaining = 0
                
                # 如果賣超過持有（可能是基準日前就有倉位），剩餘的 remaining 當作「無基底賣出」
                # 用當日買均作為推估成本，避免異常損益
                if remaining > 0:
                    # 使用當日買均作為假設成本（保守處理）
                    assumed_cost = buy_avg if buy_avg > 0 else sell_avg
                    pnl = (sell_avg - assumed_cost) * remaining * 1000 / 10000
                    day_pnl_wan += pnl
                    lots_closed_today += remaining
            
            # 記錄當日已實現
            if abs(day_pnl_wan) > 0.001 or lots_closed_today > 0:
                day_pnl_wan = round(day_pnl_wan, 2)
                stock_store["realized_history"].append({
                    "date": trade_date,
                    "pnl_wan": day_pnl_wan,
                    "lots_closed": lots_closed_today,
                })
                stock_store["total_realized_wan"] = round(
                    stock_store.get("total_realized_wan", 0.0) + day_pnl_wan, 2
                )
    
    positions["last_update_date"] = trade_date


def compute_period_summaries(positions: dict, trade_date: str, today_branches_data: list = None):
    """
    給每個分點計算：日/週/月/累積 損益，以及交易風格
    回傳 dict: {branch_code: {daily, weekly, monthly, total, open_positions_count, style, ...}}
    
    today_branches_data: 當日爬取的 results 列表，用於計算當日風格指標
    """
    from datetime import datetime as _dt
    
    def parse_date(d):
        return _dt.strptime(d, "%Y%m%d")
    
    today = parse_date(trade_date)
    week_start = today - timedelta(days=today.weekday())  # 本週一
    month_start = today.replace(day=1)
    
    # 當日爬蟲結果 index
    today_branches_map = {}
    if today_branches_data:
        for br in today_branches_data:
            today_branches_map[br["code"]] = br
    
    summaries = {}
    
    # 先處理有 positions 紀錄的分點（歷史損益）
    all_branch_codes = set(positions.get("branches", {}).keys()) | set(today_branches_map.keys())
    
    for branch_code in all_branch_codes:
        br = positions.get("branches", {}).get(branch_code, {"stocks": {}})
        daily = 0.0
        weekly = 0.0
        monthly = 0.0
        total = 0.0
        open_pos_count = 0
        open_total_lots = 0
        
        for stock_code, stock in br.get("stocks", {}).items():
            total += stock.get("total_realized_wan", 0.0)
            for rec in stock.get("realized_history", []):
                try:
                    rec_date = parse_date(rec["date"])
                    pnl = rec.get("pnl_wan", 0.0)
                    if rec_date == today:
                        daily += pnl
                    if rec_date >= week_start:
                        weekly += pnl
                    if rec_date >= month_start:
                        monthly += pnl
                except Exception:
                    continue
            total_lots_for_stock = sum(p["lots"] for p in stock.get("open_lots", []))
            if total_lots_for_stock > 0:
                open_pos_count += 1
                open_total_lots += total_lots_for_stock
        
        # === 當日風格指標 ===
        today_br = today_branches_map.get(branch_code)
        avg_daytrade_ratio = 0.0
        today_total_buy_lot = 0
        today_total_sell_lot = 0
        today_total_buy_amt = 0
        today_total_sell_amt = 0
        today_overnight_lots = 0   # 今日淨新建倉
        today_overnight_cost_wan = 0.0
        today_daytrade_stocks = 0
        today_overnight_stocks = 0
        today_partial_stocks = 0
        stocks_count = 0
        ratio_sum = 0.0
        
        if today_br and today_br.get("buys"):
            for s in today_br["buys"]:
                if not (s.get("buy_lot") or s.get("sell_lot") or s.get("buy_amt") or s.get("sell_amt")):
                    continue
                stocks_count += 1
                today_total_buy_lot += s.get("buy_lot", 0)
                today_total_sell_lot += s.get("sell_lot", 0)
                today_total_buy_amt += s.get("buy_amt", 0)
                today_total_sell_amt += s.get("sell_amt", 0)
                today_overnight_lots += s.get("overnight_lots", 0)
                today_overnight_cost_wan += s.get("overnight_cost_wan", 0.0)
                ratio_sum += s.get("daytrade_ratio", 0.0)
                style = s.get("trade_style", "")
                if style == "daytrade":
                    today_daytrade_stocks += 1
                elif style == "overnight":
                    today_overnight_stocks += 1
                elif style == "partial":
                    today_partial_stocks += 1
        
        if stocks_count > 0:
            avg_daytrade_ratio = round(ratio_sum / stocks_count, 3)
        
        # 當日風格判定（基於當日所有股票平均）
        today_style = "unknown"
        if stocks_count >= 3:
            if avg_daytrade_ratio >= 0.55:
                today_style = "daytrader"
            elif avg_daytrade_ratio >= 0.3:
                today_style = "mixed"
            else:
                today_style = "swing"
        
        summaries[branch_code] = {
            "daily_pnl": round(daily, 2),
            "weekly_pnl": round(weekly, 2),
            "monthly_pnl": round(monthly, 2),
            "total_pnl": round(total, 2),
            "open_positions_count": open_pos_count,
            "open_total_lots": open_total_lots,
            # 風格資訊
            "today_style": today_style,
            "avg_daytrade_ratio": avg_daytrade_ratio,
            "today_buy_lot": today_total_buy_lot,
            "today_sell_lot": today_total_sell_lot,
            "today_buy_amt": today_total_buy_amt,
            "today_sell_amt": today_total_sell_amt,
            "today_net_amt": today_total_buy_amt - today_total_sell_amt,
            "today_overnight_lots": today_overnight_lots,
            "today_overnight_cost_wan": round(today_overnight_cost_wan, 2),
            "today_daytrade_stocks": today_daytrade_stocks,
            "today_overnight_stocks": today_overnight_stocks,
            "today_partial_stocks": today_partial_stocks,
            "today_stocks_count": stocks_count,
        }
    
    return summaries


def compute_limit_up_summary(today_branches_data: list, unique_branches: list):
    """
    v3.12 漲停狙擊匯總
    
    回傳:
    {
      "limit_up_stocks": [  # 今日所有漲停股
        {
          "code": "4536", "name": "達能", "change_pct": 10.0,
          "close": 123.5, "volume_lot": 3500,
          "buyers": [  # 我的分點中誰買了這檔漲停
            {"branch_code": "9227", "branch_name": "凱基-城中", 
             "master": "蔣承翰", "styles": ["next_day_flipper"],
             "buy_amt": 500, "buy_lot": 100, "net_amt": 450, "net_lot": 90,
             "overnight_lots": 90}
          ],
          "total_buy_amt": ..., "total_buy_lot": ...,
          "buyer_count": 1
        }
      ],
      "sniper_ranking": [  # 各分點的漲停狙擊成績
        {
          "branch_code": "9227", "branch_name": "凱基-城中",
          "master": "蔣承翰", "styles": ["next_day_flipper"],
          "limit_up_stocks_bought": 5,           # 買了幾檔漲停股
          "total_limit_up_buy_amt": 2850,        # 買漲停股總金額
          "total_limit_up_buy_lot": 500,         # 買漲停股總張數
          "limit_up_codes": ["4536", "5314", ...]
        }
      ],
      "master_sniper_ranking": [  # 各 master 的漲停狙擊成績（多分點合併）
        {"master": "蔣承翰", "styles": ["next_day_flipper"],
         "branches_count": 2, "limit_up_stocks_bought": 8,
         "total_limit_up_buy_amt": 4500, ...}
      ],
      "consensus_limit_up": [  # 2 位以上 master 同時買的漲停股（超強信號）
        {
          "code": "...", "name": "...", "masters_list": [...],
          "master_count": 3, "total_buy_amt": ...
        }
      ],
      "style_stats": {  # 各風格的漲停狙擊統計
        "next_day_flipper": {"masters": [...], "limit_up_count": 8, "total_buy_amt": 4500},
        ...
      },
      "total_limit_up_today": 35,   # 全市場漲停股總數
      "limit_up_bought_count": 8,    # 我的分點買到幾檔漲停
    }
    """
    code_to_branch = {b["code"]: b for b in unique_branches}
    
    # 收集所有被分點買的漲停股
    limit_up_map = {}  # {stock_code: {...}}
    sniper_map = {}    # {branch_code: {...}}
    
    # v3.13：漲停股被分點賣出 (出貨/隔日沖 Day2 結清)
    limit_up_sell_map = {}   # {stock_code: {sellers:[...]}}
    seller_map = {}          # {branch_code: {...}}
    
    for br_data in today_branches_data:
        branch_code = br_data["code"]
        branch_obj = code_to_branch.get(branch_code, {})
        master = br_data.get("master", "")
        styles = MASTER_STYLES.get(master, ["unknown"])
        
        # ───── BUY 側（原邏輯）─────
        for s in (br_data.get("buys") or []):
            if not s.get("is_limit_up"):
                continue
            
            stock_code = s.get("code")
            if not stock_code:
                continue
            
            # 加入漲停股清單
            if stock_code not in limit_up_map:
                limit_up_map[stock_code] = {
                    "code": stock_code,
                    "name": s.get("name", ""),
                    "change_pct": s.get("change_pct"),
                    "close": s.get("close_price"),
                    "volume_lot": s.get("volume_lot"),
                    "market_type": s.get("market_type"),
                    "industry": s.get("industry"),
                    "buyers": [],
                    "total_buy_amt": 0,
                    "total_buy_lot": 0,
                    "total_net_amt": 0,
                    "total_net_lot": 0,
                    "total_overnight_lots": 0,
                    "masters_set": set(),
                }
            
            lu = limit_up_map[stock_code]
            lu["buyers"].append({
                "branch_code": branch_code,
                "branch_name": br_data.get("name", ""),
                "master": master,
                "styles": styles,
                "region": br_data.get("region", "domestic"),
                "buy_amt": s.get("buy_amt", 0),
                "buy_lot": s.get("buy_lot", 0),
                "sell_amt": s.get("sell_amt", 0),
                "sell_lot": s.get("sell_lot", 0),
                "net_amt": s.get("net_amt", 0),
                "net_lot": s.get("net_lot", 0),
                "overnight_lots": s.get("overnight_lots", 0),
            })
            lu["total_buy_amt"] += s.get("buy_amt", 0) or 0
            lu["total_buy_lot"] += s.get("buy_lot", 0) or 0
            lu["total_net_amt"] += s.get("net_amt", 0) or 0
            lu["total_net_lot"] += s.get("net_lot", 0) or 0
            lu["total_overnight_lots"] += s.get("overnight_lots", 0) or 0
            lu["masters_set"].add(master)
            
            # 分點狙擊榜
            if branch_code not in sniper_map:
                sniper_map[branch_code] = {
                    "branch_code": branch_code,
                    "branch_name": br_data.get("name", ""),
                    "master": master,
                    "styles": styles,
                    "region": br_data.get("region", "domestic"),
                    "limit_up_stocks_bought": 0,
                    "total_limit_up_buy_amt": 0,
                    "total_limit_up_buy_lot": 0,
                    "total_limit_up_net_amt": 0,
                    "total_limit_up_overnight_lots": 0,
                    "limit_up_details": [],   # 每筆漲停買進
                }
            sn = sniper_map[branch_code]
            sn["limit_up_stocks_bought"] += 1
            sn["total_limit_up_buy_amt"] += s.get("buy_amt", 0) or 0
            sn["total_limit_up_buy_lot"] += s.get("buy_lot", 0) or 0
            sn["total_limit_up_net_amt"] += s.get("net_amt", 0) or 0
            sn["total_limit_up_overnight_lots"] += s.get("overnight_lots", 0) or 0
            sn["limit_up_details"].append({
                "code": stock_code,
                "name": s.get("name", ""),
                "change_pct": s.get("change_pct"),
                "buy_amt": s.get("buy_amt", 0),
                "buy_lot": s.get("buy_lot", 0),
                "net_amt": s.get("net_amt", 0),
                "overnight_lots": s.get("overnight_lots", 0),
            })
        
        # ───── SELL 側 (v3.13 新增) ─────
        # 分點「賣超」漲停股 → 疑似隔日沖 Day2 出貨 / 獲利了結
        for s in (br_data.get("sells") or []):
            if not s.get("is_limit_up"):
                continue
            stock_code = s.get("code")
            if not stock_code:
                continue
            
            # 加入漲停賣出清單
            if stock_code not in limit_up_sell_map:
                limit_up_sell_map[stock_code] = {
                    "code": stock_code,
                    "name": s.get("name", ""),
                    "change_pct": s.get("change_pct"),
                    "close": s.get("close_price"),
                    "volume_lot": s.get("volume_lot"),
                    "market_type": s.get("market_type"),
                    "sellers": [],
                    "total_sell_amt": 0,
                    "total_sell_lot": 0,
                    "total_net_sell_amt": 0,   # 淨賣（負數）
                    "total_net_sell_lot": 0,
                    "masters_set": set(),
                }
            
            ls = limit_up_sell_map[stock_code]
            ls["sellers"].append({
                "branch_code": branch_code,
                "branch_name": br_data.get("name", ""),
                "master": master,
                "styles": styles,
                "region": br_data.get("region", "domestic"),
                "buy_amt": s.get("buy_amt", 0),
                "buy_lot": s.get("buy_lot", 0),
                "sell_amt": s.get("sell_amt", 0),
                "sell_lot": s.get("sell_lot", 0),
                "net_amt": s.get("net_amt", 0),  # 會是負數（淨賣）
                "net_lot": s.get("net_lot", 0),
            })
            ls["total_sell_amt"] += s.get("sell_amt", 0) or 0
            ls["total_sell_lot"] += s.get("sell_lot", 0) or 0
            ls["total_net_sell_amt"] += s.get("net_amt", 0) or 0
            ls["total_net_sell_lot"] += s.get("net_lot", 0) or 0
            ls["masters_set"].add(master)
            
            # 分點「漲停出貨榜」
            if branch_code not in seller_map:
                seller_map[branch_code] = {
                    "branch_code": branch_code,
                    "branch_name": br_data.get("name", ""),
                    "master": master,
                    "styles": styles,
                    "region": br_data.get("region", "domestic"),
                    "limit_up_stocks_sold": 0,
                    "total_limit_up_sell_amt": 0,
                    "total_limit_up_sell_lot": 0,
                    "total_limit_up_net_sell_amt": 0,
                    "limit_up_sell_details": [],
                }
            sel = seller_map[branch_code]
            sel["limit_up_stocks_sold"] += 1
            sel["total_limit_up_sell_amt"] += s.get("sell_amt", 0) or 0
            sel["total_limit_up_sell_lot"] += s.get("sell_lot", 0) or 0
            sel["total_limit_up_net_sell_amt"] += s.get("net_amt", 0) or 0
            sel["limit_up_sell_details"].append({
                "code": stock_code,
                "name": s.get("name", ""),
                "change_pct": s.get("change_pct"),
                "sell_amt": s.get("sell_amt", 0),
                "sell_lot": s.get("sell_lot", 0),
                "net_amt": s.get("net_amt", 0),
            })
    
    # 後處理：漲停股清單 + 排序
    limit_up_stocks = []
    consensus_limit_up = []
    for code, lu in limit_up_map.items():
        lu["masters_list"] = sorted(lu["masters_set"])
        lu["master_count"] = len(lu["masters_set"])
        lu["buyer_count"] = len(lu["buyers"])
        del lu["masters_set"]
        limit_up_stocks.append(lu)
        
        # 2 位以上 master 共買 → 加入 consensus
        if lu["master_count"] >= 2:
            consensus_limit_up.append(lu)
    
    limit_up_stocks.sort(key=lambda x: (-x["master_count"], -x["total_buy_amt"]))
    consensus_limit_up.sort(key=lambda x: (-x["master_count"], -x["total_buy_amt"]))
    
    # 分點狙擊排名
    sniper_ranking = sorted(sniper_map.values(), 
                             key=lambda x: (-x["limit_up_stocks_bought"], -x["total_limit_up_buy_amt"]))
    
    # Master 層級聚合（多分點合併）
    master_sniper_map = {}
    for sn in sniper_ranking:
        m = sn["master"]
        if m not in master_sniper_map:
            master_sniper_map[m] = {
                "master": m,
                "styles": sn["styles"],
                "branches": [],
                "limit_up_codes_set": set(),
                "total_limit_up_buy_amt": 0,
                "total_limit_up_buy_lot": 0,
                "total_limit_up_net_amt": 0,
                "total_limit_up_overnight_lots": 0,
            }
        ms = master_sniper_map[m]
        ms["branches"].append({
            "code": sn["branch_code"],
            "name": sn["branch_name"],
            "limit_up_stocks_bought": sn["limit_up_stocks_bought"],
            "total_buy_amt": sn["total_limit_up_buy_amt"],
        })
        ms["total_limit_up_buy_amt"] += sn["total_limit_up_buy_amt"]
        ms["total_limit_up_buy_lot"] += sn["total_limit_up_buy_lot"]
        ms["total_limit_up_net_amt"] += sn["total_limit_up_net_amt"]
        ms["total_limit_up_overnight_lots"] += sn["total_limit_up_overnight_lots"]
        for d in sn["limit_up_details"]:
            ms["limit_up_codes_set"].add(d["code"])
    
    master_sniper_ranking = []
    for m, data in master_sniper_map.items():
        data["branches_count"] = len(data["branches"])
        data["limit_up_stocks_bought"] = len(data["limit_up_codes_set"])
        data["limit_up_codes"] = sorted(data["limit_up_codes_set"])
        del data["limit_up_codes_set"]
        master_sniper_ranking.append(data)
    master_sniper_ranking.sort(key=lambda x: (-x["limit_up_stocks_bought"], -x["total_limit_up_buy_amt"]))
    
    # 依風格統計
    style_stats = {}
    for sn in sniper_ranking:
        for style in sn["styles"]:
            if style not in style_stats:
                style_stats[style] = {
                    "style": style,
                    "masters": set(),
                    "limit_up_count": 0,
                    "total_buy_amt": 0,
                    "total_buy_lot": 0,
                }
            ss = style_stats[style]
            ss["masters"].add(sn["master"])
            ss["limit_up_count"] += sn["limit_up_stocks_bought"]
            ss["total_buy_amt"] += sn["total_limit_up_buy_amt"]
            ss["total_buy_lot"] += sn["total_limit_up_buy_lot"]
    for style, ss in style_stats.items():
        ss["masters"] = sorted(ss["masters"])
        ss["master_count"] = len(ss["masters"])
    
    # v3.13：漲停賣出 (隔日沖 Day2 出貨 / 獲利了結) 後處理
    limit_up_sold_stocks = []
    for code, ls in limit_up_sell_map.items():
        ls["masters_list"] = sorted(ls["masters_set"])
        ls["master_count"] = len(ls["masters_set"])
        ls["seller_count"] = len(ls["sellers"])
        del ls["masters_set"]
        limit_up_sold_stocks.append(ls)
    limit_up_sold_stocks.sort(key=lambda x: (-x["master_count"], -x["total_sell_amt"]))
    
    # 分點漲停出貨排名
    seller_ranking = sorted(seller_map.values(),
                             key=lambda x: (-x["limit_up_stocks_sold"], -x["total_limit_up_sell_amt"]))
    
    return {
        "limit_up_stocks": limit_up_stocks,
        "sniper_ranking": sniper_ranking,
        "master_sniper_ranking": master_sniper_ranking,
        "consensus_limit_up": consensus_limit_up,
        "style_stats": style_stats,
        "limit_up_bought_count": len(limit_up_stocks),
        # v3.13 新增
        "limit_up_sold_stocks": limit_up_sold_stocks,   # 今日被我分點賣超的漲停股
        "seller_ranking": seller_ranking,               # 分點漲停出貨排名
        "limit_up_sold_count": len(limit_up_sold_stocks),
    }


def compute_next_day_flip_verification(today_branches_data: list, 
                                        yesterday_branches_data: list,
                                        unique_branches: list):
    """
    v3.13 隔日沖驗證 — 比對「昨日漲停買進」vs「今日賣超」
    
    實戰場景:
      Day 1: 蔣承翰的 9227 分點買進漲停聯發科 300 張
      Day 2: 9227 分點賣超聯發科 280 張 → 確認隔日沖出貨
    
    回傳:
    {
      "verified_flips": [  # 確認隔日沖的案例
        {
          "branch_code": "9227", "branch_name": "凱基-城中",
          "master": "蔣承翰", "styles": [...],
          "stock_code": "2454", "stock_name": "聯發科",
          "yesterday_buy_lot": 300,  "yesterday_buy_amt": 5000,
          "yesterday_change_pct": 10.0,
          "today_sell_lot": 280, "today_sell_amt": 4800,
          "today_change_pct": -2.5,
          "flip_ratio": 93.3,  # 出貨比例 = 今賣張 / 昨買張
          "status": "full_flip" | "partial_flip" | "over_flip",
        }
      ],
      "pending_positions": [  # 昨日買進但今日未賣（還在留倉）
        { ..., "flip_ratio": 0, "status": "still_holding" }
      ],
      "flipper_scorecard": [  # 依 master 聚合出貨表現
        {
          "master": "蔣承翰", "styles": [...],
          "verified_flip_count": 8,
          "pending_count": 2,
          "total_yesterday_buy_lot": 1200,
          "total_today_sell_lot": 1080,
          "overall_flip_ratio": 90.0,
        }
      ],
      "is_first_day": bool,  # 是否為系統首日（沒昨日資料）
    }
    """
    if not yesterday_branches_data:
        return {
            "verified_flips": [],
            "pending_positions": [],
            "flipper_scorecard": [],
            "is_first_day": True,
        }
    
    code_to_branch = {b["code"]: b for b in unique_branches}
    
    # Step 1: 建 index — 昨日漲停買進明細
    # key = (branch_code, stock_code), value = {...}
    yesterday_limit_up_buys = {}
    for br_data in yesterday_branches_data:
        branch_code = br_data.get("code")
        if not branch_code or not br_data.get("buys"):
            continue
        for s in br_data["buys"]:
            # v3.12 之前沒有 is_limit_up 欄位，相容處理
            is_lu = s.get("is_limit_up")
            if is_lu is None:
                # 用 change_pct 判定
                cp = s.get("change_pct")
                is_lu = (cp is not None and cp >= LIMIT_UP_THRESHOLD)
            if not is_lu:
                continue
            stock_code = s.get("code")
            if not stock_code:
                continue
            key = (branch_code, stock_code)
            yesterday_limit_up_buys[key] = {
                "branch_code": branch_code,
                "stock_code": stock_code,
                "stock_name": s.get("name", ""),
                "buy_lot": s.get("buy_lot", 0) or 0,
                "buy_amt": s.get("buy_amt", 0) or 0,
                "overnight_lots": s.get("overnight_lots", 0) or 0,
                "change_pct": s.get("change_pct"),
            }
    
    # Step 2: 建 index — 今日「該分點 vs 該股」的所有交易（買+賣）
    today_trades = {}
    for br_data in today_branches_data:
        branch_code = br_data.get("code")
        if not branch_code:
            continue
        # buys 和 sells 都要看
        for s in (br_data.get("buys") or []) + (br_data.get("sells") or []):
            stock_code = s.get("code")
            if not stock_code:
                continue
            key = (branch_code, stock_code)
            # 累加（因為 buys 和 sells 理論上不會有同一檔，但保險處理）
            if key in today_trades:
                continue
            today_trades[key] = {
                "branch_code": branch_code,
                "stock_code": stock_code,
                "buy_lot": s.get("buy_lot", 0) or 0,
                "sell_lot": s.get("sell_lot", 0) or 0,
                "buy_amt": s.get("buy_amt", 0) or 0,
                "sell_amt": s.get("sell_amt", 0) or 0,
                "change_pct": s.get("change_pct"),
            }
    
    # Step 3: 配對 — 昨日漲停買進 × 今日賣出動作
    verified_flips = []
    pending_positions = []
    
    for key, yest in yesterday_limit_up_buys.items():
        branch_code = yest["branch_code"]
        branch_obj = code_to_branch.get(branch_code, {})
        master = branch_obj.get("master", "")
        styles = MASTER_STYLES.get(master, ["unknown"])
        
        today = today_trades.get(key, {})
        today_sell_lot = today.get("sell_lot", 0)
        today_sell_amt = today.get("sell_amt", 0)
        
        # 計算出貨比例
        if yest["buy_lot"] > 0:
            flip_ratio = round(today_sell_lot / yest["buy_lot"] * 100, 1)
        else:
            flip_ratio = 0.0
        
        # 判定狀態
        if flip_ratio >= 90:
            status = "full_flip"        # 幾乎全部出清
        elif flip_ratio >= 30:
            status = "partial_flip"     # 部分出貨
        elif flip_ratio > 0:
            status = "minor_flip"       # 少量出貨
        else:
            status = "still_holding"    # 尚未賣出
        
        record = {
            "branch_code": branch_code,
            "branch_name": branch_obj.get("name", ""),
            "master": master,
            "styles": styles,
            "region": branch_obj.get("region", "domestic"),
            "stock_code": yest["stock_code"],
            "stock_name": yest["stock_name"],
            "yesterday_buy_lot": yest["buy_lot"],
            "yesterday_buy_amt": yest["buy_amt"],
            "yesterday_overnight_lots": yest["overnight_lots"],
            "yesterday_change_pct": yest["change_pct"],
            "today_sell_lot": today_sell_lot,
            "today_sell_amt": today_sell_amt,
            "today_change_pct": today.get("change_pct"),
            "flip_ratio": flip_ratio,
            "status": status,
        }
        
        if status == "still_holding":
            pending_positions.append(record)
        else:
            verified_flips.append(record)
    
    # 按出貨比例降序
    verified_flips.sort(key=lambda x: -x["flip_ratio"])
    pending_positions.sort(key=lambda x: -x["yesterday_buy_amt"])
    
    # Step 4: Master 聚合評分
    master_map = {}
    for rec in verified_flips + pending_positions:
        m = rec["master"]
        if m not in master_map:
            master_map[m] = {
                "master": m,
                "styles": rec["styles"],
                "verified_flip_count": 0,
                "pending_count": 0,
                "total_yesterday_buy_lot": 0,
                "total_yesterday_buy_amt": 0,
                "total_today_sell_lot": 0,
                "total_today_sell_amt": 0,
            }
        mm = master_map[m]
        if rec["status"] != "still_holding":
            mm["verified_flip_count"] += 1
        else:
            mm["pending_count"] += 1
        mm["total_yesterday_buy_lot"] += rec["yesterday_buy_lot"]
        mm["total_yesterday_buy_amt"] += rec["yesterday_buy_amt"]
        mm["total_today_sell_lot"] += rec["today_sell_lot"]
        mm["total_today_sell_amt"] += rec["today_sell_amt"]
    
    flipper_scorecard = []
    for m, mm in master_map.items():
        if mm["total_yesterday_buy_lot"] > 0:
            mm["overall_flip_ratio"] = round(
                mm["total_today_sell_lot"] / mm["total_yesterday_buy_lot"] * 100, 1)
        else:
            mm["overall_flip_ratio"] = 0.0
        flipper_scorecard.append(mm)
    flipper_scorecard.sort(key=lambda x: -x["overall_flip_ratio"])
    
    return {
        "verified_flips": verified_flips,
        "pending_positions": pending_positions,
        "flipper_scorecard": flipper_scorecard,
        "is_first_day": False,
    }


def compute_master_summaries(branch_summaries: dict, unique_branches: list, today_branches_data: list = None):
    """
    按高手（master）聚合多分點的統計
    v3.10：支援 co_masters（一分點歸入多位 master）
    回傳: {master_name: {branches: [...], total_*, consensus_stocks: [...]}}
    """
    # 分點代號 → [主 master] + [co_masters]（陣列形式）
    def all_masters_of(b):
        lst = [b.get("master", "未知")]
        lst.extend(b.get("co_masters", []) or [])
        return [m for m in lst if m]
    
    code_to_all_masters = {b["code"]: all_masters_of(b) for b in unique_branches}
    code_to_branch = {b["code"]: b for b in unique_branches}
    
    # 今日爬蟲資料 index
    today_map = {}
    if today_branches_data:
        for br in today_branches_data:
            today_map[br["code"]] = br
    
    master_data = {}
    
    for branch_code, summary in branch_summaries.items():
        # v3.10：一個分點可能歸入多位 master
        for master in code_to_all_masters.get(branch_code, ["未知"]):
            if master not in master_data:
                master_data[master] = {
                    "master": master,
                    "branches": [],
                    "total_daily_pnl": 0.0,
                    "total_weekly_pnl": 0.0,
                    "total_monthly_pnl": 0.0,
                    "total_cumulative_pnl": 0.0,
                    "total_buy_amt": 0,
                    "total_sell_amt": 0,
                    "total_buy_lot": 0,
                    "total_sell_lot": 0,
                    "total_overnight_lots": 0,
                    "total_overnight_cost_wan": 0.0,
                    "total_open_positions": 0,
                    "total_open_lots": 0,
                    "avg_daytrade_ratio_sum": 0.0,
                    "branches_count_with_data": 0,
                    "daytrade_stocks": 0,
                    "overnight_stocks": 0,
                    "partial_stocks": 0,
                    "tags_personal": set(),
                    "tags_market": set(),
                    "stock_stats": {},
                    "sell_stats": {},  # v3.13 賣超個股彙整
                }
            
            mdata = master_data[master]
            branch_obj = code_to_branch.get(branch_code, {})
            
            # v3.10：如果此分點對此 master 是「共用」，加個標記
            is_shared = (branch_obj.get("master") != master)
            primary_master = branch_obj.get("master", "")
            
            mdata["branches"].append({
                "code": branch_code,
                "name": branch_obj.get("name", ""),
                "summary": summary,
                "tags_personal": branch_obj.get("tags_personal", []),
                "tags_market": branch_obj.get("tags_market", []),
                "is_shared": is_shared,       # v3.10：是否共用
                "primary_master": primary_master,  # v3.10：主要歸屬（若共用）
            })
            for t in branch_obj.get("tags_personal", []):
                mdata["tags_personal"].add(t)
            for t in branch_obj.get("tags_market", []):
                mdata["tags_market"].add(t)
            mdata["total_daily_pnl"] += summary["daily_pnl"]
            mdata["total_weekly_pnl"] += summary["weekly_pnl"]
            mdata["total_monthly_pnl"] += summary["monthly_pnl"]
            mdata["total_cumulative_pnl"] += summary["total_pnl"]
            mdata["total_buy_amt"] += summary.get("today_buy_amt", 0)
            mdata["total_sell_amt"] += summary.get("today_sell_amt", 0)
            mdata["total_buy_lot"] += summary.get("today_buy_lot", 0)
            mdata["total_sell_lot"] += summary.get("today_sell_lot", 0)
            mdata["total_overnight_lots"] += summary.get("today_overnight_lots", 0)
            mdata["total_overnight_cost_wan"] += summary.get("today_overnight_cost_wan", 0.0)
            mdata["total_open_positions"] += summary.get("open_positions_count", 0)
            mdata["total_open_lots"] += summary.get("open_total_lots", 0)
            mdata["daytrade_stocks"] += summary.get("today_daytrade_stocks", 0)
            mdata["overnight_stocks"] += summary.get("today_overnight_stocks", 0)
            mdata["partial_stocks"] += summary.get("today_partial_stocks", 0)
            
            if summary.get("today_stocks_count", 0) > 0:
                mdata["avg_daytrade_ratio_sum"] += summary.get("avg_daytrade_ratio", 0.0)
                mdata["branches_count_with_data"] += 1
            
            # 彙整該分點買進的個股
            today_br = today_map.get(branch_code)
            if today_br and today_br.get("buys"):
                for s in today_br["buys"]:
                    code = s["code"]
                    if code not in mdata["stock_stats"]:
                        mdata["stock_stats"][code] = {
                            "code": code, "name": s["name"],
                            "branches": [],
                            "total_buy_amt": 0, "total_sell_amt": 0, "total_net_amt": 0,
                            "total_buy_lot": 0, "total_sell_lot": 0, "total_net_lot": 0,
                            "total_overnight_lots": 0,
                        }
                    ss = mdata["stock_stats"][code]
                    ss["branches"].append({
                        "code": branch_code,
                        "name": code_to_branch.get(branch_code, {}).get("name", ""),
                        "buy_amt": s.get("buy_amt", 0),
                        "sell_amt": s.get("sell_amt", 0),
                        "net_amt": s.get("net_amt", 0),
                        "buy_lot": s.get("buy_lot", 0),
                        "sell_lot": s.get("sell_lot", 0),
                        "net_lot": s.get("net_lot", 0),
                        "overnight_lots": s.get("overnight_lots", 0),
                    })
                    ss["total_buy_amt"] += s.get("buy_amt", 0)
                    ss["total_sell_amt"] += s.get("sell_amt", 0)
                    ss["total_net_amt"] += s.get("net_amt", 0)
                    ss["total_buy_lot"] += s.get("buy_lot", 0)
                    ss["total_sell_lot"] += s.get("sell_lot", 0)
                    ss["total_net_lot"] += s.get("net_lot", 0)
                    ss["total_overnight_lots"] += s.get("overnight_lots", 0)
            
            # v3.13 新增：彙整該分點「賣超」的個股（淨賣方向）
            if today_br and today_br.get("sells"):
                for s in today_br["sells"]:
                    code = s["code"]
                    if code not in mdata["sell_stats"]:
                        mdata["sell_stats"][code] = {
                            "code": code, "name": s["name"],
                            "branches": [],
                            "total_buy_amt": 0, "total_sell_amt": 0, "total_net_amt": 0,
                            "total_buy_lot": 0, "total_sell_lot": 0, "total_net_lot": 0,
                        }
                    ss = mdata["sell_stats"][code]
                    ss["branches"].append({
                        "code": branch_code,
                        "name": code_to_branch.get(branch_code, {}).get("name", ""),
                        "buy_amt": s.get("buy_amt", 0),
                        "sell_amt": s.get("sell_amt", 0),
                        "net_amt": s.get("net_amt", 0),
                        "buy_lot": s.get("buy_lot", 0),
                        "sell_lot": s.get("sell_lot", 0),
                        "net_lot": s.get("net_lot", 0),
                    })
                    ss["total_buy_amt"] += s.get("buy_amt", 0) or 0
                    ss["total_sell_amt"] += s.get("sell_amt", 0) or 0
                    ss["total_net_amt"] += s.get("net_amt", 0) or 0
                    ss["total_buy_lot"] += s.get("buy_lot", 0) or 0
                    ss["total_sell_lot"] += s.get("sell_lot", 0) or 0
                    ss["total_net_lot"] += s.get("net_lot", 0) or 0
    
    # 最後計算平均當沖比、風格判定
    for master, mdata in master_data.items():
        n = mdata["branches_count_with_data"]
        if n > 0:
            mdata["avg_daytrade_ratio"] = round(mdata["avg_daytrade_ratio_sum"] / n, 3)
        else:
            mdata["avg_daytrade_ratio"] = 0.0
        del mdata["avg_daytrade_ratio_sum"]
        
        # 風格判定
        total_style_stocks = mdata["daytrade_stocks"] + mdata["overnight_stocks"] + mdata["partial_stocks"]
        if total_style_stocks >= 3:
            dt_pct = mdata["daytrade_stocks"] / total_style_stocks
            ov_pct = mdata["overnight_stocks"] / total_style_stocks
            if dt_pct >= 0.5:
                mdata["today_style"] = "daytrader"
            elif ov_pct >= 0.5:
                mdata["today_style"] = "swing"
            else:
                mdata["today_style"] = "mixed"
        else:
            mdata["today_style"] = "unknown"
        
        mdata["total_net_amt"] = mdata["total_buy_amt"] - mdata["total_sell_amt"]
        mdata["total_cumulative_pnl"] = round(mdata["total_cumulative_pnl"], 2)
        mdata["total_daily_pnl"] = round(mdata["total_daily_pnl"], 2)
        mdata["total_weekly_pnl"] = round(mdata["total_weekly_pnl"], 2)
        mdata["total_monthly_pnl"] = round(mdata["total_monthly_pnl"], 2)
        mdata["total_overnight_cost_wan"] = round(mdata["total_overnight_cost_wan"], 2)
        
        # set 轉 list 才能 JSON 序列化
        mdata["tags_personal"] = sorted(mdata["tags_personal"])
        mdata["tags_market"] = sorted(mdata["tags_market"])
        
        # 共識個股（2 個以上分點買同一檔）
        mdata["consensus_stocks"] = [
            s for s in mdata["stock_stats"].values() if len(s["branches"]) >= 2
        ]
        mdata["consensus_stocks"].sort(key=lambda x: -x["total_net_amt"])
        
        # 轉換 stock_stats 為 list 以便序列化
        mdata["top_stocks"] = sorted(
            mdata["stock_stats"].values(),
            key=lambda x: -x["total_net_amt"]
        )[:30]
        del mdata["stock_stats"]  # 省空間
        
        # v3.13 新增：共識賣超個股 + top_sells
        mdata["consensus_sells"] = [
            s for s in mdata["sell_stats"].values() if len(s["branches"]) >= 2
        ]
        mdata["consensus_sells"].sort(key=lambda x: x["total_net_amt"])  # 淨賣越大（負值）越前面
        
        mdata["top_sells"] = sorted(
            mdata["sell_stats"].values(),
            key=lambda x: x["total_net_amt"]  # 淨買由小到大（最賣超的在前）
        )[:30]
        del mdata["sell_stats"]
    
    return master_data


# ========== 主流程 ==========

def main():
    password = os.environ.get("CHIP_RADAR_PASSWORD", "").strip()
    if not password:
        print("❌ 環境變數 CHIP_RADAR_PASSWORD 未設定！")
        sys.exit(1)
    
    if len(password) < 6:
        print("⚠️  警告：密碼太短（< 6 字元）")
    
    print(f"[{now_tw().strftime('%Y-%m-%d %H:%M:%S')}] 開始爬取 {len(WATCHED_BRANCHES)} 個分點 (🔒 加密+📊 FIFO 模式)")
    
    # 去除重複分點
    seen = set()
    unique_branches = []
    for b in WATCHED_BRANCHES:
        if b["code"] not in seen:
            seen.add(b["code"])
            unique_branches.append(b)
    if len(unique_branches) < len(WATCHED_BRANCHES):
        print(f"  （去重後 {len(unique_branches)} 個分點）")
    
    # ===== 載入股票分類器（規則 + API + 快取）=====
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    today_str = now_tw().strftime("%Y%m%d")
    classify_stock_fn, _ = get_classifier(data_dir, today_str)
    
    # 爬取所有分點
    results = []
    trade_date = None
    success_count = 0
    fail_count = 0
    empty_count = 0
    
    for i, branch in enumerate(unique_branches):
        code = branch["code"]
        print(f"  [{i+1}/{len(unique_branches)}] {branch['master']} | {branch['name']} ({code}) ", end="", flush=True)
        
        data = fetch_branch_combined(code)
        
        if data["error"]:
            print(f"❌ {data['error']}")
            fail_count += 1
        elif not data["buys"] and not data["sells"]:
            print(f"⚪ 無資料")
            empty_count += 1
        else:
            # 檢查是否有張數（沒有的話簡單提示）
            has_lot = any(s.get("buy_lot", 0) > 0 for s in data["buys"])
            lot_hint = "✓" if has_lot else "⚠金額only"
            print(f"{lot_hint} 買{len(data['buys'])}/賣{len(data['sells'])}")
            success_count += 1
            if data["date"] and not trade_date:
                trade_date = data["date"]
        
        # 為每檔股票加上市場分類
        for s in data.get("buys", []):
            cinfo = classify_stock_fn(s["code"], s["name"])
            s["market_type"] = cinfo["category"]              # 細分 (8 類)
            s["market_type_simple"] = cinfo["category_simple"]  # 簡單 (5 類)
            s["market_type_basic"] = cinfo["category_basic"]    # 最簡 (3 類)
            s["industry"] = cinfo.get("industry", "")
            s["is_ky"] = cinfo.get("is_ky", False)
        for s in data.get("sells", []):
            cinfo = classify_stock_fn(s["code"], s["name"])
            s["market_type"] = cinfo["category"]
            s["market_type_simple"] = cinfo["category_simple"]
            s["market_type_basic"] = cinfo["category_basic"]
            s["industry"] = cinfo.get("industry", "")
            s["is_ky"] = cinfo.get("is_ky", False)
        
        results.append({
            **branch,  # 包含 code, name, master, tags_personal, tags_market
            "date": data["date"],
            "buys": data["buys"],
            "sells": data["sells"],
            "error": data["error"],
        })
        
        if i < len(unique_branches) - 1:
            if (i + 1) % COOL_DOWN_EVERY == 0:
                print(f"    ⏸  休息 {COOL_DOWN_SECONDS} 秒...")
                time.sleep(COOL_DOWN_SECONDS)
            else:
                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    
    if not trade_date:
        trade_date = now_tw().strftime("%Y%m%d")
    
    # ════════════════════════════════════════════════════════════════
    # 假日 / 全部失敗 偵測：保留前一日資料，不寫新檔
    # ════════════════════════════════════════════════════════════════
    # 判斷條件:
    #   - 全部分點都失敗或無資料 → 視為假日/系統異常
    #   - 不更新 latest.json / 不寫新日期檔 / 不更新 positions
    #   - 確保前一日有效資料保留可看
    
    if success_count == 0:
        print(f"\n⚠️ ════════════════════════════════════════════════")
        print(f"  全部 {len(unique_branches)} 個分點皆無資料")
        print(f"  失敗: {fail_count} / 無資料: {empty_count}")
        print(f"  推測為假日 / 系統異常 / 富邦頁面變更")
        print(f"  → 保留前一日資料，不寫入新檔，不影響網站運作")
        print(f"════════════════════════════════════════════════════\n")
        # 正常退出（exit code 0），讓 GitHub Actions 不顯示紅字
        return
    
    # ════════════════════════════════════════════════════════════════
    # 正常流程：FIFO 累積 + 寫入新資料
    # ════════════════════════════════════════════════════════════════
    
    # ===== 更新 FIFO 部位 =====
    print(f"\n[FIFO] 更新累積部位...")
    positions = load_positions(data_dir, password)
    apply_day_to_positions(positions, trade_date, results)
    
    # ════════════════════════════════════════════════════════════════
    # v3.7 新增：抓取三大法人 + 收盤行情，注入到每檔股票
    # v3.14.2: 傳入 priority_codes 供 MIS fallback 補抓
    # ════════════════════════════════════════════════════════════════
    print(f"\n[公開資訊] 抓取三大法人與收盤行情...")
    
    # 收集我的分點出現的所有股票代號（供 fallback 使用）
    priority_codes = set()
    for br in results:
        for s in (br.get("buys", []) + br.get("sells", [])):
            code = s.get("code")
            if code:
                priority_codes.add(code)
    priority_codes = list(priority_codes)
    print(f"  (我的分點今日涉及 {len(priority_codes)} 檔個股)")
    
    try:
        institutional_map, daily_quotes_map = fetch_all_public_data(trade_date, priority_codes=priority_codes)
    except Exception as e:
        print(f"  ⚠️ 公開資訊抓取整體失敗: {e}（繼續執行，不影響主流程）")
        institutional_map, daily_quotes_map = {}, {}
    
    # 為每檔股票注入三大法人資料 + 收盤行情 + 浮盈
    inst_inject_count = 0
    quote_inject_count = 0
    align_aligned = 0
    align_opposing = 0
    
    for br in results:
        for s in (br.get("buys", []) + br.get("sells", [])):
            code = s.get("code")
            if not code:
                continue
            
            # ── 三大法人 ──
            inst = institutional_map.get(code)
            if inst:
                s["inst_foreign_net_lot"] = inst["foreign_net_lot"]
                s["inst_trust_net_lot"] = inst["trust_net_lot"]
                s["inst_dealer_net_lot"] = inst["dealer_net_lot"]
                s["inst_total_net_lot"] = inst["total_net_lot"]
                
                # 計算分點 vs 外資對齊狀況（張數版本）
                branch_net = s.get("net_lot", 0) or 0
                s["align_with_foreign"] = compute_alignment(branch_net, inst["foreign_net_lot"])
                if s["align_with_foreign"] == "aligned":
                    align_aligned += 1
                elif s["align_with_foreign"] == "opposing":
                    align_opposing += 1
                
                inst_inject_count += 1
            else:
                s["inst_foreign_net_lot"] = None
                s["inst_trust_net_lot"] = None
                s["inst_dealer_net_lot"] = None
                s["inst_total_net_lot"] = None
                s["align_with_foreign"] = "neutral"
            
            # ── 收盤行情 + 浮盈 ──
            quote = daily_quotes_map.get(code)
            if quote:
                s["close_price"] = quote["close"]
                s["change_pct"] = quote["change_pct"]
                s["volume_lot"] = quote["volume_lot"]
                # v3.14.2: 標記資料來源 (twse / tpex / mis_tse / mis_otc)
                s["quote_source"] = quote.get("source", "")
                s["quote_stale"] = False  # 本次爬蟲抓到的都是即時資料
                
                # 計算當日浮盈（買均 vs 收盤）
                buy_avg = s.get("buy_avg", 0) or 0
                if buy_avg and quote["close"]:
                    s["floating_pnl_pct"] = compute_floating_pnl_pct(buy_avg, quote["close"])
                else:
                    s["floating_pnl_pct"] = None
                
                # v3.12 漲停判定
                cp = quote["change_pct"] or 0
                s["is_limit_up"] = cp >= LIMIT_UP_THRESHOLD
                s["is_near_limit_up"] = cp >= NEAR_LIMIT_UP_THRESHOLD
                
                quote_inject_count += 1
            else:
                s["close_price"] = None
                s["change_pct"] = None
                s["volume_lot"] = None
                s["floating_pnl_pct"] = None
                s["is_limit_up"] = False
                s["is_near_limit_up"] = False
                s["quote_source"] = None
                s["quote_stale"] = True  # 沒抓到，標記為過時
    
    print(f"[公開資訊] ✓ 注入完成 — 三大法人 {inst_inject_count} 筆 / 收盤行情 {quote_inject_count} 筆")
    print(f"          對齊統計：與外資同向 {align_aligned} / 反向 {align_opposing}")
    
    # 計算各期間匯總（含當日風格指標）
    summaries = compute_period_summaries(positions, trade_date, today_branches_data=results)
    
    # 高手聚合摘要
    master_summaries = compute_master_summaries(summaries, unique_branches, today_branches_data=results)
    print(f"[聚合] 高手視角合併完成，共 {len(master_summaries)} 位高手")
    
    # v3.12 漲停狙擊匯總
    limit_up_summary = compute_limit_up_summary(results, unique_branches)
    print(f"[漲停狙擊] 我的分點買到 {limit_up_summary['limit_up_bought_count']} 檔漲停股")
    if limit_up_summary['sniper_ranking']:
        top_sniper = limit_up_summary['sniper_ranking'][0]
        print(f"  🎯 最強狙擊手：{top_sniper['master']} - {top_sniper['branch_name']}"
              f"（買 {top_sniper['limit_up_stocks_bought']} 檔漲停，{top_sniper['total_limit_up_buy_amt']:.0f} 萬）")
    if limit_up_summary['consensus_limit_up']:
        print(f"  👥 多位高手共買漲停股：{len(limit_up_summary['consensus_limit_up'])} 檔")
    
    # v3.13 隔日沖驗證 — 比對昨日漲停買進 × 今日賣超
    print(f"\n[隔日沖驗證] 比對昨日漲停買進 vs 今日賣超...")
    yesterday_branches_data = []
    try:
        # 找昨日的加密檔
        existing_dates_sorted = sorted(
            [f.stem for f in data_dir.glob("*.json") if f.stem.isdigit() and len(f.stem) == 8 and f.stem != trade_date],
            reverse=True
        )
        if existing_dates_sorted:
            yest_date = existing_dates_sorted[0]
            yest_file = data_dir / f"{yest_date}.json"
            with open(yest_file, "r", encoding="utf-8") as f:
                yest_raw = json.load(f)
            if yest_raw.get("encrypted"):
                yest_plain = decrypt_data(yest_raw["data"], password)
                yest_data = json.loads(yest_plain)
                yesterday_branches_data = yest_data.get("branches", [])
                print(f"  ✓ 載入昨日資料 ({yest_date}): {len(yesterday_branches_data)} 個分點")
    except Exception as e:
        print(f"  ⚠️ 昨日資料載入失敗: {e}（首日執行此為正常現象）")
    
    next_day_verification = compute_next_day_flip_verification(
        results, yesterday_branches_data, unique_branches)
    
    if next_day_verification["is_first_day"]:
        print(f"  ℹ️ 首日執行，明日才能開始比對")
    else:
        vf = next_day_verification["verified_flips"]
        pp = next_day_verification["pending_positions"]
        full_flips = [r for r in vf if r["status"] == "full_flip"]
        partial_flips = [r for r in vf if r["status"] == "partial_flip"]
        print(f"  ✓ 完全出貨 (flip>=90%): {len(full_flips)} 筆")
        print(f"  ✓ 部分出貨 (flip>=30%): {len(partial_flips)} 筆")
        print(f"  ⏸️ 尚未出貨（留倉中）: {len(pp)} 筆")
        if next_day_verification["flipper_scorecard"]:
            top = next_day_verification["flipper_scorecard"][0]
            print(f"  🎯 最高出貨率：{top['master']} - 整體 {top['overall_flip_ratio']:.1f}% "
                  f"（昨買 {top['total_yesterday_buy_lot']} 張 → 今賣 {top['total_today_sell_lot']} 張）")
    
    save_positions(positions, data_dir, password)
    print(f"[FIFO] 累積部位已更新，涉及 {len(positions.get('branches', {}))} 個分點")
    
    # ════════════════════════════════════════════════════════════════
    # v3.7 新增：建立全市場法人排行（前 100 名各類）
    # ════════════════════════════════════════════════════════════════
    print(f"[公開資訊] 建立全市場排行...")
    
    # 為了讓前端能查股票名稱，建立 code → name 對照（從分點資料）
    code_to_name = {}
    for br in results:
        for s in (br.get("buys", []) + br.get("sells", [])):
            if s.get("code") and s.get("name"):
                code_to_name[s["code"]] = s["name"]
    # 補上沒在分點裡的（從收盤行情順便取）
    # （這些股票富邦分點沒交易，但有市場活動）
    
    def build_inst_ranking(field_key: str, top_n: int = 100):
        """從 institutional_map 建立某類法人排行"""
        rows = []
        for code, info in institutional_map.items():
            net = info.get(field_key, 0) or 0
            if abs(net) < 1:
                continue
            quote = daily_quotes_map.get(code, {})
            rows.append({
                "code": code,
                "name": code_to_name.get(code, ""),  # 名稱可能空，前端要 fallback
                "net_lot": net,
                "close": quote.get("close"),
                "change_pct": quote.get("change_pct"),
                "market_source": info.get("source", ""),  # twse/tpex
            })
        # 同時排正向（買超）和負向（賣超）
        rows_buy = sorted([r for r in rows if r["net_lot"] > 0], key=lambda x: -x["net_lot"])[:top_n]
        rows_sell = sorted([r for r in rows if r["net_lot"] < 0], key=lambda x: x["net_lot"])[:top_n]
        return {"buy": rows_buy, "sell": rows_sell}
    
    institutional_rankings = {
        "foreign": build_inst_ranking("foreign_net_lot"),
        "trust": build_inst_ranking("trust_net_lot"),
        "dealer": build_inst_ranking("dealer_net_lot"),
        "total": build_inst_ranking("total_net_lot"),
    }
    print(f"  ✓ 外資買超前 {len(institutional_rankings['foreign']['buy'])} / "
          f"投信 {len(institutional_rankings['trust']['buy'])} / "
          f"自營 {len(institutional_rankings['dealer']['buy'])}")
    
    # ════════════════════════════════════════════════════════════════
    # v3.11 新增：融資融券抓取 + 智慧注入 + 排行榜
    # v3.14.4 升級：加入 HiStock 日期驗證 + STAGE 模式
    # ════════════════════════════════════════════════════════════════
    STAGE = os.environ.get('CHIP_RADAR_STAGE', 'full').strip().lower()
    print(f"\n[融資融券] 抓取全市場融資融券資料... (STAGE={STAGE})")
    margin_all = {}
    margin_filtered = {}
    margin_rankings = {}
    margin_inject_count = 0
    margin_verification = None  # v3.14.4
    
    try:
        margin_result = margin.fetch_all_margin(verify_date=True)
        margin_all = margin_result.get('data', {})
        margin_verification = margin_result.get('verification')
        
        if margin_all:
            # 注入到每檔分點個股（無論是否 Top 100）
            margin_inject_count = margin.inject_margin_into_stocks(results, margin_all)
            print(f"[融資融券] ✓ 注入 {margin_inject_count} 筆分點個股")
            
            # 智慧混合策略：我的分點個股 + Top 100 + 使用率高 + 券資比高
            my_branch_codes = set()
            for br in results:
                for s in (br.get("buys", []) + br.get("sells", [])):
                    if s.get("code"):
                        my_branch_codes.add(s["code"])
            
            target_codes = margin.select_target_codes(margin_all, my_branch_codes, top_n=100)
            margin_filtered = margin.filter_margin_data(margin_all, target_codes)
            print(f"[融資融券] ✓ 智慧混合：保留 {len(margin_filtered)} 檔"
                  f"（我的 {len(my_branch_codes)} + 全市場 Top）")
            
            # 全市場排行榜
            margin_rankings = margin.build_margin_rankings(margin_all, top_n=30)
            print(f"[融資融券] ✓ 全市場排行榜 (7 類 × Top 30)")
    except Exception as e:
        print(f"  ⚠️ 融資融券抓取失敗: {e}（不影響主流程）")
        import traceback; traceback.print_exc()
    
    # ════════════════════════════════════════════════════════════════
    # v3.15.0 新增：產業分類注入
    # ════════════════════════════════════════════════════════════════
    industry_map = {}
    industry_inject_count = 0
    try:
        print(f"\n[產業分類] 建立/讀取產業對照表...")
        industry_map = industry_classifier.get_industry_map(data_dir)
        industry_inject_count = industry_classifier.inject_industry_into_stocks(results, industry_map)
        print(f"[產業分類] ✓ 注入 {industry_inject_count} 筆分點個股產業資訊")
        
        # 也注入到 margin_filtered (前端排行榜用)
        for code, m in margin_filtered.items():
            ind = industry_map.get('stock_industry', {}).get(code)
            if ind:
                m['industry'] = ind
    except Exception as e:
        print(f"  ⚠️ 產業分類失敗: {e}（不影響主流程）")
        import traceback; traceback.print_exc()
    
    # ════════════════════════════════════════════════════════════════
    # v3.15.2 新增：歷史資料累積 (for 三線比較圖)
    # ════════════════════════════════════════════════════════════════
    try:
        history.update_history(
            data_dir=data_dir,
            trade_date=trade_date,
            daily_quotes_map=daily_quotes_map,
            industry_map=industry_map,
            branches_results=results,
        )
    except Exception as e:
        print(f"  ⚠️ 歷史累積失敗: {e}(不影響主流程)")
        import traceback; traceback.print_exc()
    
    # ════════════════════════════════════════════════════════════════
    # v3.17 新增:期貨選擇權籌碼
    # ════════════════════════════════════════════════════════════════
    futures_data = {}
    try:
        print(f"\n[期貨籌碼] 抓取 TAIFEX 期貨/選擇權/大額交易人...")
        futures_data = futures.fetch_all_futures_data(trade_date)
        # 印出關鍵摘要
        summary = futures_data.get('summary', {})
        if summary:
            print(f"  ✓ 外資等效大台淨 OI: {summary.get('foreign_equivalent_net_oi', 0):,} 口")
            print(f"  ✓ 散戶小台淨 OI (推算): {summary.get('retail_mxf_net_oi', 0):,} 口")
            pc = summary.get('pc_ratio_oi')
            if pc:
                print(f"  ✓ P/C Ratio: {pc}")
            t10_ratio = summary.get('top10_long_ratio')
            if t10_ratio:
                print(f"  ✓ 十大交易人買方集中度: {t10_ratio*100:.1f}%")
        
        # v3.17.1: 累積期貨歷史
        try:
            history.update_futures_history(
                data_dir=data_dir,
                trade_date=trade_date,
                futures_data=futures_data,
            )
        except Exception as e:
            print(f"  ⚠️ 期貨歷史累積失敗: {e}")
    except Exception as e:
        print(f"  ⚠️ 期貨籌碼抓取失敗: {e}(不影響主流程)")
        import traceback; traceback.print_exc()
    
    # ===== 組裝當日 JSON =====
    raw_output = {
        "trade_date": trade_date,
        "crawled_at": now_tw().isoformat(),
        "baseline_date": BASELINE_DATE,
        "version": "3.17.1",
        "stage": STAGE,  # v3.14.4: 記錄此次爬蟲階段 (full/margin_only)
        "success": success_count,
        "failed": fail_count,
        "empty": empty_count,
        "branches": results,
        "branch_summaries": summaries,            # 每分點日/週/月/累積損益 + 風格
        "master_summaries": master_summaries,     # 按高手聚合
        "institutional_rankings": institutional_rankings,  # v3.7 全市場法人排行
        "institutional_count": len(institutional_map),
        "quotes_count": len(daily_quotes_map),
        # v3.11 新增
        "margin_data": margin_filtered,           # 智慧混合後的個股融資融券
        "margin_rankings": margin_rankings,       # 7 類排行榜
        "margin_total_count": len(margin_all),    # 全市場總檔數（統計用）
        # v3.14.4 新增：融資融券資料日期驗證結果
        "margin_verification": margin_verification,  # HiStock 驗證結果
        # v3.12 新增
        "limit_up_summary": limit_up_summary,     # 漲停狙擊匯總
        # v3.13 新增
        "next_day_verification": next_day_verification,  # 隔日沖驗證
        # v3.15.0 新增：產業分類
        "industry_map": {
            "stock_industry": industry_map.get('stock_industry', {}),
            "industry_groups": industry_map.get('industry_groups', {}),
            "updated_at": industry_map.get('updated_at'),
        },
        # v3.17 新增:期貨選擇權籌碼
        "futures_data": futures_data,
    }
    
    plaintext = json.dumps(raw_output, ensure_ascii=False)
    print(f"[加密] 原始大小: {len(plaintext)/1024:.1f} KB")
    encrypted_token = encrypt_data(plaintext, password)
    print(f"[加密] 加密後大小: {len(encrypted_token)/1024:.1f} KB")
    
    encrypted_output = {
        "encrypted": True,
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "trade_date": trade_date,
        "crawled_at": now_tw().isoformat(),
        "baseline_date": BASELINE_DATE,
        "data": encrypted_token,
    }
    
    # 寫入日期檔 + latest
    dated_file = data_dir / f"{trade_date}.json"
    with open(dated_file, "w", encoding="utf-8") as f:
        json.dump(encrypted_output, f, ensure_ascii=False, indent=2)
    
    latest_file = data_dir / "latest.json"
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(encrypted_output, f, ensure_ascii=False, indent=2)
    
    # index.json
    index_file = data_dir / "index.json"
    existing_dates = []
    if index_file.exists():
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                existing_dates = json.load(f).get("dates", [])
        except Exception:
            pass
    
    all_dates = set(existing_dates)
    all_dates.add(trade_date)
    for f in data_dir.glob("*.json"):
        if f.stem.isdigit() and len(f.stem) == 8:
            all_dates.add(f.stem)
    
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump({
            "dates": sorted(all_dates, reverse=True),
            "latest": trade_date,
            "updated_at": now_tw().isoformat(),
            "branches_count": len(unique_branches),
            "baseline_date": BASELINE_DATE,
            "encrypted": True,
            "version": "3.17.1",
        }, f, ensure_ascii=False, indent=2)
    
    # v3.9 週報/月報自動生成（僅在週一/月初觸發）
    try:
        generated = reports.maybe_generate_reports(
            data_dir, password, decrypt_data, encrypt_data
        )
        if generated:
            print(f"\n[報告] ✓ 產生 {len(generated)} 份報告")
            # 更新 reports_index.json 以供前端讀取
            reports_list = reports.list_available_reports(data_dir)
            with open(data_dir / "reports_index.json", "w", encoding="utf-8") as f:
                json.dump({
                    "updated_at": now_tw().isoformat(),
                    "weekly": reports_list["weekly"],
                    "monthly": reports_list["monthly"],
                }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ⚠️ 報告生成錯誤（不影響主流程）: {e}")
        import traceback; traceback.print_exc()
    
    print(f"\n[{now_tw().strftime('%H:%M:%S')}] ✅ 完成！")
    print(f"  資料日期: {trade_date}")
    print(f"  成功: {success_count} / 失敗: {fail_count} / 無資料: {empty_count}")
    print(f"  歷史共 {len(all_dates)} 天")
    print(f"  🔒 資料已加密  📊 FIFO 部位已更新")


# ════════════════════════════════════════════════════════════════════
#  v3.14.4 新增: margin_only STAGE - 只更新融資融券 (用於 22:30/00:00/08:00)
# ════════════════════════════════════════════════════════════════════
def main_margin_only():
    """
    v3.14.4 新增：階段 2/3/4 只更新融資融券部分,不重爬分點
    
    流程：
      1. 讀取 data/latest.json (解密)
      2. 抓取最新融資融券 + HiStock 驗證
      3. 比對「驗證日期」vs「現有 margin_verification.data_date」
         - 如果新抓到的日期 > 現有 (更新) → 覆蓋
         - 如果一樣 (已是 T-0) → 跳過本次 (省資源)
         - 如果更舊 → 保留原資料 + 加警告
      4. 寫回加密檔
    """
    password = os.environ.get("CHIP_RADAR_PASSWORD", "").strip()
    if not password:
        print("❌ 環境變數 CHIP_RADAR_PASSWORD 未設定！")
        sys.exit(1)
    
    stage_name = os.environ.get('CHIP_RADAR_STAGE', 'margin_only').strip()
    print(f"[{now_tw().strftime('%Y-%m-%d %H:%M:%S')}] 🔄 STAGE={stage_name} 融資融券補更新")
    
    data_dir = Path(__file__).parent / "data"
    latest_file = data_dir / "latest.json"
    
    if not latest_file.exists():
        print(f"❌ {latest_file} 不存在，無法進行 margin_only 更新")
        print(f"  請先執行主爬蟲 (CHIP_RADAR_STAGE=full python crawler.py)")
        sys.exit(1)
    
    # ===== 讀取現有資料並解密 =====
    print(f"\n[1/4] 讀取現有資料...")
    with open(latest_file, "r", encoding="utf-8") as f:
        encrypted_doc = json.load(f)
    
    try:
        plaintext = decrypt_data(encrypted_doc["data"], password)
        current_data = json.loads(plaintext)
    except Exception as e:
        print(f"❌ 解密失敗: {e}")
        sys.exit(1)
    
    current_date = current_data.get("trade_date")
    current_verification = current_data.get("margin_verification") or {}
    current_data_date = current_verification.get("data_date")
    
    print(f"  現有 trade_date: {current_date}")
    print(f"  現有融資融券驗證日期: {current_data_date or '(未驗證)'}")
    print(f"  現有融資融券信心: {current_verification.get('confidence', 'N/A')}")
    
    # ===== 聰明跳過: 如果已經是 T-0 (最新交易日),跳過本次 =====
    today_str = now_tw().strftime("%Y%m%d")
    # 取最近一個交易日 (週末的情況: 若今天週六,最近交易日是週五)
    import calendar
    now = now_tw()
    check = now
    for _ in range(5):
        if check.weekday() < 5:  # 週一(0) ~ 週五(4)
            break
        check = check - timedelta(days=1)
    latest_trade_day = check.strftime("%Y%m%d")
    # 若已 8 點前，則上個交易日
    if now.hour < 8:
        yesterday = now - timedelta(days=1)
        while yesterday.weekday() >= 5:
            yesterday = yesterday - timedelta(days=1)
        latest_trade_day = yesterday.strftime("%Y%m%d")
    
    if current_data_date and current_data_date >= latest_trade_day and current_verification.get('confidence') == 'high':
        print(f"\n✅ 現有融資融券資料已是 {current_data_date} (最新交易日)，跳過本次更新")
        print(f"   省下 GitHub Actions 分鐘數。")
        return
    
    # ===== 抓取最新融資融券 + 驗證 =====
    print(f"\n[2/4] 抓取最新融資融券 + HiStock 驗證...")
    try:
        margin_result = margin.fetch_all_margin(verify_date=True)
        margin_all = margin_result.get('data', {})
        new_verification = margin_result.get('verification')
    except Exception as e:
        print(f"❌ 融資融券抓取失敗: {e}")
        sys.exit(1)
    
    if not margin_all:
        print(f"❌ 抓到 0 檔融資融券,本次跳過")
        return
    
    new_data_date = (new_verification or {}).get('data_date')
    new_confidence = (new_verification or {}).get('confidence', 'low')
    print(f"  新抓到驗證日期: {new_data_date}")
    print(f"  新抓到信心: {new_confidence}")
    
    # ===== 決定是否覆蓋 =====
    print(f"\n[3/4] 決定是否覆蓋...")
    should_update = False
    
    if not current_data_date:
        # 現有沒驗證過 → 新的一定比較好
        should_update = True
        reason = "現有資料未驗證過"
    elif new_data_date and new_data_date > current_data_date:
        # 新的比現有更新 → 覆蓋
        should_update = True
        reason = f"新日期 {new_data_date} > 現有 {current_data_date}"
    elif new_data_date and new_data_date == current_data_date:
        if new_confidence == 'high' and current_verification.get('confidence') != 'high':
            # 同日期但信心更高 → 也更新
            should_update = True
            reason = f"同日期但驗證信心提升 ({current_verification.get('confidence')}→{new_confidence})"
        else:
            reason = "新日期與現有相同，信心也相同，保持不變"
    else:
        # 新的是 T-1 或未驗證,保留現有
        reason = f"新抓到日期 {new_data_date} 不優於現有 {current_data_date}，保留現有"
    
    print(f"  決定: {'✅ 覆蓋' if should_update else '⏸️ 不覆蓋'} ({reason})")
    
    if not should_update:
        print(f"\n  本次執行結束,未修改資料。")
        return
    
    # ===== 覆蓋並重新加密 =====
    print(f"\n[4/4] 合併、重新加密、寫回...")
    
    # 注入到每檔分點個股 (和主流程相同邏輯)
    margin_inject_count = margin.inject_margin_into_stocks(
        current_data.get("branches", []), margin_all
    )
    print(f"  注入 {margin_inject_count} 筆分點個股")
    
    # 智慧混合
    my_branch_codes = set()
    for br in current_data.get("branches", []):
        for s in (br.get("buys", []) + br.get("sells", [])):
            if s.get("code"):
                my_branch_codes.add(s["code"])
    
    target_codes = margin.select_target_codes(margin_all, my_branch_codes, top_n=100)
    margin_filtered = margin.filter_margin_data(margin_all, target_codes)
    margin_rankings = margin.build_margin_rankings(margin_all, top_n=30)
    
    # 更新相關欄位
    current_data["margin_data"] = margin_filtered
    current_data["margin_rankings"] = margin_rankings
    current_data["margin_total_count"] = len(margin_all)
    current_data["margin_verification"] = new_verification
    current_data["stage"] = stage_name  # 記錄最後一次是哪個階段更新的
    current_data["last_margin_update_at"] = now_tw().isoformat()
    
    # 重新加密
    plaintext = json.dumps(current_data, ensure_ascii=False)
    print(f"  重加密中 (原始 {len(plaintext)/1024:.1f} KB)...")
    encrypted_token = encrypt_data(plaintext, password)
    
    encrypted_output = {
        "encrypted": True,
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "trade_date": current_date,
        "crawled_at": now_tw().isoformat(),
        "baseline_date": BASELINE_DATE,
        "data": encrypted_token,
    }
    
    # 寫回日期檔 + latest.json
    dated_file = data_dir / f"{current_date}.json"
    with open(dated_file, "w", encoding="utf-8") as f:
        json.dump(encrypted_output, f, ensure_ascii=False, indent=2)
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(encrypted_output, f, ensure_ascii=False, indent=2)
    
    print(f"\n[{now_tw().strftime('%H:%M:%S')}] ✅ margin_only 更新完成！")
    print(f"  融資融券資料日期: {new_data_date}")
    print(f"  驗證信心: {new_confidence}")
    print(f"  篩選保留: {len(margin_filtered)} 檔")


if __name__ == "__main__":
    stage = os.environ.get('CHIP_RADAR_STAGE', 'full').strip().lower()
    if stage == 'margin_only':
        main_margin_only()
    else:
        main()
