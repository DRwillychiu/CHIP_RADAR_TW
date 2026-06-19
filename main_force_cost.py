"""
========================================================================
Module: main_force_cost.py  (v3.46.0 後9 — Tier 2 Sprint 8)

主力成本線估算 — 業界普及功能

定義 (業界共識):
  主力成本線 = Σ(每日主力買進金額) ÷ Σ(每日主力買進量)
             = 主力過去 N 天的平均買進成本

「主力」的定義:
  本系統用「buys 榜的所有 watched 分點 master 級買進」當主力
  (跟「市場主力 = 投信 + 自營商 + 外資」不同, 我們是「分點大戶主力」)

實戰用法:
  1. 個股當前股價 vs 主力成本線:
     - 高於成本線 5%+: 主力浮盈 (持續性高)
     - 低於成本線 5%+: 主力套牢 (可能被迫殺出)
  2. 兩條線交叉 → 主力進出方向變化

輸出 inject 進 raw_output.branches[].buys[]:
  stock['main_force_cost_5d'] = N 日成本線
  stock['main_force_cost_20d'] = 20 日成本線
  stock['main_force_cost_premium_pct'] = (today_close - 5d_cost) / 5d_cost × 100

依賴: 60 天 stock_history.json (v3.44.0 起延長)
========================================================================
"""
from collections import defaultdict
from typing import Dict, Any, List, Optional


def compute_main_force_cost_per_stock(history: List[Dict[str, Any]],
                                        window_days: int = 5) -> Dict[str, float]:
    """從 60 天 history 算每股的主力成本線.

    Args:
      history: list of daily JSON (解密後),
               每筆含 branches[].buys[] (僅 watched master)
      window_days: 5 or 20 (兩條常用)

    Returns:
      {code: cost_line} 元/股
    """
    # 取最後 window_days 天
    recent = history[-window_days:] if len(history) > window_days else history
    # 每股累計買金額 (仟元) + 累計買張數
    amt_sum = defaultdict(int)
    lot_sum = defaultdict(int)
    for day in recent:
        for br in day.get('data', {}).get('branches', []):
            # 只算有 master 的分點 (watched)
            master = br.get('master')
            if not master:
                continue
            for s in (br.get('buys') or []):
                code = str(s.get('code') or '')
                if not code:
                    continue
                amt_sum[code] += (s.get('buy_amt', 0) or 0)
                lot_sum[code] += (s.get('buy_lot', 0) or 0)
    out = {}
    for code in amt_sum:
        lot = lot_sum[code]
        if lot <= 0:
            continue
        # buy_amt (仟元) ÷ buy_lot (張) = 元/股
        out[code] = round(amt_sum[code] / lot, 2)
    return out


def inject_main_force_cost(branches: List[Dict[str, Any]],
                            history: List[Dict[str, Any]],
                            daily_quotes_map: Optional[Dict[str, Dict[str, Any]]] = None
                            ) -> Dict[str, Any]:
    """注入 5d / 20d 主力成本線到 branches[].buys/sells 各 stock.

    Returns: {'computed': N, 'sample_5d_codes': [...]}
    """
    cost_5d = compute_main_force_cost_per_stock(history, 5)
    cost_20d = compute_main_force_cost_per_stock(history, 20)

    injected = 0
    seen_codes = set()
    for br in branches:
        for side in ('buys', 'sells'):
            for stock in (br.get(side) or []):
                code = str(stock.get('code') or '')
                if not code:
                    continue
                c5 = cost_5d.get(code)
                c20 = cost_20d.get(code)
                if c5 is None and c20 is None:
                    continue
                stock['main_force_cost_5d'] = c5
                stock['main_force_cost_20d'] = c20
                # premium pct (vs today close)
                today_close = (daily_quotes_map or {}).get(code, {}).get('close') if daily_quotes_map else None
                if today_close and c5 and c5 > 0:
                    stock['main_force_cost_premium_5d_pct'] = round(
                        (float(today_close) - c5) / c5 * 100, 2)
                if today_close and c20 and c20 > 0:
                    stock['main_force_cost_premium_20d_pct'] = round(
                        (float(today_close) - c20) / c20 * 100, 2)
                injected += 1
                seen_codes.add(code)
    return {
        'computed': injected,
        'unique_codes_5d': len(cost_5d),
        'unique_codes_20d': len(cost_20d),
        'sample_5d_codes': list(cost_5d.keys())[:5],
    }
