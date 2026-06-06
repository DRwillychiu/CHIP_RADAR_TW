"""
========================================================================
Module: daily_signals.py  (v3.32.0 實戰模式)
功能: 每日實戰信號 — 回答交易者 21:30 打開系統的 3 個核心問題

Q1 異常行為偵測: 「今天誰在大動作?」
  - 某 master 今天買進金額 vs 他過去 N 天平均 → 偏離 > 2σ = 異常
  - 某 master 今天買了他「從沒買過」的新股 = 新標的進場

Q2 派系共識信號: 「買的股票有沒有派系共識?」
  - 同一派系 2+ 人同天買同股 = 共識信號
  - 共識強度 = 幾個派系成員買 × 總金額

Q3 連續加碼追蹤: 「誰在連續加碼某檔?」
  - 某 master 連續 N 天買同股 (≥ 3 天) = 連續加碼
  - 連續天數越長 = 信念越強

Output:
  data/daily_trading_signals.json (每天覆寫)
  {
    'date': '20260605',
    'anomalies': [...],       # Q1
    'consensus': [...],       # Q2
    'accumulations': [...],   # Q3
    'summary': '...'
  }
========================================================================
"""
import json
import statistics
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))

ANOMALY_SIGMA = 2.0        # 買進金額偏離 > 2σ = 異常
MIN_HISTORY_DAYS = 5       # 至少 5 天歷史才算偏離
ACCUMULATION_MIN_DAYS = 3  # 連續加碼 ≥ 3 天


