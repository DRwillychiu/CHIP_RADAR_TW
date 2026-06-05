"""
========================================================================
Module: master_performance.py  (v3.31.20 Phase 2 績效面)
功能: 跟著 master 買的「隔日報酬率 / 勝率 / 累積績效」

核心問題: 「跟蔣承翰買會賺嗎? 跟民哥買呢?」

算法:
  對每個 master 的每筆 buy trade:
    1. 找該股 trade_date 的 close (買入日收盤)
    2. 找該股 trade_date+1 的 close (次日收盤)
    3. next_day_return = (close_t1 - close_t0) / close_t0
    4. 加權: buy_amt 越大權重越高 (大資金 master 的大單更有意義)

  彙總 metrics:
    - win_rate:      次日報酬 > 0 的筆數 / 總筆數
    - avg_return:    平均次日報酬 (等權)
    - weighted_avg:  buy_amt 加權平均次日報酬
    - best/worst:    最佳/最差單筆
    - total_trades:  可算的筆數

限制:
  - stock_history 只有 close 沒有 intraday → 用收盤算
  - 隔日沖 master 可能不是真的隔日賣 → 只是「如果你跟買次日賣」的假設報酬
  - 波段 master 次日報酬不代表波段報酬

CLI:
  CHIP_RADAR_PASSWORD=<pwd> python master_performance.py
  python master_performance.py --master 蔣承翰
========================================================================
"""
import os
import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))


