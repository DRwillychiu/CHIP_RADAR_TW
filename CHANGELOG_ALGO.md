# Chip Radar TW · 演算法參數變更紀錄

> **目的**:每次 `config/algo_params.yaml` 變動都留底,確保「歷史可重現」
> **格式**:semver-like `major.minor.patch` (跟 chip radar code 版本獨立)
>
> **改值流程**:
> 1. 升 algo_version (改 yaml)
> 2. 本文件加 entry
> 3. 跑全套測試確認無 regression
> 4. git commit `algo(vX.Y.Z): <短標>`
> 5. git tag `algo-vX.Y.Z`

---

## algo-v3.42.0 (2026-06-19) — C2 Phase B backtest 上線

**作者**:DRwillychiu (Sprint 5)
**狀態**:🟢 active
**git tag**:`algo-v3.42.0`

**內容**:
- 新 `backtester_phase_b.py` — 用內建 `data/temp_history.json` 跑 Phase B backtest
- 避開 FinMind 外部 API (對抗式建議: API 風險 + 配額)
- 涵蓋 4 個未回測信號: 外資現貨 / 分點漲停 / 融資熱度 / 法人共識
- 二分法:≥55% enable / <45% disable / 樣本 n<10 insufficient
- market_regime_caveat 偵測強單邊行情 → trust_weights=False → signal_engine 自動歸 0
- `signal_engine.load_phase_b_weights()` 從 `data/backtest_phase_b_results.json` 動態載入
- 前端溫度計 chip 加 hit_rate badge + 樣本警示

**實證結果 (首次跑 2026-06-19, 樣本 25 天)**:
- market_regime = strong_bull(next_day_up_pct=100%)
- 🚨 偵測到 data quality bug: temp_history.next_day_change_pct 30 天全正 → 不可能
- trust_weights = False → 所有 weights 暫不採信
- 待修 crawler 的 next_day backfill 邏輯 + 累積 180+ 天樣本後重評

**影響**:
- ✅ signal_engine Phase B weights 仍維持 0 (因 strong_bull regime 不採信)
- ✅ daily_signal 行為跟 v3.40.0 一致 (無 weight 漂移)
- ✅ 機制就緒, 等資料品質修好 + 樣本累積後自動生效

---

## algo-v3.40.0 (2026-06-19) — 凍結基線

**作者**:DRwillychiu via institutional roadmap Sprint 3
**狀態**:🟢 active
**git tag**:`algo-v3.40.0`

**內容**:
- 建立 `config/algo_params.yaml` 集中所有閾值,凍結為基線版本
- 把散布在 `master_profile.py THRESH` / `master_alliance.py` / `disposal_holdings.py` / `margin_maintenance.py` / `tdcc_holdings.py` / `crawler_pipeline.py TEMP_THRESHOLDS` 的閾值集中
- `chip_temperature` 7 信號標記 `pending_calibration`,目標 2026-09-01 前完成 backtester Phase B
- 每日 `latest.json` 的 `_meta.algo_version` 自此版本後會帶入此值(B3 metadata 注入)

**影響**:
- ✅ 純結構化,無數值變動,所有現有 master profile / disposal / margin 結果不變
- ✅ 33+ 套件迴歸 0 regression

**已知 pending review (排 2026-07-04)**:
- 10 個新 master(6/4 加入)樣本滿 30 天後評估標籤穩定性
- 謝孟恭(股癌)分點代號需確認
- T+1 verified flip ratio 跟業界印象差異 > 50% 的 master 重評

---

## 之前的零散變動歷史 (僅作參考, 未發 algo_version)

### v3.31.10 (2026-06-04) — 一次性大校準
基於 32 天真實資料 + 業界印象反推,7 個閾值調整:
- `limit_up_hit_high`: 0.60 → 0.18(蔣承翰 21% 觸發,民哥 14% 不觸發)
- `locked_at_lu_ratio_amt`: 0.40 → 0.15(蔣承翰 19% 鎖漲停 / total)
- `style_dominant`: 0.50 → 0.40
- `concentration_high`: 50 → 35
- `consistency_high`: 0.80 → 0.65
- `streak_long`: 8 → 15
- `long_term_days_threshold`: 5 → 15

### v3.31.19 (2026-06-04) — 聯動面初值
- `jaccard_threshold`: 0.30
- `min_co_days`: 1(後在 v3.31.23 升 5,防新 master 1 天 = 100% 污染)

### v3.31.23 (2026-06-05) — 第一波優化
- `min_co_days`: 1 → 5

### v3.33.0 (2026-06-11) — B3 時間衰減
- 新增 `decay_half_life`: 20

### v3.36.0 (2026-06-13) — B5 處置持倉
- 新增 `disposal_holdings.min_net_lots`: 100
- 新增 `disposal_holdings.min_net_wan`: 1000

### v3.37.0 (2026-06-19) — 融資維持率
- 新增 `margin_maintenance.*` 所有閾值

---

## 變更影響評估指南

每次升 algo_version 都要回答:

1. **數值變動範圍**:哪些欄位 / 由 X → Y
2. **影響的 metric**:`master_profile.operation_metrics` 哪幾個欄位會變
3. **影響的標籤**:哪個 master 預期會多/少哪個標籤
4. **回測情境**:本次變動是否需要重跑 30 天歷史比對
5. **rollback 計畫**:若上線後發現問題,如何降版到上一個 algo tag

---

## 季度 review 模板 (季初執行)

每季 1/4/7/10 月第一週執行,逐項檢視:

### Review check-list

- [ ] 過去一季 master profile 標籤分布是否穩定 (vs 業界印象)
- [ ] 派系 jaccard 結果是否合理 (是否漏抓真派系 / 是否誤判巧合)
- [ ] 處置持倉命中率(`bought_during_disposal_count > 0` 的 master 比例)
- [ ] 維持率分布:健康 / 警戒 / 高風險 / 斷頭 數量比是否漂移
- [ ] TDCC 大戶比例 movers 是否反映真實籌碼流動
- [ ] 7 信號溫度計 hit rate(需 backtester Phase B 完成後才能評)

### 觸發升級的紀律

- 任何一條 master 的標籤連續 5 個交易日跟業界印象不符 → 重評相關閾值
- 派系結構連續 3 週無變化 → 重評 `jaccard_threshold`(可能太鬆/嚴)
- 處置持倉率 < 5% 或 > 60% → 重評 `disposal_holdings.min_net_lots`
- 維持率「斷頭區」連續 3 天 > 5 檔 → 重評 `n_days_avg` / `margin_rate`