def compute_daily_signals(history: List[Dict[str, Any]],
                            individual_masters: Dict[str, List[str]],
                            factions: Optional[List[List[str]]] = None
                            ) -> Dict[str, Any]:
    """計算當日(history 最後一天)的 3 個實戰信號."""

    if len(history) < 2:
        return {'error': 'need at least 2 days history'}

    today = history[-1]
    today_date = today['date']
    past = history[:-1]

    signals = {
        'date': today_date,
        'generated_at': datetime.now(TW_TZ).isoformat(),
        'anomalies': [],
        'consensus': [],
        'accumulations': [],
    }

    # ── 預處理: 每天每 master 的交易統計 ──
    # {master: {date: {total_buy_amt, stocks: set(codes), stock_details: {code: amt}}}}
    daily_stats: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(
        lambda: {'total_buy_amt': 0, 'stocks': set(), 'stock_details': defaultdict(int)}
    ))

    for day in history:
        d = day['date']
        for br in day['data'].get('branches', []):
            master = br.get('master')
            co = br.get('co_masters') or []
            all_m = ([master] if master else []) + list(co)
            for m in all_m:
                if m not in individual_masters:
                    continue
                for s in (br.get('buys') or []):
                    code = s.get('code')
                    amt = s.get('buy_amt', 0) or 0
                    if code and amt > 0:
                        stats = daily_stats[m][d]
                        stats['total_buy_amt'] += amt
                        stats['stocks'].add(code)
                        stats['stock_details'][code] += amt

    # ══════════════════════════════════════════
    # Q1: 異常行為偵測
    # ══════════════════════════════════════════
    for master in sorted(individual_masters.keys()):
        past_amts = [daily_stats[master][d]['total_buy_amt']
                      for d in [day['date'] for day in past]
                      if daily_stats[master][d]['total_buy_amt'] > 0]
        today_amt = daily_stats[master][today_date]['total_buy_amt']
        today_stocks = daily_stats[master][today_date]['stocks']

        if len(past_amts) < MIN_HISTORY_DAYS or today_amt == 0:
            continue

        avg = statistics.mean(past_amts)
        std = statistics.stdev(past_amts) if len(past_amts) > 1 else avg * 0.3
        if std == 0:
            std = avg * 0.1

        z_score = (today_amt - avg) / std
        if z_score > ANOMALY_SIGMA:
            signals['anomalies'].append({
                'master': master,
                'type': 'volume_spike',
                'today_buy_amt_wan': round(today_amt / 10),
                'avg_buy_amt_wan': round(avg / 10),
                'z_score': round(z_score, 2),
                'description': f'{master} 今日買進 {today_amt/10:,.0f} 萬 '
                               f'(平均 {avg/10:,.0f} 萬, 偏離 {z_score:.1f}σ)',
            })

        # 新標的進場
        past_all_stocks: Set[str] = set()
        for d in [day['date'] for day in past]:
            past_all_stocks |= daily_stats[master][d]['stocks']
        new_stocks = today_stocks - past_all_stocks
        if len(new_stocks) >= 3:
            top_new = sorted(
                [(c, daily_stats[master][today_date]['stock_details'][c]) for c in new_stocks],
                key=lambda x: -x[1]
            )[:5]
            signals['anomalies'].append({
                'master': master,
                'type': 'new_stocks',
                'count': len(new_stocks),
                'top_new': [{'code': c, 'buy_amt_wan': round(a / 10)} for c, a in top_new],
                'description': f'{master} 今日買進 {len(new_stocks)} 檔新標的 '
                               f'(過去從沒買過)',
            })

    signals['anomalies'].sort(key=lambda x: x.get('z_score', 0), reverse=True)

    # ══════════════════════════════════════════
    # Q2: 派系共識信號
    # ══════════════════════════════════════════
    if factions:
        for fi, faction in enumerate(factions):
            # 每個成員今天買了哪些股
            faction_buys: Dict[str, List[str]] = {}  # {code: [masters who bought]}
            for m in faction:
                for code in daily_stats[m][today_date]['stocks']:
                    if code not in faction_buys:
                        faction_buys[code] = []
                    faction_buys[code].append(m)

            # 2+ 人共買 = 共識
            for code, buyers in faction_buys.items():
                if len(buyers) >= 2:
                    total_amt = sum(daily_stats[b][today_date]['stock_details'].get(code, 0)
                                    for b in buyers)
                    signals['consensus'].append({
                        'faction_id': fi + 1,
                        'faction_members': faction,
                        'stock_code': code,
                        'buyers': buyers,
                        'buyer_count': len(buyers),
                        'total_buy_amt_wan': round(total_amt / 10),
                        'description': f'派系{fi+1} 共識: {"/".join(buyers)} '
                                       f'同買 {code} (合計 {total_amt/10:,.0f} 萬)',
                    })

        signals['consensus'].sort(key=lambda x: (-x['buyer_count'], -x['total_buy_amt_wan']))
    signals['consensus'] = signals['consensus'][:15]   # Top 15 (過多=雜訊)

    # ══════════════════════════════════════════
    # Q3: 連續加碼追蹤
    # ══════════════════════════════════════════
    dates = [d['date'] for d in history]
    for master in sorted(individual_masters.keys()):
        today_stocks = daily_stats[master][today_date]['stocks']
        for code in today_stocks:
            # 往回看連續幾天有買
            streak = 1
            for i in range(len(dates) - 2, -1, -1):
                if code in daily_stats[master][dates[i]]['stocks']:
                    streak += 1
                else:
                    break
            if streak >= ACCUMULATION_MIN_DAYS:
                total_amt = sum(daily_stats[master][dates[d_i]]['stock_details'].get(code, 0)
                                 for d_i in range(len(dates) - streak, len(dates)))
                signals['accumulations'].append({
                    'master': master,
                    'stock_code': code,
                    'consecutive_days': streak,
                    'total_buy_amt_wan': round(total_amt / 10),
                    'description': f'{master} 連續 {streak} 天加碼 {code} '
                                   f'(累計 {total_amt/10:,.0f} 萬)',
                })

    signals['accumulations'].sort(key=lambda x: (-x['consecutive_days'], -x['total_buy_amt_wan']))
    signals['accumulations'] = signals['accumulations'][:15]   # Top 15

    # Summary
    a_count = len(signals['anomalies'])
    c_count = len(signals['consensus'])
    acc_count = len(signals['accumulations'])
    signals['summary'] = (f'{today_date} 實戰信號: '
                           f'{a_count} 異常行為 / {c_count} 派系共識 / {acc_count} 連續加碼')

    return signals


def format_daily_signals(signals: Dict[str, Any]) -> str:
    """終端格式化."""
    lines = [f"\n{'='*70}", f"  📡 {signals.get('summary', '')}", f"{'='*70}"]

    if signals.get('anomalies'):
        lines.append("\n🚨 異常行為:")
        for a in signals['anomalies'][:10]:
            lines.append(f"  • {a['description']}")

    if signals.get('consensus'):
        lines.append("\n🤝 派系共識:")
        for c in signals['consensus'][:10]:
            lines.append(f"  • {c['description']}")

    if signals.get('accumulations'):
        lines.append("\n📈 連續加碼:")
        for a in signals['accumulations'][:10]:
            lines.append(f"  • {a['description']}")

    if not any([signals.get('anomalies'), signals.get('consensus'), signals.get('accumulations')]):
        lines.append("\n  (今日無特殊信號)")

    return '\n'.join(lines)
