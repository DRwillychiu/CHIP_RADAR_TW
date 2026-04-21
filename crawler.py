"""
分點籌碼觀察站 - 自動爬蟲
每日抓取指定分點的買超/賣超前 N 名，輸出 data/latest.json + data/YYYYMMDD.json
"""
import requests
import re
import json
import time
import os
import sys
import random
from pathlib import Path
from datetime import datetime, timezone, timedelta
 
# 台灣時區 (UTC+8)
TW_TZ = timezone(timedelta(hours=8))
 
def now_tw():
    """取得台灣現在時間"""
    return datetime.now(TW_TZ)
 
# ========== 設定區（您可以編輯這裡增減分點） ==========

# 您要關注的分點（從歷史資料整理出來，可自行增刪）
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
    {"code": "700c", "name": "兆豐-民生",     "master": "陳族元"},
    {"code": "8450", "name": "康和總公司",    "master": "陳族元"},
    {"code": "9A9R", "name": "永豐金-信義",   "master": "陳族元"},
    {"code": "585c", "name": "統一-仁愛",     "master": "陳族元"},
    {"code": "9217", "name": "凱基-松山",     "master": "迷你哥/松山哥"},
    {"code": "9200", "name": "凱基證券",          "master": "迷你哥/松山哥"},
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
    {"code": "585c", "name": "統一-仁愛",     "master": "陳律師"},
    {"code": "700c", "name": "兆豐-民生",     "master": "陳律師"},
    {"code": "8450", "name": "康和證券",     "master": "陳律師"},
    {"code": "9A9R", "name": "永豐金-信義",     "master": "陳律師"},
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
 
URL_TPL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb0.djhtm?a={code}&b={code}"
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
    rows = []
    for m in ROW_PATTERN.finditer(html):
        code = m.group(1) or m.group(3)
        name = (m.group(2) or m.group(4) or "").strip()
        try:
            buy = int(m.group(5).replace(",", ""))
            sell = int(m.group(6).replace(",", ""))
            net = int(m.group(7).replace(",", ""))
        except ValueError:
            continue
        rows.append({
            "code": code, "name": name,
            "buy": buy, "sell": sell, "net": net,
        })
    return rows
 
 
def fetch_branch(branch_code, max_retries=3):
    url = URL_TPL.format(code=branch_code)
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
                last_err = f"頁面過小 ({len(html)}b)，可能被擋"
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
 
 
def main():
    print(f"[{now_tw().strftime('%Y-%m-%d %H:%M:%S')}] 開始爬取 {len(WATCHED_BRANCHES)} 個分點")
    
    # 去除重複的分點代號
    seen = set()
    unique_branches = []
    for b in WATCHED_BRANCHES:
        if b["code"] not in seen:
            seen.add(b["code"])
            unique_branches.append(b)
    
    if len(unique_branches) < len(WATCHED_BRANCHES):
        print(f"  （偵測到 {len(WATCHED_BRANCHES) - len(unique_branches)} 個重複分點，自動去重）")
    
    results = []
    trade_date = None
    success_count = 0
    fail_count = 0
    empty_count = 0
    
    for i, branch in enumerate(unique_branches):
        code = branch["code"]
        print(f"  [{i+1}/{len(unique_branches)}] {branch['master']} | {branch['name']} ({code}) ", end="", flush=True)
        
        data = fetch_branch(code)
        
        if data["error"]:
            print(f"❌ {data['error']}")
            fail_count += 1
        elif not data["buys"] and not data["sells"]:
            print(f"⚪ 無資料")
            empty_count += 1
        else:
            print(f"✓ 買{len(data['buys'])}/賣{len(data['sells'])}")
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
                print(f"    ⏸  休息 {COOL_DOWN_SECONDS} 秒避免 rate limit...")
                time.sleep(COOL_DOWN_SECONDS)
            else:
                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    
    if not trade_date:
        trade_date = now_tw().strftime("%Y%m%d")
    
    output = {
        "trade_date": trade_date,
        "crawled_at": now_tw().isoformat(),
        "success": success_count,
        "failed": fail_count,
        "empty": empty_count,
        "branches": results,
    }
    
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    
    dated_file = data_dir / f"{trade_date}.json"
    with open(dated_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    latest_file = data_dir / "latest.json"
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
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
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n[{now_tw().strftime('%H:%M:%S')}] 完成！")
    print(f"  資料日期: {trade_date}")
    print(f"  成功: {success_count}, 失敗: {fail_count}, 無資料: {empty_count}")
    print(f"  歷史共 {len(all_dates)} 天")
    
    if success_count == 0:
        print("⚠️  全部失敗，可能是假日或被擋")
        sys.exit(1)
 
 
if __name__ == "__main__":
    main()
