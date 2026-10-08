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
check("X 大買 → Y 同日跟買: lift > 3、p 極小", xy and xy['lift'] > 3 and xy['p_value'] < 1e-10,
      xy and (round(xy['lift'], 1), xy['p_value']))
check("X 大買 → F 隔日跟買 (lag 1)", xf and xf['lift'] > 5 and xf['p_value'] < 1e-10, xf and round(xf['lift'], 1))
check("v3.83.2 強邊帶出同步事件 (X 日期, Y 日期, 股票)", xf and xf['events'] and all(
      dates.index(dy) == dates.index(dx) + 1 and (dx, c) in cells for dx, dy, c in xf['events']), xf and xf['events'][:2])
check("F 同日不跟 (lag 0 沒有強邊)", (get('X', 'F', 0) or {'lift': 0})['lift'] < 2)
noise = [e for e in edges if e['x'] in ('N1', 'N2') and e['y'] in ('N3', 'N4') and e['lag'] == 0]
# few co-buys pass min_co by chance (selection inflates their lift) -> judge by significance
check("背景分點彼此不顯著 (p > 0.001), 不會成為關係", all(e['p_value'] > 1e-3 for e in noise),
      [(round(e['lift'], 1), round(e['p_value'], 4)) for e in noise])
print("\nC/D. 同大戶與關係群")
xs = get('X', 'S', 0)
check("X 與 S 同一個大戶 → same_master", xs and xs['same_master'])
groups = rel.clusters(edges)
# X-S is excluded as same master, but Y-S (different masters) still co-trade -> one group
check("關係群 = {S, X, Y}: X-S 同大戶邊不算, 但 S 經由 Y 相連; F 是隔日跟, 不進同日群",
      groups and groups[0] == ['S', 'X', 'Y'] and all('F' not in g for g in groups), groups[:2])
check("binomial 尾機率正確: P(K>=2 | n=2, p=0.5) = 0.25", abs(rel._binom_sf(2, 2, 0.5) - 0.25) < 1e-12)
check("Poisson 尾機率正確: P(K>=1 | mean 1) = 1 - e^-1", abs(rel._poisson_sf(1, 1.0) - (1 - 2.718281828459045 ** -1)) < 1e-12)

print("\nF. 熱門股不可製造關聯 (v3.83.1, 真實 DB 第一次跑全部 83 個分點連成一群)")
cells2 = {}
for i, d in enumerate(dates):
    for c in stocks[:5]:                                       # 5 hot stocks: 30 crowd branches buy them daily
        for b in [f'H{j}' for j in range(30)]:
            if rnd.random() < 0.8:
                cells2.setdefault((d, c), {})[b] = 5_000
        cells2.setdefault((d, c), {})['BIG'] = 60_000           # BIG's big buys are always in hot stocks
    for c in rnd.sample(stocks[5:], 20):
        for b in [f'H{j}' for j in range(30)]:
            if rnd.random() < 0.1:
                cells2.setdefault((d, c), {})[b] = 3_000
e2 = rel.co_trading(cells2, dates)
hot = [e for e in e2 if e['x'] == 'BIG' and e['lag'] == 0]
check("大買都在熱門股的分點, 與一般活躍分點 lift ≈ 1 (調整擁擠度後)", hot and all(0.8 < e['lift'] < 1.25 for e in hot),
      sorted(round(e['lift'], 2) for e in hot)[:3])
check("熱門股情境不產生關係群", not rel.clusters(e2), rel.clusters(e2)[:1])

print("\nG. v3.83.3 多重檢定與重疊天數 (焦家 x 村長: 統一-內湖只追蹤 3 天, 13,251 組同時檢定)")
fake = [{"p_value": p, "lift": 1, "same_master": False} for p in (0.001, 0.01, 0.02, 0.04, 0.5)]
ranked = sorted(fake, key=lambda e: e["p_value"])
m, prev = len(ranked), 1.0
for rank in range(m, 0, -1):
    prev = min(prev, ranked[rank - 1]["p_value"] * m / rank)
    ranked[rank - 1]["q"] = prev
check("BH q-value 手算: p=(.001,.01,.02,.04,.5) -> q=(.005,.025,.0333,.05,.5)",
      [round(e["q"], 4) for e in ranked] == [0.005, 0.025, 0.0333, 0.05, 0.5])
qs = sorted((e["p_value"], e["q_value"]) for e in edges)
check("模組算出的 q 值單調且 >= p", all(q >= p - 1e-15 for p, q in qs)
      and all(qs[i][1] <= qs[i + 1][1] + 1e-15 for i in range(len(qs) - 1)))
cells3 = {k: dict(v) for k, v in cells.items()}
for d in dates[-4:]:                                    # NEW only exists 4 days, always with X
    for c in [c for (dd, c), row in cells3.items() if dd == d and row.get('X', 0) >= 50_000]:
        cells3[(d, c)]['NEW'] = 30_000
e3 = rel.co_trading(cells3, dates)
xn = next((e for e in e3 if e['x'] == 'X' and e['y'] == 'NEW' and e['lag'] == 0), None)
check("只有 4 天共同資料的強同步 → overlap_days < 20, 不算關係",
      xn and xn['overlap_days'] < rel.MIN_OVERLAP_DAYS and not rel.is_relation(xn), xn and xn['overlap_days'])
check("X-Y 長期同步仍是關係", rel.is_relation(get('X', 'Y', 0)))

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

print("\nH. v3.82.2 多重屬性 + 使用者標註 (2026-10-08)")
lab = lambda **m: sorted(bp.style_labels(m)["style_labels"])
check("新光-新竹: <=5 日 37% -> 波段/短線", lab(hold_le5=0.37, hold_le1=0.17, two_sided_share=0.55) == ["short_term", "swing"])
check("凱基-城中型: <=1 日 69% -> 加上隔日沖", "next_day_flipper" in lab(hold_le5=0.80, hold_le1=0.69))
check("強勢日門檻 = 當天漲幅 >= 7% (使用者 2026-10-08)", bp.STRONG_DAY == 0.07)
check("同日雙邊 55% 不再算當沖 (門檻 75%)", "day_trader" not in lab(hold_le5=0.4, hold_le1=0.1, two_sided_share=0.55))
import branches
check("使用者標註的 5 個分點寫在 BRANCH_STYLES", set(branches.BRANCH_STYLES) == {"8563", "779Z", "9217", "9666", "9B18"}
      and branches.BRANCH_STYLES["9B18"] == ["next_day_flipper", "short_term"])
src_rep = (pathlib.Path(__file__).resolve().parent.parent / "scripts" / "branch_performance_report.py").read_text(encoding="utf-8")
check("報告: 使用者標註優先, 評估期間依屬性 (both / recent / full)", 'style_source="owner" if owner else "measured"' in src_rep
      and 'res["judged_on"] = "both"' in src_rep)

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
