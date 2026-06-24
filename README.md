# Chip Radar TW · 分點籌碼觀察站

> 自動化追蹤台股券商分點 + 期貨選擇權籌碼 + 法人動向 + 大戶策略分析的專業級個人看板
> **當前版本**:v3.66.3(2026-06-24) ｜ **網站**:https://drwillychiu.github.io/CHIP_RADAR_TW/
> **結構**:機構級 Data Analyst 分層(src/ 8 大類 + tests/ + docs/),60 模組

v3.40-v3.51 機構級升級重點(Sprint 1-13):
- **B1-B6**:masters_roster owner trail / algo_params 凍結 / _meta metadata / 樣本不足三檔標籤 / ToS 合規 + safe_fetch 指數退避 / manipulation_flags 操縱偵測
- **C1-C7**:EventLogger SIEM-ready JSONL / ReasoningChain dataclass / keyboard shortcuts / CSV export 4 button
- **C2 backtest**:Phase B hit_rate 二元判定(揭穿 TAIEX 100% 全正 data bug + 修)
- **Tier 1**:後端最痛(stock_history 60 天 / disposal 7-day fallback / safe_fetch 全 migrate)
- **Tier 2 競品 gap**:注意股 / 借券 / 除權息 / 主力成本線(4 個 fetcher + 前端 chip)
- **重整**:crawler.py main 拆 9 helper(1225→1022 行) / **root 110+ → 7 .py(機構級重整)**

---

## 專案定位

```
Chip Radar 是「台股籌碼分析專家」
─────────────────────────────────────
不是宏觀晨報、不是美股工具、不是 Podcast 整合
專注做好一件事:把台股每日籌碼數據,變成你能秒判讀的儀表板
```

---

## 數據準確性承諾

> **所有期貨/選擇權數值,經逐欄位審計,100% 對齊 TAIFEX 官方公告。**

| 類別 | 欄位數 | 來源 | 狀態 |
|------|------|------|------|
| 期貨三大法人 (TXF/MXF/TMF) | 36 | TAIFEX | ✅ |
| 選擇權三大法人 (TXO Call/Put) | 18 | TAIFEX | ✅ |
| P/C Ratio + 全市場 OI | 4 | TAIFEX | ✅ |
| 大額交易人 | 3 | TAIFEX | ✅ |
| 衍生指標 | 5 | 計算 | ✅ |
| 期貨 OHLC | 13 | TAIFEX | ✅ |
| 夜盤三大法人 | 4 | TAIFEX | ✅ |
| **總計** | **83** | **TAIFEX** | **✅ 100%** |

**Cross-check 涵蓋面**:V1 全分點 + V2 個股行情 + W1 融資 + U1 內部人 + histock 個股×分點反向驗證 + 5 invariant 壓力測試

---

## 核心功能（15 個 Tab）

### 即時籌碼分析
| Tab | 功能 | 資料來源 |
|-----|------|---------|
| 01 | 今日三視角 | 81 分點當沖/隔日沖/波段 |
| 02 | 共買榜 | 多分點同步買進標的 |
| 03 | 分點動態 | 81 個券商分點即時動向 |
| 04 | 累積排行 | N 天累積買超排行 |
| 05 | 高手合併視圖 | 29 位 master 模式比對 |
| 06 | 三大法人 | 外資/投信/自營商 |

### 期貨選擇權
| Tab | 功能 |
|-----|------|
| 07 | 期貨情報（TXF/MXF/TMF + TXO + P/C Ratio + 十大交易人） |

### 進階分析
| Tab | 功能 |
|-----|------|
| 08 | 融資融券（含維持率三級警示 + 高風險 Top 30） |
| 09 | 漲停狙擊（分點分析） |
| **10** | **個股追蹤 + Tier 2 chip**(v3.48.0):💰 主力成本 5d/20d + premium% / 📅 除權息 D-N / 🔻 借券量 + ratio / ⚠️ 注意股累計次數 |
| 11 | 高手 master |
| 12 | 操作日報 |
| 13 | 大戶畫像 — 29 master × 15 標籤 + Level 1/2/3 分層 + 策略色碼 + 派系面板 + T+1 跨日追蹤 + 實戰信號 |
| 14 | 處置股持倉追蹤 + 6 天歷史 |
| 15 | TDCC 集保大戶（≥400 張 movers + 持股結構） |

