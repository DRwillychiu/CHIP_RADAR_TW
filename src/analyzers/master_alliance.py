"""
========================================================================
Module: master_alliance.py  (v3.31.19 Phase 2 聯動面)
功能: master × master 同向率矩陣 + 派系自動發現

算法:
  對每天: 每個 master 買了哪些 stock_code → set
  對每對 (master_a, master_b):
    co_buy_days   = 兩人同天買同股的天數
    co_buy_stocks = 兩人同天買同股的 unique 股票數
    alignment     = co_buy_days / min(active_days_a, active_days_b)

  派系: alignment > threshold 的 master 群歸同一派
========================================================================
"""
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, List, Optional, Set, Tuple

ALLIANCE_THRESHOLD = 0.30   # 同向率 > 30% = 同陣營
MIN_CO_DAYS = 5             # v3.31.23: 最少共買 5 天才算有效配對 (防 1 天新 master 污染派系)


def compute_alliance_matrix(history: List[Dict[str, Any]],
                              individual_masters: Dict[str, List[str]]
                              ) -> Dict[str, Any]:
    """計算 master × master 同向率矩陣.

    Args:
        history: master_profile.load_history 回傳的 [{date, data}, ...]
        individual_masters: get_individual_masters() 回傳的 {name: [styles]}

    Returns:
        {
            'matrix': {master_a: {master_b: {co_days, co_stocks, alignment, top_co_stocks}}},
            'factions': [['蔣承翰', 'Tradow', ...], ['民哥', '林滄海', ...]],
            'top_alliances': [{pair, alignment, co_stocks}, ...],
        }
    """
    master_names = sorted(individual_masters.keys())

    # Step 1: 對每天每 master 建「買了哪些股」set
    # {date: {master: set(stock_codes)}}
    daily_buys: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
    # 同時記每 master 有幾天活躍
    active_days: Dict[str, int] = defaultdict(int)

    for day in history:
        date = day['date']
        day_masters: Dict[str, Set[str]] = defaultdict(set)
        for br in day['data'].get('branches', []):
            master = br.get('master')
            co = br.get('co_masters') or []
            all_m = ([master] if master else []) + list(co)
            for m in all_m:
                if m not in individual_masters:
                    continue
                for s in (br.get('buys') or []):
                    code = s.get('code')
                    if code:
                        day_masters[m].add(code)
        for m, stocks in day_masters.items():
            if stocks:
                daily_buys[date][m] = stocks
                active_days[m] += 1

    # Step 2: 對每對 master 算同向率
    matrix: Dict[str, Dict[str, Dict[str, Any]]] = {}
    all_pairs: List[Dict[str, Any]] = []

    for i, ma in enumerate(master_names):
        matrix[ma] = {}
        for j, mb in enumerate(master_names):
            if i >= j:
                continue  # 只算上三角

            co_days = 0
            co_stocks_set: Set[str] = set()
            co_stock_count_by_code: Dict[str, int] = defaultdict(int)

            for date, day_m in daily_buys.items():
                sa = day_m.get(ma, set())
                sb = day_m.get(mb, set())
                if not sa or not sb:
                    continue
                overlap = sa & sb
                # v3.31.19: 用 Jaccard similarity (交集/聯集) 取代「有無交集」
                # 因為每 master 每天 40-90 stocks, 隨機 overlap 極高
                # Jaccard 消除「基數大 → 必然交集」的假相關
                jaccard = len(overlap) / len(sa | sb) if (sa | sb) else 0
                if jaccard > 0.30:   # Jaccard > 30% 才算「顯著同買」
                    co_days += 1
                    co_stocks_set |= overlap
                    for code in overlap:
                        co_stock_count_by_code[code] += 1

            min_active = min(active_days.get(ma, 1), active_days.get(mb, 1))
            alignment = round(co_days / max(min_active, 1), 3)

            # Top 5 共買股
            top_co = sorted(co_stock_count_by_code.items(), key=lambda x: -x[1])[:5]

            pair_data = {
                'co_days': co_days,
                'co_stocks': len(co_stocks_set),
                'alignment': alignment,
                'top_co_stocks': [{'code': c, 'days': d} for c, d in top_co],
            }
            matrix[ma][mb] = pair_data
            # 對稱填
            if mb not in matrix:
                matrix[mb] = {}
            matrix[mb][ma] = pair_data

            if alignment > 0 and co_days >= MIN_CO_DAYS:
                all_pairs.append({
                    'pair': [ma, mb],
                    'alignment': alignment,
                    'co_days': co_days,
                    'co_stocks': len(co_stocks_set),
                })

    # Step 3: Top alliances (排序)
    top_alliances = sorted(all_pairs, key=lambda x: -x['alignment'])[:20]

    # Step 4: 派系發現 (simple union-find on alignment > threshold)
    factions = _discover_factions(master_names, matrix, ALLIANCE_THRESHOLD)

    return {
        'matrix': matrix,
        'factions': factions,
        'top_alliances': top_alliances,
        'threshold': ALLIANCE_THRESHOLD,
        'window_days': len(history),
    }


def _discover_factions(names: List[str],
                        matrix: Dict[str, Dict[str, Dict]],
                        threshold: float) -> List[List[str]]:
    """Simple union-find 派系發現."""
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a in names:
        for b, data in matrix.get(a, {}).items():
            if data['alignment'] >= threshold and data.get('co_days', 0) >= MIN_CO_DAYS:
                union(a, b)

    groups: Dict[str, List[str]] = defaultdict(list)
    for n in names:
        groups[find(n)].append(n)

    # 只回傳 >1 人的派系, 按大小 desc
    factions = [sorted(g) for g in groups.values() if len(g) > 1]
    factions.sort(key=lambda x: -len(x))
    return factions


def format_alliance_summary(alliance_data: Dict[str, Any]) -> str:
    """印終端 summary."""
    lines = []
    lines.append(f"=== 聯動面 (同向率 > {alliance_data['threshold']*100:.0f}% = 同陣營) ===")
    lines.append(f"  窗口 {alliance_data['window_days']} 天")
    lines.append("")

    # Top 10 alliances
    lines.append("Top 10 同向配對:")
    for i, a in enumerate(alliance_data['top_alliances'][:10], 1):
        lines.append(f"  {i:2d}. {a['pair'][0]} × {a['pair'][1]}: "
                      f"{a['alignment']*100:.0f}% ({a['co_days']}天/{a['co_stocks']}股)")
    lines.append("")

    # Factions
    if alliance_data['factions']:
        lines.append(f"自動發現 {len(alliance_data['factions'])} 個派系:")
        for i, faction in enumerate(alliance_data['factions'], 1):
            lines.append(f"  派系 {i} ({len(faction)} 人): {' / '.join(faction)}")
    else:
        lines.append("  未發現明顯派系 (可能閾值太高)")

    return '\n'.join(lines)
