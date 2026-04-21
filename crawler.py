"""
分點籌碼觀察站 - 完整版爬蟲 (v3)
功能：
  1. 爬取每個分點的「金額 (c=B)」和「張數 (c=E)」雙模式資料
  2. FIFO 部位追蹤，累積已實現損益（基準日 2026/4/21 起算）
  3. 資料 AES-256-GCM 加密
  4. 自動更新 positions.json 累積部位狀態
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
 
TW_TZ = timezone(timedelta(hours=8))
 
def now_tw():
    return datetime.now(TW_TZ)
 
# ========== 關注分點清單 ==========

WATCHED_BRANCHES = [
    {"code": "9B25", "name": "台新-五權西",     "master": "民哥"},
    {"code": "9666", "name": "富邦-南屯",     "master": "民哥"},
    {"code": "779W", "name": "國票-彰化",     "master": "國票彰化"},
    {"code": "9658", "name": "富邦-建國",     "master": "林滄海"},
    {"code": "9309", "name": "華南永昌-古亭", "master": "林滄海"},
    {"code": "1260", "name": "宏遠證券",      "master": "林滄海"},
    {"code": "9216", "name": "凱基-信義",     "master": "林滄海"},
    {"code": "779Z", "name": "國票-安和",     "master": "張濬安(航海王)"},
    {"code": "9B2E", "name": "台新-城中",     "master": "張濬安(航海王)"},
    {"code": "920F", "name": "凱基-站前",     "master": "張濬安(航海王)"},
    {"code": "6167", "name": "中國信託-松江", "master": "張濬安(航海王)"},
    {"code": "961M", "name": "富邦-木柵",     "master": "張濬安(航海王)"},
    {"code": "9100", "name": "群益金鼎證券",  "master": "張濬安(航海王)"},
    {"code": "8880", "name": "國泰證券",      "master": "陳族元"},
    {"code": "9300", "name": "華南永昌證券",  "master": "陳族元"},
    {"code": "9661", "name": "富邦-新店",     "master": "陳族元"},
    {"code": "9A9g", "name": "永豐金-內湖",   "master": "陳族元"},
    {"code": "700c", "name": "兆豐-民生",     "master": "陳律師"},
    {"code": "8450", "name": "康和總公司",    "master": "陳律師"},
    {"code": "9A9R", "name": "永豐金-信義",   "master": "陳律師"},
    {"code": "585c", "name": "統一-仁愛",     "master": "陳律師"},
    {"code": "9217", "name": "凱基-松山",     "master": "迷你哥/松山哥"},
    {"code": "9200", "name": "凱基證券",      "master": "迷你哥/松山哥"},
    {"code": "9600", "name": "富邦證券",      "master": "迷你哥/松山哥"},
    {"code": "9A8F", "name": "永豐金-敦南",   "master": "布哥/n_nchang"},
    {"code": "9B2r", "name": "台新-城東",     "master": "強森"},
    {"code": "984K", "name": "元大-館前",     "master": "強森"},
    {"code": "989N", "name": "元大-內湖",     "master": "強森"},
    {"code": "9215", "name": "凱基-高美館",   "master": "強森"},
    {"code": "9B2D", "name": "台新-大昌",     "master": "強森"},
    {"code": "9B2a", "name": "台新-松德",     "master": "Tradow"},
    {"code": "9B2n", "name": "台新-西松",     "master": "巨人傑"},
    {"code": "9B2z", "name": "台新-文心",     "master": "巨人傑"},
    {"code": "9227", "name": "凱基-城中",     "master": "蔣承翰"},
    {"code": "9B18", "name": "台新-建北",     "master": "蔣承翰"},
    {"code": "8563", "name": "新光-新竹",     "master": "大牌分析師"},
    {"code": "9874", "name": "元大-雙和",     "master": "東億資本"},
    {"code": "884F", "name": "玉山-桃園",     "master": "Krenz(再多一位數本人)"},
]

# 每檔保留前幾名（50 = 抓到的全部，建議 20~30 平衡資訊量與檔案大小）
# 每檔保留前幾名
TOP_N = 40
 
# 請求間隔（秒）
DELAY_MIN = 2.0
DELAY_MAX = 4.0
 
# 每 N 個分點休息一次
COOL_DOWN_EVERY = 10
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
    
    # 避免重複處理同一日
    last_date = positions.get("last_update_date")
    if last_date and trade_date <= last_date:
        print(f"  (跳過累積損益更新，{trade_date} 已處理過，last_update_date={last_date})")
        return
    
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
 
 
def compute_master_summaries(branch_summaries: dict, unique_branches: list, today_branches_data: list = None):
    """
    按高手（master）聚合多分點的統計
    回傳: {master_name: {branches: [...], total_*, consensus_stocks: [...]}}
    """
    # 分點代號 → master name
    code_to_master = {b["code"]: b["master"] for b in unique_branches}
    code_to_branch = {b["code"]: b for b in unique_branches}
    
    # 今日爬蟲資料 index
    today_map = {}
    if today_branches_data:
        for br in today_branches_data:
            today_map[br["code"]] = br
    
    master_data = {}
    
    for branch_code, summary in branch_summaries.items():
        master = code_to_master.get(branch_code, "未知")
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
                "stock_stats": {},  # 該高手旗下所有分點對各股票的合計（共識個股）
            }
        
        mdata = master_data[master]
        mdata["branches"].append({
            "code": branch_code,
            "name": code_to_branch.get(branch_code, {}).get("name", ""),
            "summary": summary,
        })
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
        
        # 彙整該分點買進的個股（用於共識個股分析）
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
        
        # 共識個股（2 個以上分點買同一檔）
        mdata["consensus_stocks"] = [
            s for s in mdata["stock_stats"].values() if len(s["branches"]) >= 2
        ]
        mdata["consensus_stocks"].sort(key=lambda x: -x["total_net_amt"])
        
        # 轉換 stock_stats 為 list 以便序列化（也留 dict 以便前端快速查）
        mdata["top_stocks"] = sorted(
            mdata["stock_stats"].values(),
            key=lambda x: -x["total_net_amt"]
        )[:30]
        del mdata["stock_stats"]  # 省空間
    
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
        
        results.append({
            **branch,
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
    
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    
    # ===== 更新 FIFO 部位 =====
    print(f"\n[FIFO] 更新累積部位...")
    positions = load_positions(data_dir, password)
    apply_day_to_positions(positions, trade_date, results)
    
    # 計算各期間匯總（含當日風格指標）
    summaries = compute_period_summaries(positions, trade_date, today_branches_data=results)
    
    # 高手聚合摘要
    master_summaries = compute_master_summaries(summaries, unique_branches, today_branches_data=results)
    print(f"[聚合] 高手視角合併完成，共 {len(master_summaries)} 位高手")
    
    save_positions(positions, data_dir, password)
    print(f"[FIFO] 累積部位已更新，涉及 {len(positions.get('branches', {}))} 個分點")
    
    # ===== 組裝當日 JSON =====
    raw_output = {
        "trade_date": trade_date,
        "crawled_at": now_tw().isoformat(),
        "baseline_date": BASELINE_DATE,
        "success": success_count,
        "failed": fail_count,
        "empty": empty_count,
        "branches": results,
        "branch_summaries": summaries,  # 每分點日/週/月/累積損益 + 風格
        "master_summaries": master_summaries,  # 按高手聚合
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
            "version": "3.0",
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n[{now_tw().strftime('%H:%M:%S')}] ✅ 完成！")
    print(f"  資料日期: {trade_date}")
    print(f"  成功: {success_count} / 失敗: {fail_count} / 無資料: {empty_count}")
    print(f"  歷史共 {len(all_dates)} 天")
    print(f"  🔒 資料已加密  📊 FIFO 部位已更新")
    
    if success_count == 0:
        print("⚠️  全部失敗，可能是假日或被擋")
        sys.exit(1)
 
 
if __name__ == "__main__":
    main()
