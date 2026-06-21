"""
crawler_fetch.py — 抓取層 (v3.35.0 B1 從 crawler.py 拆出)

TWSE 分點「金額 (c=B) + 張數 (c=E)」雙模式爬取 + merge_rows 合併。
fetch_branch_combined 是 main() 抓 81 分點的唯一入口。

trade_style 判定 (daytrade/partial/overnight) 在 merge_rows 內 —
這是 master_profile 15 標籤體系的最底層資料來源。
"""
import re
import time
import random

import requests

# ========== 爬蟲參數 ==========

TOP_N = 30                # 每個分點保留的買/賣超前 N 檔
DELAY_MIN = 2.0           # 請求間隔最小秒
DELAY_MAX = 4.0           # 請求間隔最大秒
COOL_DOWN_EVERY = 10      # 每 N 個分點後長休息
COOL_DOWN_SECONDS = 8

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

