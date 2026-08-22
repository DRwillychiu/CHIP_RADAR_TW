"""
========================================================================
Module: margin_maintenance.py  (v3.37.0, v3.74.0 加公司行動校正)
個股「市場平均融資維持率」估算 + 風險分級

⚠️ 資料限制與業界估算法 (誠實揭露):
  TWSE 公開資料『不』提供個股的「融資餘額金額」(只有全市場合計約 5570 億)。
  個股維持率必須用估算: 業界 (Goodinfo / Histock) 都用「N 日均價」當融資成本近似。

公式 (本模組):
  estimated_cost  = N_DAYS_AVG_CLOSE   # 假設融資建倉均勻分布於近 N 天
  ⚠️ v3.74.0: 均價前先做「公司行動還原」— 窗口跨過除權息/減資/面額變更(分割)/
     現增時, 原始收盤有尺度斷層, 直接平均會得到無意義的數字.
     實例: 寶雅 5904 於 20260810 做 1:10 分割, 未校正時 30 日均價 = 475.4
     (720 元時代與 79 元時代混算) → 維持率 26% 誤判斷頭, 實際約 164% 健康.
     全市場掃描: 131 檔窗內有跳空, 48 檔風險分級被算錯 (皆為假警報方向).
  required_close  = estimated_cost × 0.6 × 1.20   # 維持率 120% 斷頭價
  maintenance     = today_close ÷ (estimated_cost × 0.6) × 100%

風險分級:
  健康 (healthy)   ≥ 150%
  ⚠️警戒 (watch)   130-150%   — 接近追繳線
  🚨高風險 (high)  120-130%   — 跌破即觸發追繳通知
  ❌斷頭區 (margin_call)  < 120% — 已過斷頭線

⚠️ UI 必須標示「市場估算, 非個人帳戶」:
  - 真實個人帳戶維持率: 看券商系統 (整戶計算 + 真實成本價)
  - 本估算定位: 大盤系統性風險指標 (整體跌破 140% 時市場警戒)

整合點:
  inject_maintenance_into_stocks(results, daily_quotes_map, stock_history)
  → 寫入每個 stock dict 的 margin_maintenance_ratio + margin_risk_level
========================================================================
"""
from typing import Dict, Any, Optional, List

# ════════════════════════════════════════════════════════════════════
#  參數 (集中可調)
# ════════════════════════════════════════════════════════════════════

N_DAYS_AVG = 30           # 用近 N 天收盤均價當融資成本估算

# P1-6 (v3.39.0): 融資成數法源 — TWSE 證券交易法
# 官方融資成數: 上市/上櫃股票 60% (亦即客戶自付 40%, 證金公司借 60%)
# 部分主管機關列管股 (處置/警示) 融資成數降至 50% 甚或停止融資
# 來源: https://www.twse.com.tw/zh/products/trading/services/margin/announcement.html
# 來源: https://www.tdcc.com.tw/portal/zh/marketing/financing
# 此常數變動時請同步檢查: 處置股維持率估算需另用 0.5 (處置中常見成數)
MARGIN_RATE = 0.6
INITIAL_MAINT = 1.667     # 初始維持率 = 1/MARGIN_RATE ≈ 166.67%

# v3.74.1: 處置股融資成數 — 主管機關列管期間成數調降
# 用 0.6 算處置股會**低估**維持率約 17% (0.5/0.6 = 0.833) → 假警報方向
# 蔣承翰等 sniper 專抓漲停, 漲停股極易進處置 → 此路徑使用頻率高
DISPOSAL_MARGIN_RATE = 0.5

# P1-6: 風險分級門檻 (%) 法源 — TWSE「整戶擔保維持率」規定
# 健康 ≥150%: 一般操作區間
# 警戒 130-150%: 接近追繳線, 風險偵測區
# 高風險 120-130%: 跌破即觸發補繳通知 (T+2 內須補)
# 斷頭 <120%: 證金公司強制平倉 (整戶斷頭)
# 來源: 證券商辦理有價證券買賣融資融券業務操作辦法 第 11/12 條
# 來源: https://www.cnyes.com/glossary/maintain.aspx (淺顯說明)
THRESHOLDS = {
    'healthy':      150.0,    # ≥ 150%
    'watch':        130.0,    # 130-150% — 法定追繳線
    'high_risk':    120.0,    # 120-130% — 跌破即追繳
    # 'margin_call': < 120% — 法定斷頭線
}

