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
