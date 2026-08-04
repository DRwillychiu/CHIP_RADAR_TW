# -*- coding: utf-8 -*-
"""v3.73.0 個股分點買賣超榜 (stock → branches) — 富邦 DJ 當日資料源

動機 (2026-08-04 事故):
  v3.72.x 用 histock 判定「該股全市場買超#1」, 但實測 histock 在 21:39 TW
  仍是 T-1 資料 → 我們 21:17/22:37/23:47 三個排程全部拿到過期資料
  → 時效 guard 正確擋掉 → 但結果是「永遠不會有 highlight」.

解法:
  富邦 DJ zco.djhtm (個股分點進出) 21:17 就有**當日**資料, 且用跟我們
  crawler 相同的分點代號系統 (branches.py 的 9A9S/9227/8888 等).
  → 改用富邦當 primary, histock 降為 fallback.

Endpoint:
  https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a={stock_code}

HTML 結構 (每 <TR> 10 個 <TD>):
  [0] 買超券商 <a href="...&b={bno}&BHID={parent}">名稱</a>
  [1] 買進(張) [2] 賣出(張) [3] 買超(張) [4] 佔成交比重
  [5] 賣超券商 <a ...>  [6] 買進 [7] 賣出 [8] 賣超 [9] 佔比

  買超側已按「買超張數」desc 排序 → rows[0] = 該股當日買超 #1.

⚠️ 注意: b= 是分點代號 (我們要的), BHID= 是母券商代號.
   e.g. 國泰-敦南 b=8888 BHID=8880 (8880 = 國泰證券總公司)
"""
from __future__ import annotations

import re
import time
import random
from typing import Any, Dict, List, Optional

import requests

FUBON_STOCK_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a={code}"
FUBON_HOME = "https://fubon-ebrokerdj.fbs.com.tw/"

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

# 一個 session 重用 (含 cookie), 降低被擋機率
_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": random.choice(UA_POOL),
            "Referer": FUBON_HOME,
            "Accept-Language": "zh-TW,zh;q=0.9",
        })
        try:
            s.get(FUBON_HOME, timeout=10)   # 拿 cookie
        except Exception:
            pass
        _SESSION = s
    return _SESSION


def reset_session() -> None:
    """測試/重試用: 丟掉現有 session 換新 UA."""
    global _SESSION
    _SESSION = None


_ROW_RE = re.compile(r"<TR>\s*(<TD class=\"t4t1\".*?)</tr>", re.S | re.I)
_TD_RE = re.compile(r"<TD[^>]*>(.*?)</TD>", re.S | re.I)
_BNO_RE = re.compile(r"[?&]b=([0-9A-Za-z]{3,6})[&\"]", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"(\d{4}/\d{2}/\d{2})")


def _clean(html: str) -> str:
    return _TAG_RE.sub("", html).replace("&nbsp;", "").strip()


def _to_int(s: str) -> int:
    s = _clean(s).replace(",", "")
    if not s or s in ("-", "--"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def parse_fubon_stock_page(html: str, stock_code: str = "") -> Optional[Dict[str, Any]]:
    """解析富邦 zco.djhtm HTML.

    Returns:
      {
        'stock_code': '2330',
        'date': '2026/08/04',              # 頁面標示的資料日
        'buys':  [{'bno','name','buy_lot','sell_lot','net','pct'}, ...],  # 買超 desc
        'sells': [{...}, ...],                                            # 賣超 desc
      }
      或 None (解析失敗)
    """
    if not html:
        return None

    dates = _DATE_RE.findall(html)
    trade_date = dates[0] if dates else ""

    buys: List[Dict[str, Any]] = []
    sells: List[Dict[str, Any]] = []

    for row_html in _ROW_RE.findall(html):
        tds = _TD_RE.findall(row_html)
        if len(tds) < 10:
            continue
        bnos = _BNO_RE.findall(row_html)
        # 每 row 應有 2 個 <a> (買超側 + 賣超側)
        buy_bno = bnos[0] if len(bnos) >= 1 else ""
        sell_bno = bnos[1] if len(bnos) >= 2 else ""

        buy_name = _clean(tds[0])
        if buy_name and buy_bno:
            buys.append({
                "bno": buy_bno,
                "name": buy_name,
                "buy_lot": _to_int(tds[1]),
                "sell_lot": _to_int(tds[2]),
                "net": _to_int(tds[3]),          # 買超張數 (正)
                "pct": _clean(tds[4]),
            })

        sell_name = _clean(tds[5])
        if sell_name and sell_bno:
            sells.append({
                "bno": sell_bno,
                "name": sell_name,
                "buy_lot": _to_int(tds[6]),
                "sell_lot": _to_int(tds[7]),
                "net": -_to_int(tds[8]),         # 賣超張數 → 存負值統一語意
                "pct": _clean(tds[9]),
            })

    if not buys and not sells:
        return None

    return {
        "stock_code": stock_code,
        "date": trade_date,
        "buys": buys,
        "sells": sells,
        "source": "fubon",
    }


def fetch_stock_branch_ranking(stock_code: str, timeout: int = 15,
                                max_retries: int = 2,
                                delay_range: tuple = (1.5, 3.0)) -> Optional[Dict[str, Any]]:
    """抓單一個股的分點買賣超榜 (當日).

    Args:
      stock_code: 股票代號 e.g. '2330'
      timeout: 單次 request timeout 秒
      max_retries: 重試次數
      delay_range: 每次 request 前隨機延遲 (禮貌爬取, 跟 crawler 同標準)

    Returns: parse_fubon_stock_page 的 dict, 或 None
    """
    url = FUBON_STOCK_URL.format(code=stock_code)
    s = _get_session()

    for attempt in range(max_retries):
        try:
            if delay_range:
                time.sleep(random.uniform(*delay_range))
            r = s.get(url, timeout=timeout)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                parsed = parse_fubon_stock_page(r.text, stock_code)
                if parsed:
                    return parsed
                # 200 但 parse 不出 → 可能個股冷門無資料, 不重試
                return None
            if attempt < max_retries - 1:
                time.sleep(3 + attempt * 2)
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(3)
    return None


def get_top_net_buyer(stock_code: str, trade_date: Optional[str] = None,
                      **kwargs) -> Optional[str]:
    """便利函式: 回傳該股當日買超 #1 的分點代號 (bno).

    Args:
      stock_code: 股票代號
      trade_date: YYYYMMDD, 若給則做時效 guard (頁面日期需相符)

    Returns: bno e.g. '9A9S' / None (抓不到、日期不符、或 net<=0)
    """
    data = fetch_stock_branch_ranking(stock_code, **kwargs)
    if not data or not data.get("buys"):
        return None
    if trade_date:
        page_date = (data.get("date") or "").replace("/", "")
        if page_date and page_date != trade_date:
            return None
    top = data["buys"][0]
    if int(top.get("net", 0) or 0) <= 0:
        return None
    return top.get("bno")
