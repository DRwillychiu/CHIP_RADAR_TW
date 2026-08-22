# -*- coding: utf-8 -*-
"""v3.74.0 公司行動 (Corporate Actions) 抓取 + 股價還原因子

動機 (2026-08-21 用戶回報):
  寶雅 5904 於 20260810 做 1:10 股票分割 (面額變更), 但 stock_history.json
  存的是**未還原**收盤價 (20260729=720 → 20260810=79.2).
  margin_maintenance 用「近 30 天收盤均價」當融資成本, 窗口跨過分割日 →
  均價 475.4 (720 元時代與 79 元時代混算) →
  維持率 = 74.5 / (475.4 × 0.6) = 26% → 誤判為「❌ 斷頭區」
  實際約 157% (健康). 全市場掃描: 131 檔窗內有跳空, 46 檔風險分級被算錯.

  用戶會依維持率警示調整部位 → 假警報會直接造成錯誤決策.

解法 — 三層取得公司行動 + 還原因子:
  Tier 1 官方 (精確):
    TWSE TWT49U  除權除息計算結果表   → 除權息前收盤價 / 除權息參考價
    TWSE TWTAUU  減資‧面額變更恢復買賣 → 停止買賣前收盤價 / 恢復買賣參考價
    TPEx tpex_exright_prepost         → 上櫃除權息
  Tier 2 自我偵測 (推估, 涵蓋官方 API 未開放的類型):
    TPEx 未開放「面額變更」API (寶雅正是此類) → 從價格序列偵測
    單日 |漲跌| > 11% (超出 ±10% 漲跌停極限) ⇒ 必為公司行動
    factor = 前一日收盤 / 當日收盤   (殘差 = 當日真實漲跌, 上限 ±10%)
  Tier 3 無法判定:
    回報 confidence='none', 呼叫端應「不顯示」而非顯示錯值

還原因子語意:
  factor = 事件前價格 ÷ 事件後價格   (寶雅 ≈ 9.09, 真實分割比 10)
  還原: adjusted_close = raw_close ÷ factor   (把事件前價格拉到事件後尺度)

輸出 data/corporate_actions.json:
  {"updated_at": ISO, "actions": {code: [{date, type, factor, confidence, ...}]}}
"""
from __future__ import annotations

import re
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

TW_TZ = timezone(timedelta(hours=8))
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-TW,zh;q=0.9",
}

TWSE_EXRIGHT = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U?date={ym}01&response=json"
TWSE_REDUCT = "https://www.twse.com.tw/rwd/zh/reducation/TWTAUU?date={ym}01&response=json"
TPEX_EXRIGHT = "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost"

# 超出漲跌停極限 → 必為公司行動 (台股 ±10%, 留 1% 緩衝給資料誤差)
LIMIT_MOVE_PCT = 11.0
# 事件後至少要幾天才足以重算均價
MIN_POST_DAYS = 5


def _f(x) -> Optional[float]:
    """字串轉 float (去逗號/空白), 失敗回 None."""
    if x is None:
        return None
    s = str(x).replace(",", "").replace("&nbsp;", "").strip()
    if not s or s in ("-", "--", "0", "0.00"):
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _roc_to_ad(s: str) -> Optional[str]:
    """民國日期 115/08/24 或 1150824 → 20260824."""
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"^(\d{2,3})[/-](\d{1,2})[/-](\d{1,2})$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif re.fullmatch(r"\d{7}", s):
        y, mo, d = int(s[:3]), int(s[3:5]), int(s[5:7])
    else:
        return None
    return f"{y + 1911:04d}{mo:02d}{d:02d}"


def _get_json(url: str, timeout: int = 25, retries: int = 2) -> Optional[Any]:
    for a in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                return r.json()
        except Exception:
            pass
        if a < retries - 1:
            time.sleep(2 + a * 2)
    return None


# ══════════════════════════════════════════════════════════════════
#  Tier 1 — 官方來源
# ══════════════════════════════════════════════════════════════════

def fetch_twse_exright(ym: str) -> List[Dict[str, Any]]:
    """TWSE 除權除息計算結果表 (上市). ym = 'YYYYMM'.

    fields: 資料日期 / 股票代號 / 股票名稱 / 除權息前收盤價 / 除權息參考價 / ...
    """
    j = _get_json(TWSE_EXRIGHT.format(ym=ym))
    out: List[Dict[str, Any]] = []
    for row in ((j or {}).get("data") or []):
        if len(row) < 5:
            continue
        d = _roc_to_ad(row[0])
        code = str(row[1]).strip()
        pre, post = _f(row[3]), _f(row[4])
        if not (d and code and pre and post):
            continue
        out.append({
            "code": code, "date": d, "type": "exright",
            "pre_price": pre, "post_price": post,
            "factor": round(pre / post, 6), "confidence": "official",
            "source": "TWSE_TWT49U",
        })
    return out


