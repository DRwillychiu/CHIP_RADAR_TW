"""
========================================================================
Module: margin_maintenance.py  (v3.37.0)
個股「市場平均融資維持率」估算 + 風險分級

⚠️ 資料限制與業界估算法 (誠實揭露):
  TWSE 公開資料『不』提供個股的「融資餘額金額」(只有全市場合計約 5570 億)。
  個股維持率必須用估算: 業界 (Goodinfo / Histock) 都用「N 日均價」當融資成本近似。

公式 (本模組):
  estimated_cost  = N_DAYS_AVG_CLOSE   # 假設融資建倉均勻分布於近 N 天
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
MARGIN_RATE = 0.6         # 融資成數 (1.6 倍槓桿; 60% 自備款 40% 融資)
INITIAL_MAINT = 1.667     # 初始維持率 (1/0.6) ≈ 166.67%

# 風險分級門檻 (%)
THRESHOLDS = {
    'healthy':      150.0,    # ≥ 150%
    'watch':        130.0,    # 130-150%
    'high_risk':    120.0,    # 120-130% (跌破即追繳)
    # 'margin_call': < 120%
}

# 最低有效融資餘額 (張) — 低於此不算 (估算失準)
MIN_BALANCE_LOTS = 100

# 除權息日偵測門檻 (單日跌幅 > X% 視為跳空)
EX_DIV_DROP_PCT = 7.0


def compute_n_day_avg_close(code: str,
                              stock_history: Optional[Dict[str, Any]],
                              n_days: int = N_DAYS_AVG) -> Optional[float]:
    """從 stock_history.json 取近 N 天收盤均價 (用作融資成本估算).

    stock_history 格式 (v3.33+): {'stocks': {code: {'daily': {date: {close, ...}}}}}
    回傳: 均價 (元) 或 None (資料不足)"""
    if not stock_history:
        return None
    stocks = stock_history.get('stocks', {}) or {}
    rec = stocks.get(code) or {}
    daily = rec.get('daily', {}) or {}
    if not daily:
        return None
    # 取最近 N 天 (按日期降冪)
    dates_sorted = sorted(daily.keys(), reverse=True)[:n_days]
    closes = []
    for d in dates_sorted:
        c = (daily[d] or {}).get('close')
        if c and c > 0:
            closes.append(float(c))
    if len(closes) < max(5, n_days // 6):   # 至少 5 天或 1/6 樣本
        return None
    return sum(closes) / len(closes)


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
                                prev_close: Optional[float] = None
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
    denom = estimated_cost * MARGIN_RATE
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
    }


def inject_maintenance_into_stocks(
    branches: List[Dict[str, Any]],
    margin_all: Dict[str, Dict[str, Any]],
    daily_quotes_map: Dict[str, Dict[str, Any]],
    stock_history: Optional[Dict[str, Any]] = None,
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
                                          stock_history)
                    cache[code] = m
                if m:
                    stock.update(m)
                    computed += 1
                    if m['margin_risk_level'] in by_risk:
                        by_risk[m['margin_risk_level']].add(code)

    # 全市場排行: 從 margin_all 計所有股票 (給 tab 08 / tab 15 用)
    market_summary = _compute_market_summary(margin_all, daily_quotes_map,
                                              stock_history)

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
                       stock_history: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    m_rec = margin_all.get(code)
    if not m_rec:
        return None
    q_rec = daily_quotes_map.get(code) or {}
    today_close = q_rec.get('close')
    prev_close = q_rec.get('prev_close')
    if not today_close:
        return None
    margin_bal = m_rec.get('margin_balance', 0) or 0
    estimated_cost = compute_n_day_avg_close(code, stock_history)
    return compute_stock_maintenance(float(today_close), margin_bal,
                                      estimated_cost, prev_close)


def _compute_market_summary(margin_all: Dict[str, Dict[str, Any]],
                              daily_quotes_map: Dict[str, Dict[str, Any]],
                              stock_history: Optional[Dict[str, Any]]
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
        estimated_cost = compute_n_day_avg_close(code, stock_history)
        if not estimated_cost:
            counts['insufficient_data'] += 1
            continue
        r = compute_stock_maintenance(float(today_close), margin_bal,
                                       estimated_cost, q_rec.get('prev_close'))
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
