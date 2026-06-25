# scripts/

入庫的維運腳本。歷史上這類腳本住在 Desktop（個人化路徑），v3.49.0 (運1) 移進此目錄以受 git 管控。

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
