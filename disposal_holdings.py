"""
========================================================================
Module: disposal_holdings.py  (v3.36.0 B5 新增)
處置股持倉追蹤 — 「誰現在抱著即將進處置/處置中的股票」

與 ⚠️處置股獵手 (行為偏好: 買進金額 30%+ 在處置股) 的差別:
  獵手 = 他「常買」處置股 (流量)
  持倉 = 他「現在抱著」處置股 (存量) → 被鎖風險 / 搶跑賣壓預警

實戰意義:
  1. 差1次 + 大戶重倉 → 再觸標準明天進處置 → 大戶今天可能搶跑 (賣壓預警)
  2. 處置中還在買 → 處置玩家 (出關行情觀察名單)
  3. 隔日沖大戶買差1次股 → 他自己的量就是最後一根稻草 (處置事件預測)

⚠️ 可信度誠實揭露 — 持倉是「窗口內可見淨累積」不是真實庫存 (~70-75%):
  1. TWSE 每分點每日只公布 Top 30 榜 → 沒上榜的交易看不到
  2. 跨券商賣出不可見 (同 declared_styles 結構性盲點)
  3. 窗口 (60天) 外的舊部位看不到
  對策: 只標大額命中 (≥MIN_LOTS 張 或 ≥MIN_WAN 萬) + 輸出買/賣/天數組成
        供人眼複核。當沖/隔日沖買賣自然互抵 → 被標出的幾乎都是真持倉者。

資料來源:
  - history daily JSON (buys + sells 雙榜, 60 天)
  - disposal_fetcher.get_disposal_map (差1次/差2次/處置中)
  - data/disposal_history/*.json 每日快照 (判定「處置生效後還在買」)

輸出 (掛進 master_profiles.json):
  per-master: profile['disposal_holdings'] = {summary + positions[]}
  全體:       result['disposal_holdings_global'] = {exposures[] 按曝險排序}
========================================================================
"""
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, List, Optional

# 「大額」門檻 (OR 條件, 可調)
MIN_NET_LOTS = 100      # 淨累積 ≥ 100 張
MIN_NET_WAN = 1000      # 或 淨累積金額 ≥ 1000 萬

# 風險分級 (status → risk)
RISK_BY_STATUS = {
    'active': 'trapped',       # ⛓️ 處置中持倉 = 已被鎖 (分盤交易出不來)
    'imminent_1': 'high',      # 🚨 差1次 = 再觸一次標準就進處置
    'imminent_2': 'watch',     # 👀 差2次 = 觀察
}
RISK_ICON = {'trapped': '⛓️', 'high': '🚨', 'watch': '👀'}


def _extract_net_flows(history: List[Dict[str, Any]],
                        master_name: str) -> Dict[str, Dict[str, Any]]:
    """每 master × 每股的窗口內淨流量 (buys + sells 雙榜都算).

    注意: extract_master_trades 只抓 buys 榜 — 持倉推算必須含 sells 榜
    (master 出貨日該股常只出現在賣超榜)。同 (date, branch, code) 在雙榜
    重複出現時只算一次 (TWSE 雙榜的 buy/sell 欄位是同一份數字)。

    回傳 {code: {name, buy_lot, sell_lot, buy_amt, sell_amt,
                 buy_dates: [..], last_buy_date}}"""
    flows: Dict[str, Dict[str, Any]] = {}
    for day in history:
        date = day.get('date', '')
        for br in day.get('data', {}).get('branches', []):
            br_master = br.get('master')
            co = br.get('co_masters') or []
            if br_master != master_name and master_name not in co:
                continue
            seen = set()   # (branch, code) 當日去重 (雙榜同股同數字)
            for side in ('buys', 'sells'):
                for stock in (br.get(side) or []):
                    code = str(stock.get('code') or '')
                    if not code:
                        continue
                    key = (br.get('code'), code)
                    if key in seen:
                        continue
                    seen.add(key)
                    f = flows.setdefault(code, {
                        'name': stock.get('name') or '',
                        'buy_lot': 0, 'sell_lot': 0,
                        'buy_amt': 0, 'sell_amt': 0,
                        'buy_dates': [], 'last_buy_date': None,
                    })
                    bl = stock.get('buy_lot', 0) or 0
                    sl = stock.get('sell_lot', 0) or 0
                    f['buy_lot'] += bl
                    f['sell_lot'] += sl
                    f['buy_amt'] += stock.get('buy_amt', 0) or 0   # 仟元
                    f['sell_amt'] += stock.get('sell_amt', 0) or 0
                    if bl > 0:
                        f['buy_dates'].append(date)
                        if f['last_buy_date'] is None or date > f['last_buy_date']:
                            f['last_buy_date'] = date
    return flows


def _load_active_history(data_dir: str) -> Dict[str, str]:
    """讀 disposal_history/ 快照 → {code: 該股首次出現在 active 名單的日期}.
    用途: 判定「處置生效後還在買」(buy_date >= first_active_date)."""
    history_dir = Path(data_dir) / 'disposal_history'
    if not history_dir.exists():
        return {}
    first_active: Dict[str, str] = {}
    for f in sorted(history_dir.glob('[0-9]' * 8 + '.json')):
        try:
            snap = json.loads(f.read_text(encoding='utf-8'))
            for code in (snap.get('sets', {}).get('active') or []):
                first_active.setdefault(str(code), f.stem)
        except Exception:
            continue
    return first_active


