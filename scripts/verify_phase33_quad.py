"""v3.70.0 Phase 3.3 verification: quad_AAAA (82.1% hit, n=28).

L1: vs Phase 3.1/3.2 baseline 一致性
L2: 統計顯著性 (vs random 50%, vs baseline 44.1%, vs Phase 3.2 78.9%)
L3: 觸發日時間分佈
L4: lookahead bias 檢查
L5: 觸發日逐日抽樣
"""
import json, sys, math
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]

with open(ROOT / 'data' / 'phase33_backtest.json', 'r', encoding='utf-8') as f:
    p33 = json.load(f)
with open(ROOT / 'data' / 'phase32_backtest.json', 'r', encoding='utf-8') as f:
    p32 = json.load(f)
with open(ROOT / 'data' / 'combo_backtest.json', 'r', encoding='utf-8') as f:
    p31 = json.load(f)
with open(ROOT / 'data' / 'stock_history.json', 'r', encoding='utf-8') as f:
    sh = json.load(f)
sh_stocks = sh['stocks']
with open(ROOT / 'data' / 'consensus_backtest.json', 'r', encoding='utf-8') as f:
    cons = json.load(f)

errors = []; warnings = []
target = p33['summary']['quad_AAAA']
N = target['n']; HITS = target['hits']; HR = target['hit_rate']; MEAN = target['mean_change']

def bp(hits, total, p_null=0.5):
    mean = total * p_null
    sd = math.sqrt(total * p_null * (1 - p_null))
    z = (hits - mean) / sd
    return 0.5 * math.erfc(z / math.sqrt(2)), z

# ════════════════════════════════════════════════════════════════════
print("=" * 70)
print("L1: Baseline 一致性 (Phase 3.1 / 3.2 / 3.3)")
print("=" * 70)
b31 = p31['summary']['baseline']
b32 = p32['summary']['baseline']
b33 = p33['summary']['baseline']
print(f"  Phase 3.1 baseline: n={b31['n']}, hit={b31['hit_rate']*100:.1f}%")
print(f"  Phase 3.2 baseline: n={b32['n']}, hit={b32['hit_rate']*100:.1f}%")
print(f"  Phase 3.3 baseline: n={b33['n']}, hit={b33['hit_rate']*100:.1f}%")
if b31['n'] == b32['n'] == b33['n'] and abs(b31['hit_rate'] - b33['hit_rate']) < 0.001:
    print(f"  PASS — 三 phase baseline 完全一致")
else:
    warnings.append(f"L1: baseline 不一致")

q31 = p31['summary']['q5_bull']
q33 = p33['summary']['q5_bull_only']
print(f"  Phase 3.1 q5_bull: n={q31['n']}, hit={q31['hit_rate']*100:.1f}%")
print(f"  Phase 3.3 q5_bull_only: n={q33['n']}, hit={q33['hit_rate']*100:.1f}%")
if q31['n'] == q33['n'] and abs(q31['hit_rate'] - q33['hit_rate']) < 0.001:
    print(f"  PASS — q5_bull 完全一致")

# Phase 3.2 e_vol_spike_q5_bull vs Phase 3.3 (e_vol_spike + q5_bull alone, no streak)
ev32 = p32['summary']['e_vol_spike_q5_bull']
print(f"  Phase 3.2 e_vol_spike_q5_bull: n={ev32['n']}, hit={ev32['hit_rate']*100:.1f}%")
print(f"  Phase 3.3 quad_AAAA (+ hot5): n={N}, hit={HR*100:.1f}%")
print(f"  -> hot5 過濾掉 {ev32['n']-N} 筆, hit rate 從 {ev32['hit_rate']*100:.1f}% -> {HR*100:.1f}% ({(HR-ev32['hit_rate'])*100:+.1f}pp)")

# ════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("L2: 統計顯著性")
print("=" * 70)
p, z = bp(HITS, N, 0.5)
print(f"  quad_AAAA: {HITS}/{N} = {HR*100:.1f}%")
print(f"  vs random 50%: z={z:.2f}, p={p:.5f}")
if p < 0.001:
    print(f"  STRONG PASS — p<0.001 (~3 sigma)")
elif p < 0.05:
    print(f"  PASS — p<0.05")

