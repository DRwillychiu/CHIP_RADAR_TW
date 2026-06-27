# docs/ 索引

> 12 個文件,按用途分類。新進場 → 看 ⭐ 必讀。

## ⭐ 必讀 (新對話 / 新進場)

| 檔 | 行 | 用途 |
|---|---|---|
| [CONTINUATION_GUIDE.md](CONTINUATION_GUIDE.md) | — | **Claude 新對話接手必讀** (1-pager: 系統現況/常用 path/最新版本) |
| [ONBOARDING.md](ONBOARDING.md) | 485 | 環境設定/dev workflow/常用命令 |
| [LABELS_DEFINITION.md](LABELS_DEFINITION.md) | 657 | 所有 ⭐⭐/⭐/⚠️/🔁/🆕 標籤定義 + 顏色語義 |

## 📚 架構 / 設計

| 檔 | 行 | 用途 |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 437 | 系統架構 (src/ 8 大類 / 資料流 / 8 大模組) |
| [INSTITUTIONAL_ROADMAP.md](INSTITUTIONAL_ROADMAP.md) | 1303 | 完整版本歷史 + Sprint 紀錄 (v3.71.12 為止) |
| [CHANGELOG_ALGO.md](CHANGELOG_ALGO.md) | 184 | 演算法閾值變更 history (algo_params.yaml) |

## 🛡️ 資料 / 合規

| 檔 | 行 | 用途 |
|---|---|---|
| [DATA_SOURCE_STANDARDS.md](DATA_SOURCE_STANDARDS.md) | 95 | TWSE/TPEX/attstock 資料來源規範 |
| [DATA_SOURCES_COMPLIANCE.md](DATA_SOURCES_COMPLIANCE.md) | 124 | 合規 SOP (robots.txt / ToS / rate limit) |

## 🚨 Production SOP (alarm 觸發後查)

| 檔 | 行 | 用途 |
|---|---|---|
| [PHASE32_ALPHA_FAILURE_SOP.md](PHASE32_ALPHA_FAILURE_SOP.md) | 140 | **quad alpha 失效應對** (rolling 30d hit <50% AND n≥20 觸發) |
| [MASTER_REVIEW_SOP.md](MASTER_REVIEW_SOP.md) | 110 | Master 月度評估流程 (PREMIUM 升降 / 汰換) |

## 🤖 Auto-generated (cron 寫入, 不要手改)

| 檔 | 行 | 用途 |
|---|---|---|
| `WORKFLOW_HEALTH.md` | — | weekly cron 統計 12 workflows 過去 7 天健康度 |
| `MASTER_TIER_HISTORY.md` | — | 月度 master tier 變動快照 (待 v3.71.12 後第一次月度跑) |

## 📖 其他

| 檔 | 行 | 用途 |
|---|---|---|
| [COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md) | 144 | 同類產品比較 (CMoney/籌碼K線/etc) |
| [TELEGRAM_BOT_SETUP.md](TELEGRAM_BOT_SETUP.md) | 133 | (deferred) Telegram 通知設定 |
| [memory.md](memory.md) | 666 | (legacy) 早期專案 memory, archive 用 |

---

## 加新文件規則

1. **檔名大寫_底線分隔** (e.g. `MASTER_REVIEW_SOP.md`)
2. **加新檔必更本 index** (15min 紀律)
3. 分類選 SOP / 架構 / 合規 / Auto-generated
4. 純 incident log → archive 到 `docs/incidents/YYYY-MM-DD-xxx.md`
