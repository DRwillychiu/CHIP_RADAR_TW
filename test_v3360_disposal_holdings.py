# -*- coding: utf-8 -*-
"""
test_v3360_disposal_holdings.py — v3.36.0 (B5) 處置股持倉追蹤測試

驗證:
  1. 淨流量抽取: buys + sells 雙榜都算 (出貨日只在賣超榜也要抓到)
  2. 同 (branch, code) 雙榜去重 (同一份數字不重複計)
  3. 處置名單交叉 + 風險三級 (active=trapped / imminent_1=high / imminent_2=watch)
  4. 大額門檻 OR 邏輯 (張數或金額其一達標)
  5. 淨流出/打平 → 不列入 (無可見持倉)
  6. 快照判定「處置生效後還在買」
  7. ⛓️ 處置持倉標籤生成 (trapped/high 才標, watch 不標)
  8. 全體曝險排行排序 (trapped > high > watch, 同級按金額)
  9. graceful None (無處置名單 / 無命中)
  10. co_masters 共用分點也算

跑法: python test_v3360_disposal_holdings.py  (免密碼, 合成 fixture)
"""
import sys
import io
import json
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from disposal_holdings import (
    _extract_net_flows,
    compute_master_disposal_holdings,
    compute_all_disposal_holdings,
)
from master_profile import generate_labels, LABEL_L1_MAP

PASS = 0
FAIL = 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def mk_stock(code, buy_lot=0, sell_lot=0, buy_amt=0, sell_amt=0):
    return {'code': code, 'name': f'股{code}', 'buy_lot': buy_lot, 'sell_lot': sell_lot,
            'buy_amt': buy_amt, 'sell_amt': sell_amt, 'is_limit_up': False,
            'trade_style': 'overnight'}


def mk_day(date, branches):
    """branches: [(branch_code, master, co_masters, buys, sells)]"""
    return {'date': date, 'data': {'branches': [
        {'code': bc, 'name': bc, 'master': m, 'co_masters': co, 'buys': b, 'sells': s}
        for bc, m, co, b, s in branches]}}


# ────────────────────────────────────────────────────────────────────
print("\n[Case 1] 淨流量: buys 榜買進 + sells 榜出貨 都要算")
history = [
    # day1: 甲在買超榜買 3700 300張/3000仟元
    mk_day('20260601', [('9A00', '甲', [], [mk_stock('3700', buy_lot=300, buy_amt=3000)], [])]),
    # day2: 甲出貨 → 3700 只出現在賣超榜 (賣 100 張)
    mk_day('20260602', [('9A00', '甲', [], [], [mk_stock('3700', sell_lot=100, sell_amt=1100)])]),
]
flows = _extract_net_flows(history, '甲')
check("3700 有抓到", '3700' in flows)
check("buy_lot=300 (買榜)", flows['3700']['buy_lot'] == 300)
check("sell_lot=100 (賣榜也算!)", flows['3700']['sell_lot'] == 100,
      f"got {flows['3700']['sell_lot']}")
check("buy_dates 只記有買的日子", flows['3700']['buy_dates'] == ['20260601'])

# ────────────────────────────────────────────────────────────────────
print("\n[Case 2] 同 (branch, code) 雙榜同日去重")
h2 = [mk_day('20260601', [('9A00', '甲', [],
                            [mk_stock('3700', buy_lot=200, sell_lot=50, buy_amt=2000, sell_amt=500)],
                            [mk_stock('3700', buy_lot=200, sell_lot=50, buy_amt=2000, sell_amt=500)])])]
f2 = _extract_net_flows(h2, '甲')
check("雙榜重複只算一次 (buy=200 非 400)", f2['3700']['buy_lot'] == 200,
      f"got {f2['3700']['buy_lot']}")