def _build_close_map(data_dir: str) -> Dict[str, Dict[str, float]]:
    """從 stock_history.json 建 {code: {date: close}} lookup."""
    sh_path = Path(data_dir) / 'stock_history.json'
    if not sh_path.exists():
        return {}
    with open(sh_path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    close_map = {}
    for code, info in d.get('stocks', {}).items():
        daily = info.get('daily', {})
        if daily:
            close_map[code] = {dt: entry['close'] for dt, entry in daily.items()
                                if isinstance(entry, dict) and 'close' in entry}
    return close_map


def _get_next_trading_day(date: str, all_dates: List[str]) -> Optional[str]:
    """找 date 的下一個交易日."""
    try:
        idx = all_dates.index(date)
        if idx + 1 < len(all_dates):
            return all_dates[idx + 1]
    except ValueError:
        # date 不在 all_dates 裡 → 找第一個 > date
        for d in all_dates:
            if d > date:
                return d
    return None


def compute_performance(history: List[Dict[str, Any]],
                         master_name: str,
                         close_map: Dict[str, Dict[str, float]],
                         all_dates: List[str],
                         individual_masters: Dict[str, List[str]]
                         ) -> Optional[Dict[str, Any]]:
    """算單一 master 的績效 metrics."""
    from master_profile import extract_master_trades

    trades = extract_master_trades(history, master_name)
    if not trades:
        return None

    results = []
    for t in trades:
        code = t.get('stock_code')
        date = t.get('date')
        buy_amt = t.get('buy_amt', 0) or 0
        is_lu = t.get('is_limit_up', False)

        if not code or not date or code not in close_map:
            continue

        stock_close = close_map[code]
        close_t0 = stock_close.get(date)
        next_day = _get_next_trading_day(date, all_dates)
        close_t1 = stock_close.get(next_day) if next_day else None

        if close_t0 is None or close_t1 is None or close_t0 <= 0:
            continue

        ret = (close_t1 - close_t0) / close_t0
        results.append({
            'code': code,
            'date': date,
            'close_t0': close_t0,
            'close_t1': close_t1,
            'return': ret,
            'buy_amt': buy_amt,
            'is_limit_up': is_lu,
        })

    if not results:
        return None

    returns = [r['return'] for r in results]
    wins = sum(1 for r in returns if r > 0)
    total = len(returns)
    total_amt = sum(r['buy_amt'] for r in results) or 1
    weighted_returns = sum(r['return'] * r['buy_amt'] / total_amt for r in results)

    # 漲停股 subset
    lu_results = [r for r in results if r['is_limit_up']]
    lu_returns = [r['return'] for r in lu_results]
    lu_wins = sum(1 for r in lu_returns if r > 0) if lu_returns else 0

    # Top 5 best / worst
    sorted_by_ret = sorted(results, key=lambda x: x['return'])
    best5 = sorted_by_ret[-5:][::-1]
    worst5 = sorted_by_ret[:5]

    return {
        'total_trades': total,
        'win_rate': round(wins / total, 3),
        'avg_return_pct': round(sum(returns) / total * 100, 3),
        'weighted_avg_return_pct': round(weighted_returns * 100, 3),
        'median_return_pct': round(sorted(returns)[total // 2] * 100, 3),
        'max_return_pct': round(max(returns) * 100, 2),
        'min_return_pct': round(min(returns) * 100, 2),
        # 漲停股特化
        'limit_up_trades': len(lu_results),
        'limit_up_win_rate': round(lu_wins / len(lu_results), 3) if lu_results else None,
        'limit_up_avg_return_pct': round(sum(lu_returns) / len(lu_returns) * 100, 3) if lu_returns else None,
        # Top trades
        'best5': [{'code': r['code'], 'date': r['date'], 'return_pct': round(r['return'] * 100, 2)}
                   for r in best5],
        'worst5': [{'code': r['code'], 'date': r['date'], 'return_pct': round(r['return'] * 100, 2)}
                    for r in worst5],
    }


def compute_all_performance(history: List[Dict[str, Any]],
                              data_dir: str = 'data') -> Dict[str, Dict[str, Any]]:
    """算所有個人大戶的績效."""
    from master_profile import get_individual_masters

    close_map = _build_close_map(data_dir)
    if not close_map:
        print("  ⚠️ stock_history.json 無資料")
        return {}

    # 所有交易日 (sorted)
    all_dates = set()
    for code_data in close_map.values():
        all_dates |= set(code_data.keys())
    all_dates = sorted(all_dates)

    indiv = get_individual_masters()
    results = {}
    for master in sorted(indiv.keys()):
        perf = compute_performance(history, master, close_map, all_dates, indiv)
        if perf:
            results[master] = perf

    return results


def format_performance_table(perf_data: Dict[str, Dict[str, Any]]) -> str:
    """格式化終端 summary."""
    lines = []
    lines.append(f"\n{'Master':25s} {'筆數':>5s} {'勝率':>6s} {'均報酬':>7s} {'加權報酬':>8s} "
                  f"{'漲停勝率':>8s} {'漲停報酬':>8s} {'最佳':>6s} {'最差':>6s}")
    lines.append("─" * 110)

    # 按加權報酬 desc 排序
    sorted_masters = sorted(perf_data.items(), key=lambda x: x[1].get('weighted_avg_return_pct', 0), reverse=True)

    for master, p in sorted_masters:
        lu_wr = f"{p['limit_up_win_rate']*100:.0f}%" if p.get('limit_up_win_rate') is not None else '-'
        lu_ar = f"{p['limit_up_avg_return_pct']:.2f}%" if p.get('limit_up_avg_return_pct') is not None else '-'
        lines.append(
            f"{master:25s} {p['total_trades']:>5d} {p['win_rate']*100:>5.1f}% {p['avg_return_pct']:>6.2f}% "
            f"{p['weighted_avg_return_pct']:>7.2f}% {lu_wr:>8s} {lu_ar:>8s} "
            f"{p['max_return_pct']:>5.1f}% {p['min_return_pct']:>5.1f}%"
        )

    return '\n'.join(lines)


# ════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Phase 2 績效面: master 跟單報酬')
    parser.add_argument('--master', default=None, help='只算單一 master')
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()

    password = os.environ.get('CHIP_RADAR_PASSWORD', '')
    if not password:
        print("❌ 需要 CHIP_RADAR_PASSWORD")
        sys.exit(1)

    from master_profile import load_history
    history = load_history(args.data_dir, None, password)
    print(f"[Performance] 載入 {len(history)} 天歷史")

    if args.master:
        from master_profile import get_individual_masters
        close_map = _build_close_map(args.data_dir)
        all_dates = sorted({d for cm in close_map.values() for d in cm})
        perf = compute_performance(history, args.master, close_map, all_dates, get_individual_masters())
        if perf:
            print(json.dumps(perf, ensure_ascii=False, indent=2))
        else:
            print(f"❌ {args.master} 無績效資料")
    else:
        perf_data = compute_all_performance(history, args.data_dir)
        print(format_performance_table(perf_data))


if __name__ == '__main__':
    main()
