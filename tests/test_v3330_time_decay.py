# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

# -*- coding: utf-8 -*-
"""
test_v3330_time_decay.py — v3.33.0 (B3) 滾動窗口時間衰減測試

驗證:
  1. 權重公式: 今天=1.0 / 20天前=0.5 / 40天前=0.25
  2. 向後相容: decay_ref_date=None → 全 1.0 (= v3.32 行為)
  3. half_life 停用 (0/None) → 全 1.0
  4. 風格 ratio 偏向近期 (舊 overnight + 新 daytrade → 加權後 daytrade 主導)
  5. 漲停命中加權
  6. 集中度加權 (舊大部位衰減)
  7. 絕對值欄位 raw 不加權 (trades_count / total_buy_amt_wan)
  8. 長線金額占比加權, 天數判定 raw
  9. build_master_profile 整合: decay_applied + 錨點=窗口最新日
  10. timing metrics 不受衰減影響

跑法: python test_v3330_time_decay.py  (免密碼, 全合成 fixture)
"""
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from master_profile import (
    _compute_trade_weights,
    compute_operation_metrics,
    compute_timing_metrics,
    build_master_profile,
    THRESH,
)

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


def mk_trade(date, style='overnight', code='2330', amt=1000, lot=10,
             limit_up=False):
    return {
        'date': date, 'branch_code': '9A00', 'stock_code': code,
        'stock_name': 'X', 'buy_lot': lot, 'sell_lot': 0,
        'buy_amt': amt, 'sell_amt': 0,
        'is_limit_up': limit_up, 'trade_style': style,
    }


# ────────────────────────────────────────────────────────────────────
print("\n[Case 1] 權重公式: 今天=1.0 / 20天前=0.5 / 40天前=0.25")
trades = [mk_trade('20260610'), mk_trade('20260521'), mk_trade('20260501')]
w = _compute_trade_weights(trades, '20260610', half_life=20)
check("今天 weight = 1.0", abs(w[0] - 1.0) < 1e-9, f"got {w[0]}")
check("20 天前 weight = 0.5", abs(w[1] - 0.5) < 1e-9, f"got {w[1]}")
check("40 天前 weight = 0.25", abs(w[2] - 0.25) < 1e-9, f"got {w[2]}")

# ────────────────────────────────────────────────────────────────────
print("\n[Case 2] 向後相容: decay_ref_date=None → 全 1.0")
w = _compute_trade_weights(trades, None)
check("None ref → 全 1.0", all(x == 1.0 for x in w), f"got {w}")

# ────────────────────────────────────────────────────────────────────
print("\n[Case 3] half_life 停用 (0 / None / 壞日期) → 全 1.0")
w0 = _compute_trade_weights(trades, '20260610', half_life=0)
check("half_life=0 → 全 1.0", all(x == 1.0 for x in w0), f"got {w0}")
wbad = _compute_trade_weights(trades, 'not-a-date', half_life=20)
check("壞 ref_date → 全 1.0", all(x == 1.0 for x in wbad), f"got {wbad}")
wmix = _compute_trade_weights([mk_trade('bad-date')], '20260610', half_life=20)
check("壞 trade date → 該筆 1.0", wmix == [1.0], f"got {wmix}")

# ────────────────────────────────────────────────────────────────────
print("\n[Case 4] 風格 ratio 偏向近期: 30 筆舊 overnight + 10 筆新 daytrade")
# 不衰減: overnight 30/40 = 0.75 主導
# 衰減 (40 天前 w=0.25): overnight 30×0.25=7.5, daytrade 10×1.0=10 → daytrade 0.571 主導
trades4 = ([mk_trade('20260501', style='overnight') for _ in range(30)] +
           [mk_trade('20260610', style='daytrade') for _ in range(10)])
op_raw = compute_operation_metrics(trades4)                                # 不衰減
op_dec = compute_operation_metrics(trades4, decay_ref_date='20260610')     # 衰減
check("不衰減 overnight=0.75 主導", abs(op_raw['overnight_ratio'] - 0.75) < 0.001,
      f"got {op_raw['overnight_ratio']}")
check("衰減後 daytrade > overnight",
      op_dec['daytrade_ratio'] > op_dec['overnight_ratio'],
      f"daytrade={op_dec['daytrade_ratio']} overnight={op_dec['overnight_ratio']}")
check("衰減後 daytrade ≈ 0.571", abs(op_dec['daytrade_ratio'] - 0.571) < 0.005,
      f"got {op_dec['daytrade_ratio']}")
check("三 ratio 加總仍 = 1.0",
      abs(op_dec['daytrade_ratio'] + op_dec['partial_ratio']
          + op_dec['overnight_ratio'] - 1.0) < 0.01)

# ────────────────────────────────────────────────────────────────────
print("\n[Case 5] 漲停命中加權: 舊漲停多 + 近期無漲停 → 加權後下降")
trades5 = ([mk_trade('20260501', limit_up=True) for _ in range(10)] +
           [mk_trade('20260610', limit_up=False) for _ in range(10)])
op5_raw = compute_operation_metrics(trades5)
op5_dec = compute_operation_metrics(trades5, decay_ref_date='20260610')
check("不衰減 limit_up = 0.5", abs(op5_raw['limit_up_hit_ratio'] - 0.5) < 0.001)
# 衰減: 10×0.25 / (10×0.25 + 10×1.0) = 2.5/12.5 = 0.2
check("衰減後 limit_up = 0.2", abs(op5_dec['limit_up_hit_ratio'] - 0.2) < 0.005,
      f"got {op5_dec['limit_up_hit_ratio']}")