# ────────────────────────────────────────────────────────────────────
print("\n[Case 3] 處置交叉 + 風險三級")
SETS = {'active': {'1111'}, 'imminent_1': {'2222'}, 'imminent_2': {'3333'}}
h3 = [mk_day('20260601', [('9A00', '甲', [], [
    mk_stock('1111', buy_lot=200, buy_amt=20000),   # 處置中 → trapped
    mk_stock('2222', buy_lot=150, buy_amt=15000),   # 差1次 → high
    mk_stock('3333', buy_lot=120, buy_amt=12000),   # 差2次 → watch
    mk_stock('4444', buy_lot=500, buy_amt=50000),   # 不在名單 → 不列
], [])])]
r3 = compute_master_disposal_holdings(h3, '甲', SETS)
check("3 筆命中 (4444 排除)", r3 is not None and len(r3['positions']) == 3)
risks = {p['stock_code']: p['risk'] for p in r3['positions']}
check("1111=trapped", risks.get('1111') == 'trapped')
check("2222=high", risks.get('2222') == 'high')
check("3333=watch", risks.get('3333') == 'watch')
check("counts 正確", r3['trapped_count'] == 1 and r3['high_count'] == 1 and r3['watch_count'] == 1)
check("排序 trapped 在最前", r3['positions'][0]['stock_code'] == '1111')

# ────────────────────────────────────────────────────────────────────
print("\n[Case 4] 大額門檻 OR: 張數小但金額大 → 仍列入; 兩者都小 → 排除")
h4 = [mk_day('20260601', [('9A00', '甲', [], [
    mk_stock('1111', buy_lot=20, buy_amt=15000),   # 20張 < 100 但 1500萬 ≥ 1000萬 → 列入
    mk_stock('2222', buy_lot=30, buy_amt=3000),    # 30張 + 300萬 都不達標 → 排除
], [])])]
r4 = compute_master_disposal_holdings(h4, '甲', SETS)
codes4 = [p['stock_code'] for p in r4['positions']]
check("金額達標列入 (1111)", '1111' in codes4)
check("雙不達標排除 (2222)", '2222' not in codes4)

# ────────────────────────────────────────────────────────────────────
print("\n[Case 5] 淨流出/打平 → 無可見持倉不列入")
h5 = [
    mk_day('20260601', [('9A00', '甲', [], [mk_stock('1111', buy_lot=200, buy_amt=20000)], [])]),
    mk_day('20260602', [('9A00', '甲', [], [], [mk_stock('1111', sell_lot=200, sell_amt=21000)])]),
]
r5 = compute_master_disposal_holdings(h5, '甲', SETS)
check("買 200 賣 200 → 淨 0 → None", r5 is None)

# ────────────────────────────────────────────────────────────────────
print("\n[Case 6] 快照判定「處置生效後還在買」")
with tempfile.TemporaryDirectory() as td:
    hist_dir = Path(td) / 'disposal_history'
    hist_dir.mkdir()
    # 1111 在 6/3 首次出現在 active
    (hist_dir / '20260603.json').write_text(json.dumps(
        {'sets': {'active': ['1111'], 'imminent_1': [], 'imminent_2': []}}), encoding='utf-8')
    h6 = [
        mk_day('20260601', [('9A00', '甲', [], [mk_stock('1111', buy_lot=150, buy_amt=15000)], [])]),
        mk_day('20260605', [('9A00', '甲', [], [mk_stock('1111', buy_lot=100, buy_amt=10000)], [])]),  # 處置後還買!
        mk_day('20260601', [('9B00', '乙', [], [mk_stock('1111', buy_lot=150, buy_amt=15000)], [])]),  # 只在處置前買
    ]
    disposal_map = {'sets': {'active': ['1111'], 'imminent_1': [], 'imminent_2': []}}
    rall = compute_all_disposal_holdings(h6, {'甲': ['swing'], '乙': ['swing']},
                                          disposal_map, data_dir=td)
    pm = rall['per_master']
    check("甲 bought_during=True (6/5 > 6/3)",
          pm['甲']['positions'][0]['bought_during_disposal'] is True)
    check("乙 bought_during=False (6/1 < 6/3)",
          pm['乙']['positions'][0]['bought_during_disposal'] is False)
    check("甲 bought_during_disposal_count=1", pm['甲']['bought_during_disposal_count'] == 1)