---

## 數據規模

| 維度 | 規模 |
|------|------|
| 監控分點 | **81 個**（含 10 地緣特色分點） |
| Master 高手 | **29 位個人大戶** + 8 外資 + 2 官股 + 2 公司 + 10 地緣 = 51 |
| 個人大戶標籤 | 16 規則標籤 + 2 T+1 verified = 18 (v3.52.0 加 📦 連續囤貨) |
| Level 2 策略 | 10 種子類 |
| 派系 | 2 個已知派系（Jaccard ≥ 30%） |
| 產業分類 | 上市 1082 + 上櫃 883 = **1965 檔** |
| 期貨商品 | TXF + MXF + TMF |
| 歷史窗口 | 60 天滾動（hot/warm/cold 三層） |
| DB | SQLite OLAP（7 tables + 4 views + 8 indexes） |
| Tab 數量 | **15 個** |
| 測試套件 | **41 套** / 400+ case |
| 後端模組 | **60 個**(src/* 8 大類) + 6 entry points |
| 新 fetcher(v3.46+) | TWSE 1980 檔上市櫃 / 注意股 / 借券+融券 / 除權息 |

---

## 技術架構

### 後端（60 模組,機構級 Data Analyst 分層）

```
root (7 個 entry points)
├── crawler.py              主編排 (~1022 行 main(), 抽 9 個 _post_*/_stage_* helper)
├── heartbeat_check.py      資料新鮮度心跳
├── tdcc_holdings.py        TDCC 集保大戶
├── intraday_settlement.py  盤後 13:35 即時結算
├── pre_market_brief.py     盤前 08:00 大事曆+夜盤
└── weekly_summary.py       週五 14:30 高手調整+績效

src/fetchers/ (13) — 抓資料層
├── safe_fetch              指數退避 + per-source 軟性配額 + ResponseTooLargeError
├── attention_fetcher       TWSE 注意股 (v3.46.0)
├── short_lending_fetcher   TWSE TWTASU 借券+融券 (v3.46.0)
├── dividend_fetcher        TWSE TWT48U 除權息預告 + ROC 日期轉換 (v3.46.0)
├── listing_fetcher         TWSE+TPEx 1980 檔上市櫃 + first_listed (v3.45.0)
├── disposal_fetcher        chengwaye 處置股 + 7 天 stale fallback (v3.44.0)
├── institutional / margin / futures / insiders
├── industry_classifier / market_classifier
└── history                 60 天滾動 (v3.44.0 從 30 天延長)

src/analyzers/ (11) — 分析層
├── master_profile          29 master × 15 標籤 + per-branch + Level 1/2/3 + 時間衰減
├── master_alliance         Jaccard 同向率 + 派系 union-find
├── master_performance / cross_day_tracker / trade_pattern
├── manipulation_flags      操縱/對敲/出貨偵測 (v3.40.0)
├── disposal_holdings / margin_maintenance
├── main_force_cost         主力成本線 5d/20d + premium% (v3.46.0)
└── signal_engine           backtest 信號加權 + regime guard

src/pipelines/ (6) — 編排層
├── crawler_fetch / crawler_pipeline / crawler_output  (B1 拆三層)
├── db_pipeline             SQLite OLAP (7 tables / 4 views / 8 indexes)
├── archive_manager         hot/warm/cold 三層 (7天/60天)
└── reports                 週報/月報

src/backtest/ (3) — 回測層
├── backtester              個股 alpha 回測
├── backtester_phase_b      hit_rate 二元 ENABLE/DISABLE/INSUFFICIENT (v3.42.0)
└── backfill_market_history TAIEX next_day backfill 修正

src/audit/ (12) — 稽核層
├── audit_branches / audit_margin / auto_audit / signal_audit
├── excel_content_audit / excel_full_audit
├── histock_branch_audit / histock_verifier
├── insider_cross_check / margin_cross_check / stock_cross_check
└── stress_test_data_integrity  5 invariant 壓力測試

src/alerts/ (3) — 警報層
├── alerts                  推播警報 + dry-run
├── daily_signals           實戰信號 (異常+共識+加碼)
└── event_logger            SIEM-ready JSONL (v3.41.0 C1)

