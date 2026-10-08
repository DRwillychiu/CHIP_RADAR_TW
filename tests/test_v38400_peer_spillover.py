# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib, random
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.84.0 R3 族群連動 (使用者 2026-10-08) — 離線

  A. X 大買龍頭後 0~3 日自己也買同族群 → same_branch_peer lift 高
  B. 其他分點在 X 大買後買老二 → other_branch_runner_up lift 高
  C. 不相干的族群 lift ≈ 1; 少於 3 檔的族群不用
"""
import peer_spillover as ps

all_pass = True


def check(label, ok, detail=''):
    global all_pass
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  ({detail})" if detail else ''))
    if not ok:
        all_pass = False


rnd = random.Random(5)
dates = [f'd{i:03d}' for i in range(150)]
groups = {'L1': 'MLCC', 'L2': 'MLCC', 'L3': 'MLCC', 'L4': 'MLCC', 'Z1': 'CEMENT', 'Z2': 'CEMENT', 'Z3': 'CEMENT',
          'P1': 'TINY', 'P2': 'TINY'}
rank = {'L1': 1, 'L2': 2, 'L3': 3, 'L4': 4, 'Z1': 1, 'Z2': 2, 'Z3': 3, 'P1': 1, 'P2': 2}
cells, events = {}, []
def put(d, c, b, amt):
    cells.setdefault((d, c), {})[b] = amt
for i, d in enumerate(dates):
    for c in groups:                                  # background: random small buys by N1..N3
        for b in ('N1', 'N2', 'N3'):
            if rnd.random() < 0.02:
                put(d, c, b, 2_000)
    if i % 15 == 0 and i + 3 < len(dates):            # X big-buys the MLCC leader (sparse) ...
        put(d, 'L1', 'X', 80_000)
        events.append(('X', d, 'L1'))
        put(dates[i + 1], 'L3', 'X', 20_000)          # ... adds a peer next day
        put(dates[i + 2], 'L2', 'Y', 15_000)          # ... Y buys the runner-up 2 days later
    if i % 7 == 3:                                    # X also big-buys cement leader, no follow-up
        put(d, 'Z1', 'X', 60_000)
        events.append(('X', d, 'Z1'))
    if i % 9 == 4:
        events.append(('X', d, 'P1'))
res = ps.spillover(cells, dates, groups, rank, events)
o = res['overall']

print("=" * 72)
print("  v3.84.0 R3 族群連動 (離線)")
print("=" * 72)
check("A. 自己隔天加碼同族群: same_branch_peer lift 高", o['same_branch_peer']['lift'] > 2,
      round(o['same_branch_peer']['lift'], 2))
mlcc = next(e for e in res['per_group'] if e['kind'] == 'other_branch_runner_up' and e['group'] == 'MLCC')
cem = next(e for e in res['per_group'] if e['kind'] == 'other_branch_runner_up' and e['group'] == 'CEMENT')
check("B. MLCC 龍頭被大買 → 其他分點 2 日內買老二: 族群 lift 高", mlcc['lift'] > 2 and mlcc['rate'] == 1.0,
      (round(mlcc['lift'], 2), mlcc['rate']))
check("B. 水泥龍頭被大買後沒人買老二: lift 低", (cem['lift'] or 0) < 1.5, cem['lift'])
check("老二事件只算龍頭被大買 (MLCC 與 水泥的龍頭)", o['other_branch_runner_up']['events'] == sum(
      1 for x, d, c in events if c in ('L1', 'Z1') and dates.index(d) + 3 < len(dates)), o['other_branch_runner_up']['events'])
check("C. 少於 3 檔的族群 (TINY) 不計入", res['groups_used'] == 2)
check("老二例子帶出 (龍頭, 老二, 族群)", any(e['leader'] == 'L1' and e['runner_up'] == 'L2' and e['group'] == 'MLCC'
                                         for e in res['runner_up_examples']))

print()
print("─" * 72)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
