# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, random
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.83.0 R2 分點同步操作 + v3.82.1 分點屬性 (使用者 2026-10-08) — 離線

  A. Y 在 X 大買的同一天幾乎都跟買 → lift 高、p 值極小; 隔天才跟 → lag 1 抓到
  B. 互不相干的分點 → lift ≈ 1
  C. 同一個大戶的分點互相同步 → 標 same_master, 不進關係群
  D. 關係群 = 強同步邊的連通分量
  E. 屬性: 當沖 (同日雙邊) / 隔日沖 (持有 <= 1 日) / 短線 / 波段 / 長抱, 與對應的評估期間
"""
import branch_relations as rel
import branch_performance as bp

all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


rnd = random.Random(3)
dates = [f'2026{m:02d}{d:02d}' for m in (7, 8, 9) for d in range(1, 29)][:70]
stocks = [str(1000 + i) for i in range(120)]
cells = {}
def put(d, c, b, amt):
    cells.setdefault((d, c), {})[b] = amt
for i, d in enumerate(dates):
    for c in rnd.sample(stocks, 40):
        for b in ('N1', 'N2', 'N3', 'N4'):                     # background noise branches
            if rnd.random() < 0.15:
                put(d, c, b, rnd.choice([1, -1]) * rnd.randint(1000, 30000))
    for c in rnd.sample(stocks, 3):                            # X big buys, Y same day, F next day, S same master
        put(d, c, 'X', 50_000)
        put(d, c, 'Y', 20_000)
        put(d, c, 'S', 15_000)
        if i + 1 < len(dates):
            put(dates[i + 1], c, 'F', 18_000)
masters = {'X': ['M1'], 'S': ['M1'], 'Y': ['M2'], 'F': ['M3']}
edges = rel.co_trading(cells, dates, masters=masters)
get = lambda x, y, lag: next((e for e in edges if e['x'] == x and e['y'] == y and e['lag'] == lag), None)

print("=" * 72)
print("  v3.83.0 分點同步操作 / v3.82.1 分點屬性 (離線)")
print("=" * 72)
print("\nA/B. lift 與方向")
xy, xf = get('X', 'Y', 0), get('X', 'F', 1)
check("X 大買 → Y 同日跟買: lift 高、p 極小", xy and xy['lift'] > 5 and xy['p_value'] < 1e-10,
      xy and (round(xy['lift'], 1), xy['p_value']))
check("X 大買 → F 隔日跟買 (lag 1)", xf and xf['lift'] > 5 and xf['p_value'] < 1e-10, xf and round(xf['lift'], 1))
check("F 同日不跟 (lag 0 沒有強邊)", (get('X', 'F', 0) or {'lift': 0})['lift'] < 2)
noise = [e for e in edges if e['x'] in ('N1', 'N2') and e['y'] in ('N3', 'N4') and e['lag'] == 0]
check("背景分點彼此 lift ≈ 1", noise and all(0.5 < e['lift'] < 2 for e in noise), [round(e['lift'], 2) for e in noise])
print("\nC/D. 同大戶與關係群")
xs = get('X', 'S', 0)
check("X 與 S 同一個大戶 → same_master", xs and xs['same_master'])
groups = rel.clusters(edges)
# X-S is excluded as same master, but Y-S (different masters) still co-trade -> one group
check("關係群 = {S, X, Y}: X-S 同大戶邊不算, 但 S 經由 Y 相連; F 是隔日跟, 不進同日群",
      groups and groups[0] == ['S', 'X', 'Y'] and all('F' not in g for g in groups), groups[:2])
check("binomial 尾機率正確: P(K>=2 | n=2, p=0.5) = 0.25", abs(rel._binom_sf(2, 2, 0.5) - 0.25) < 1e-12)

print("\nE. 分點屬性")
st = bp.style_metrics([], [{'buy_lots': 10, 'sell_lots': 9}, {'buy_lots': 10, 'sell_lots': 8}], 20_000)
check("同日雙邊 >= 50% → 當沖型, 用近期評估", st['style'] == 'day_trader' and st['horizon'] == 'recent', st['style'])
st = bp.style_metrics([(1000, 1), (1000, 1), (1000, 4)], [{'buy_lots': 3, 'sell_lots': 0}], 3000)
check("配對賣出 2/3 持有 <= 1 日 → 隔日沖型", st['style'] == 'next_day_flipper' and abs(st['hold_le1'] - 2 / 3) < 1e-9,
      st['style'])
st = bp.style_metrics([(1000, 12), (1000, 15), (1000, 9)], [{'buy_lots': 4, 'sell_lots': 0}], 4000)
check("持有中位數 12 日、配對比 75% → 波段型, 用 60 日評估", st['style'] == 'swing' and st['horizon'] == 'full'
      and st['hold_median'] == 12, (st['style'], st['hold_median']))
st = bp.style_metrics([(1000, 40)], [{'buy_lots': 10, 'sell_lots': 0}], 10000)
check("配對比只有 10% (多半還抱著) → 長抱型", st['style'] == 'longterm', st['style'])
b = bp.Book()
b.buy(1000, 10, day=3)
b.buy(1000, 11, day=5)
b.sell(1500, 12, day=9)
check("FIFO 持有天數: 1000 股 6 日、500 股 4 日", b.holds == [(1000, 6), (500, 4)], b.holds)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