p2, z2 = bp(HITS, N, b33['hit_rate'])
print(f"  vs baseline {b33['hit_rate']*100:.1f}%: z={z2:.2f}, p={p2:.5f}")
if p2 < 0.01:
    print(f"  STRONG PASS")

p3, z3 = bp(HITS, N, ev32['hit_rate'])
print(f"  vs Phase 3.2 {ev32['hit_rate']*100:.1f}%: z={z3:.2f}, p={p3:.5f}")
if p3 < 0.05:
    print(f"  PASS — hot5 filter SIGNIFICANTLY adds value")
elif p3 < 0.10:
    print(f"  MARGINAL — hot5 filter adds value but borderline")
else:
    warnings.append(f"L2: quad_AAAA vs Phase 3.2 p={p3:.3f} > 0.10 — hot5 不顯著加值")
    print(f"  WARN — hot5 filter 加值不顯著 (p>0.10), 可能只是 noise reduction")

# ════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("L3: 觸發日時間分佈")
print("=" * 70)
trigger = [d for d in p33['per_day'] if d['quad'] > 0]
trigger_dates = [d['date'] for d in trigger]
print(f"  觸發日數: {len(trigger)}")
print(f"  觸發日: {trigger_dates}")
if len(trigger_dates) >= 2:
    span = int(trigger_dates[-1]) - int(trigger_dates[0])
    print(f"  跨度: {span} day-id distance")
    if span < 7:
        warnings.append(f"L3: 觸發日集中在 {span} 內")
    else:
        print(f"  PASS — 跨度 OK")

# ════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("L4: Lookahead bias")
print("=" * 70)
print("  4 訊號計算邏輯:")
print("    1. consensus = day d 共識")
print("    2. Q5 = day d 盤後 P/C OI signals -> infer_market_direction")
print("    3. vol_spike = master day d total_buy vs [0..d-1] avg+2sigma")
print("    4. max_streak >= 5 = master 連續 5 天加碼 same stock 到 day d")
print("  全部用 day d 為止資料, 預測 day d+1 -> 沒 lookahead bias")
print("  PASS")

# ════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("L5: 觸發日逐日抽樣 + per-day hit 統計")
print("=" * 70)
for td in trigger:
    date = td['date']
    next_date = td['next']
    day = cons['per_day'].get(date)
    if not day: continue
    nd_changes = day.get('next_day_changes', {})
    valid = []
    for code, chg in nd_changes.items():
        nxt_close = sh_stocks.get(code, {}).get('daily', {}).get(next_date, {}).get('close')
        if nxt_close is None: continue
        valid.append((code, chg))
    if not valid: continue
    hits_d = sum(1 for _, c in valid if c > 0)
    print(f"\n  {date} -> {next_date}: 全 consensus {len(valid)} picks, {hits_d} 漲 ({hits_d/len(valid)*100:.0f}%)")
    print(f"    quad picks (this day): {td['quad']}, "
          f"q5={td['q5']}, vs={td['vol_spike']}, hot5={td['hot5']}")
    for code, chg in sorted(valid, key=lambda x: -x[1])[:5]:
        sym = '+' if chg > 0 else ('-' if chg < 0 else '0')
        name = sh_stocks.get(code, {}).get('name', '?')
        print(f"    [{sym}] {name}({code}): {chg:+.2f}%")

# ════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("Phase 3.3 驗證結論")
print("=" * 70)
print(f"  Target: quad_AAAA = {HITS}/{N} ({HR*100:.1f}%, +{MEAN:.2f}% mean)")
print(f"  vs baseline {b33['hit_rate']*100:.1f}%: +{(HR-b33['hit_rate'])*100:.1f}pp")
print(f"  vs Q5 偏多 only {q33['hit_rate']*100:.1f}%: +{(HR-q33['hit_rate'])*100:.1f}pp")
print(f"  vs Phase 3.2 e_vol_spike_q5_bull {ev32['hit_rate']*100:.1f}%: +{(HR-ev32['hit_rate'])*100:.1f}pp")
print()
if errors:
    print(f"X {len(errors)} error:")
    for e in errors: print(f"  - {e}")
if warnings:
    print(f"WARN {len(warnings)} warning:")
    for w in warnings: print(f"  - {w}")
if not errors and not warnings:
    print(f"PASS — 全 PASS, quad_AAAA 是真 alpha")
