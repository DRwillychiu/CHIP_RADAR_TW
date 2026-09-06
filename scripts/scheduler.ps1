# =====================================================================
# Chip Radar TW - Local Scheduler (called every minute by Task Scheduler)
# =====================================================================
# Mirrors the GitHub Actions cron schedules for local Windows execution.
# Each minute: check current time → if a job matches → run it.
# Jobs write to local_data/ via CHIP_RADAR_DATA_DIR env var.
# =====================================================================
$ErrorActionPreference = "Continue"

# ── Paths ──
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# ── Load .env ──
$dotenvFile = Join-Path $projectRoot ".env"
if (Test-Path $dotenvFile) {
    Get-Content $dotenvFile -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $k, $v = $line -split "=", 2
            $k = $k.Trim(); $v = $v.Trim()
            if ($v -and -not [System.Environment]::GetEnvironmentVariable($k)) {
                Set-Item -Path "env:$k" -Value $v
            }
        }
    }
}
$logFile = if ($env:CHIP_RADAR_LOG_DIR) {
    Join-Path $env:CHIP_RADAR_LOG_DIR 'chip_radar_scheduler.log'
} elseif (Test-Path "$env:USERPROFILE\Desktop") {
    "$env:USERPROFILE\Desktop\chip_radar_scheduler.log"
} else {
    Join-Path $PSScriptRoot 'chip_radar_scheduler.log'
}

# ── Ensure Python is on PATH ──
$pyPaths = @(
    "$env:LOCALAPPDATA\Programs\Python\Python311",
    "$env:LOCALAPPDATA\Programs\Python\Python312",
    "$env:LOCALAPPDATA\Programs\Python\Python313",
    "C:\Python311", "C:\Python312", "C:\Python313"
)
foreach ($p in $pyPaths) {
    if (Test-Path $p) { $env:Path = "$p;$p\Scripts;$env:Path"; break }
}

# ── Activate venv if exists (overrides system Python) ──
$venvScripts = Join-Path $projectRoot ".venv\Scripts"
if (Test-Path (Join-Path $venvScripts "python.exe")) {
    $env:Path = "$venvScripts;$env:Path"
    $env:VIRTUAL_ENV = Join-Path $projectRoot ".venv"
}

# ── Environment ──
$env:CHIP_RADAR_DATA_DIR = Join-Path $projectRoot "local_data"
$env:PYTHONIOENCODING = "utf-8"

# v3.73.2: 修 log 中文亂碼 (「鞈??交?」)。
#   Python 依 PYTHONIOENCODING 以 UTF-8 輸出,但 PowerShell 接收子行程 stdout 時
#   是用 [Console]::OutputEncoding 解碼的,預設為系統 OEM codepage (zh-TW = CP950),
#   於是 UTF-8 bytes 被當成 Big5 解讀 → 亂碼寫進 log。
#   改成以 UTF-8 解碼即可 (寫檔端本來就已經是 -Encoding UTF8)。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# ── Structured execution log (JSONL) ──
$logsDir = Join-Path $projectRoot "logs"
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir -Force | Out-Null }

function Write-ExecutionRecord {
    param(
        [string]$JobName,
        [string]$Command,
        [string]$Status,     # OK / FAIL / SKIP / EXCEPTION
        [int]$ExitCode = 0,
        [double]$DurationMin = 0,
        [string]$OutputTail = "",
        [string]$ErrorMsg = ""
    )
    $dateStr = (Get-Date).ToString("yyyyMMdd")
    $record = @{
        ts        = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        job       = $JobName
        cmd       = $Command
        status    = $Status
        exit_code = $ExitCode
        duration_min = $DurationMin
        output    = $OutputTail
        error     = $ErrorMsg
    }
    $jsonLine = $record | ConvertTo-Json -Compress
    $jsonlPath = Join-Path $logsDir "scheduler_$dateStr.jsonl"
    Add-Content -Path $jsonlPath -Value $jsonLine -Encoding UTF8
}

