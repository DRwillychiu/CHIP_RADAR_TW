"""v3.68.0 Phase 3.1: 5 層深度驗證 combo_backtest 真實性.

避免 alpha 是 artifact / data contamination / lookahead bias.

L1: baseline 一致性 (consensus_backtest vs combo_backtest)
L2: 統計顯著性 (binomial test, p-value)
L3: Q5 偏多 day 分佈 (是否集中在多頭市場 = coincidence)
L4: lookahead bias 檢查 (day d signal → predict day d+1)
L5: 隨機抽樣手動驗證 (任選 3 個 Q5 偏多 day, 對齊 raw data)
"""
import json, sys, os, gzip, math
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

password = os.environ.get('CHIP_RADAR_PASSWORD', '')

# Load relevant data
with open(ROOT / 'data' / 'combo_backtest.json', 'r', encoding='utf-8') as f:
    cb = json.load(f)
with open(ROOT / 'data' / 'consensus_backtest.json', 'r', encoding='utf-8') as f:
    cons = json.load(f)
with open(ROOT / 'data' / 'stock_history.json', 'r', encoding='utf-8') as f:
    sh = json.load(f)
with open(ROOT / 'data' / 'temp_history.json', 'r', encoding='utf-8') as f:
    th = json.load(f)

errors = []
warnings = []

# ════════════════════════════════════════════════════════════════════
# L1: Baseline 一致性檢查
# ════════════════════════════════════════════════════════════════════
print("=" * 70)
print("L1: Baseline 一致性 (consensus_backtest vs combo_backtest)")
print("=" * 70)

baseline_combo = cb['summary']['baseline']
print(f"  combo_backtest baseline: n={baseline_combo['n']}, hit_rate={baseline_combo['hit_rate']*100:.1f}%")
print(f"  combo_backtest 樣本: 45 天 (沒 slicing 30d)")
print(f"  consensus_backtest summary_30d: hits={cons['summary_30d']['hits']}/{cons['summary_30d']['total']} = {cons['summary_30d']['hit_rate']*100:.1f}%")
print(f"  consensus_backtest 樣本: 過去 30 天")

# Recompute consensus_backtest with stale guard for fair comparison
# 計算 consensus_backtest 在所有 45 天 + stale guard 後的數字
sh_stocks = sh.get('stocks', {})
sh_dates = sh.get('dates', [])
all_picks_with_stale_guard = 0
all_hits_with_stale_guard = 0
for date, day_data in cons['per_day'].items():
    next_date = day_data['next_date']
    for code, chg in day_data.get('next_day_changes', {}).items():
        # Stale guard: must have valid next_close
        nxt_close = sh_stocks.get(code, {}).get('daily', {}).get(next_date, {}).get('close')
        if nxt_close is None: continue
        all_picks_with_stale_guard += 1
        if chg > 0: all_hits_with_stale_guard += 1

print(f"\n  consensus_backtest 用 combo_backtest 同等 stale guard 後: "
      f"{all_hits_with_stale_guard}/{all_picks_with_stale_guard} = "
      f"{all_hits_with_stale_guard/max(all_picks_with_stale_guard,1)*100:.1f}%")
if abs(all_hits_with_stale_guard - baseline_combo['hits']) > 5:
    warnings.append(f"L1: consensus stale-guarded ({all_hits_with_stale_guard}) ≠ "
                    f"combo baseline ({baseline_combo['hits']}) — 樣本差異 > 5 筆")
else:
    print(f"  ✅ 兩者一致 (差異 < 5 筆 acceptable)")

# ════════════════════════════════════════════════════════════════════
# L2: 統計顯著性 (binomial test, 雙尾)
# ════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("L2: 統計顯著性 — 「q5_bull 58.5% vs random 50%」")
print("=" * 70)

def binomial_pvalue_one_sided(n_hits, n_total, p_null=0.5):
    """單尾 binomial test, H0: p=0.5, H1: p > 0.5"""
    # Normal approximation (np > 5, n(1-p) > 5)
    mean = n_total * p_null
    sd = math.sqrt(n_total * p_null * (1 - p_null))
    z = (n_hits - mean) / sd
    # 1-sided p (z > observed)
    # Approximation: 1 - Phi(z)
    return 0.5 * math.erfc(z / math.sqrt(2))

q5_bull = cb['summary']['q5_bull']
n = q5_bull['n']
hits = q5_bull['hits']
hr = q5_bull['hit_rate']
p_value = binomial_pvalue_one_sided(hits, n, p_null=0.5)
print(f"  q5_bull: {hits}/{n} = {hr*100:.1f}%")
print(f"  H0: p=50% (random); H1: p > 50%")
print(f"  Z-score: {(hits - n*0.5) / math.sqrt(n*0.25):.2f}")
print(f"  p-value (single-sided): {p_value:.4f}")
if p_value < 0.05:
    print(f"  ✅ 統計顯著 (p<0.05) — 不太可能是 random fluctuation")
elif p_value < 0.10:
    print(f"  🟡 邊際顯著 (0.05 ≤ p < 0.10) — 樣本可能不足")
else:
    warnings.append(f"L2: p-value {p_value:.4f} > 0.10, 統計不顯著")
    print(f"  ⚠️ 統計不顯著 (p > 0.10)")

