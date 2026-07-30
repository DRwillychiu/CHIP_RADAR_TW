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
    @{ time="21:17"; days=$WEEKDAY_1_5; job="daily-full"; pre=@("python scripts/refresh_attstock_disposal.py"); cmd="python crawler.py"; post=@("python scripts/daily_rolling_update.py", "python scripts/send_daily_telegram.py") }
    @{ time="22:37"; days=$WEEKDAY_1_5; job="daily-full"; pre=@("python scripts/refresh_attstock_disposal.py"); cmd="python crawler.py"; post=@("python scripts/daily_rolling_update.py", "python scripts/send_daily_telegram.py") }
    @{ time="23:47"; days=$WEEKDAY_1_5; job="daily-full"; pre=@("python scripts/refresh_attstock_disposal.py"); cmd="python crawler.py"; post=@("python scripts/daily_rolling_update.py", "python scripts/send_daily_telegram.py") }

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
$matched = $schedule | Where-Object { $_.time -eq $hhmm -and $_.days -contains $dow }

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

    Add-Content -Path $logFile -Value "[$timestamp] [$jobName] START: $cmd" -Encoding UTF8
    $startTime = Get-Date

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
        $status = if ($exitCode -eq 0) { "OK" } else { "FAIL (exit $exitCode)" }
        Add-Content -Path $logFile -Value "[$timestamp] [$jobName] $status (${duration} min)" -Encoding UTF8

        $lastLines = ($output | Select-Object -Last 5) -join " | "
        Add-Content -Path $logFile -Value "[$timestamp] [$jobName] Output: $lastLines" -Encoding UTF8

        $recStatus = if ($exitCode -eq 0) { "OK" } else { "FAIL" }
        Write-ExecutionRecord -JobName $jobName -Command $cmd -Status $recStatus -ExitCode $exitCode -DurationMin $duration -OutputTail $lastLines
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
