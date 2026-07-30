"""v3.71.17 N6 review: disposal_history snapshot 成熟度 audit.

v3.36.2 D 方案決定「等 30 天後 ~7/4 重評」, 因為早期 first_active_date 全卡在 6/4
→ 28/29 master 「處置中買進」全中 = 噪音.

本 script 提前 review (6/27, 累積 21 snapshot):
  1. 看 first_active_date 分布是否散開
  2. 看 「bought_during_disposal」 master 數是否回歸合理 (< 28/29)
  3. 結論: 是否可提前開「⚠️ 處置玩家」標籤
"""
import json, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
HIST_DIR = ROOT / 'data' / 'disposal_history'

files = sorted(HIST_DIR.glob('*.json'))
print(f"=== disposal_history snapshots ===")
print(f"total: {len(files)}, range: {files[0].stem} ~ {files[-1].stem}\n")

# Build per-stock first_active_date (first time appearing in snapshot)
stock_first_seen = {}
all_stocks_per_day = defaultdict(set)
for f in files:
    date = f.stem
    data = json.loads(f.read_text(encoding='utf-8'))
    sets = data.get('sets') or {}
    # sets 可能含 'in_disposal' / 'pending' etc
    for k, codes in sets.items():
        if isinstance(codes, list):
            for c in codes:
                if c not in stock_first_seen:
                    stock_first_seen[c] = date
                all_stocks_per_day[date].add(c)

# first_active_date distribution
first_dates = Counter(stock_first_seen.values())
print(f"=== first_active_date 分布 (越分散越好) ===")
print(f"{'date':<12} {'new stocks'}")
for d, n in sorted(first_dates.items()):
    bar = '█' * min(n, 40)
    print(f"  {d}  {n:>3}  {bar}")

oldest = files[0].stem
oldest_count = first_dates.get(oldest, 0)
total_stocks = len(stock_first_seen)
oldest_pct = oldest_count / total_stocks * 100 if total_stocks else 0
print(f"\n第一天 ({oldest}) 占比: {oldest_count}/{total_stocks} = {oldest_pct:.1f}%")
print(f"  > 50% → 嚴重 clip (歷史處置股全卡這天)")
print(f"  20-50% → 中度 clip")
print(f"  < 20% → 散開充足, 可開標籤")

# Per-day stocks count (看是否穩定有 ~280 risk stocks)
print(f"\n=== Per-day risk stocks count (應該 stable 200-300) ===")
for f in files[-5:]:
    date = f.stem
    n = len(all_stocks_per_day[date])
    print(f"  {date}: {n}")

# 結論
print(f"\n=== 結論 ===")
if oldest_pct > 50:
    print(f"⚠️ 第一天占比 {oldest_pct:.1f}% > 50% → 嚴重 clip, **不建議提前開標籤**")
    print(f"   建議: 等到 ~7/4 後 (再 ~5 個交易日) re-audit")
elif oldest_pct > 20:
    print(f"🟡 第一天占比 {oldest_pct:.1f}% (20-50%) → 中度 clip")
    print(f"   建議: 開「⚠️ 處置玩家」標籤但加 「資料窗口未滿 30 天」註腳, 用戶自行判斷")
else:
    print(f"✅ 第一天占比 {oldest_pct:.1f}% < 20% → 散開充足")
    print(f"   建議: 可以提前開「⚠️ 處置玩家」標籤")