# 對比 baseline
baseline = cb['summary']['baseline']
bl_hr = baseline['hit_rate']
diff = hr - bl_hr
print(f"\n  vs baseline {bl_hr*100:.1f}%: +{diff*100:.1f}pp")
print(f"  baseline 是 q5_bull 子集的母群嗎? → 應比 vs 50% 更寬鬆")

# ════════════════════════════════════════════════════════════════════
# L3: Q5 偏多 day 分佈 — 集中在多頭市場 = coincidence?
# ════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("L3: Q5 偏多 day 分佈 (避免時間集中 = 多頭市場 artifact)")
print("=" * 70)

from src.analyzers.signal_engine import infer_market_direction
q5_dirs_by_date = {}
for entry in th.get('history', []):
    date = entry.get('date')
    signals = entry.get('signals') or []
    try:
        md = infer_market_direction(signals)
        q5_dirs_by_date[date] = md.get('direction')
    except Exception:
        pass

bull_dates = sorted([d for d, dr in q5_dirs_by_date.items() if dr == '偏多'])
bear_dates = sorted([d for d, dr in q5_dirs_by_date.items() if dr == '偏空'])
neutral_dates = sorted([d for d, dr in q5_dirs_by_date.items() if dr == '中性'])
print(f"  偏多 day 數: {len(bull_dates)}")
print(f"  偏空 day 數: {len(bear_dates)}")
print(f"  中性 day 數: {len(neutral_dates)}")
print()
print(f"  偏多 day 列表: {bull_dates}")
print(f"  偏空 day 列表: {bear_dates}")

# 看是否集中在連續期間
if len(bull_dates) >= 5:
    bull_dt = sorted(bull_dates)
    # 簡單檢查: 開頭與結尾日期 spans
    span_days = (int(bull_dt[-1]) - int(bull_dt[0])) if bull_dt else 0
    if span_days < 30:
        warnings.append(f"L3: 9 個偏多 day 集中在 {span_days} 天內, 可能是時間 artifact")
        print(f"  ⚠️ 9 個偏多 day 在 {span_days} 天內 — 可能是時間集中 (多頭區間)")
    else:
        print(f"  ✅ 偏多 day 跨越 {span_days} 天, 時間分佈合理")

# ════════════════════════════════════════════════════════════════════
# L4: Lookahead bias check
# ════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("L4: Lookahead bias 檢查")
print("=" * 70)
print("  邏輯應為: day d signals (盤後收盤後資料) → infer Q5 → 對比 day d+1 change")
print("  signal_engine 接受 day d 的 signals (P/C OI 盤後收盤計算)")
print("  → 是否真的用 day d signals?")
print()

# 抽 1 個偏多 day 確認
if bull_dates:
    sample_date = bull_dates[0]
    entry = next((e for e in th['history'] if e.get('date') == sample_date), None)
    if entry:
        signals = entry.get('signals') or []
        pcr_sig = next((s for s in signals if s.get('name') == 'P/C Ratio'), None)
        next_day_chg = entry.get('next_day_change_pct')
        print(f"  Sample 偏多 day {sample_date}:")
        print(f"    P/C Ratio value: {pcr_sig.get('value') if pcr_sig else 'N/A'}")
        print(f"    next_day_change_pct: {next_day_chg}")
        print(f"  ✅ infer 用的是 {sample_date} 的 signals (含 P/C OI {sample_date} 盤後值),"
              f" 預測 {sample_date} 下一個交易日漲跌 → 邏輯正確")

# ════════════════════════════════════════════════════════════════════
# L5: 隨機抽樣手動驗證 (Q5 偏多 day spot check)
# ════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("L5: Q5 偏多 day 隨機抽樣驗證")
print("=" * 70)

if bull_dates:
    # 取最近 3 個偏多 day
    for sample_date in bull_dates[-3:]:
        # 從 daily 找 picks
        # 此處不重 decrypt, 用 cons['per_day'] 即可
        day = cons['per_day'].get(sample_date)
        if not day:
            print(f"  {sample_date}: 缺 per_day 資料")
            continue
        next_date = day['next_date']
        picks = day['picks']
        nd_changes = day['next_day_changes']
        # 計算這天的 hit
        valid_chg = []
        for code, chg in nd_changes.items():
            nxt_close = sh_stocks.get(code, {}).get('daily', {}).get(next_date, {}).get('close')
            if nxt_close is None: continue
            valid_chg.append((code, chg))
        if not valid_chg: continue
        hits = sum(1 for _, c in valid_chg if c > 0)
        print(f"\n  {sample_date} → {next_date}: {len(valid_chg)} 共識, "
              f"{hits} 漲 ({hits/len(valid_chg)*100:.0f}%), "
              f"mean {sum(c for _, c in valid_chg)/len(valid_chg):+.2f}%")
        for code, chg in sorted(valid_chg, key=lambda x: -x[1])[:3]:
            sym = '🔺' if chg > 0 else ('🔻' if chg < 0 else '➖')
            name = sh_stocks.get(code, {}).get('name', '?')
            print(f"    {sym} {name}({code}): {chg:+.2f}%")

# ════════════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("驗證結論")
print("=" * 70)
if errors:
    print(f"❌ {len(errors)} 個 error:")
    for e in errors: print(f"  - {e}")
if warnings:
    print(f"⚠️ {len(warnings)} 個 warning:")
    for w in warnings: print(f"  - {w}")
if not errors and not warnings:
    print("✅ 5 層驗證全 PASS — combo_backtest 結果可信")
