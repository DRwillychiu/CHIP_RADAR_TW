# scripts/

入庫的維運腳本。歷史上這類腳本住在 Desktop（個人化路徑），v3.49.0 (運1) 移進此目錄以受 git 管控。

## 📋 28 scripts 分類索引 (v3.71.9, flat structure)

> 為避免 break workflow yml path + internal subprocess reference, 保持 flat. 命名前綴規範分類用途.

### 🔬 Backtest / Alpha Research
重跑歷史 backtest, 計算 alpha 指標.

- `bootstrap_combo_backtest.py` — Phase 3.4 訊號組合 backtest (14 combos)
- `bootstrap_phase32_e_anomaly.py` — Phase 3.2 三訊號 quad backtest (78.9% hit)
- `bootstrap_phase33_f_hot.py` — Phase 3.3 quad + hot5 streak 探索
- `bootstrap_consensus_backtest.py` — Phase 2.5 baseline 共識股 backtest
- `bootstrap_multiday_backtest.py` — Phase 3.5 t+1~t+5 多日 alpha (Loop Iter 1)
- `bootstrap_timeseries.py` — Section A Q1-Q4 KPI 時序 cache (60 天滾動)
- `analyze_master_vol_spike_reliability.py` — per-master 可靠度 → PREMIUM_MASTERS 來源

### ✅ Audit / Verify
對齊 ground truth, cross_validate Excel 數字.

- `audit_alpha_overlap.py` — Phase 3.4 alpha overlap (quad vs mild_up) audit
- `audit_phase32_sheets.py` — 4 個 Phase 3.2 enrichment sheet 數字 cross-check
- `audit_data_bars_real.py` — Excel data bars 視覺正確性
- `audit_stock_close_vs_twse.py` — stock_history close 對齊 TWSE 官方
- `cross_validate_dashboard.py` — Dashboard 所有 section 數字 GT 比對 (主 audit)
- `verify_combo_backtest.py` — Phase 3.1 q5_bull 5 層驗證
- `verify_phase32_e_anomaly.py` — Phase 3.2 quad 5 層驗證
- `verify_phase33_quad.py` — Phase 3.3 quad_AAAA 5 層驗證
- `verify_consensus_vs_website.py` — Section 0 共識 vs 前端對齊
- `verify_pcr_vs_taifex.py` — P/C ratio 對齊 TAIFEX 官方
- `sanity_check_618.py` — 6/18 trigger day 個股逐筆 spot check

### 🔧 Maintenance / Refresh
每日 / 週期執行, 更新 production data.

- `daily_rolling_update.py` — daily-full.yml 在 crawler 後 (re-bootstrap phase32 + update hit_log + regen Excel)
- `update_quad_hit_log.py` — 被 daily_rolling_update 呼叫
- `refresh_attstock_disposal.py` — daily-full.yml (抓 attstock 處置股 → Mobile sheet 避開)。
  UA 必須是完整瀏覽器字串,短的 `Mozilla/5.0` 一律 403;逐檔請求保留 0.5s 節流
- `extract_mobile_summary_text.py` — daily-full.yml 最後 step (Mobile sheet → email body)
- `backfill_taiex_history.py` — 一次性 (v3.71.4 修 6/2-6/8 兜底重複日汙染殘留)
- `regen_excel_618.py` — 一次性 (6/18 Excel 重生 audit 用)
- `inspect_section_a_618.py` — 一次性 debug

### 📲 Telegram (本機 track 2, 見 docs/TELEGRAM_BOT_SETUP.md)
只跑在本機 `scheduler.ps1`,雲端不跑。設定在 `.env`。

- `send_daily_telegram.py` — 推手機摘要 + `latest.xlsx`,同交易日重跑改為編輯原訊息
- `push_disposal_telegram.py` — 推處置股圖卡 × 4 (media group)。圖來自
  disposal-watch 的雲端 artifact,本機不重算也不畫。`--list-chats` 可查群組 id
- `telegram_poll.py` — 長輪詢指令 (`scheduler.ps1` 的 `every=1` + `detached` job,
  每分鐘起一個、聽 55 秒,指令 1-2 秒內就有反應)。
  手機下 `/refresh` 就重抓 artifact 並更新既有訊息;只認管理者私訊,群組不回應。
  `--setup-menu` 裝輸入框旁的藍色選單 (setMyCommands,裝一次就好)

三支共用 `.env` 的 `TELEGRAM_CHAT_ID`(逗號分隔 = 推給多個對象)。
`--force` 一律是「重抓並**原地更新**」,不是重貼一份。

### 🛠️ Tools
- `check_ps1_syntax.ps1` — PowerShell script syntax validator (memory: M4)
- `trigger_chip_radar.ps1` — 本機手動觸發 GitHub Actions (見下節說明)

---

### 加新 script 規則

1. **命名前綴對齊類別** (bootstrap_/audit_/verify_/refresh_/update_/backfill_/extract_/check_)
2. 加新 script 後**必更新本 README** (5min 紀律)
3. Production 用 script 必含 try/except + 0 exit code (給 GitHub Actions `continue-on-error`)

---



## trigger_chip_radar.ps1

每日 21:17 + 22:37 兜底由 Windows Task Scheduler 觸發，做：

1. dispatch GitHub Actions `daily-full.yml` workflow
2. poll run 完成（每 30s 一次，最多 15 分鐘）
3. 抓 `data/daily_audit.json` verdict（PASS/WARN/FAIL）
4. Windows toast 通知結果