def compute_master_disposal_holdings(history: List[Dict[str, Any]],
                                       master_name: str,
                                       disposal_sets: Dict[str, Any],
                                       first_active: Optional[Dict[str, str]] = None,
                                       min_net_lots: int = MIN_NET_LOTS,
                                       min_net_wan: int = MIN_NET_WAN
                                       ) -> Optional[Dict[str, Any]]:
    """單一 master 的處置股持倉.

    disposal_sets: {'imminent_1': set, 'imminent_2': set, 'active': set}
    回傳 {trapped_count, high_count, watch_count, total_exposure_wan,
          bought_during_disposal_count, positions: [...]} 或 None (無命中)."""
    sets = {k: set(str(c) for c in (disposal_sets.get(k) or []))
            for k in ('active', 'imminent_1', 'imminent_2')}
    all_risky = sets['active'] | sets['imminent_1'] | sets['imminent_2']
    if not all_risky:
        return None

    flows = _extract_net_flows(history, master_name)
    positions = []
    for code, f in flows.items():
        if code not in all_risky:
            continue
        net_lots = f['buy_lot'] - f['sell_lot']
        net_amt_wan = round((f['buy_amt'] - f['sell_amt']) / 10)   # 仟元 → 萬元
        if net_lots <= 0:
            continue   # 可見淨流出/打平 → 無可見持倉
        # 大額門檻 (OR): 張數或金額其一達標
        if net_lots < min_net_lots and net_amt_wan < min_net_wan:
            continue
        # 狀態判定 (active 優先 — 同股可能同時在多名單)
        if code in sets['active']:
            status = 'active'
        elif code in sets['imminent_1']:
            status = 'imminent_1'
        else:
            status = 'imminent_2'
        risk = RISK_BY_STATUS[status]
        # 處置生效後還在買? (處置玩家行為)
        bought_during = False
        if first_active and code in first_active:
            fa = first_active[code]
            bought_during = any(d >= fa for d in f['buy_dates'])
        positions.append({
            'stock_code': code,
            'stock_name': f['name'],
            'status': status,
            'risk': risk,
            'net_lots': net_lots,
            'net_amt_wan': net_amt_wan,
            'buy_lot': f['buy_lot'],
            'sell_lot': f['sell_lot'],
            'buy_days': len(set(f['buy_dates'])),
            'last_buy_date': f['last_buy_date'],
            'bought_during_disposal': bought_during,
        })
    if not positions:
        return None

    # 排序: trapped > high > watch, 同級按金額
    risk_order = {'trapped': 0, 'high': 1, 'watch': 2}
    positions.sort(key=lambda p: (risk_order[p['risk']], -p['net_amt_wan']))
    return {
        'trapped_count': sum(1 for p in positions if p['risk'] == 'trapped'),
        'high_count': sum(1 for p in positions if p['risk'] == 'high'),
        'watch_count': sum(1 for p in positions if p['risk'] == 'watch'),
        'bought_during_disposal_count': sum(1 for p in positions if p['bought_during_disposal']),
        'total_exposure_wan': sum(p['net_amt_wan'] for p in positions),
        'positions': positions,
    }


def compute_all_disposal_holdings(history: List[Dict[str, Any]],
                                    masters: Dict[str, List[str]],
                                    disposal_map: Optional[Dict[str, Any]],
                                    data_dir: str = 'data'
                                    ) -> Optional[Dict[str, Any]]:
    """全體 master 的處置持倉 + 全體曝險排行.

    disposal_map: disposal_fetcher.get_disposal_map() 回傳 (含 'sets')
    回傳 {per_master: {name: {...}}, exposures: [...], note} 或 None."""
    if not disposal_map or not disposal_map.get('sets'):
        return None
    first_active = _load_active_history(data_dir)
    per_master = {}
    exposures = []
    for m in masters:
        h = compute_master_disposal_holdings(history, m, disposal_map['sets'],
                                              first_active=first_active)
        if h:
            per_master[m] = h
            for p in h['positions']:
                exposures.append({'master': m, **p})
    if not per_master:
        return None
    risk_order = {'trapped': 0, 'high': 1, 'watch': 2}
    exposures.sort(key=lambda e: (risk_order[e['risk']], -e['net_amt_wan']))
    return {
        'per_master': per_master,
        'exposures': exposures[:30],   # 全體面板 cap 30 筆
        'masters_with_exposure': len(per_master),
        'snapshot_days': len(set(_load_active_history(data_dir).values())) if first_active else 0,
        'note': ('持倉 = 窗口內可見淨累積 (TWSE Top30 榜 + 跨券商賣出盲點, '
                 '非真實庫存) — 大額命中才列入, 買/賣組成可人眼複核'),
    }


def format_holdings_summary(result: Dict[str, Any]) -> str:
    """console summary (crawler log 用)."""
    if not result:
        return "  [Disposal Holdings] 無大額處置持倉命中"
    lines = [f"  [Disposal Holdings] {result['masters_with_exposure']} 位 master 有處置股持倉:"]
    for e in result['exposures'][:8]:
        icon = RISK_ICON.get(e['risk'], '?')
        during = ' [處置中還在買!]' if e['bought_during_disposal'] else ''
        lines.append(f"    {icon} {e['master']} × {e['stock_name']}({e['stock_code']}) "
                     f"淨{e['net_lots']}張/{e['net_amt_wan']}萬 {e['status']}{during}")
    return '\n'.join(lines)
