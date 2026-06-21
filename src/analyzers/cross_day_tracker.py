"""
========================================================================
Module: cross_day_tracker.py  (v3.31.22)
功能: T+1 跨日追蹤 — 用真實 sells 驗證「真正隔日沖」vs「真正波段持有」

核心問題: trade_style (daytrade/partial/overnight) 只看「同天 buy/sell 比例」,
         看不到跨日行為。T+1 追蹤用連續兩天的 raw data 直接驗:
         T 日買 stock A → T+1 有賣 stock A = 確認隔日沖
         T 日買 stock A → T+1 沒賣 = 確認留倉 (波段/長線)

新 metrics (per master):
  actual_flip_ratio:    confirmed flips / total buys (真隔日沖比例)
  actual_hold_ratio:    confirmed holds / total buys (真留倉比例)
  flip_unknown_ratio:   T+1 資料不存在 (窗口邊界) / total buys

新 labels 升級:
  短打型(declared) → 可升級為「隔日沖(verified)」if actual_flip_ratio > 0.3
  波段囤貨 → 更有信心 if actual_hold_ratio > 0.6
========================================================================
"""
from collections import defaultdict
from typing import Dict, Any, List, Optional, Set, Tuple


def compute_cross_day_metrics(history: List[Dict[str, Any]],
                                master_name: str,
                                individual_masters: Dict[str, List[str]]
                                ) -> Optional[Dict[str, Any]]:
    """對單一 master 做 T+1 跨日追蹤.

    掃 history: 對每天 T, 每個 master 買的 stock set 跟 T+1 的 sell set 比對.

    Returns:
        {
            'total_buy_events': int,      # T 日買的(stock × branch)組合數
            'confirmed_flips': int,       # T+1 同分點有賣 = 真隔日沖
            'confirmed_holds': int,       # T+1 同分點沒賣 = 真留倉
            'unknown': int,               # T+1 資料不存在
            'actual_flip_ratio': float,   # flips / (flips + holds)
            'actual_hold_ratio': float,
            'top_flip_stocks': list,      # 被隔日沖最多的 Top 5 stock
            'top_hold_stocks': list,      # 被留倉最多的 Top 5 stock
        }
    """
    # Step 1: 對每天建 {master: {branch: set(buy_codes)}} 和 {master: {branch: set(sell_codes)}}
    # day_buys[date][(branch_code)] = set(stock_codes bought)
    # day_sells[date][(branch_code)] = set(stock_codes sold)
    day_buys: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
    day_sells: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))

    for day in history:
        date = day['date']
        for br in day['data'].get('branches', []):
            master = br.get('master')
            co = br.get('co_masters') or []
            if master != master_name and master_name not in co:
                continue
            bcode = br.get('code')
            if not bcode:
                continue

            for s in (br.get('buys') or []):
                code = s.get('code')
                if code and (s.get('buy_lot', 0) or 0) > 0:
                    day_buys[date][bcode].add(code)

            for s in (br.get('sells') or []):
                code = s.get('code')
                if code and (s.get('sell_lot', 0) or 0) > 0:
                    day_sells[date][bcode].add(code)

    # Step 2: 對每個 (T, branch, stock) buy event, 查 T+1 有沒有 sell
    dates = sorted(day_buys.keys())
    date_to_next = {}
    for i, d in enumerate(dates):
        # 找 history 裡的下一天 (不一定是 d+1, 可能跨週末)
        next_dates = [dd for dd in sorted(day_sells.keys()) if dd > d]
        if next_dates:
            # 只看最近的下一天 (≤ 3 天, 跨週末)
            candidate = next_dates[0]
            diff = int(candidate) - int(d)
            if diff <= 4:  # 週五→週一 = 3 天
                date_to_next[d] = candidate

    total_buy_events = 0
    confirmed_flips = 0
    confirmed_holds = 0
    unknown = 0
    flip_stock_count: Dict[str, int] = defaultdict(int)
    hold_stock_count: Dict[str, int] = defaultdict(int)

    for date, branch_buys in day_buys.items():
        next_date = date_to_next.get(date)
        for bcode, buy_codes in branch_buys.items():
            for stock in buy_codes:
                total_buy_events += 1
                if next_date is None:
                    unknown += 1
                    continue

                # 查 T+1 同分點是否有賣這檔
                # 注意: sells 可能在任何分點 (not just same branch)
                # 但最精確是同分點查
                next_sells_same = day_sells.get(next_date, {}).get(bcode, set())
                # 也查所有分點 (跨分點賣)
                next_sells_all = set()
                for bc, sc in day_sells.get(next_date, {}).items():
                    next_sells_all |= sc

                if stock in next_sells_same:
                    confirmed_flips += 1
                    flip_stock_count[stock] += 1
                elif stock in next_sells_all:
                    # 跨分點賣 = 也算 flip (但信心稍低)
                    confirmed_flips += 1
                    flip_stock_count[stock] += 1
                else:
                    confirmed_holds += 1
                    hold_stock_count[stock] += 1

    if total_buy_events == 0:
        return None

    verifiable = confirmed_flips + confirmed_holds
    flip_ratio = round(confirmed_flips / verifiable, 3) if verifiable else 0
    hold_ratio = round(confirmed_holds / verifiable, 3) if verifiable else 0

    top_flips = sorted(flip_stock_count.items(), key=lambda x: -x[1])[:5]
    top_holds = sorted(hold_stock_count.items(), key=lambda x: -x[1])[:5]

    return {
        'total_buy_events': total_buy_events,
        'confirmed_flips': confirmed_flips,
        'confirmed_holds': confirmed_holds,
        'unknown': unknown,
        'actual_flip_ratio': flip_ratio,
        'actual_hold_ratio': hold_ratio,
        'top_flip_stocks': [{'code': c, 'count': n} for c, n in top_flips],
        'top_hold_stocks': [{'code': c, 'count': n} for c, n in top_holds],
    }


def compute_all_cross_day(history: List[Dict[str, Any]],
                            individual_masters: Dict[str, List[str]]
                            ) -> Dict[str, Dict[str, Any]]:
    """全 master 算 T+1 跨日追蹤."""
    results = {}
    for master in sorted(individual_masters.keys()):
        metrics = compute_cross_day_metrics(history, master, individual_masters)
        if metrics:
            results[master] = metrics
    return results


def format_cross_day_table(data: Dict[str, Dict[str, Any]]) -> str:
    """終端 summary."""
    lines = [f"\n{'Master':25s} {'買入事件':>7s} {'隔日沖':>6s} {'留倉':>5s} {'未知':>4s} "
             f"{'真隔日沖%':>8s} {'真留倉%':>7s}"]
    lines.append("─" * 80)

    sorted_m = sorted(data.items(), key=lambda x: -x[1].get('actual_flip_ratio', 0))
    for m, d in sorted_m:
        lines.append(
            f"{m:25s} {d['total_buy_events']:>7d} {d['confirmed_flips']:>6d} "
            f"{d['confirmed_holds']:>5d} {d['unknown']:>4d} "
            f"{d['actual_flip_ratio']*100:>7.1f}% {d['actual_hold_ratio']*100:>6.1f}%"
        )
    return '\n'.join(lines)