src/exports/ (4) — 輸出層
├── excel_report            月檔 + 29 master 色塊
├── reasoning               ReasoningChain dataclass (v3.41.0 C3)
├── backfill_to_monthly / db_excel_import

src/core/ (3) — 共用工具
├── branches                81 watched + 29 MASTER_STYLES + co_masters
├── price_utils             tick-size 精確漲停價
└── query_db                SQL wrapper
```

### 前端

```
index.html (~470KB)
├── HTML/CSS/JS 單檔
├── Chart.js 4.4.1
├── AES-256-GCM + PBKDF2-SHA256 + gzip 加密解鎖
└── 14 個 tab (含 Tab 14 大戶畫像)
```

### 自動化排程（GitHub Actions 6 個 workflow）

| # | Workflow | 排程 | 功能 |
|---|----------|------|------|
| 1 | Daily Full Crawl | 21:17 + 22:37 + 23:47 TW（三層兜底） | 主爬蟲 + Excel + DB + master_profile + signals |
| 2 | Margin Refresh | 7 重排程 | 融資融券補抓 |
| 3 | Keepalive | 週日 04:00 TW | 防 60 天 disable |
| 4 | Security Audit | 週一 03:00 TW | pip-audit + safety |
| 5 | Heartbeat | 00:30 + 09:00 TW | 資料新鮮度,stale 自動開 issue |
| 6 | Pages Build | 自動 | GitHub Pages 部署 |

**本地觸發**:Windows Task Scheduler + `trigger_chip_radar.ps1`（21:17 + 22:37,BurntToast 桌面通知）

---

## Data 目錄結構

```
data/
├── latest.json                加密+gzip (當日, 網站讀)
├── YYYYMMDD.json              加密 (hot, 最近 7 天)
├── archive/                   加密 (warm, 7-60 天)
├── stock_history.json         60 天個股 close + 期貨 + 大盤 (v3.44+ 從 30 天延長)
├── temp_history.json          60 天信號歷史
├── master_profiles.json       29 master × 15 標籤 + 聯動 + 信號 (未加密)
├── daily_trading_signals.json 實戰信號 (異常+共識+加碼)
├── daily_audit.json           auto_audit verdict
├── daily_signal.json          signal_engine 輸出
├── backtest_phase_b_results.json  Phase B hit_rate 二元判定 (v3.42+)
├── disposal_map.json          處置股 cache (TTL 1 天, 7 天 stale fallback)
├── disposal_history/          每日處置快照 YYYYMMDD.json
├── attention_map.json         TWSE 注意股 (v3.46+)
├── short_lending.json         TWSE 借券+融券 (v3.46+)
├── dividend_calendar.json     TWSE 除權息預告 + upcoming_30d (v3.46+)
├── listing_history.json       TWSE+TPEx 1980 檔上市櫃 (v3.45+)
├── masters_roster.json        高手分點 owner trail (v3.40+ B1)
├── industry_map.json          產業分類 (7 天 cache)
├── chip_radar_v2.db           SQLite OLAP (本機, .gitignore)
├── reports/
│   ├── chip_radar_2026-MM.xlsx  月檔 (每日 add sheet)
│   ├── latest.xlsx              = 當月 copy
│   └── weekly_*.json/md         週報
└── heartbeat.json
```

---

## 加密協議

- **演算法**:AES-256-GCM + PBKDF2-SHA256
- **壓縮**:gzip（v3.30.1+,magic bytes `1F 8B` auto-detect）
- **Backward compat**:100%（舊未壓縮 ciphertext 仍能正常解密）
- **密碼**:GitHub Secret `CHIP_RADAR_PASSWORD`
- **前端解密**:JS `SubtleCrypto` + `DecompressionStream`

---

## 快速部署（新手 15 分鐘）

### Step 1:Fork 或 Clone
```bash
git clone https://github.com/DRwillychiu/CHIP_RADAR_TW.git
```

### Step 2:設定 Secret
GitHub Repo → Settings → Secrets → Actions → 新增:
```
Name:  CHIP_RADAR_PASSWORD
Value: 自設密碼
```

### Step 3:開啟 GitHub Pages
Settings → Pages → Source: `main` / `(root)` → Save

### Step 4:授權 Actions
Settings → Actions → General → Workflow permissions → Read and write

### Step 5:手動跑第一次
Actions → `1. Daily Full Crawl (21:17)` → Run workflow

### Step 6:開啟網站
`https://YOUR_USERNAME.github.io/CHIP_RADAR_TW/` → 輸入密碼解鎖

