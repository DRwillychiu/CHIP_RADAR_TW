# Master 月度評估 SOP

> 每月 review 13 位追蹤 master 的 alpha 貢獻, 決定 PREMIUM_MASTERS 變動 / 汰換低貢獻 master / 招募新候選.

## 觸發頻率
**每月第一個交易日**, 跑完 daily-full 後執行.

## 步驟

### 1. 跑兩個 analyzer (per-master 雙維度)

```bash
python scripts/analyze_master_vol_spike_reliability.py
python scripts/analyze_master_contribution.py
```

- **analyzer #1** = per-master 自己配對的 picks hit% (vol_spike reliability)
- **analyzer #2** = LOO 對比「沒此 master 後整體 quad pool」 (contribution / 拖後腿判定)

兩個維度互補 — 高 hit% 不等於高 contribution (e.g. 陳律師 77.8% hit 但 LOO 差 -2.2pp = 「中性, 不增益」).

v3.71.16 snapshot (2026-06-26, n=38 quad pool):
- 核心 alpha (contrib ≥30% + Δpp >0): 無
- 輔助 (Δpp >+5pp): 竹科主力分點 (+13pp) / 陳族元 (+5.2pp)
- 中性 (|Δpp| ≤5): 陳律師 / 蔣承翰
- **拖後腿 (Δpp <-5pp)**: 強森 (-28.4pp ⚠️) / 張濬安(航海王) (-16.1) / Tradow (-13.3)
- 未貢獻 (n_with=0): 大牌分析師 / 巨人傑 / 布哥 / 林滄海 / 民哥 / 迷你哥(松山哥)

**注意**: 樣本 n=38 還小, Wilson CI 很寬, 不要因單月分析就 production 變動 (n≥80 後才 actionable).

第一個 analyzer 輸出按 hit% 排序的 master tier:

```
Master              trigger | picks | hit% | mean%
竹科主力分點             1   |   9   | 88.9 | +4.65
陳族元                  1   |   6   | 83.3 | +5.22
陳律師                  3   |  18   | 77.8 | +4.90
蔣承翰                  2   |   8   | 75.0 | +3.74
Tradow                  1   |   3   | 66.7 | +3.84
張濬安(航海王)           1   |   9   | 66.7 | +2.69
強森                   2   |  16   | 62.5 | +3.30
```

### 2. 對比上個月 snapshot

對照 `docs/MASTER_TIER_HISTORY.md` (本檔自動 append) 看:
- **進步 master**: hit% 上升 / 從未觸發 → 開始觸發
- **退步 master**: hit% 下降 / picks 增加但 hit 沒升 (alpha 衰退)
- **持平**: ±3pp 視為 noise, 不動

### 3. PREMIUM_MASTERS 變動決策

當前 (v3.71.5 snapshot 2026-06-26):
```python
PREMIUM_MASTERS = {'陳律師', '竹科主力分點', '陳族元'}
```

**升入 premium** 條件 (兩條皆滿足):
- hit% ≥ 77% AND
- n ≥ 5 picks (避免 1-pick noise)

**踢出 premium** 條件 (任一發生):
- hit% drop 持續 2 個月 < 70%
- 上月 n=0 (停止觸發)

若有變動, 改 `src/exports/excel_report.py` PREMIUM_MASTERS set, commit message 必含:
- 變動原因 (數字)
- 影響範圍 (預期 quad alpha 變化)

### 4. 從未觸發 master 評估 (6 位)

當前 6 位過去 30+ 天從未觸發 vol_spike:
大牌分析師 / 巨人傑 / 布哥 / 林滄海 / 民哥 / 迷你哥(松山哥)

**對每位檢查**:
- master_profiles.json 看活躍程度 (active_ratio / streak)
- 如果連 3 個月 active 但從未 vol_spike → **真低 alpha**, 列汰換候選
- 如果 active_ratio < 40% → **不夠活躍**, 不算汰換 (低頻精選型)

**汰換流程**:
1. 在 `src/core/master_mapping.py` 標 `disabled: true` (保 metadata 不 hard delete)
2. 等 1 個月觀察期, 看是否「冷凍突然爆發」
3. 仍未動 → hard delete + 更新 LABELS_DEFINITION

### 5. 新 master 招募評估

候選來源:
- 觀察非追蹤 master 在 Section 0 共識中出現頻率
- backtest 假設加入後 quad alpha 變化 (用 `scripts/bootstrap_combo_backtest.py` 加 mock filter)

**加入條件**:
- 過去 60 天有 ≥ 5 個 vol_spike trigger 日
- 主流分點公開 (避免分點輪換難追)

### 6. 文件化

每月評估後, append 到 `docs/MASTER_TIER_HISTORY.md`:

```markdown
## 2026-07 月度評估

**當前 PREMIUM**: {3}
**變動**: 無 / +名單 / -名單
**汰換候選**: [名單]
**新招募**: [名單]

### Per-master 數據 (vs 上月 △)
[Table]
```

---

## 不該做的事

- ❌ **不要根據 1 個月小樣本 (n<5) 升降 premium** — noise 太大
- ❌ **不要「全砍從未觸發」** — 低頻精選型 master 也有價值, 等他出手
- ❌ **不要改 PREMIUM 後不更新 commit message** — 必含數字 + 影響

---

## 歷史快照

| Date | PREMIUM | Notes |
|---|---|---|
| 2026-06-26 (v3.71.5) | 陳律師 / 竹科主力分點 / 陳族元 | 初始定義 (3 days × 33 picks backtest) |
