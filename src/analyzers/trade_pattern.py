"""trade_pattern.py — v3.30.0 客製化 AI 解讀層 (規則式 + 模板 narrative)

User 5/24 需求:
  - 從 raw data 升級到「解讀層」: 個股 + 分點 → 50-100 字中性專業說明
  - 模式判斷: 隔日沖 / 當沖 / 波段持股 / 部分當沖
  - 透過 popup 視窗呈現

設計選擇 (5/24 AI-c):
  - 規則式 classify_trade_pattern (基於 master_styles + daytrade_ratio + is_limit_up)
  - 模板式 generate_narrative (不需 API key, 模仿 AI 中性口吻)
  - Phase 2 押真 AI (Anthropic Claude API)

Output:
  在 raw_output 各 stock dict 注入 2 個 fields:
    trade_pattern: '隔日沖' / '當沖' / '波段持股' / '部分當沖' / '未明'
    insight_narrative: 50-100 字模板式說明
  前端 popup 讀這 2 個 field render

注意:
  trade_pattern 是「該分點 × 該個股 × 該日」的單一判斷,跨日累積 (囤貨判定) 需另寫
  v3.30.1+ 加 cross-day 囤貨偵測
"""

from typing import Dict, List, Optional


# ════════════════════════════════════════════════════════════════════
#  Style labels 對應 (給 narrative 用)
# ════════════════════════════════════════════════════════════════════
STYLE_LABELS_CHINESE = {
    'next_day_flipper': '隔日沖',
    'day_trader':       '當沖',
    'swing':            '波段',
    'longterm':         '長線',
    'foreign_ib':       '外資',
    'public':           '官股',
    'unknown':          '未分類',
}


# ════════════════════════════════════════════════════════════════════
#  模式分類規則
# ════════════════════════════════════════════════════════════════════
def classify_trade_pattern(stock: Dict, master_styles: List[str] = None) -> str:
    """根據 stock + master_styles 判斷該分點對該個股的操作模式.

    判斷優先序 (5 模式):
      1. 隔日沖 — master 風格 = next_day_flipper, 或 (漲停 + 大買留倉)
      2. 當沖 — master 風格 = day_trader, 或 trade_style = daytrade
      3. 波段持股 — master 風格 in {swing, longterm} + 留倉
      4. 部分當沖 — trade_style = partial (買賣比 30-70%)
      5. 未明 — fallback (資料不足)

    Args:
        stock: branch stock dict (含 trade_style / is_limit_up / daytrade_ratio / etc.)
        master_styles: 該 master 的風格陣列 (從 branches.MASTER_STYLES 取)

    Returns:
        '隔日沖' / '當沖' / '波段持股' / '部分當沖' / '未明'
    """
    master_styles = master_styles or []
    is_lu = stock.get('is_limit_up', False)
    ts = stock.get('trade_style', 'unknown')
    dt_ratio = stock.get('daytrade_ratio', 0) or 0

    # 1. 隔日沖 (優先)
    if 'next_day_flipper' in master_styles:
        return '隔日沖'
    if is_lu and ts == 'overnight':
        return '隔日沖'

    # 2. 當沖
    if 'day_trader' in master_styles:
        return '當沖'
    if ts == 'daytrade':
        return '當沖'

    # 3. 波段持股
    if ('swing' in master_styles or 'longterm' in master_styles) and ts in ('overnight', 'partial'):
        return '波段持股'

    # 4. 部分當沖
    if ts == 'partial':
        return '部分當沖'

    # 5. 留倉但 master style 不明
    if ts == 'overnight':
        return '波段持股'

    return '未明'


# ════════════════════════════════════════════════════════════════════
#  模板式 narrative (50-100 字, 中性專業)
# ════════════════════════════════════════════════════════════════════
def _fmt_amt_wan(amt_kilo: float) -> str:
    """仟元 → 萬元 字串"""
    if not amt_kilo:
        return '0'
    wan = amt_kilo / 10
    return f'{wan:,.0f}' if wan >= 1 else f'{wan:.1f}'


def _master_style_label(master_styles: List[str]) -> str:
    """['next_day_flipper'] → '隔日沖型' """
    if not master_styles:
        return '未分類'
    primary = master_styles[0]
    label = STYLE_LABELS_CHINESE.get(primary, '未分類')
    return f'{label}型'


def _change_pct_desc(change_pct: Optional[float], is_lu: bool) -> str:
    """漲跌幅 → 中性描述"""
    if is_lu:
        return f'今日漲停 (+{change_pct or 0:.2f}%)'
    if change_pct is None:
        return '行情資料不全'
    if change_pct >= 5:
        return f'今日大漲 +{change_pct:.2f}%'
    if change_pct >= 1:
        return f'今日上漲 +{change_pct:.2f}%'
    if change_pct >= -1:
        return f'今日小幅波動 ({change_pct:+.2f}%)'
    if change_pct >= -5:
        return f'今日下跌 {change_pct:.2f}%'
    return f'今日大跌 {change_pct:.2f}%'