# ────────────────────────────────────────────────────────────────────
print("\n[Case 6] 集中度加權: 舊大部位衰減 → 集中度反映近期持股")
# 舊: 單檔 A 100000 (40天前, w=0.25 → 25000)
# 新: 10 檔各 5000 (今天, w=1.0 → 50000)
# 不衰減: top5 = 100000+5000×4=120000 / 150000 = 80%
# 衰減: A=25000 仍最大, top5 = 25000+5000×4 = 45000 / 75000 = 60%
trades6 = ([mk_trade('20260501', code='9999', amt=100000)] +
           [mk_trade('20260610', code=f'10{i:02d}', amt=5000) for i in range(10)])
op6_raw = compute_operation_metrics(trades6)
op6_dec = compute_operation_metrics(trades6, decay_ref_date='20260610')
check("不衰減集中度 = 80%", abs(op6_raw['concentration_top5_pct'] - 80.0) < 0.5,
      f"got {op6_raw['concentration_top5_pct']}")
check("衰減後集中度 = 60%", abs(op6_dec['concentration_top5_pct'] - 60.0) < 0.5,
      f"got {op6_dec['concentration_top5_pct']}")

# ────────────────────────────────────────────────────────────────────
print("\n[Case 7] 絕對值欄位 raw: trades_count / total_buy_amt_wan 不加權")
check("trades_count = 11 (raw)", op6_dec['trades_count'] == 11,
      f"got {op6_dec['trades_count']}")
# raw total = 100000 + 50000 = 150000 仟元 = 15000 萬
check("total_buy_amt_wan = 15000 (raw)", op6_dec['total_buy_amt_wan'] == 15000,
      f"got {op6_dec['total_buy_amt_wan']}")
check("decay_applied = True", op6_dec['decay_applied'] is True)
check("decay_half_life = 20", op6_dec['decay_half_life'] == THRESH['decay_half_life'])
check("不衰減時 decay_applied = False", op6_raw['decay_applied'] is False)
check("不衰減時 decay_half_life = None", op6_raw['decay_half_life'] is None)

# ────────────────────────────────────────────────────────────────────
print("\n[Case 8] 長線金額占比加權, 天數判定 raw")
# 股票 L: 連續 16 天買 (≥15 天 → 長線), 但全在窗口前段 (舊)
# 股票 S: 今天 1 筆大買
dates_old = [f'202605{d:02d}' for d in range(1, 17)]   # 5/1~5/16, 16 天
trades8 = ([mk_trade(d, code='5555', amt=1000) for d in dates_old] +
           [mk_trade('20260610', code='6666', amt=16000)])
op8_raw = compute_operation_metrics(trades8)
op8_dec = compute_operation_metrics(trades8, decay_ref_date='20260610')
check("長線股數 = 1 (天數 raw, 不衰減)", op8_raw['long_term_stocks_count'] == 1)
check("衰減後長線股數仍 = 1 (天數判定不變)", op8_dec['long_term_stocks_count'] == 1,
      f"got {op8_dec['long_term_stocks_count']}")
check("衰減後長線金額占比 < 不衰減 (舊部位衰減)",
      op8_dec['long_term_amt_ratio'] < op8_raw['long_term_amt_ratio'],
      f"dec={op8_dec['long_term_amt_ratio']} raw={op8_raw['long_term_amt_ratio']}")

# ────────────────────────────────────────────────────────────────────
print("\n[Case 9] build_master_profile 整合: 錨點 = 窗口最新日")
history = []
for d in ['20260501', '20260520', '20260610']:
    history.append({
        'date': d,
        'data': {'branches': [{
            'code': '9A00', 'name': '測試分點', 'master': '測試大戶',
            'co_masters': [],
            'buys': [mk_trade(d, style='daytrade' if d == '20260610' else 'overnight')],
        }]},
    })
profile = build_master_profile('測試大戶', history, {'測試大戶': ['swing']})
op9 = profile['operation_metrics']
check("profile 產出 decay_applied = True", op9.get('decay_applied') is True,
      f"got {op9.get('decay_applied')}")
check("profile decay_half_life = 20", op9.get('decay_half_life') == 20)
# 錨點 20260610: 5/1 (w=0.25) + 5/20 (w≈0.483) overnight vs 6/10 daytrade (w=1.0)
# daytrade = 1.0/(0.25+0.483+1.0) ≈ 0.577 > overnight ≈ 0.423
check("近期 daytrade 主導 (加權生效)",
      op9['daytrade_ratio'] > op9['overnight_ratio'],
      f"daytrade={op9['daytrade_ratio']} overnight={op9['overnight_ratio']}")

# ────────────────────────────────────────────────────────────────────
print("\n[Case 10] timing metrics 不受衰減影響")
tm = compute_timing_metrics(trades4, 41)
check("active_days 照算 (2 天)", tm['active_days'] == 2, f"got {tm['active_days']}")
tm9 = profile['timing_metrics']
check("profile timing active_days = 3", tm9['active_days'] == 3,
      f"got {tm9['active_days']}")

# ────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"test_v3330_time_decay: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
