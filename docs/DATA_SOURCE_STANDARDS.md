# 資料源驗證標準 (Cross-Validation Standards)

> v3.64.5 起 — Dashboard 所有判斷類數據必須有「參考資料源 + 交叉驗證」

---

## 原則

任何 Dashboard 顯示的「**判斷類**」數據（信號、方向、信心度、共識個股等）必須符合：

1. **可追溯**：每個 cell value 都能 trace 回原始公開資訊源
2. **可驗算**：演算公式寫在 code（不是隱性魔法），且有單元驗證
3. **可比對**：與**至少一個獨立來源**（公開網站 or 本網站其他 tab）能交叉比對

---

## Q5 Banner 資料源 chain (v3.64.5)

```
TAIFEX 官方公告 (https://www.taifex.com.tw/cht/3/pcRatio)
        ↓
src/fetchers/futures.py: fetch P/C OI Ratio
        ↓
data/temp_history.json: { date, signals: [{name, value, level}] }
        ↓ (level 由 TEMP_THRESHOLDS 標籤化)
src/pipelines/crawler_pipeline.py TEMP_THRESHOLDS
        ↓ (weight 由 SIGNAL_WEIGHTS 查表)
src/analyzers/signal_engine.py SIGNAL_WEIGHTS  (1-year backtest)
        ↓ (公式: 50 + net*100)
data/daily_signal.json: { market_direction: {direction, confidence_pct} }
        ↓ (Excel cell + format)
chip_radar_2026-MM.xlsx Dashboard Section A Q5 banner
```

### 7 個信號的公開參考來源

| Signal | 公開資訊源 | 本網站 tab | 狀態 |
|--------|-----------|-----------|------|
| **P/C Ratio (信號 3)** | https://www.taifex.com.tw/cht/3/pcRatio | 06 三大法人 → PCR card | ✅ Phase A |
| **結算日壓力 (信號 7)** | TAIFEX 結算日曆 + 信號 2 | 06 三大法人 → 結算倒數 | ✅ Phase A |
| **外資現貨 (信號 1)** | https://www.twse.com.tw/zh/trading/foreign | 06 三大法人 → 外資現貨 | ⏳ Phase B pending |
| **外資期貨 (信號 2)** | https://www.taifex.com.tw/cht/3/futAndOpt | 06 三大法人 → 外資期貨 | ❌ KILLED v3.29 (hit 41% < 50% random) |
| **分點漲停 (信號 4)** | (內部計算自 branches buys) | 09 漲停狙擊 | ⏳ Phase B pending |
| **融資熱度 (信號 5)** | https://www.twse.com.tw/zh/trading/margin | 08 融資融券 | ⏳ Phase B pending |
| **法人共識 (信號 6)** | 外資現貨 + 投信現貨 同向 | 06 三大法人 | ⏳ Phase B pending |

---

## Backtest 證據存放

| 用途 | 檔案 | 驗證 |
|------|------|------|
| Phase A signals (P/C + 結算) | `data/backtest_results.json` | 1-year (5/2025-5/2026) 247 對 |
| Phase B signals (1/4/5/6) | `data/backtest_phase_b_results.json` | trust_weights 動態 |
| Killed signal (信號 2) | code 註解 (signal_engine.py L115-122) | n=140 hit 41.4% |

---

## 驗證腳本

```powershell
# 每次 Dashboard 變更必跑
python scripts/cross_validate_dashboard.py
```

**自動驗證的 3 層**：

| Layer | 內容 | 涵蓋 |
|-------|------|------|
| **L1** | Excel cell value = `daily_signal.json` 內容 | 顯示一致性 |
| **L2** | `daily_signal` 內部公式 chain (net → confidence → direction) | 演算正確性 |
| **L3** | `temp_history` raw value → level (via TEMP_THRESHOLDS) → weight (via SIGNAL_WEIGHTS) | 信號標籤+權重一致性 |

---

## 新增信號的 SOP

任何新增「判斷類」信號或 KPI 必須：

1. **寫明公開資料源** — 加入上方表格
2. **threshold + weight 寫死 code 註解** — 含 backtest hit rate / n 樣本數
3. **加 cross_validate** — `scripts/cross_validate_dashboard.py` 必須含此信號的 3 層驗證
4. **更新本文件** — 確保未來開發者知道資料源

---

## 已踩過的雷

- **v3.27.3**: TWSE OpenAPI stale (21:30 還在 publish 前日資料) → 必須驗 `Date` 欄位
- **v3.29**: 信號 2 (外資期貨) backtest 不及格 (hit 41%) → 已 KILL
- **v3.64.5 之前**: Section D 「籌碼溫度」silently 失效 (`temperature_score` schema 已重構) → Dashboard 全部顯示 `—` → 用戶看不出來 → 教訓: **每個 KPI 必須在 cross_validate 內**

---

**最後更新**: 2026-06-23 (v3.64.5)