# ── Schedule table (mirrors .github/workflows/*.yml) ──
# Format: HH:mm = @{ days = "Mon-Fri" or "Tue-Sat" or "Sat" or "Sun"; job = "name" }
#
# Days key: Mon=1 Tue=2 Wed=3 Thu=4 Fri=5 Sat=6 Sun=0
$WEEKDAY_1_5 = @(1,2,3,4,5)          # Mon-Fri
$WEEKDAY_2_6 = @(2,3,4,5,6)          # Tue-Sat
$SAT_ONLY    = @(6)                    # Sat
$FRI_ONLY    = @(5)                    # Fri

$schedule = @(
    # ── daily-full.yml: 主爬蟲 (3-layer redundancy) ──
    # v3.73.1: post = 爬完後的後續步驟,鏡射 daily-full.yml 的 step 6/7 + 推播。
    #   每個 post 步驟獨立執行、失敗不中斷後續 (等同雲端的 continue-on-error)。
    #   順序刻意跟雲端不同: 處置股放在 crawler 之前。
    #   雲端是 crawler → regen Excel → refresh disposal,等於 Excel 用到的是
    #   前一天的處置資料;本機提前抓,當天的 Excel 就吃得到當天處置清單。
    #   send_daily_telegram.py 自己用 marker 檔去重 (同一 trade_date 只推一次),
    #   所以 22:37 / 23:47 兜底跑到那步會自動跳過,不會重複推。
    # v3.75.0: push_disposal_telegram.py = 處置股圖卡,下載 disposal-watch 的雲端
    #   artifact 後推 TG (四張一組 media group)。本專案不自己畫、也不再本機重跑
    #   上游管線 (v3.74.x 的借跑在 attstock 封 IP 後整整壞了四天且靜默無感)。
    #   21:17 這班的 crawler 要跑約 19 分鐘,實際執行落在 21:37 左右,
    #   雲端 21:20-21:25 已上傳完 artifact,時序來得及。
    #   自帶去重 (同一 artifact 不重推、同報表日改為編輯原訊息),兜底重跑不洗版。
    @{ time="21:17"; days=$WEEKDAY_1_5; job="daily-full"; pre=@("python scripts/refresh_attstock_disposal.py"); cmd="python crawler.py"; post=@("python scripts/daily_rolling_update.py", "python scripts/send_daily_telegram.py", "python scripts/push_disposal_telegram.py") }
    @{ time="22:37"; days=$WEEKDAY_1_5; job="daily-full"; pre=@("python scripts/refresh_attstock_disposal.py"); cmd="python crawler.py"; post=@("python scripts/daily_rolling_update.py", "python scripts/send_daily_telegram.py", "python scripts/push_disposal_telegram.py") }
    @{ time="23:47"; days=$WEEKDAY_1_5; job="daily-full"; pre=@("python scripts/refresh_attstock_disposal.py"); cmd="python crawler.py"; post=@("python scripts/daily_rolling_update.py", "python scripts/send_daily_telegram.py", "python scripts/push_disposal_telegram.py") }

    # ── v3.75.0: Telegram 指令輪詢 ──
    #   手機打 /refresh 就重抓 disposal-watch 的 artifact 並更新既有訊息。
    #   every=2 (每 2 分鐘) 而非固定時刻 —— 指令要能隨時下,列 720 個時刻不現實。
    #   quiet: 沒收到指令時完全不寫 log,否則一天 720 次會把有用的紀錄淹掉。
    #   telegram_poll.py 自帶鎖檔,前一次還沒跑完時不會重入 (Telegram 對同一
    #   個 bot 同時 getUpdates 會回 409)。
    @{ every=2; days=@(0,1,2,3,4,5,6); job="tg-poll"; quiet=$true; detached=$true; cmd="python scripts/telegram_poll.py" }

    # ── margin-refresh.yml: 融資融券 7-layer defense ──
    @{ time="22:30"; days=$WEEKDAY_1_5; job="margin";       cmd="python crawler.py"; env=@{CHIP_RADAR_STAGE="margin_only"} }
    @{ time="23:30"; days=$WEEKDAY_1_5; job="margin";       cmd="python crawler.py"; env=@{CHIP_RADAR_STAGE="margin_only"} }
    @{ time="00:30"; days=$WEEKDAY_2_6; job="margin";       cmd="python crawler.py"; env=@{CHIP_RADAR_STAGE="margin_only"} }
    @{ time="02:00"; days=$WEEKDAY_2_6; job="margin";       cmd="python crawler.py"; env=@{CHIP_RADAR_STAGE="margin_only"} }
    @{ time="08:00"; days=$WEEKDAY_2_6; job="margin";       cmd="python crawler.py"; env=@{CHIP_RADAR_STAGE="margin_only"} }
    @{ time="09:00"; days=$WEEKDAY_2_6; job="margin";       cmd="python crawler.py"; env=@{CHIP_RADAR_STAGE="margin_only"} }
    @{ time="12:00"; days=$WEEKDAY_2_6; job="margin";       cmd="python crawler.py"; env=@{CHIP_RADAR_STAGE="margin_only"} }

    # ── pre-market-alert.yml: 盤前簡報 ──
    @{ time="08:50"; days=$WEEKDAY_2_6; job="pre-market";   cmd="python pre_market_brief.py" }

    # ── intraday-settlement.yml: 盤後速報 ──
    @{ time="13:35"; days=$WEEKDAY_2_6; job="intraday";     cmd="python intraday_settlement.py" }

    # ── settlement-tracking.yml: 結算週 tail risk (D-3~D+1 才跑) ──
    @{ time="13:30"; days=$WEEKDAY_2_6; job="settlement";   cmd="python intraday_settlement.py"; settlement_only=$true }
    @{ time="17:30"; days=$WEEKDAY_2_6; job="settlement";   cmd="python intraday_settlement.py"; settlement_only=$true }
    @{ time="21:30"; days=$WEEKDAY_2_6; job="settlement";   cmd="python intraday_settlement.py"; settlement_only=$true }

    # ── tdcc-weekly.yml: 集保大戶 (2-layer) ──
    @{ time="11:00"; days=$SAT_ONLY;    job="tdcc";         cmd="python tdcc_holdings.py --data-dir local_data" }
    @{ time="14:00"; days=$SAT_ONLY;    job="tdcc";         cmd="python tdcc_holdings.py --data-dir local_data" }

    # ── weekly-summary.yml: 週報 ──
    @{ time="14:30"; days=$FRI_ONLY;    job="weekly";       cmd="python weekly_summary.py" }

    # ── heartbeat.yml: 資料新鮮度 ──
    @{ time="00:30"; days=@(0,1,2,3,4,5,6); job="heartbeat"; cmd="python heartbeat_check.py --latest local_data/latest.json --output local_data/heartbeat.json" }
    @{ time="09:00"; days=@(0,1,2,3,4,5,6); job="heartbeat"; cmd="python heartbeat_check.py --latest local_data/latest.json --output local_data/heartbeat.json" }

    # ── morning report: 每日執行報告彈窗 ──
    @{ time="08:10"; days=@(0,1,2,3,4,5,6); job="morning-report"; cmd="morning_report.ps1"; gui=$true }
)