### Setup

#### 1. Task Scheduler 設定

```
General:
  Name: Chip Radar Daily Full (21:17)
  Run whether user is logged in or not: ☑
  Run with highest privileges: ☑

Triggers:
  Daily, 21:17, recur every 1 day, Mon-Fri only

Actions:
  Program: powershell.exe
  Arguments: -NoProfile -ExecutionPolicy Bypass -File "C:\path\to\repo\scripts\trigger_chip_radar.ps1"
  Start in: C:\path\to\repo
```

兜底排程把時間改成 `22:37` 即可。

#### 2. (Optional) 客製化 log 路徑

預設 log 寫到 `$env:USERPROFILE\Desktop\chip_radar_trigger.log`。若 Desktop 沒這檔或不想污染，設環境變數：

```powershell
[System.Environment]::SetEnvironmentVariable('CHIP_RADAR_LOG_DIR', 'C:\Logs', 'User')
```

優先順序：
1. `$env:CHIP_RADAR_LOG_DIR` (明確 override)
2. `$env:USERPROFILE\Desktop` (一般 Windows user)
3. `$PSScriptRoot` (script 旁邊 — fallback)

#### 3. Prerequisites

- **GitHub CLI** (`gh`) — install via winget 或 [cli.github.com](https://cli.github.com)
- `gh auth login` 完成一次驗證
- (Optional) **BurntToast** PowerShell module 提供現代 Windows 10/11 toast；沒裝會 fallback 到 BalloonTip

### 為什麼不用 GitHub Actions cron 直接排？

GitHub Actions cron 在 21:17 TW 時容易延遲 15-30 分鐘（高負載時段）。Windows Task Scheduler 本地觸發 + GitHub Actions 雲端執行的混合架構 = 時間精準 + 算力雲端。

### 安全性

- ❌ 此腳本不含 password 或 API key
- ❌ 不含個人化絕對路徑（log 走 env var fallback）
- ✅ 倉庫名 `DRwillychiu/CHIP_RADAR_TW` 是公開資訊
- ✅ 用 `gh auth login` 取代 token 寫死 (`gh` 自己管 credential)

### 改腳本後的驗證

```powershell
# 1. PSParser 語法檢查 (Rule 9)
powershell -NoProfile -File scripts/check_ps1_syntax.ps1 -Path scripts/trigger_chip_radar.ps1

# 2. dry-run (但不真的觸發 workflow)
# 把 line `& gh workflow run daily-full.yml ...` 暫時註解掉, 跑一次, 確認 log 有寫
```

---

## Windows 本機執行

除了透過 GitHub Actions 雲端跑之外，也可以在 Windows 本機直接跑 crawler。資料存在 `local_data/`（不會上傳 GitHub），可透過 Tailscale + Windows 共享資料夾讓其他設備讀取。

### 前置安裝

```powershell
# 1. Python 3.11+
winget install Python.Python.3.11

# 2. 安裝 Python 依賴
pip install -r requirements.txt
```

### 設定密碼（做一次就好）

跟 GitHub Actions 的 Secrets 一樣的概念，在 Windows 上用系統環境變數存密碼：

1. `Win + R` → 輸入 `sysdm.cpl` → Enter
2. 「進階」分頁 → 「環境變數」
3. 使用者變數 → 新增
   - 變數名稱：`CHIP_RADAR_PASSWORD`
   - 變數值：（填你在 GitHub Secrets 裡的密碼）

或用 PowerShell 一行搞定：

```powershell
[System.Environment]::SetEnvironmentVariable('CHIP_RADAR_PASSWORD', '你的密碼', 'User')
```

### run_local.ps1

在本機跑完整 crawler，資料輸出到 `local_data/`。

```powershell
# 手動執行
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_local.ps1
```

#### Task Scheduler 設定（自動排程）

```
General:
  Name: Chip Radar Local (21:17)
  Run whether user is logged in or not: ☑

Triggers:
  Daily, 21:17, recur every 1 day, Mon-Fri only

Actions:
  Program: powershell.exe
  Arguments: -NoProfile -ExecutionPolicy Bypass -File "C:\path\to\repo\scripts\run_local.ps1"
  Start in: C:\path\to\repo
```

### Tailscale 共享資料夾

跑完後 `local_data/` 就有所有資料。透過 Windows 共享資料夾 + Tailscale 讓其他設備存取：

1. 右鍵 `local_data/` → 內容 → 共用 → 選擇要共用的人員
2. 其他設備透過 Tailscale 內網 IP 存取：`\\100.x.x.x\local_data\`

### backup_gdrive.ps1

每週壓縮 `local_data/` 上傳到 Google Drive，保留最近 2 份。

#### 前置：安裝 rclone

```powershell
winget install Rclone.Rclone

# 設定 Google Drive remote (照畫面操作一次)
rclone config
# → New remote → name: gdrive → Storage: Google Drive → 照提示授權

# 驗證
rclone lsd gdrive:
```

#### Task Scheduler 設定

```
General:
  Name: Chip Radar Backup (Sun 18:00)

Triggers:
  Weekly, Sunday 18:00

Actions:
  Program: powershell.exe
  Arguments: -NoProfile -ExecutionPolicy Bypass -File "C:\path\to\repo\scripts\backup_gdrive.ps1"
  Start in: C:\path\to\repo
```

備份檔名格式：`chip_radar_backup_YYYYMMDD.zip`，自動刪除超過 2 份的舊備份。