# 最低有效融資餘額 (張) — 低於此不算 (估算失準)
MIN_BALANCE_LOTS = 100

# 除權息日偵測門檻 (單日跌幅 > X% 視為跳空)
EX_DIV_DROP_PCT = 7.0


def compute_n_day_avg_close(code: str,
                              stock_history: Optional[Dict[str, Any]],
                              n_days: int = N_DAYS_AVG,
                              corporate_actions: Optional[Dict[str, Any]] = None
                              ) -> Optional[Dict[str, Any]]:
    """從 stock_history.json 取近 N 天收盤均價 (用作融資成本估算).

    v3.74.0: 公司行動自動校正 —
      窗口若跨過除權息/減資/面額變更(分割)/現增, 原始收盤價會有尺度斷層,
      直接平均會得到毫無意義的數字 (寶雅 5904 分割後均價 475 vs 實際 77,
      維持率被算成 26% 誤判斷頭).
      → 用 corporate_actions 的 factor 把事件前價格還原到現行尺度後再平均.
      → 單日資料錯誤 (一去一回的尖刺) 直接排除, 不納入平均.

    Args:
      corporate_actions: {code: [action,...]} from corporate_actions.build_action_map

    回傳: {'avg': float, 'adjusted': bool, 'action': dict|None,
           'n_used': int, 'excluded_bad_days': int}  或 None (資料不足)
    """
    if not stock_history:
        return None
    stocks = stock_history.get('stocks', {}) or {}
    rec = stocks.get(code) or {}
    daily = rec.get('daily', {}) or {}
    if not daily:
        return None

    dates_sorted = sorted(daily.keys(), reverse=True)[:n_days]
    if not dates_sorted:
        return None
    window = {d: daily[d] for d in dates_sorted}

    acts = (corporate_actions or {}).get(code) or []
    action_in_window = None
    closes_map: Dict[str, float] = {}
    bad_days: List[str] = []

    try:
        from src.fetchers.corporate_actions import (
            adjust_closes, latest_action_within, detect_bad_price_days,
        )
        action_in_window = latest_action_within(acts, dates_sorted)
        # 壞資料日用完整序列判斷 (需要前後各一天), 再交集到窗口
        bad_days = [d for d in detect_bad_price_days(daily) if d in window]
        closes_map = adjust_closes(window, acts)
    except Exception:
        # 還原模組不可用 → 退回原始行為 (至少不 crash)
        closes_map = {d: float((window[d] or {}).get('close') or 0)
                      for d in window}
        closes_map = {d: c for d, c in closes_map.items() if c > 0}

    closes = [c for d, c in closes_map.items() if d not in set(bad_days) and c > 0]
    if len(closes) < max(5, n_days // 6):   # 至少 5 天或 1/6 樣本
        return None

    return {
        'avg': sum(closes) / len(closes),
        'adjusted': bool(action_in_window),
        'action': action_in_window,
        'n_used': len(closes),
        'excluded_bad_days': len(bad_days),
    }


def detect_ex_dividend(today_close: float,
                        prev_close: Optional[float]) -> bool:
    """偵測除權息日 — 單日跌幅 > 門檻 → 視為跳空 (維持率計算 stale)."""
    if not prev_close or prev_close <= 0:
        return False
    drop_pct = (prev_close - today_close) / prev_close * 100
    return drop_pct > EX_DIV_DROP_PCT


def compute_stock_maintenance(today_close: float,
                                margin_balance_lots: int,
                                estimated_cost: Optional[float],
                                prev_close: Optional[float] = None,
                                margin_rate: Optional[float] = None,
                                is_disposal: bool = False
                                ) -> Optional[Dict[str, Any]]:
    """計算單一個股的市場估算維持率 + 風險分級.

    Returns: {maintenance_ratio, risk_level, risk_label, estimated_cost,
              stale_due_to_ex_div, ...} 或 None (資料不足)"""
    if not today_close or today_close <= 0:
        return None
    if margin_balance_lots < MIN_BALANCE_LOTS:
        return None
    if not estimated_cost or estimated_cost <= 0:
        return None

    # 除權息偵測 (僅作 stale flag, 仍算)
    stale = detect_ex_dividend(today_close, prev_close)

    # 核心公式
    # 融資金額 ≈ 平均成本 × 餘額張數 × 1000 × MARGIN_RATE
    # 擔保品市值 = 今日收盤 × 餘額張數 × 1000
    # 維持率 = 擔保品市值 / 融資金額 = today / (avg_cost × MARGIN_RATE)
    # P0-5: ZeroDivisionError 防守 (估算成本 = 0 / MARGIN_RATE 配置錯, 都會炸)
    # v3.74.1: 處置股融資成數降至 0.5 (未指定 margin_rate 時依 is_disposal 自動選)
    rate = margin_rate if margin_rate else (
        DISPOSAL_MARGIN_RATE if is_disposal else MARGIN_RATE)
    denom = estimated_cost * rate
    if denom <= 0:
        return None
    maintenance = (today_close / denom) * 100

    # 分級
    if maintenance >= THRESHOLDS['healthy']:
        risk_level = 'healthy'
        risk_label = '健康'
        risk_icon = '✅'
    elif maintenance >= THRESHOLDS['watch']:
        risk_level = 'watch'
        risk_label = '警戒'
        risk_icon = '⚠️'
    elif maintenance >= THRESHOLDS['high_risk']:
        risk_level = 'high_risk'
        risk_label = '高風險'
        risk_icon = '🚨'
    else:
        risk_level = 'margin_call'
        risk_label = '斷頭區'
        risk_icon = '❌'

    return {
        'margin_maintenance_ratio': round(maintenance, 1),
        'margin_risk_level': risk_level,
        'margin_risk_label': risk_label,
        'margin_risk_icon': risk_icon,
        'estimated_cost': round(estimated_cost, 2),
        'maintenance_method': f'{N_DAYS_AVG}d_avg_close',
        'margin_stale_due_to_ex_div': stale,
        'margin_rate_used': rate,                  # v3.74.1 揭露用了哪個成數
        'is_disposal_stock': bool(is_disposal),
    }


def inject_maintenance_into_stocks(
    branches: List[Dict[str, Any]],
    margin_all: Dict[str, Dict[str, Any]],
    daily_quotes_map: Dict[str, Dict[str, Any]],
    stock_history: Optional[Dict[str, Any]] = None,
    corporate_actions: Optional[Dict[str, Any]] = None,
    disposal_codes: Optional[set] = None,
) -> Dict[str, Any]:
    """注入個股維持率到 branches[].buys/sells 各 stock dict.

    參數:
      branches: crawler.py 主流程 results list (branches list 本身)
      margin_all: margin.py 抓的 {code: {margin_balance, ...}}
      daily_quotes_map: {code: {close, prev_close, ...}} from institutional.py
      stock_history: 解析 data/stock_history.json (近 30 天收盤)

    Returns: {'computed': N, 'high_risk_codes': [...], 'margin_call_codes': [...],
              'summary': market_summary_dict}"""
    computed = 0
    by_risk = {'high_risk': set(), 'margin_call': set(), 'watch': set()}

    # per-stock 快取 (同股可能在多分點出現, 算一次重用)
    cache: Dict[str, Optional[Dict[str, Any]]] = {}

    for br in branches:
        for side in ('buys', 'sells'):
            for stock in (br.get(side) or []):
                code = str(stock.get('code') or '')
                if not code:
                    continue
                if code in cache:
                    m = cache[code]
                else:
                    m = _compute_for_code(code, margin_all, daily_quotes_map,
                                          stock_history, corporate_actions,
                                          disposal_codes)
                    cache[code] = m
                if m:
                    stock.update(m)
                    computed += 1
                    if m['margin_risk_level'] in by_risk:
                        by_risk[m['margin_risk_level']].add(code)

    # 全市場排行: 從 margin_all 計所有股票 (給 tab 08 / tab 15 用)
    market_summary = _compute_market_summary(margin_all, daily_quotes_map,
                                              stock_history, corporate_actions,
                                              disposal_codes)

    return {
        'computed': computed,
        'high_risk_codes': sorted(by_risk['high_risk']),
        'margin_call_codes': sorted(by_risk['margin_call']),
        'watch_codes': sorted(by_risk['watch']),
        'summary': market_summary,
    }


def _compute_for_code(code: str,
                       margin_all: Dict[str, Dict[str, Any]],
                       daily_quotes_map: Dict[str, Dict[str, Any]],
                       stock_history: Optional[Dict[str, Any]],
                       corporate_actions: Optional[Dict[str, Any]] = None,
                       disposal_codes: Optional[set] = None
                       ) -> Optional[Dict[str, Any]]:
    m_rec = margin_all.get(code)
    if not m_rec:
        return None
    q_rec = daily_quotes_map.get(code) or {}
    today_close = q_rec.get('close')
    prev_close = q_rec.get('prev_close')
    if not today_close:
        return None
    margin_bal = m_rec.get('margin_balance', 0) or 0
    ci = compute_n_day_avg_close(code, stock_history,
                                 corporate_actions=corporate_actions)
    if not ci:
        return None
    r = compute_stock_maintenance(float(today_close), margin_bal,
                                  ci['avg'], prev_close,
                                  is_disposal=code in (disposal_codes or set()))
    if r:
        # v3.74.0: 揭露成本基準是否經公司行動校正 (供 UI 標示)
        r['cost_adjusted_for_corp_action'] = ci['adjusted']
        r['cost_n_days_used'] = ci['n_used']
        if ci['excluded_bad_days']:
            r['cost_excluded_bad_days'] = ci['excluded_bad_days']
        act = ci.get('action')
        if act:
            r['corp_action'] = {
                'date': act.get('date'), 'type': act.get('type'),
                'factor': act.get('factor'), 'confidence': act.get('confidence'),
            }
    return r


def _compute_market_summary(margin_all: Dict[str, Dict[str, Any]],
                              daily_quotes_map: Dict[str, Dict[str, Any]],
                              stock_history: Optional[Dict[str, Any]],
                              corporate_actions: Optional[Dict[str, Any]] = None,
                              disposal_codes: Optional[set] = None
                              ) -> Dict[str, Any]:
    """全市場維持率分布: 健康/警戒/高風險/斷頭數量 + Top 高風險清單."""
    counts = {'healthy': 0, 'watch': 0, 'high_risk': 0, 'margin_call': 0,
              'insufficient_data': 0}
    high_risk_stocks = []   # (code, ratio, name, balance)

    for code, m_rec in margin_all.items():
        margin_bal = m_rec.get('margin_balance', 0) or 0
        if margin_bal < MIN_BALANCE_LOTS:
            counts['insufficient_data'] += 1
            continue
        q_rec = daily_quotes_map.get(code) or {}
        today_close = q_rec.get('close')
        if not today_close:
            counts['insufficient_data'] += 1
            continue
        ci = compute_n_day_avg_close(code, stock_history,
                                     corporate_actions=corporate_actions)
        if not ci:
            counts['insufficient_data'] += 1
            continue
        r = compute_stock_maintenance(float(today_close), margin_bal,
                                       ci['avg'], q_rec.get('prev_close'),
                                       is_disposal=code in (disposal_codes or set()))
        if r:
            counts[r['margin_risk_level']] += 1
            if r['margin_risk_level'] in ('high_risk', 'margin_call'):
                high_risk_stocks.append({
                    'code': code,
                    'name': m_rec.get('name', ''),
                    'ratio': r['margin_maintenance_ratio'],
                    'risk_level': r['margin_risk_level'],
                    'margin_balance': margin_bal,
                    'today_close': today_close,
                    'estimated_cost': r['estimated_cost'],
                    # v3.74.0/1: 供前端標記 🔧 已校正 / ⚠️處 處置股
                    'cost_adjusted_for_corp_action': ci.get('adjusted', False),
                    'is_disposal_stock': r.get('is_disposal_stock', False),
                    'margin_rate_used': r.get('margin_rate_used', MARGIN_RATE),
                })

    # 按維持率升冪 (最危險在前)
    high_risk_stocks.sort(key=lambda x: x['ratio'])
    return {
        'method': f'market_estimate_{N_DAYS_AVG}d_avg_close',
        'caveat': '市場估算非個人帳戶 — 個人實際維持率需查券商系統 (整戶計算+真實成本)',
        'counts': counts,
        'high_risk_stocks': high_risk_stocks[:30],   # Top 30 危險清單
        'thresholds': {
            'healthy': '≥150%', 'watch': '130-150%',
            'high_risk': '120-130%', 'margin_call': '<120%',
        },
    }