---

## 版本歷程（重要里程碑）

| 版本 | 日期 | 重點 |
|------|------|------|
| **v3.66.3** | 6/24 | **G empty state + H 借券 hot 標記** — G 「✅ 今日無新增注意股」綠斜體 / H ratio≥1000x 🔴 紅粗體 / 千分位 format |
| v3.66.2 | 6/24 | Section J 集中度 + Master 色塊 — 新增 Top3 合計% col / Master cell 套 MASTER_BLOCK_COLORS / ≥80% 標 🔥 + 紅字粗體 |
| v3.66.1 | 6/24 | Section G/H/I 時間正確性 — I 過濾過期 ex_date + G/H/I header 加 applicable_date + cross_validate 加 strict assertion |
| v3.66.0 | 6/23 | Dashboard 簡潔原則: E 大砍 + F hot 標記 — E 砍 consensus/accumulation 留 anomalies top 10 + 修 new_stocks 沉底 bug / F ≥10 天 🔴 紅字粗體 |
| v3.65.0 | 6/23 | Section B/C 視覺優化 + ETF 全 Dashboard 排除 — B master 色塊延伸 / C 個股 `name(code)` 格式 + 漲跌% 紅綠 / 5 section ETF filter |
| v3.64.0 | 6/22 | Excel Section A 擴增 + L 欄損益字色修 — 4→6 stat × 2 row,L 欄拿掉 ColorScaleRule 改深紅/深綠 font,master block 上高對比 |
| v3.63.9 | 6/22 | Section 0 強共識排序優化 — 主排序改總金額 desc + ⚠️ 領頭佔 ≥50% 假共識警示 + cell comment 詳解 + 註腳 row |
| v3.63.1-8 | 6/21 | Section 0 完整重設計 + 嚴格淨買 + 6 個資料路徑 bug 修 + L 欄高對比配色 (筆電 push) |
| v3.63.0 | 6/21 | Sprint 26 Excel Tier 2 — E6 freeze panes(Dashboard A3 + day sheet C2) + E7 Pivot-style Section J(Master × Top 3 個股) |
| v3.62.1 | 6/21 | Excel 增強 fix: 4 sheet 合 1 Dashboard sheet(用戶要求) + audit 修補 |
| v3.62.0 | 6/21 | Sprint 25 Excel 增強 E1-E5 + strict_verify D1-D8 (99% 精準度) |
| v3.61.0 | 6/21 | Sprint 24 DB 進階查詢 — query_db CLI 7→15 preset + JSON/CSV 輸出 + crawler 每日 snapshot + 前端 Tab 12 預設下拉 + CSV 匯出 |
| v3.60.0 | 6/21 | Sprint 23 P0-E Tab lazy render + DOM 快取 — 前端 P0 6/6 完滿,切回 tab 從 100-300ms → <1ms |
| v3.59.0 | 6/21 | Sprint 22 P0-C 前端 ARIA + 鍵盤導航 — WAI-ARIA tablist + Arrow/Home/End 標準 + Skip link + focus-visible 統一樣式 |
| v3.58.0 | 6/21 | Sprint 21 P0-F 前端機構級響應式佈局 — 2 新 breakpoint(640/380), tab nav scroll / stat-row wrap / controls 堆疊 / table horizontal scroll |
| v3.57.0 | 6/21 | Sprint 20 P0-B 前端 Dark / Light theme 切換 — `:root[data-theme]` 雙 palette + 浮動 toggle button + localStorage 持久 |
| v3.56.0 | 6/21 | Sprint 19 P0-D 前端 render perf — CSS content-visibility + contain + renderWithFragment 擴大採用 6 處 |
| v3.55.0 | 6/21 | Sprint 18 P0-A 前端 Web Worker 解密 — latest.json 解密移出 main thread, UI 不再凍結 1-2s |
| v3.54.0 | 6/21 | Sprint 16 長2 Telegram Bot 推播 — send_telegram + 並行推 Discord, setup 教學 docs/TELEGRAM_BOT_SETUP.md |
| v3.53.0 | 6/21 | Sprint 15 長3 latest.json lazy load — 拆出 inst_rankings + margin_rankings 獨立 unencrypted JSON,前端 getter 加 fallback |
| v3.52.0 | 6/21 | Sprint 14 長4 跨日囤貨偵測 — 新標籤 📦 連續囤貨 + accumulation_stocks per-master |
| v3.51.0 | 6/21 | Sprint 13 機構級 Data Analyst 重整 — root 110+→7 .py / src/ 8 大類 / tests+docs 分離 |
| v3.50.0 | 6/20 | Sprint 12 後2 main() 抽 3 pure-read stage helper (1090→1022 行) |
| v3.49.0 | 6/19 | Sprint 11 運1 trigger_chip_radar.ps1 入庫 (Tier 3 維運) |
| v3.48.0 | 6/19 | **Sprint 10 Tier 2 整合** — Tab 10 加 4 chip (主力成本/除權息/借券/注意股) |
| v3.47.0 | 6/19 | Sprint 9 後2 crawler.py 後處理 6 helper 抽出 (main 1225→1090) |
| v3.46.0 | 6/19 | **Sprint 8 Tier 2 4 fetcher** — 注意股 / 借券+融券 / 除權息預告 / 主力成本線 |
| v3.45.0 | 6/19 | Sprint 7 Tier 1 — TAIEX 重複日 / 謝孟恭 9676 / listing_fetcher 1980 檔 |
| v3.44.0 | 6/19 | Sprint 6 後端最痛 — stock_history 60 天 / disposal 7-day fallback / safe_fetch 全 migrate |
| v3.43.0 | 6/18 | TAIEX 100% 全正 data bug 修 + backfill 30 天歷史 + C8 survivorship hook |
| v3.42.0 | 6/18 | Sprint 5 C2 Phase B backtest hit_rate 二元判定 (≥55 enable / <45 disable) |
| v3.41.0 | 6/18 | Sprint 4 — C1 EventLogger SIEM JSONL / C3 ReasoningChain / C6+C7 鍵盤+CSV / 4 workflow |
| v3.40.0 | 6/18 | Sprint 3 機構級 P0 — masters_roster / algo_params / _meta / B4 三檔標籤 / safe_fetch backoff / manipulation_flags |
| v3.39.0 | 6/17 | Sprint 2 P1 — PBKDF2 動態 / fetch timeout / DocumentFragment / tab 視覺優先級 |
| v3.38.0 | 6/16 | Sprint 1 P0 — 7 fixes(timezone/silent_corruption/SCHEMA/cache_invalidation/ZeroDiv/dedup/CI) |
| v3.37.0 | 6/16 | margin 維持率估算 + TDCC 400 張大戶 + tab 15 持股結構 |
| v3.36.0 | 6/15 | B5 處置股持倉追蹤 + tab 14 disposal_holdings |
| v3.35.0 | 6/15 | B1 crawler.py 拆 fetch/pipeline/output 三層 |
| v3.34.0 | 6/14 | M5 audit_history 趨勢化 + B6 族群輪動 |
| v3.33.0 | 6/13 | B3 master_profile 時間衰減 + B2 Tab 14 排序+篩選 |
| v3.32.4 | 6/6 | GitHub Actions Node.js 20→24 升級（6/16 deadline） |
| v3.32.3 | 6/6 | 自動回補機制 + 期貨歷史補齊 |
| v3.32.1 | 6/6 | 修 Python 3.12 `import history` scope bug |
| v3.32.0 | 6/5 | 實戰信號系統（異常偵測+派系共識+連續加碼） |
| v3.31.23 | 6/5 | 第一波優化（波段不標+T+1 verified+派系門檻+資料不足提示） |
| v3.31.22 | 6/5 | T+1 跨日追蹤 + 60 天滾動窗口 |
| v3.31.19 | 6/4 | 聯動面 Phase 2（Jaccard 派系自動發現） |
| v3.31.18 | 6/4 | 個人大戶 19→29（Excel 交叉比對加 10 master + 25 分點） |
| v3.31.16 | 6/4 | Level 1/2/3 標籤分層 + 10 策略子類 |
| v3.31.14 | 6/3 | DB 雲端 Artifact 累積（GitHub Actions 間傳遞 SQLite） |
| v3.31.2 | 6/1 | DB Pipeline Phase 1.0（SQLite OLAP 7 tables） |
| v3.31.0 | 6/1 | Excel 月檔模式 + master 色塊 |
| v3.30.14 | 5/30 | Tab 14 大戶畫像上線 |
| v3.30.8 | 5/29 | master_profile Phase 1（15 標籤 + per-branch） |
| v3.30.3 | 5/28 | Data Heartbeat 主動告警 + 三層兜底 |
| v3.30.1 | 5/24 | gzip 瘦身 + pip-audit + size limit |
| v3.29.0 | 5/14 | Signal Engine MVP |
| v3.28.0 | 5/12 | tick-size 精確漲停價 |
| v3.27 | 5/10 | 籌碼溫度計 7 信號 |
| v3.26 | 5/10 | Excel 風格分流（sniper vs swing） |
| v3.24 | 5/9 | Excel 嚴格模仿手動版 |
| v3.21 | 5/5 | 全資料源 100% 對齊審計 |
| v3.20 | 5/3 | MOPS 內部人 + Discord 推播 |
| v3.17 | 4/28 | 期貨情報 tab + TAIFEX 83 欄位 |

