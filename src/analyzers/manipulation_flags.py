"""
========================================================================
Module: manipulation_flags.py  (v3.40.0 B6 機構級 P0)

操縱 / 對敲 / 出貨偵測 — 從「看盤」進化到「監控」

3 條規則 (從機構合規視角):

A. 拉抬嫌疑 (same-branch pump):
   單分點當沖比 > 70% AND 該股當日漲停 (is_limit_up=True) AND
   買金額 ≥ 中位數 × 3
   → 該分點可能在「拉抬」此股

B. 對敲 / Wash trade (cross-branch wash):
   同一股當日在 2+ 分點分別出現 (一買一賣) AND
   買賣量級匹配 (買 lot × 0.7 ≤ 賣 lot ≤ 買 lot × 1.3)
   → 同人多帳戶互沖嫌疑 (依分點隸屬同 master / co_master 加權)

C. 主力出貨 (distribution at high):
   分點當日 sell_lot ≥ 5x avg 30 天 sell_lot AND
   該股近 5 天有 ≥ 2 次漲停 AND
   此 master 該股 30 天累積為 net_seller (sell > buy)
   → 主力在「高點出貨」

⚠️ 法律免責 (機構合規):
  - 本模組僅標 *嫌疑 flag*, 非定罪
  - 結果不代表實際違法行為 (合法策略也可能觸發)
  - 任何後續行動 (檢舉 / 投資決策) 為用戶自負

輸出:
  data/red_flags.json:
  {
    'generated_at': ISO,
    'trade_date': YYYYMMDD,
    'pump_suspicion': [{stock_code, branch_code, master, ...}],
    'wash_trade': [{stock_code, branches: [(code, buy/sell, lot, amt)], ...}],
    'distribution': [{stock_code, branch_code, master, ...}],
    'summary': {pump_count, wash_count, distribution_count, total},
  }
========================================================================
"""
import json
import statistics
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple

TW_TZ = timezone(timedelta(hours=8))

# 閾值 (集中可調, 與 algo_params.yaml 對齊)
THRESH = {
    'pump_daytrade_ratio': 0.70,        # 規則 A: 當沖比
    'pump_amt_median_x': 3.0,            # 規則 A: 買金額 ≥ 中位數 × 3
    'wash_lot_match_lo': 0.7,            # 規則 B: 買賣量級匹配下界
    'wash_lot_match_hi': 1.3,            # 規則 B: 買賣量級匹配上界
    'distribution_sell_x': 5.0,          # 規則 C: 當日 sell ≥ 30天均 × 5
    'distribution_lookback_days': 30,
    'distribution_recent_lu_days': 5,
    'distribution_recent_lu_min': 2,
    'min_lots': 50,                       # 規則 A/C: 至少 50 張才視為「大額」
}


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


def _stock_amt_median(branches: List[Dict[str, Any]], stock_code: str,
                       side: str = 'buys') -> float:
    """全市場該股 (該日, 該邊) 金額中位數 — 給規則 A 用."""
    amts = []
    for br in branches:
        for s in (br.get(side) or []):
            if str(s.get('code') or '') == stock_code:
                amt = s.get('buy_amt' if side == 'buys' else 'sell_amt', 0) or 0
                if amt > 0:
                    amts.append(amt)
    return statistics.median(amts) if amts else 0


def detect_pump_suspicion(branches: List[Dict[str, Any]]
                            ) -> List[Dict[str, Any]]:
    """規則 A: 拉抬嫌疑."""
    flags = []
    # 預先算每股的買金額中位數 cache
    stock_amt_median_cache: Dict[str, float] = {}
    for br in branches:
        for s in (br.get('buys') or []):
            code = str(s.get('code') or '')
            if not code or not s.get('is_limit_up'):
                continue
            buy_lot = s.get('buy_lot', 0) or 0
            sell_lot = s.get('sell_lot', 0) or 0
            buy_amt = s.get('buy_amt', 0) or 0
            if buy_lot < THRESH['min_lots']:
                continue
            max_lot = max(buy_lot, sell_lot)
            min_lot = min(buy_lot, sell_lot)
            if max_lot == 0:
                continue
            daytrade_ratio = min_lot / max_lot
            if daytrade_ratio < THRESH['pump_daytrade_ratio']:
                continue
            # 中位數 cache
            if code not in stock_amt_median_cache:
                stock_amt_median_cache[code] = _stock_amt_median(branches, code, 'buys')
            median_amt = stock_amt_median_cache[code]
            if median_amt > 0 and buy_amt < median_amt * THRESH['pump_amt_median_x']:
                continue
            flags.append({
                'stock_code': code,
                'stock_name': s.get('name', ''),
                'branch_code': br.get('code'),
                'branch_name': br.get('name', ''),
                'master': br.get('master', ''),
                'buy_lot': buy_lot,
                'sell_lot': sell_lot,
                'buy_amt_wan': round(buy_amt / 10),
                'daytrade_ratio': round(daytrade_ratio, 2),
                'amt_vs_median_x': round(buy_amt / median_amt, 1) if median_amt > 0 else None,
                'rule': 'A_pump',
                'severity': 'high' if daytrade_ratio > 0.85 else 'medium',
                'reasoning': (
                    f"當沖比 {daytrade_ratio*100:.0f}% (> 70%) + 漲停 + "
                    f"買金額 {round(buy_amt/10):,} 萬 (中位數 {round(median_amt/10):,} 萬 × {(buy_amt/median_amt):.1f})"
                ),
            })
    return flags


