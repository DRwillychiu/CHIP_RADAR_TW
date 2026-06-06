"""v3.30.8 master_profile 單元測試 (合成歷史)"""
import sys
sys.path.insert(0, '.')

from master_profile import (
    extract_master_trades, compute_operation_metrics, compute_timing_metrics,
    generate_labels, generate_narrative, build_master_profile, build_all_profiles,
)

all_pass = True
print("=" * 64)
print("  v3.30.8 master_profile 單元測試")
print("=" * 64)


def mk_trade(stock_code, buy_amt, lu, style):
    return {'code': stock_code, 'name': f'股{stock_code}',
            'buy_lot': max(1, buy_amt // 200), 'sell_lot': 0,
            'buy_amt': buy_amt, 'sell_amt': 0,
            'is_limit_up': lu, 'trade_style': style}


# 合成 5 天歷史 (20260520~20260524, 週三~週日)
def mk_history():
    return [
        {'date': '20260520', 'data': {'branches': [
            {'code': '9227', 'master': '蔣承翰', 'co_masters': [],
             'buys': [mk_trade('3443', 100_000, True, 'partial'),
                      mk_trade('6147', 80_000, True, 'partial')],
             'sells': []},
            {'code': '9B25', 'master': '民哥', 'co_masters': [],
             'buys': [mk_trade('2330', 500_000, False, 'overnight')],
             'sells': []},
        ]}},
        {'date': '20260521', 'data': {'branches': [
            {'code': '9227', 'master': '蔣承翰', 'co_masters': [],
             'buys': [mk_trade('3443', 120_000, True, 'partial'),
                      mk_trade('2454', 60_000, True, 'partial')],
             'sells': []},
            {'code': '9B25', 'master': '民哥', 'co_masters': [],
             'buys': [mk_trade('2330', 600_000, False, 'overnight')],
             'sells': []},
        ]}},
        {'date': '20260522', 'data': {'branches': [
            {'code': '9227', 'master': '蔣承翰', 'co_masters': [],
             'buys': [mk_trade('3443', 90_000, True, 'partial')],
             'sells': []},
            {'code': '9B25', 'master': '民哥', 'co_masters': [],
             'buys': [mk_trade('2330', 700_000, False, 'overnight'),
                      mk_trade('2317', 100_000, False, 'overnight')],
             'sells': []},
        ]}},
        # 5/23 週六 5/24 週日 跳 (民哥沒交易 → 練 streak)
        {'date': '20260525', 'data': {'branches': [
            {'code': '9227', 'master': '蔣承翰', 'co_masters': [],
             'buys': [mk_trade('3443', 110_000, True, 'partial')],
             'sells': []},
        ]}},
        {'date': '20260526', 'data': {'branches': [
            {'code': '9B25', 'master': '民哥', 'co_masters': [],
             'buys': [mk_trade('2330', 800_000, False, 'overnight')],
             'sells': []},
        ]}},
    ]


# ── 1. extract_master_trades ──
# fixture: 5/20 2筆 + 5/21 2筆 + 5/22 1筆 + 5/25 1筆 = 6 筆
print("\n1. extract_master_trades 抓出蔣承翰 4 天 6 筆交易")
h = mk_history()
trades = extract_master_trades(h, '蔣承翰')
ok = len(trades) == 6 and all(t['is_limit_up'] for t in trades)
print(f"  {'OK' if ok else 'FAIL'} 蔣承翰 trades={len(trades)} 全漲停={all(t['is_limit_up'] for t in trades)}")
if not ok: all_pass = False

# ── 2. compute_operation_metrics 蔣承翰風格 ──
print("\n2. 蔣承翰 operation_metrics: partial 100% + limit_up 100%")
op = compute_operation_metrics(trades)
ok = (op['partial_ratio'] == 1.0 and op['limit_up_hit_ratio'] == 1.0
      and op['unique_stocks'] == 3 and op['trades_count'] == 6)
print(f"  {'OK' if ok else 'FAIL'} partial={op['partial_ratio']} lu={op['limit_up_hit_ratio']} "
      f"stocks={op['unique_stocks']} consistency={op['consistency']}")
if not ok: all_pass = False

# ── 3. 民哥 (波段) operation_metrics ──
print("\n3. 民哥 operation_metrics: overnight 100% + limit_up 0%")
m_trades = extract_master_trades(h, '民哥')
op_m = compute_operation_metrics(m_trades)
ok = (op_m['overnight_ratio'] == 1.0 and op_m['limit_up_hit_ratio'] == 0.0
      and op_m['concentration_top5_pct'] > 80)  # 2330 主導 + 2317 小量
print(f"  {'OK' if ok else 'FAIL'} overnight={op_m['overnight_ratio']} "
      f"lu={op_m['limit_up_hit_ratio']} concentration={op_m['concentration_top5_pct']}%")
if not ok: all_pass = False

# ── 4. timing_metrics 活躍天數 ──
print("\n4. 蔣承翰 timing_metrics: 4 天活躍 / 5 天窗口")
tm = compute_timing_metrics(trades, 5)
ok = tm['active_days'] == 4 and tm['active_days_ratio'] == 0.8 and tm['total_window_days'] == 5
print(f"  {'OK' if ok else 'FAIL'} active={tm['active_days']}/{tm['total_window_days']} "
      f"ratio={tm['active_days_ratio']}")
if not ok: all_pass = False

# ── 5. 蔣承翰 labels: 漲停獵手 + 短打型 + 集中投資 + 風格純粹 + 高頻 ──
print("\n5. 蔣承翰 labels: 漲停獵手/短打型/風格純粹/高頻")
labels = generate_labels(op, tm)
expected = {'漲停獵手', '短打型', '風格純粹'}
ok = expected.issubset(set(labels))
print(f"  {'OK' if ok else 'FAIL'} labels={labels}")
if not ok: all_pass = False

# ── 6. 民哥 labels: 波段囤貨 + 集中投資 + 風格純粹 ──
print("\n6. 民哥 labels: 波段囤貨/集中投資/風格純粹")
tm_m = compute_timing_metrics(m_trades, 5)
labels_m = generate_labels(op_m, tm_m)
expected_m = {'集中投資', '風格純粹'}   # v3.31.23: 波段不再標 (default 不標)
ok = expected_m.issubset(set(labels_m))
print(f"  {'OK' if ok else 'FAIL'} labels={labels_m}")
if not ok: all_pass = False

# ── 7. narrative 結構 ──
print("\n7. narrative 含關鍵字 (master/次數/漲停%/集中%)")
narr = generate_narrative('蔣承翰', op, tm, labels)
ok = all(s in narr for s in ['蔣承翰', '6 次', '漲停命中', '集中', '主軸'])
print(f"  {'OK' if ok else 'FAIL'}")
print(f"  narrative: {narr}")
if not ok: all_pass = False

# ── 8. build_master_profile 整合 ──
print("\n8. build_master_profile 完整結構")
master_styles = {'蔣承翰': ['next_day_flipper'], '民哥': ['swing']}
prof = build_master_profile('蔣承翰', h, master_styles)
ok = (prof['master'] == '蔣承翰'
      and prof['declared_styles'] == ['next_day_flipper']
      and 'operation_metrics' in prof
      and 'timing_metrics' in prof
      and 'strategy_labels' in prof
      and 'narrative' in prof)
print(f"  {'OK' if ok else 'FAIL'} 結構完整, declared={prof['declared_styles']}, "
      f"labels 數={len(prof['strategy_labels'])}")
if not ok: all_pass = False

# ── 9. no_data 處理 ──
print("\n9. master 無資料 → no_data 標記")
prof_empty = build_master_profile('不存在的人', h, {'不存在的人': ['swing']})
ok = prof_empty.get('no_data') is True
print(f"  {'OK' if ok else 'FAIL'} no_data={prof_empty.get('no_data')}")
if not ok: all_pass = False

# ── 10. 端到端 build_all_profiles ──
print("\n10. build_all_profiles 端到端 (用合成 history)")
# 需 mock get_individual_masters
import master_profile as mp
orig = mp.get_individual_masters
mp.get_individual_masters = lambda: {'蔣承翰': ['next_day_flipper'], '民哥': ['swing']}
try:
    result = build_all_profiles(h)
    ok = (result['master_count'] == 2
          and '蔣承翰' in result['masters']
          and '民哥' in result['masters']
          and 'trade_date_range' in result)
    print(f"  {'OK' if ok else 'FAIL'} master_count={result['master_count']}, "
          f"range={result['trade_date_range']}")
    if not ok: all_pass = False
finally:
    mp.get_individual_masters = orig

print()
print("─" * 64)
print(f"  整體: {'OK ALL PASS' if all_pass else 'FAIL HAS FAIL'}")
sys.exit(0 if all_pass else 1)