def fetch_twse_reduction(ym: str) -> List[Dict[str, Any]]:
    """TWSE 減資‧面額變更 恢復買賣參考價 (上市). ym = 'YYYYMM'.

    fields: 恢復買賣日期 / 股票代號 / 名稱 / 停止買賣前收盤價格 / 恢復買賣參考價 / ...
    """
    j = _get_json(TWSE_REDUCT.format(ym=ym))
    out: List[Dict[str, Any]] = []
    for row in ((j or {}).get("data") or []):
        if len(row) < 5:
            continue
        d = _roc_to_ad(row[0])
        code = str(row[1]).strip()
        pre, post = _f(row[3]), _f(row[4])
        if not (d and code and pre and post):
            continue
        out.append({
            "code": code, "date": d, "type": "reduction_or_parvalue",
            "pre_price": pre, "post_price": post,
            "factor": round(pre / post, 6), "confidence": "official",
            "source": "TWSE_TWTAUU",
        })
    return out


def fetch_tpex_exright() -> List[Dict[str, Any]]:
    """TPEx 除權息前後 (上櫃). 只有配股/配息率, 無前後收盤價 →
    factor 由配股率推算: factor = 1 + 股票股利率 (現金股利影響另計, 較小)."""
    j = _get_json(TPEX_EXRIGHT)
    out: List[Dict[str, Any]] = []
    for x in (j or []):
        if not isinstance(x, dict):
            continue
        d = _roc_to_ad(x.get("ExRrightsExDividendDate", ""))
        code = str(x.get("SecuritiesCompanyCode", "")).strip()
        if not (d and code):
            continue
        try:
            stock_div = float(x.get("StockDividendRatio") or 0)
        except (TypeError, ValueError):
            stock_div = 0.0
        if stock_div <= 0:
            continue   # 純現金股利對股價尺度影響小, 不列為需還原的公司行動
        out.append({
            "code": code, "date": d, "type": "exright_stock_dividend",
            "pre_price": None, "post_price": None,
            "factor": round(1.0 + stock_div, 6), "confidence": "official",
            "source": "TPEX_exright_prepost",
        })
    return out


# ══════════════════════════════════════════════════════════════════
#  Tier 2 — 自我偵測 (涵蓋官方未開放者, 如 TPEx 面額變更)
# ══════════════════════════════════════════════════════════════════

def detect_from_price_series(daily: Dict[str, Dict[str, Any]],
                              limit_pct: float = LIMIT_MOVE_PCT
                              ) -> List[Dict[str, Any]]:
    """從單一個股的 daily{date:{close}} 偵測公司行動跳空.

    單日 |漲跌| > limit_pct (預設 11%, 超出台股 ±10% 極限) ⇒ 必為公司行動.
    factor = 前一日收盤 / 當日收盤 (殘差 = 當日真實漲跌, 上限 ±10%)
    """
    dates = sorted(daily.keys())
    closes = [(d, (daily[d] or {}).get("close")) for d in dates]
    closes = [(d, float(c)) for d, c in closes if c and float(c) > 0]
    raw: List[Dict[str, Any]] = []
    for i in range(1, len(closes)):
        (_, prev), (d_cur, cur) = closes[i - 1], closes[i]
        if prev <= 0:
            continue
        move = (cur - prev) / prev * 100
        if abs(move) <= limit_pct:
            continue
        raw.append({
            "date": d_cur, "type": "detected_gap", "idx": i,
            "pre_price": round(prev, 4), "post_price": round(cur, 4),
            "factor": round(prev / cur, 6), "confidence": "inferred",
            "raw_move_pct": round(move, 2), "source": "price_series",
        })

    # v3.74.0 spike 過濾: 單日資料錯誤會產生「一去一回」兩筆偽行動
    #   e.g. 瑞儀 6176: 102.0 → 10.0 → 102.85  (20260602 收盤漏一位數)
    #   特徵: 相鄰兩筆偵測的 factor 互為倒數 (f1 × f2 ≈ 1) 且 index 相差 1
    # 公司行動不會隔天就反向還原, 故此模式必為壞資料 → 兩筆都剔除.
    bad_idx = set()
    drop = set()
    for a, b in zip(raw, raw[1:]):
        if b["idx"] - a["idx"] != 1:
            continue
        prod = a["factor"] * b["factor"]
        if 0.85 <= prod <= 1.15:          # 互為倒數 (容忍當日真實漲跌 ±10%)
            drop.add(a["date"]); drop.add(b["date"])
            bad_idx.add(a["date"])        # 中間那天 (a 的 date) 就是壞值
    out = [{k: v for k, v in a.items() if k != "idx"}
           for a in raw if a["date"] not in drop]
    for a in out:
        a["bad_data_dates"] = []
    if out and bad_idx:
        out[0]["bad_data_dates"] = sorted(bad_idx)
    return out


