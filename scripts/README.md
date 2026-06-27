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
- `refresh_attstock_disposal.py` — daily-full.yml (抓 attstock 處置股 → Mobile sheet 避開)
- `extract_mobile_summary_text.py` — daily-full.yml 最後 step (Mobile sheet → email body)
- `backfill_taiex_history.py` — 一次性 (v3.71.4 修 6/2-6/8 兜底重複日汙染殘留)
- `regen_excel_618.py` — 一次性 (6/18 Excel 重生 audit 用)
- `inspect_section_a_618.py` — 一次性 debug

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