# ── Check current time ──
$now = Get-Date
$hhmm = $now.ToString("HH:mm")
$dow = [int]$now.DayOfWeek  # Sun=0, Mon=1, ..., Sat=6

# ── Find matching jobs ──
# v3.75.0: 除了固定時刻 (time),再支援每 N 分鐘 (every)。Telegram 指令輪詢
#   需要高頻檢查,列 720 個固定時刻不現實。
$matched = $schedule | Where-Object {
    $_.days -contains $dow -and (
        ($_.time -and $_.time -eq $hhmm) -or
        ($_.every -and ($now.Minute % $_.every) -eq 0)
    )
}

if (-not $matched -or $matched.Count -eq 0) { exit 0 }

# ── Execute matched jobs ──
foreach ($entry in $matched) {
    $jobName = $entry.job
    $cmd = $entry.cmd
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    # Settlement window check
    if ($entry.settlement_only) {
        try {
            $checkResult = & python -c "
import sys; sys.path.insert(0,'src/pipelines')
from crawler_pipeline import _days_to_settlement
from datetime import datetime, timezone, timedelta
tw = datetime.now(timezone(timedelta(hours=8)))
d = _days_to_settlement(tw.strftime('%Y%m%d'))
in_window = d is not None and -1 <= d <= 3
print('YES' if in_window else 'NO')
" 2>&1
            if ($checkResult -ne "YES") {
                Add-Content -Path $logFile -Value "[$timestamp] [$jobName] SKIP (not in settlement window)" -Encoding UTF8
                Write-ExecutionRecord -JobName $jobName -Command $cmd -Status "SKIP" -ErrorMsg "not in settlement window"
                continue
            }
        } catch {
            Add-Content -Path $logFile -Value "[$timestamp] [$jobName] Settlement check failed: $_" -Encoding UTF8
            Write-ExecutionRecord -JobName $jobName -Command $cmd -Status "SKIP" -ErrorMsg "settlement check failed: $_"
            continue
        }
    }

    # Set extra env vars if specified
    if ($entry.env) {
        foreach ($k in $entry.env.Keys) {
            Set-Item -Path "env:$k" -Value $entry.env[$k]
        }
    }

    # v3.75.0: quiet job (每 2 分鐘的指令輪詢) 沒事時完全不寫 log ——
    #   一天 720 次 x 3 行會把真正有用的紀錄淹掉。有輸出或非 0 離開碼才記。
    $quiet = [bool]$entry.quiet
    if (-not $quiet) {
        Add-Content -Path $logFile -Value "[$timestamp] [$jobName] START: $cmd" -Encoding UTF8
    }
    $startTime = Get-Date

    # v3.75.0: detached job —— 丟出去就不等它跑完。
    #   本工作的 MultipleInstances 是 IgnoreNew: 同步等待任何長工作,都會讓
    #   後續每一分鐘的觸發被丟掉。實證: 21:30 settlement 在 8/24~8/28 一次都
    #   沒跑過,因為 21:17 daily-full 佔住排程器到 21:36。
    #   tg-poll 的網路呼叫實測 1.2-4.4 秒、最壞 15 秒,雖然還不到一分鐘,但
    #   Task Scheduler 本身延遲時仍可能壓到下一分鐘的固定時刻 job。改成丟出去
    #   就走,佔用降到毫秒級 —— 結構上不可能吃掉別的 job。
    #   代價: 拿不到輸出與離開碼,所以 telegram_poll.py 自己寫 .tg_worker.log。
    if ($entry.detached) {
        $parts = $cmd -split ' ', 2
        try {
            Start-Process -FilePath $parts[0] -ArgumentList $parts[1] `
                          -WorkingDirectory $projectRoot -WindowStyle Hidden
        } catch {
            Add-Content -Path $logFile -Value "[$timestamp] [$jobName] DETACH FAILED: $_" -Encoding UTF8
            Write-ExecutionRecord -JobName $jobName -Command $cmd -Status "EXCEPTION" -ErrorMsg "$_"
        }
        continue
    }

    # ── v3.73.1: pre 步驟 (爬蟲之前) ──
    # 每個獨立執行,失敗不中斷 — 等同 daily-full.yml 的 continue-on-error
    if ($entry.pre) {
        foreach ($preCmd in $entry.pre) {
            try {
                $preOut = & cmd /c "cd /d `"$projectRoot`" && $preCmd" 2>&1
                $preExit = $LASTEXITCODE
                $preStatus = if ($preExit -eq 0) { "OK" } else { "FAIL (exit $preExit)" }
                Add-Content -Path $logFile -Value "[$timestamp] [$jobName] PRE $preStatus : $preCmd" -Encoding UTF8
                Write-ExecutionRecord -JobName "$jobName/pre" -Command $preCmd `
                    -Status $(if ($preExit -eq 0) { "OK" } else { "FAIL" }) -ExitCode $preExit `
                    -OutputTail (($preOut | Select-Object -Last 3) -join " | ")
            } catch {
                Add-Content -Path $logFile -Value "[$timestamp] [$jobName] PRE EXCEPTION: $preCmd -> $_" -Encoding UTF8
                Write-ExecutionRecord -JobName "$jobName/pre" -Command $preCmd -Status "EXCEPTION" -ErrorMsg "$_"
            }
        }
    }

    # GUI jobs (morning report) need a visible window — fire-and-forget via Start-Process
    if ($entry.gui) {
        $scriptPath = Join-Path $PSScriptRoot $cmd
        try {
            Start-Process -FilePath "powershell.exe" -ArgumentList "-ExecutionPolicy Bypass -File `"$scriptPath`"" -WindowStyle Normal
            Add-Content -Path $logFile -Value "[$timestamp] [$jobName] LAUNCHED (gui)" -Encoding UTF8
            Write-ExecutionRecord -JobName $jobName -Command $cmd -Status "OK"
        } catch {
            Add-Content -Path $logFile -Value "[$timestamp] [$jobName] LAUNCH FAILED: $_" -Encoding UTF8
            Write-ExecutionRecord -JobName $jobName -Command $cmd -Status "EXCEPTION" -ErrorMsg "$_"
        }
        continue
    }

    try {
        $output = & cmd /c "cd /d `"$projectRoot`" && $cmd" 2>&1
        $exitCode = $LASTEXITCODE
        $duration = [math]::Round(((Get-Date) - $startTime).TotalMinutes, 1)
        $lastLines = ($output | Select-Object -Last 5) -join " | "
        # quiet job 順利跑完又沒有輸出 = 什麼事都沒發生,不留痕跡
        if (-not ($quiet -and $exitCode -eq 0 -and [string]::IsNullOrWhiteSpace($lastLines))) {
            $status = if ($exitCode -eq 0) { "OK" } else { "FAIL (exit $exitCode)" }
            Add-Content -Path $logFile -Value "[$timestamp] [$jobName] $status (${duration} min)" -Encoding UTF8
            Add-Content -Path $logFile -Value "[$timestamp] [$jobName] Output: $lastLines" -Encoding UTF8

            $recStatus = if ($exitCode -eq 0) { "OK" } else { "FAIL" }
            Write-ExecutionRecord -JobName $jobName -Command $cmd -Status $recStatus -ExitCode $exitCode -DurationMin $duration -OutputTail $lastLines
        }
    } catch {
        $duration = [math]::Round(((Get-Date) - $startTime).TotalMinutes, 1)
        Add-Content -Path $logFile -Value "[$timestamp] [$jobName] EXCEPTION (${duration} min): $_" -Encoding UTF8
        Write-ExecutionRecord -JobName $jobName -Command $cmd -Status "EXCEPTION" -DurationMin $duration -ErrorMsg "$_"
    }

    # ── v3.73.1: post 步驟 (爬蟲之後) ──
    # 不論主命令成敗都跑 — 等同 daily-full.yml 的 continue-on-error。
    # send_daily_telegram.py 自帶防呆: 爬蟲失敗時 trade_date 沒推進,
    # marker 比對後會自動跳過,不會推到舊資料。
    if ($entry.post) {
        foreach ($postCmd in $entry.post) {
            try {
                $postOut = & cmd /c "cd /d `"$projectRoot`" && $postCmd" 2>&1
                $postExit = $LASTEXITCODE
                $postStatus = if ($postExit -eq 0) { "OK" } else { "FAIL (exit $postExit)" }
                Add-Content -Path $logFile -Value "[$timestamp] [$jobName] POST $postStatus : $postCmd" -Encoding UTF8
                Add-Content -Path $logFile -Value "[$timestamp] [$jobName] POST Output: $(($postOut | Select-Object -Last 3) -join ' | ')" -Encoding UTF8
                Write-ExecutionRecord -JobName "$jobName/post" -Command $postCmd `
                    -Status $(if ($postExit -eq 0) { "OK" } else { "FAIL" }) -ExitCode $postExit `
                    -OutputTail (($postOut | Select-Object -Last 3) -join " | ")
            } catch {
                Add-Content -Path $logFile -Value "[$timestamp] [$jobName] POST EXCEPTION: $postCmd -> $_" -Encoding UTF8
                Write-ExecutionRecord -JobName "$jobName/post" -Command $postCmd -Status "EXCEPTION" -ErrorMsg "$_"
            }
        }
    }

    # Reset extra env vars
    if ($entry.env) {
        foreach ($k in $entry.env.Keys) {
            Remove-Item -Path "env:$k" -ErrorAction SilentlyContinue
        }
    }
}