def generate_narrative(stock: Dict, master_name: str, branch_name: str,
                      pattern: str, master_styles: List[str] = None) -> str:
    """根據模式 + stock + master + branch 生成 50-100 字中性專業說明.

    模板針對 5 種模式各設計 1 個版本, 字數控制在 60-100 字之間.

    Args:
        stock: branch stock dict
        master_name: e.g. '蔣承翰'
        branch_name: e.g. '凱基-城中'
        pattern: classify_trade_pattern() 回傳值
        master_styles: 給 _master_style_label 用

    Returns:
        50-100 字 narrative 字串
    """
    master_styles = master_styles or []
    name = stock.get('name', '') or ''
    code = stock.get('code', '') or ''
    stock_label = f'{name}({code})' if name and code else (name or code or '個股')

    buy_lot = stock.get('buy_lot', 0) or 0
    sell_lot = stock.get('sell_lot', 0) or 0
    buy_amt = stock.get('buy_amt', 0) or 0
    sell_amt = stock.get('sell_amt', 0) or 0
    net_lot = stock.get('net_lot', 0) or 0
    net_amt = stock.get('net_amt', 0) or 0
    change_pct = stock.get('change_pct')
    is_lu = stock.get('is_limit_up', False)
    daytrade_ratio = stock.get('daytrade_ratio', 0) or 0

    buy_amt_wan = _fmt_amt_wan(buy_amt)
    sell_amt_wan = _fmt_amt_wan(sell_amt)
    net_amt_wan = _fmt_amt_wan(net_amt)
    style_label = _master_style_label(master_styles)
    chg_desc = _change_pct_desc(change_pct, is_lu)

    # ── 模式對應模板 ──
    if pattern == '隔日沖':
        n = (
            f'{master_name}({style_label})於{branch_name}分點搶買{stock_label}'
            f' {buy_lot} 張共 {buy_amt_wan} 萬元,淨買 {net_lot} 張,{chg_desc}。'
            f'隔日沖風格偏好高動能漲停股,留倉特徵符合其於高點佈局、'
            f'隔日開盤即出貨的操作邏輯。'
        )
    elif pattern == '當沖':
        n = (
            f'{master_name}({style_label})於{branch_name}分點當沖{stock_label},'
            f'買 {buy_lot} 張 / 賣 {sell_lot} 張(當沖比約 {daytrade_ratio:.0%}),'
            f'淨買 {net_lot} 張共 {net_amt_wan} 萬元,{chg_desc}。'
            f'當沖風格不留隔夜部位,以盤中價差捕捉為核心。'
        )
    elif pattern == '波段持股':
        n = (
            f'{master_name}({style_label})於{branch_name}分點淨買{stock_label}'
            f' {net_lot} 張共 {net_amt_wan} 萬元,{chg_desc}。'
            f'波段風格 master 看重基本面與技術面共識,持有週期通常數日至數週,'
            f'單日波動容忍度較高,留倉部位反映其中長期看法。'
        )
    elif pattern == '部分當沖':
        n = (
            f'{master_name}({style_label})於{branch_name}分點操作{stock_label},'
            f'買 {buy_lot} 張 / 賣 {sell_lot} 張(買賣比 {daytrade_ratio:.0%}),'
            f'淨買 {net_lot} 張,{chg_desc}。'
            f'部分當沖混合即時獲利了結與留倉策略,'
            f'反映 master 對標的短期動能與中期方向同時關注。'
        )
    else:  # '未明'
        n = (
            f'{master_name}於{branch_name}分點對{stock_label}'
            f'買 {buy_lot} 張 / 賣 {sell_lot} 張,淨買 {net_lot} 張共 {net_amt_wan} 萬元,'
            f'{chg_desc}。當日交易資料尚不足以斷定具體操作模式,建議結合該 master '
            f'歷史風格與後續日次跟單行為綜合判讀。'
        )

    return n


# ════════════════════════════════════════════════════════════════════
#  Main: 為 branches_data 注入 trade_pattern + insight_narrative
# ════════════════════════════════════════════════════════════════════
def inject_trade_patterns(branches_data: List[Dict],
                          watched_branches: List[Dict],
                          master_styles_map: Dict[str, List[str]]) -> int:
    """為每個 (branch, stock) 注入 trade_pattern + insight_narrative.

    Args:
        branches_data: crawler results (含 buys/sells per branch)
        watched_branches: branches.py WATCHED_BRANCHES (取 code → master 對應)
        master_styles_map: branches.py MASTER_STYLES dict

    Returns:
        注入的 stock count (provides log info)
    """
    # Build branch_code → master_name lookup
    branch_to_master = {}
    for wb in watched_branches:
        code = wb.get('code')
        master = wb.get('master')
        if code and master:
            branch_to_master[code] = master

    count = 0
    for br in branches_data:
        branch_code = br.get('code', '')
        branch_name = br.get('name', '')
        master_name = branch_to_master.get(branch_code, '')
        master_styles = master_styles_map.get(master_name, [])

        for side in ('buys', 'sells'):
            for s in br.get(side, []) or []:
                pattern = classify_trade_pattern(s, master_styles)
                narrative = generate_narrative(
                    s, master_name, branch_name, pattern, master_styles
                )
                s['trade_pattern'] = pattern
                s['insight_narrative'] = narrative
                count += 1

    return count
