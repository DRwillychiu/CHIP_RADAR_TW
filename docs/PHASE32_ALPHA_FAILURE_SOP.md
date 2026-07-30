# Phase 3.2 Quad Alpha 失效 SOP

> 當 ⭐ Phase 3.2 quad alpha (78.9% hit) 在 production 30d rolling 持續 <50%, 該怎麼做.
> 不是「假警報」就是「真失效」, 都要有計畫.

## 1. 觸發條件 (自動 alarm)

`_build_section_consensus` → Section 0 sub-banner #2 (Phase 3.2 三訊號) 自動偵測:

```
if rolling_30d.n >= 20 AND rolling_30d.hit_rate < 50%:
    verdict = "⚠️ alpha 可能失效 (30d 實戰 <50%) — 建議暫停使用直至改善"
    color = 紅
```

優先級: 高於「強 alpha」verdict, 不會被遮蔽。

**當前實戰** (2026-06-26 snapshot, `data/quad_hit_log.json`):
- `rolling_30d`: 2 trigger days / n=17 / hits=11 / 64.7%
- `rolling_all`: 5 trigger days / n=38 / hits=30 / 78.9%
- `vs_expected`: actual 0.7895 vs expected 0.789 (delta 0.0pp, 完美吻合)

樣本還小, alarm 至今未觸發。

---

## 2. 立即行動 (alarm 觸發後 24 小時內)

### Step 1: 確認不是 false alarm

開 `data/quad_hit_log.json` 看 `trigger_days[-5:]`:
- 最近 5 個 trigger day 各自 hit/total, 是不是有 1-2 個極端值拉低 (e.g. 1 個 0/8 拖整體)
- 若極端值是「特殊事件日」 (FOMC / TWSE 系統故障 / 結算日) → 不算失效, 排除後 hit 是否回 ≥70%

### Step 2: 對照 4 enrichment sheet
- 📉 Quad 失效歸因 sheet: 失敗原因分布 (TAIEX 整盤跌 / 假共識 / 個股弱勢 / Q5 borderline / alpha noise)
- 若 ≥3 連續 trigger day 歸因 「TAIEX 整盤跌」 → 不是 quad 失效, 是市場 regime change
- 若 ≥3 連續日歸因 「個股弱勢」 → 真失效訊號 (quad master 看走眼)

### Step 3: 切割 premium vs standard
- v3.71.5 PREMIUM_MASTERS (陳律師/竹科主力/陳族元) 是否仍 ≥70%?
- 若 premium 仍 OK 只是 standard 拖累 → 限縮到 premium-only quad
- 若 premium 也跌破 → 真 alpha 失效

---

## 3. 短期應對 (1-3 天)

| 診斷結果 | 動作 |
|---|---|
| 市場 regime change (TAIEX 連跌) | **不動 alpha**, Email subject 加 ⚠️ 提示, 用戶自行降低 quad 跟單比例 |
| 個股弱勢 ≥3 天 (真失效起點) | 在 sub-banner verdict 顯示「alpha 失效 day 1/N」累積, 用戶心理準備 |
| 噪音 / 1-2 個極端日 | 不採取行動, 觀察至下次 trigger |
| premium 仍 OK, standard 拖累 | 提案: 升級 quad 標準, 只標 premium ⭐⭐ |

---

## 4. 中期決策 (5-10 個 trigger days 後)

若 alarm 持續 ≥1 週 (n≥30, hit 仍 <55%):

**Option A — recall PREMIUM_MASTERS**
- 重跑 `analyze_master_vol_spike_reliability.py` (用最新 quad_hit_log)
- 重新挑 ≥77% hit master, update `PREMIUM_MASTERS` set
- 可能某些 master 從 premium 跌出, 某些升上來

**Option B — 砍 Phase 3.2 sub-banner (暫停 quad)**
- 在 `_build_section_consensus` 加 `QUAD_DISABLED = True` flag (algo_params.yaml)
- Section 0 / Action / Mobile 不再標 ⭐, 用戶看 baseline 44.1% 共識
- Email body 顯示「⚠️ Phase 3.2 alpha 暫停, 觀察中」

**Option C — 提升 quad 嚴格度**
- master_count ≥10 → ≥12 (更高共識門檻)
- 加 outlier filter (leader_pct < 50% 排假共識)
- 重跑 backtest 看新嚴格 quad hit 是否回 ≥70%

**Option D — 切換到 mild_up_only (反向)**
- audit 已揭穿 mild_up_only 41.7% trap, 若 mild_up_only short → 期望 59% hit
- 風險: short 機制台股不友善, 不適合散戶

---

## 5. Recall 條件 (alpha 恢復後)

如果 alpha 已暫停 (Option B), 何時恢復?

**自動 recall 觸發**:
- 30d rolling 重回 ≥65% hit AND n ≥ 20
- 連續 3 個 trigger day 都 ≥3/4 hit

**手動 recall**:
- 用戶觀察市場 regime 已穩定 (TAIEX 連 5 日正常波動)
- 重跑 phase32 backtest, 確認新 30 天 hit ≥65%

Recall 後仍需要 1 週觀察期, sub-banner 標「⚠️ 試運行, 信心待累積」直到 n≥30 + hit ≥70%。

---

## 6. 通訊 (Email body 影響)

`scripts/extract_mobile_summary_text.py` 抓 Mobile sheet, Mobile sheet 顯示 quad 命中。

**alarm 觸發時 email body 變化**:
- Mobile sheet ⭐ Quad 命中 section 標題改為 「⚠️ Quad 命中 (alpha 警示中, 跟單需謹慎)」
- 命中股 prefix 改 ⚠️ (不再 🎯)
- Subject 也可加 `⚠️ alpha 警示` 提示

**alpha 暫停時 (Option B)**:
- Mobile sheet 完全砍 ⭐ Quad section
- Email subject 加「[alpha 暫停]」前綴

---

## 7. 記錄追蹤

每次 alarm 觸發 + 應對動作必須寫 `docs/PHASE32_ALPHA_INCIDENTS.md` (incident log):
- 觸發日期
- 觸發數字 (rolling_30d hit% / n)
- 診斷結果 (regime / 個股弱勢 / 噪音)
- 採取動作 (Option A/B/C/D)
- recall 日期 (若有)
- lessons learned

每個 incident 是 alpha 演化的重要 data point, 比新增 feature 更值錢。

---

## 8. 教訓 (寫在 SOP 前面, 避免重蹈覆轍)

- **不要 panic** — n<20 觸發的 alarm 大多是噪音
- **不要 over-react** — 砍 quad 是激進動作, 先檢查歸因再決定
- **保留 premium** — 即使整體 quad 失效, 高信心 master 通常仍 OK
- **記錄是 alpha** — 每次 incident 教 quad 結構性 weakness, 比 backtest 純數字有用
- **Email 提示 > 砍訊號** — 用戶有自主權, 系統提供資訊 + 警示, 不替用戶決定買賣

---

**版本紀錄**:
- v3.71.6 (2026-06-26): SOP doc 建立
- Next review: alarm 觸發後立刻 review, 或季度 review (2026-09-30)
