# Chip Radar TW · 分點籌碼觀察站

> 自動化追蹤台股券商分點 + 期貨選擇權籌碼 + 法人動向 + 大戶策略分析的專業級個人看板
> **當前版本**:v3.32.4 ｜ **網站**:https://drwillychiu.github.io/CHIP_RADAR_TW/

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

## 核心功能（14 個 Tab）

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
| 08 | 融資融券 |
| 09 | 漲停狙擊（分點分析） |
| 10 | 個股追蹤（個股+產業+大盤 三線圖） |
| 11 | 高手 master |
| 12 | 操作日報 |
| 13 | 自選股 |

### 大戶深度分析（v3.30.8+）
| Tab | 功能 |
|-----|------|
| **14** | **大戶畫像** — 29 master × 15 標籤 + Level 1/2/3 分層 + 策略色碼 + 派系面板 + T+1 跨日追蹤 + 實戰信號 |

---

## 數據規模

| 維度 | 規模 |
|------|------|
| 監控分點 | **81 個**（含 10 地緣特色分點） |
| Master 高手 | **29 位個人大戶** + 8 外資 + 2 官股 + 2 公司 + 10 地緣 = 51 |
| 個人大戶標籤 | 15 規則標籤 + 2 T+1 verified = 17 |
| Level 2 策略 | 10 種子類 |
| 派系 | 2 個已知派系（Jaccard ≥ 30%） |
| 產業分類 | 上市 1082 + 上櫃 883 = **1965 檔** |
| 期貨商品 | TXF + MXF + TMF |
| 歷史窗口 | 60 天滾動（hot/warm/cold 三層） |
| DB | SQLite OLAP（7 tables + 4 views + 8 indexes） |
| Tab 數量 | **14 個** |
| 測試套件 | 26 套 / 200+ case |

---

## 技術架構

### 後端（~40 個 Python 模組）

```
核心 (crawler 主流程)
├── crawler.py           主編排器 (~3100 行), 9 階段 + DB + archive + master_profile + signals
├── branches.py          81 watched branches + 51 MASTER_STYLES + co_masters
├── institutional.py     三大法人 (TWSE + TPEx)
├── margin.py            融資融券
├── futures.py           TAIFEX 期貨選擇權 (~970 行)
├── insiders.py          MOPS 董監持股 + 重大訊息
├── history.py           30 天歷史累積

分析層
├── master_profile.py    29 master × 15 標籤 + per-branch + Level 1/2/3
├── master_alliance.py   Jaccard 同向率 + 派系 union-find
├── cross_day_tracker.py T+1 跨日追蹤
├── daily_signals.py     實戰信號 (異常+共識+加碼)
├── trade_pattern.py     規則式模式分類 + narrative
├── signal_engine.py     backtest 信號加權引擎
├── price_utils.py       tick-size 精確漲停價

DB + 資料管理
├── db_pipeline.py       SQLite OLAP (7 tables + 4 views + 8 indexes)
├── db_excel_import.py   Excel backup source + cross-validate
├── archive_manager.py   hot/warm/cold 三層 (7天/60天)
├── disposal_fetcher.py  chengwaye 處置股 + 歷史快照
├── query_db.py          SQL wrapper

驗證工具 (12 個)
├── stress_test_data_integrity.py  5 invariant 壓力測試
├── histock_branch_audit.py        個股×分點 histock 反向 cross-check
├── heartbeat_check.py             資料新鮮度心跳
├── auto_audit.py / excel_full_audit.py / excel_content_audit.py
├── stock_cross_check.py / margin_cross_check.py / insider_cross_check.py
└── safe_fetch.py                  HTTP size limit defense

輸出
├── excel_report.py      月檔 Excel + master 色塊 (29 master 暖/冷/灰色系)
└── reports.py           週報/月報
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
├── stock_history.json         30 天個股 close + 期貨 + 大盤 (未加密)
├── temp_history.json          60 天信號歷史
├── master_profiles.json       29 master × 15 標籤 + 聯動 + 信號 (未加密)
├── daily_trading_signals.json 實戰信號 (異常+共識+加碼)
├── daily_audit.json           auto_audit verdict
├── daily_signal.json          signal_engine 輸出
├── disposal_map.json          處置股 cache (TTL 1 天)
├── disposal_history/          每日處置快照 YYYYMMDD.json
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
| `ARCHITECTURE.md` | 系統架構（4 層資料流 + 27 module 清單 + 9 階段 + 8 ADR） |
| `ONBOARDING.md` | 7 天新手指南 + 紀律 5 條 + 3 練習任務 |
| `LABELS_DEFINITION.md` | 17 標籤完整定義 + Level 1/2/3 + 閾值 + 共存矩陣 |
| `AUDIT_REPORT.md` | TAIFEX 83 欄位逐項對比報告 |

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
