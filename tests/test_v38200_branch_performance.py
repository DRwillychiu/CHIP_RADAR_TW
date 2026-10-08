# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.82.0 分點績效模型 (使用者 2026-10-08: 損益與績效必須採用公認最完整的金融計算模型) — 離線

  A. FIFO 配對 + 手續費 0.1425% (雙邊) + 證交稅 0.3% (賣)
  B. 賣超過已知庫存 → 未配對, 不算損益, 另外回報
  C. Modified Dietz (GIPS) 教科書例題
  D. 期間損益一致性: V_end - V_begin - 淨流入 = 已實現 + 未實現 = 各持股損益加總;
     暖機期庫存以期初收盤價入帳, 暖機期的已實現不算進來
  E. 與大盤同步的部位: beta ≈ 1, 超額 ≈ 0 (只剩成本)
  F. 使用者原公式 (每千萬期望值) 照原樣重現, 並給 ÷10 的萬元版
"""
import branch_performance as bp

all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol * max(1.0, abs(b))


C, T = bp.COMMISSION, bp.TAX_SELL
print("=" * 72)
print("  v3.82.0 分點績效模型 (離線)")
print("=" * 72)

print("\nA. FIFO + 交易成本")
b = bp.Book()
out1 = b.buy(2000, 100)
out2 = b.buy(1000, 110)
cin = b.sell(2000, 120)
exp_real = 2000 * (120 * (1 - C - T) - 100 * (1 + C))
check("買進現金流含手續費", near(out1, 2000 * 100 * (1 + C)) and near(out2, 1000 * 110 * (1 + C)))
check("先賣先買進的 2 張 (FIFO), 已實現 = 2000 x (120x(1-0.1425%-0.3%) - 100x(1+0.1425%))",
      near(b.realized, exp_real), (round(b.realized, 2), round(exp_real, 2)))
check("剩 1 張成本 110x(1+0.1425%)", b.shares == 1000 and near(b.cost_basis(), 1000 * 110 * (1 + C)))
check("賣出現金流已扣手續費與證交稅", near(cin, 2000 * 120 * (1 - C - T)))

print("\nB. 未配對賣出")
b = bp.Book()
b.buy(1000, 50)
cin = b.sell(3000, 55)
check("只有 1 張配對, 2 張未配對且不產生現金與損益", b.unmatched_shares == 2000 and near(cin, 1000 * 55 * (1 - C - T))
      and near(b.realized, 1000 * (55 * (1 - C - T) - 50 * (1 + C))), b.unmatched_shares)

print("\nC. Modified Dietz 教科書例題")
r = bp.modified_dietz(100_000, 115_000, [(10, 10_000)], 30)
check("V0=100,000, 第 10/30 天流入 10,000, V1=115,000 → 4.6875%", near(r, 5000 / (100_000 + 10_000 * 20 / 30)),
      round(r, 6) if r is not None else r)

print("\nD. 期間損益一致性 (含暖機庫存)")
dates = ['d0', 'd1', 'd2', 'd3']
closes = {'AAA': {'w': 90, 'd0': 100, 'd1': 104, 'd2': 108, 'd3': 106},
          'BBB': {'d0': 50, 'd1': 50, 'd2': 55, 'd3': 60}}
index = {'d0': 1000, 'd1': 1010, 'd2': 1020, 'd3': 1015}
warm = [{'date': 'w', 'code': 'AAA', 'buy_lots': 5, 'sell_lots': 0, 'buy_amt': 5 * 90, 'sell_amt': 0}]
rows = [{'date': 'd1', 'code': 'AAA', 'buy_lots': 0, 'sell_lots': 2, 'buy_amt': 0, 'sell_amt': 2 * 104},
        {'date': 'd1', 'code': 'BBB', 'buy_lots': 4, 'sell_lots': 0, 'buy_amt': 4 * 50, 'sell_amt': 0},
        {'date': 'd2', 'code': 'BBB', 'buy_lots': 0, 'sell_lots': 1, 'buy_amt': 0, 'sell_amt': 55}]
res = bp.evaluate(rows, closes, index, dates, warmup_rows=warm, min_value=0)
check("期初市值 = 暖機 5 張 x 期初收盤 100 = 500,000", near(res['v_begin'], 500_000))
v_end = 3000 * 106 + 3000 * 60
check("期末市值 = AAA 3 張 x 106 + BBB 3 張 x 60", near(res['v_end'], v_end), res['v_end'])
real = 2000 * (104 * (1 - C - T) - 100) + 1000 * (55 * (1 - C - T) - 50 * (1 + C))
check("已實現: AAA 以期初價 100 為成本 (暖機成本 90 不算), BBB 含成本", near(res['realized_pnl'], real),
      (round(res['realized_pnl'], 1), round(real, 1)))
unreal = 3000 * (106 - 100) + 3000 * (60 - 50 * (1 + C))
check("總損益 = 期末 - 期初 - 淨流入 = 已實現 + 未實現", near(res['total_pnl'], real + unreal),
      (round(res['total_pnl'], 1), round(real + unreal, 1)))
check("持股統計: 2 檔, 都賺錢, 勝率 100%", res['positions'] == 2 and res['win_rate'] == 1.0, res['positions'])
check("Modified Dietz 與 TWR 都算得出來", res['md_return'] is not None and res['twr'] is not None)

print("\nE. 與大盤同步的部位")
days = [f'x{i:02d}' for i in range(40)]
idx = {d: 1000 * (1 + 0.01 * ((i * 7) % 5 - 2) / 2) ** 1 * (1 + i * 0.001) for i, d in enumerate(days)}
stock = {'IDX': {d: idx[d] / 10 for d in days}}
warm = [{'date': 'w', 'code': 'IDX', 'buy_lots': 100, 'sell_lots': 0, 'buy_amt': 100 * stock['IDX'][days[0]],
         'sell_amt': 0}]
res = bp.evaluate([], stock, idx, days, warmup_rows=warm, min_value=0)
check("beta = 1, alpha = 0, 超額損益 = 0 (沒有交易就沒有成本)", near(res['beta'], 1.0, 1e-9)
      and near(res['alpha_ann'], 0.0, 1e-9) and near(res['excess_pnl'], 0.0, 1e-6),
      (res['beta'], res['alpha_ann'], res['excess_pnl']))
check("Sharpe / Sortino / 最大回撤 有值", res['sharpe'] is not None and res['max_drawdown'] is not None
      and res['max_drawdown'] <= 0)

print("\nF. 使用者原公式")
# owner's 國票彰化 first 4 rows (buy lots, sell lots, buy 萬, buy avg, sell avg)
rows4 = [(1346, 1324, 16692, 124, 128.5), (37, 55, 2478, 665.68, 734.83),
         (1089, 1155, 4870, 44.69, 46.91), (637, 589, 19024, 298.41, 302.61)]
legacy, wan = bp.legacy_owner_metric(rows4)
pnl = [1324 * 4.5, 55 * (734.83 - 665.68), 1155 * (46.91 - 44.69), 589 * (302.61 - 298.41)]
exp = (sum(pnl) / 4) / ((16692 + 2478 + 4870 + 19024) / 4) * 1000
check("原公式照樣重現 (每檔損益 = 賣張 x (賣均-買均), 平均 / 平均下單 x 1000)", near(legacy, exp), round(legacy, 3))
check("萬元版 = 原值 / 10 (張 x 元 = 仟元)", near(wan, exp / 10))

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