def detect_wash_trade(branches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """規則 B: 對敲 / Wash trade — 同股 A 買 B 賣 量級匹配."""
    # 收集每股的 (branch, side, lot, amt)
    by_stock: Dict[str, List[Tuple[str, str, int, int, str, str]]] = defaultdict(list)
    for br in branches:
        for side, key in [('buys', 'buy'), ('sells', 'sell')]:
            for s in (br.get(side) or []):
                code = str(s.get('code') or '')
                if not code:
                    continue
                lot = s.get(f'{key}_lot', 0) or 0
                amt = s.get(f'{key}_amt', 0) or 0
                # 對敲偵測需大額 (避免噪音)
                if lot < THRESH['min_lots']:
                    continue
                by_stock[code].append((
                    br.get('code', ''), key, lot, amt,
                    br.get('master', ''), s.get('name', ''),
                ))

    flags = []
    for code, items in by_stock.items():
        buys = [x for x in items if x[1] == 'buy']
        sells = [x for x in items if x[1] == 'sell']
        if not buys or not sells:
            continue
        for buy in buys:
            for sell in sells:
                if buy[0] == sell[0]:
                    continue   # 同分點不算 wash
                buy_lot, sell_lot = buy[2], sell[2]
                if buy_lot == 0 or sell_lot == 0:
                    continue
                # 量級匹配檢查
                ratio = min(buy_lot, sell_lot) / max(buy_lot, sell_lot)
                if ratio < THRESH['wash_lot_match_lo']:
                    continue
                # 同 master / co_master 加權 (機構視角的「同人多戶」)
                same_master = buy[4] and sell[4] and buy[4] == sell[4]
                flags.append({
                    'stock_code': code,
                    'stock_name': buy[5] or sell[5],
                    'buy_branch_code': buy[0],
                    'buy_master': buy[4],
                    'sell_branch_code': sell[0],
                    'sell_master': sell[4],
                    'buy_lot': buy_lot,
                    'sell_lot': sell_lot,
                    'buy_amt_wan': round(buy[3] / 10),
                    'sell_amt_wan': round(sell[3] / 10),
                    'lot_match_ratio': round(ratio, 2),
                    'same_master': same_master,
                    'rule': 'B_wash',
                    'severity': 'high' if same_master else 'medium',
                    'reasoning': (
                        f"{buy[0]} 買 {buy_lot} 張 vs {sell[0]} 賣 {sell_lot} 張 "
                        f"(匹配 {ratio:.0%})"
                        + (f" 且同 master '{buy[4]}'" if same_master else "")
                    ),
                })
    # 去重 (同股可能多對, cap)
    return flags[:30]


def detect_distribution(branches: List[Dict[str, Any]],
                         history: Optional[List[Dict[str, Any]]] = None
                         ) -> List[Dict[str, Any]]:
    """規則 C: 主力出貨 — 當日 sell 異常 + 該股近期多次漲停."""
    if not history:
        return []   # 沒歷史無從比較
    # 建索引: 每 (branch, code) 的 30 天 sell_lot 紀錄
    history_30 = history[-THRESH['distribution_lookback_days']:]
    sell_history: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    stock_limit_up_days: Dict[str, int] = defaultdict(int)
    recent_days = history[-THRESH['distribution_recent_lu_days']:]
    for day in recent_days:
        for br in day.get('data', {}).get('branches', []):
            for s in (br.get('buys') or []) + (br.get('sells') or []):
                if s.get('is_limit_up'):
                    code = str(s.get('code') or '')
                    if code:
                        stock_limit_up_days[code] += 1
    for day in history_30:
        for br in day.get('data', {}).get('branches', []):
            code_to_sell: Dict[str, int] = {}
            for s in (br.get('sells') or []):
                code = str(s.get('code') or '')
                if code:
                    code_to_sell[code] = (s.get('sell_lot', 0) or 0)
            for code, sl in code_to_sell.items():
                sell_history[(br.get('code', ''), code)].append(sl)

    flags = []
    for br in branches:
        for s in (br.get('sells') or []):
            code = str(s.get('code') or '')
            if not code:
                continue
            sell_lot = s.get('sell_lot', 0) or 0
            if sell_lot < THRESH['min_lots']:
                continue
            # 近期漲停天數
            recent_lu = stock_limit_up_days.get(code, 0)
            if recent_lu < THRESH['distribution_recent_lu_min']:
                continue
            # 30 天均 sell_lot
            past = sell_history.get((br.get('code', ''), code), [])
            if not past:
                continue
            avg_sell = sum(past) / len(past)
            if avg_sell == 0:
                continue
            if sell_lot < avg_sell * THRESH['distribution_sell_x']:
                continue
            flags.append({
                'stock_code': code,
                'stock_name': s.get('name', ''),
                'branch_code': br.get('code'),
                'branch_name': br.get('name', ''),
                'master': br.get('master', ''),
                'sell_lot': sell_lot,
                'sell_amt_wan': round((s.get('sell_amt', 0) or 0) / 10),
                'avg_30d_sell_lot': round(avg_sell, 1),
                'sell_vs_avg_x': round(sell_lot / avg_sell, 1),
                'recent_5d_limit_up_count': recent_lu,
                'rule': 'C_distribution',
                'severity': 'high' if sell_lot > avg_sell * 10 else 'medium',
                'reasoning': (
                    f"當日賣 {sell_lot:,} 張 (30 天均 {avg_sell:.0f} 張 × {sell_lot/avg_sell:.1f}) + "
                    f"近 5 天漲停 {recent_lu} 次"
                ),
            })
    return flags


def compute_all_flags(branches: List[Dict[str, Any]],
                       trade_date: str,
                       history: Optional[List[Dict[str, Any]]] = None,
                       data_dir: str = 'data') -> Dict[str, Any]:
    """主入口: 算 3 條規則 → 回傳 + 寫 red_flags.json."""
    pump = detect_pump_suspicion(branches)
    wash = detect_wash_trade(branches)
    distribution = detect_distribution(branches, history)

    result = {
        'generated_at': now_tw().isoformat(),
        'trade_date': trade_date,
        'pump_suspicion': pump,
        'wash_trade': wash,
        'distribution': distribution,
        'summary': {
            'pump_count': len(pump),
            'wash_count': len(wash),
            'distribution_count': len(distribution),
            'total': len(pump) + len(wash) + len(distribution),
        },
        'disclaimer': (
            '本模組僅標嫌疑 flag, 非定罪. 結果不代表實際違法行為 '
            '(合法策略也可能觸發). 任何後續行動由用戶自負.'
        ),
    }
    try:
        path = Path(data_dir) / 'red_flags.json'
        path.parent.mkdir(exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)
    except Exception as e:
        print(f"  ⚠️ red_flags.json 寫入失敗: {e}")
    return result


def format_summary(result: Dict[str, Any]) -> str:
    """console 摘要 (crawler log 用)."""
    if not result:
        return "  [Red Flags] 無紅旗"
    s = result['summary']
    if s['total'] == 0:
        return "  [Red Flags] ✓ 當日無操縱/對敲/出貨嫌疑"
    lines = [
        f"  [Red Flags] 拉抬 {s['pump_count']} / 對敲 {s['wash_count']} / 出貨 {s['distribution_count']}"
    ]
    for f in (result['pump_suspicion'][:3] + result['wash_trade'][:3]
              + result['distribution'][:3]):
        rule = f.get('rule', '?')
        icon = {'A_pump': '🚨', 'B_wash': '🔁', 'C_distribution': '📤'}.get(rule, '?')
        code = f.get('stock_code', '?')
        name = f.get('stock_name', '')
        reasoning = f.get('reasoning', '')
        lines.append(f"    {icon} {code} {name}: {reasoning}")
    return '\n'.join(lines)