完整變更日誌見各版本 commit message。

---

## 配套文件

| 文件 | 內容 |
|------|------|
| `docs/ARCHITECTURE.md` | 系統架構（4 層資料流 + 27 module 清單 + 9 階段 + 8 ADR） |
| `docs/ONBOARDING.md` | 7 天新手指南 + 紀律 5 條 + 3 練習任務 |
| `docs/LABELS_DEFINITION.md` | 17 標籤完整定義 + Level 1/2/3 + 閾值 + 共存矩陣 |
| `docs/INSTITUTIONAL_ROADMAP.md` | 機構級升級藍圖（Sprint 1-12 完成紀錄） |
| `docs/CHANGELOG_ALGO.md` | 演算法參數變更紀錄 |
| `docs/COMPETITIVE_ANALYSIS.md` | 業界對比+獨家功能 |
| `docs/DATA_SOURCES_COMPLIANCE.md` | 資料源 ToS 合規 |

---

## 專案結構 (v3.51.0 機構級 Data Analyst 重整)

```
chip_radar_tw/
├── README.md, requirements.txt                       ← root 必留
├── index.html, 404.html                              ← GitHub Pages 必留
├── crawler.py, tdcc_holdings.py, heartbeat_check.py  ← workflow entry
├── intraday_settlement.py, pre_market_brief.py, weekly_summary.py
│
├── src/             核心程式 (8 大類, 60 模組)
│   ├── fetchers/    抓資料 (TWSE/TPEx/TDCC/chengwaye APIs, 13)
│   ├── analyzers/   分析計算 (master_profile, signal_engine, 11)
│   ├── pipelines/   編排流程 (crawler_*, db_pipeline, 6)
│   ├── backtest/    回測驗證 (backtester_phase_b, 3)
│   ├── audit/       稽核品質 (cross_check / heartbeat, 12)
│   ├── alerts/      警報通知 (alerts/daily_signals/event_logger, 3)
│   ├── exports/     輸出報告 (excel_report/reasoning, 4)
│   └── core/        共用工具 (branches/price_utils/query_db, 3)
│
├── tests/           測試 (41 個 test_*.py + conftest.py)
├── docs/            文檔 (8 個 .md)
├── config/          參數凍結 (algo_params.yaml)
├── scripts/         維運腳本 (trigger_chip_radar.ps1)
├── data/            產出資料 (加密 JSON + DB + cache)
└── .github/         CI/CD workflows
```

**Import 策略**: 6 個 root entry 開頭加 `import src`(side-effect 把 src/* 加進 sys.path),既有 `import attention_fetcher` 仍 work,免改 60 個模組內部 import。

---

## 免責聲明

本工具僅供學習研究之用,所有資料皆來自公開來源（TWSE/TPEx/TAIFEX/HiStock/chengwaye）:
- 不構成任何投資建議
- 不對資料準確性負完全責任
- 投資有風險,盈虧自負

---

## 授權

MIT License

---

## 致謝

- **TWSE** 證券交易所 — 分點 + 法人資料
- **TPEx** 櫃買中心 — 上櫃資料
- **TAIFEX** 期交所 — 期貨選擇權資料
- **HiStock** — 融資融券交叉驗證
- **chengwaye** — 處置股預測資料

---

*Last Updated: 2026/06/10 · v3.32.4*
