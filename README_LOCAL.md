# Windows 本機執行指南

本文件說明如何在 Windows 上直接跑 Chip Radar，資料存在本機 `local_data/`，不影響 GitHub Actions 的線上版本。

---

## 架構概覽

```
GitHub Actions（線上，不動）
  cron 排程 → crawler.py → data/ → commit → GitHub Pages

Windows 本機（本文件）
  start.bat → 註冊排程 + 啟動 local server
            → scheduler.ps1 每分鐘檢查，按時跑各個腳本
            → local_server.py 服務 index.html 儀表板
            → 瀏覽器開 http://localhost:8080 看資料
            → 每週日壓縮備份到 Google Drive
  stop.bat  → 停止 server + 移除排程
```

兩條線完全獨立，互不影響。

---

## 快速開始（3 步驟）

### Step 1：安裝 Python（做一次）

```powershell
winget install Python.Python.3.11
```

裝完後**關掉終端，重新開一個**，讓 PATH 生效。

### Step 2：設密碼（做一次）

```powershell
[System.Environment]::SetEnvironmentVariable('CHIP_RADAR_PASSWORD', '你的密碼', 'User')
```

填跟 GitHub Secrets 裡同一組密碼。設完**重開終端**。

或用圖形介面：`Win+R` → `sysdm.cpl` → 進階 → 環境變數 → 使用者變數 → 新增 `CHIP_RADAR_PASSWORD`。

### Step 3：啟動

**雙擊 `start.bat`**

它會：
1. 檢查 Python 和密碼
2. 啟動 local HTTP server（背景）
3. 註冊 Task Scheduler 排程
4. 自動開瀏覽器到 http://localhost:8080

完成。關掉視窗就好，排程會在背景自動跑。

---

## 日常使用

### 開機後

雙擊 `start.bat`。

### 看儀表板

瀏覽器開 http://localhost:8080，跟 GitHub Pages 的體驗一樣 — 輸入密碼就能看。

其他設備（透過 Tailscale）開 http://100.x.x.x:8080 也能看。

### 不用管的東西

排程會自動在背景跑，完全對齊 GitHub Actions 的時間表：

| 時間 | 做什麼 | 對應 workflow |
|------|--------|--------------|
| 08:00 / 09:00 / 12:00 | 融資融券更新 | margin-refresh |
| 08:50（週二~六） | 盤前簡報 | pre-market-alert |
| 13:30 / 17:30 / 21:30（結算週） | 結算尾部風險 | settlement-tracking |
| 13:35（週二~六） | 盤後三大法人速報 | intraday-settlement |
| 14:30（週五） | 週報 | weekly-summary |
| 21:17 / 22:37 / 23:47（週一~五） | 主爬蟲全量 | daily-full |
| 22:30 / 23:30（週一~五） | 融資融券更新 | margin-refresh |
| 00:30 / 02:00 | 融資融券更新（隔日） | margin-refresh |
| 00:30 / 09:00 | 資料新鮮度檢查 | heartbeat |
| 11:00 / 14:00（週六） | TDCC 集保大戶 | tdcc-weekly |
| 18:00（週日） | 壓縮備份到 Google Drive | backup |

### 查看 log

排程執行紀錄在桌面 `chip_radar_scheduler.log`：

```
[2026-06-25 21:17:00] [daily-full] START: python crawler.py
[2026-06-25 21:35:42] [daily-full] OK (18.6 min)
[2026-06-25 22:30:00] [margin] START: python crawler.py
[2026-06-25 22:31:15] [margin] OK (1.2 min)
```

### 停止

**雙擊 `stop.bat`**。移除排程 + 停止 server。

### 恢復

再**雙擊 `start.bat`**。

---

## 手動執行（進階）

不想等排程，想立刻跑：

```powershell
# 用腳本跑（推薦，自動設好環境）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_local.ps1

# 或直接跑 Python
$env:CHIP_RADAR_DATA_DIR = "local_data"
python crawler.py                    # 主爬蟲
python pre_market_brief.py           # 盤前簡報
python intraday_settlement.py        # 盤後速報
python weekly_summary.py             # 週報
python tdcc_holdings.py --data-dir local_data   # TDCC 集保
```

---

## Tailscale 共享（其他設備存取）

### 方法 A：儀表板（推薦）

其他設備的瀏覽器直接開：

```
http://100.x.x.x:8080
```

跟你本機看到的一模一樣。`100.x.x.x` 是這台的 Tailscale IP。

### 方法 B：檔案共享

1. 右鍵 `local_data/` → 內容 → 共用 → 設定共用
2. 其他設備存取 `\\100.x.x.x\local_data\`

> 兩種方式都需要這台電腦保持開機。

---

## 每週備份到 Google Drive

`start.bat` 會自動註冊每週日 18:00 的備份排程。

### 前置設定（做一次）

```powershell
# 安裝 rclone
winget install Rclone.Rclone

# 設定 Google Drive remote
rclone config
# → n (New) → name: gdrive → Storage: Google Drive → 照提示授權

# 驗證
rclone lsd gdrive:
```

### 備份機制

- 每週日 18:00 自動壓縮 `local_data/` → `chip_radar_backup_YYYYMMDD.zip`
- 上傳到 Google Drive `ChipRadar/backups/`
- 只保留最近 2 份，舊的自動刪除

### 手動備份

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backup_gdrive.ps1
```

備份 log 在桌面 `chip_radar_backup.log`。

---

## 資料目錄結構

```
local_data/
  latest.json              當天加密資料（儀表板用）
  YYYYMMDD.json            每日加密快照
  positions.json           FIFO 累積部位
  stock_history.json       60 日股價歷史
  master_profiles.json     大戶標籤
  temp_history.json        籌碼溫度
  chip_radar_v2.db         SQLite 資料庫
  pre_market_brief.json    盤前簡報
  intraday_settlement.json 盤後速報
  heartbeat.json           資料新鮮度
  archive/                 7-60 天歷史（自動輪轉）
  reports/                 週報 / 月報
```

`local_data/` 已加入 `.gitignore`，不會上傳 GitHub。

---

## 疑難排解

| 問題 | 解法 |
|------|------|
| `CHIP_RADAR_PASSWORD not set` | 設完環境變數後**重開終端再跑** start.bat |
| `Python not found` | 重開終端讓 PATH 生效 |
| 儀表板打不開 | 確認 server 有跑：`netstat -an \| findstr 8080` |
| 排程沒跑 | 看 `chip_radar_scheduler.log`，或開 Task Scheduler 看歷史 |
| rclone 授權過期 | `rclone config reconnect gdrive:` |
| 資料跟 GitHub Pages 不同 | 正常，兩邊獨立跑 |
| 終端亂碼 | 用 Windows Terminal（非 cmd），或設 `PYTHONIOENCODING=utf-8` |
| start.bat 註冊失敗 | 右鍵 start.bat → 以系統管理員身分執行 |

---

## 環境變數一覽

| 變數 | 必填 | 用途 |
|------|------|------|
| `CHIP_RADAR_PASSWORD` | 是 | 加密密碼（跟 GitHub Secrets 同一組） |
| `CHIP_RADAR_DATA_DIR` | 否 | 資料目錄（start.bat / scheduler 自動設） |
| `CHIP_RADAR_STAGE` | 否 | `full`（預設）/ `margin_only` |
| `CHIP_RADAR_PORT` | 否 | Local server port（預設 8080） |
| `CHIP_RADAR_LOG_DIR` | 否 | Log 路徑覆蓋 |
| `PYTHONIOENCODING` | 否 | 終端編碼（解決亂碼用 `utf-8`） |