def detect_bad_price_days(daily: Dict[str, Dict[str, Any]],
                           limit_pct: float = LIMIT_MOVE_PCT) -> List[str]:
    """回傳「單日資料錯誤」的日期 list (一去一回的中間那天)."""
    dates = sorted(daily.keys())
    closes = [(d, (daily[d] or {}).get("close")) for d in dates]
    closes = [(d, float(c)) for d, c in closes if c and float(c) > 0]
    bad: List[str] = []
    for i in range(1, len(closes) - 1):
        p, c, n = closes[i - 1][1], closes[i][1], closes[i + 1][1]
        if p <= 0 or c <= 0:
            continue
        m1 = (c - p) / p * 100
        m2 = (n - c) / c * 100
        if abs(m1) > limit_pct and abs(m2) > limit_pct:
            if 0.85 <= (p / c) * (c / n) <= 1.15:   # = p/n ≈ 1 → 一去一回
                bad.append(closes[i][0])
    return bad


# ══════════════════════════════════════════════════════════════════
#  合併 + 還原
# ══════════════════════════════════════════════════════════════════

def build_action_map(stock_history: Optional[Dict[str, Any]] = None,
                      months: int = 3,
                      include_official: bool = True) -> Dict[str, Any]:
    """組出 {code: [action, ...]} — 官方優先, 自我偵測補齊.

    同一 (code, date) 若官方與偵測都有, 保留官方 (factor 較精確).
    """
    actions: Dict[str, List[Dict[str, Any]]] = {}
    stats = {"official": 0, "inferred": 0, "merged_dup": 0}

    def _add(code: str, a: Dict[str, Any]):
        lst = actions.setdefault(code, [])
        for ex in lst:
            if ex["date"] == a["date"]:
                # 已有同日 → 官方勝出
                if ex["confidence"] != "official" and a["confidence"] == "official":
                    lst[lst.index(ex)] = a
                stats["merged_dup"] += 1
                return
        lst.append(a)
        stats[a["confidence"] if a["confidence"] in stats else "inferred"] += 1

    if include_official:
        now = datetime.now(TW_TZ)
        for k in range(months):
            m = now.month - k
            y = now.year
            while m <= 0:
                m += 12
                y -= 1
            ym = f"{y}{m:02d}"
            for fn in (fetch_twse_exright, fetch_twse_reduction):
                try:
                    for a in fn(ym):
                        _add(a.pop("code"), a)
                except Exception:
                    pass
                time.sleep(0.5)
        try:
            for a in fetch_tpex_exright():
                _add(a.pop("code"), a)
        except Exception:
            pass

    if stock_history:
        for code, rec in (stock_history.get("stocks") or {}).items():
            if not re.fullmatch(r"\d{4}[A-Z]?", str(code)):
                continue   # 略過權證/ETF 等
            for a in detect_from_price_series(rec.get("daily") or {}):
                _add(code, a)

    for lst in actions.values():
        lst.sort(key=lambda x: x["date"])
    return {
        "updated_at": datetime.now(TW_TZ).isoformat(),
        "actions": actions,
        "stats": stats,
    }


def adjust_closes(daily: Dict[str, Dict[str, Any]],
                   code_actions: List[Dict[str, Any]]) -> Dict[str, float]:
    """把 raw close 還原到「最新尺度」.

    事件日 D 的 factor f ⇒ D 之前 (不含 D) 的所有 close 都要 ÷ f.
    多個事件則累乘 (由新到舊逐次套用).

    Returns: {date: adjusted_close}
    """
    out = {d: float((v or {}).get("close") or 0) for d, v in (daily or {}).items()}
    out = {d: c for d, c in out.items() if c > 0}
    if not code_actions:
        return out
    for a in sorted(code_actions, key=lambda x: x["date"], reverse=True):
        f = float(a.get("factor") or 0)
        if f <= 0:
            continue
        d0 = a["date"]
        for d in list(out.keys()):
            if d < d0:
                out[d] = out[d] / f
    return out


def latest_action_within(code_actions: List[Dict[str, Any]],
                          window_dates: List[str]) -> Optional[Dict[str, Any]]:
    """回傳落在 window_dates 範圍內、最近的一次公司行動 (無則 None)."""
    if not code_actions or not window_dates:
        return None
    lo, hi = min(window_dates), max(window_dates)
    inside = [a for a in code_actions if lo <= a["date"] <= hi]
    return max(inside, key=lambda x: x["date"]) if inside else None