# ────────────────────────────────────────────────────────────────────
print("\n[Case 7] ⛓️ 處置持倉標籤: trapped/high 標, 只有 watch 不標")
op_stub = {'limit_up_hit_ratio': 0, 'daytrade_ratio': 0, 'partial_ratio': 0,
           'overnight_ratio': 0, 'concentration_top5_pct': 25, 'consistency': 0.5}
tm_stub = {'active_days_ratio': 0.5, 'max_streak_days': 3}
lbl_trapped = generate_labels(op_stub, tm_stub,
                               disposal_holdings={'trapped_count': 1, 'high_count': 0})
check("trapped → 有標籤", '⛓️ 處置持倉' in lbl_trapped)
lbl_high = generate_labels(op_stub, tm_stub,
                            disposal_holdings={'trapped_count': 0, 'high_count': 2})
check("high → 有標籤", '⛓️ 處置持倉' in lbl_high)
lbl_watch = generate_labels(op_stub, tm_stub,
                             disposal_holdings={'trapped_count': 0, 'high_count': 0, 'watch_count': 3})
check("只有 watch → 不標", '⛓️ 處置持倉' not in lbl_watch)
lbl_none = generate_labels(op_stub, tm_stub, disposal_holdings=None)
check("None → 不標", '⛓️ 處置持倉' not in lbl_none)
check("LABEL_L1_MAP 歸觀察型", LABEL_L1_MAP.get('⛓️ 處置持倉') == '觀察型')

# ────────────────────────────────────────────────────────────────────
print("\n[Case 8] 全體曝險排序: trapped > high, 同級按金額")
h8 = [mk_day('20260601', [
    ('9A00', '甲', [], [mk_stock('2222', buy_lot=300, buy_amt=30000)], []),   # high 3000萬
    ('9B00', '乙', [], [mk_stock('1111', buy_lot=110, buy_amt=11000)], []),   # trapped 1100萬
    ('9C00', '丙', [], [mk_stock('2222', buy_lot=500, buy_amt=90000)], []),   # high 9000萬
])]
r8 = compute_all_disposal_holdings(h8, {'甲': [], '乙': [], '丙': []},
                                    {'sets': SETS}, data_dir='/nonexistent')
ex = r8['exposures']
check("乙(trapped) 排第一 (即使金額較小)", ex[0]['master'] == '乙')
check("丙(high 9000萬) 排第二", ex[1]['master'] == '丙')
check("甲(high 3000萬) 排第三", ex[2]['master'] == '甲')
check("masters_with_exposure=3", r8['masters_with_exposure'] == 3)

# ────────────────────────────────────────────────────────────────────
print("\n[Case 9] graceful None")
check("無處置名單 → None", compute_all_disposal_holdings(h8, {'甲': []}, None) is None)
check("空 sets → None", compute_master_disposal_holdings(h8, '甲',
      {'active': set(), 'imminent_1': set(), 'imminent_2': set()}) is None)
r9 = compute_master_disposal_holdings(h8, '不存在的人', SETS)
check("master 無交易 → None", r9 is None)

# ────────────────────────────────────────────────────────────────────
print("\n[Case 10] co_masters 共用分點")
h10 = [mk_day('20260601', [('9A00', '主人', ['共主'],
                             [mk_stock('1111', buy_lot=200, buy_amt=20000)], [])])]
f10 = _extract_net_flows(h10, '共主')
check("co_master 也抓到流量", '1111' in f10 and f10['1111']['buy_lot'] == 200)

# ────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3360_disposal_holdings: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
