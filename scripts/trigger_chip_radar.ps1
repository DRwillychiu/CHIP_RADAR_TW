# =====================================================================
# Chip Radar TW - Daily Full Crawl Trigger
# =====================================================================
# Purpose : Used by Windows Task Scheduler to dispatch the GitHub Actions
#           daily-full workflow, poll for completion, then read the
#           daily_audit.json verdict and surface a Windows toast.
#
# History : Originally lived on user Desktop (out of repo). v3.49.0
#           moved into scripts/ for git tracking (運1 維運). Path logic
#           kept generic so any user can clone + use.
#
# Setup   : See README at bottom of file, or scripts/README.md.
#
# Audit   : Logs every attempt to chip_radar_trigger.log. Default
#           location resolves in this order:
#             1. $env:CHIP_RADAR_LOG_DIR (explicit override)
#             2. $env:USERPROFILE\Desktop (typical Windows user)
#             3. $PSScriptRoot (next to this script — fallback)
# =====================================================================
$ErrorActionPreference = "Continue"

# ── v3.49.0 (運1): log path is now configurable (was hardcoded Desktop) ──
$logFile = if ($env:CHIP_RADAR_LOG_DIR) {
    Join-Path $env:CHIP_RADAR_LOG_DIR 'chip_radar_trigger.log'
} elseif (Test-Path "$env:USERPROFILE\Desktop") {
    "$env:USERPROFILE\Desktop\chip_radar_trigger.log"
} else {
    Join-Path $PSScriptRoot 'chip_radar_trigger.log'
}
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# Ensure gh CLI is on PATH (Task Scheduler may strip user PATH)
$ghPaths = @(
    "$env:LOCALAPPDATA\Programs\GitHub CLI",
    "C:\Program Files\GitHub CLI"
)
foreach ($p in $ghPaths) {
    if (Test-Path $p) { $env:Path = "$p;$env:Path" }
}

Add-Content -Path $logFile -Value "[$timestamp] === Trigger start ===" -Encoding UTF8

# Verify gh available
$ghCheck = Get-Command gh -ErrorAction SilentlyContinue
if (-not $ghCheck) {
    Add-Content -Path $logFile -Value "[$timestamp] FATAL: gh CLI not found on PATH" -Encoding UTF8
    exit 1
}

# ── Toast helper (BalloonTip fallback if BurntToast not installed) ──
function Show-ChipRadarToast {
    param(
        [string]$Title,
        [string]$Message,
        [string]$Level = "Info"  # Info / Warning / Error
    )
    try {
        # Prefer BurntToast module if installed (modern Windows 10/11 toast)
        if (Get-Module -ListAvailable -Name BurntToast) {
            Import-Module BurntToast -ErrorAction Stop
            New-BurntToastNotification -Text $Title, $Message -ErrorAction Stop
            return
        }
    } catch { }
    # Fallback: classic NotifyIcon BalloonTip (works on all Windows)
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        $balloon = New-Object System.Windows.Forms.NotifyIcon
        $balloon.Icon = [System.Drawing.SystemIcons]::Information
        $balloon.BalloonTipTitle = $Title
        $balloon.BalloonTipText = $Message
        $balloon.BalloonTipIcon = $Level
        $balloon.Visible = $true
        $balloon.ShowBalloonTip(10000)
        Start-Sleep -Seconds 1
        $balloon.Dispose()
    } catch {
        Add-Content -Path $logFile -Value "[$timestamp] Toast 失敗: $_" -Encoding UTF8
    }
}

# Dispatch daily-full workflow
try {
    $dispatchOutput = & gh workflow run daily-full.yml --repo DRwillychiu/CHIP_RADAR_TW 2>&1
    $exitCode = $LASTEXITCODE
    Add-Content -Path $logFile -Value "[$timestamp] gh workflow run exit=$exitCode output=$dispatchOutput" -Encoding UTF8

    if ($exitCode -ne 0) {
        Add-Content -Path $logFile -Value "[$timestamp] FAILED to dispatch workflow" -Encoding UTF8
        Show-ChipRadarToast -Title "[FAIL] Chip Radar Trigger 失敗" -Message "gh workflow run exit $exitCode" -Level "Error"
        exit 1
    }
} catch {
    Add-Content -Path $logFile -Value "[$timestamp] EXCEPTION on dispatch: $_" -Encoding UTF8
    Show-ChipRadarToast -Title "[FAIL] Chip Radar Trigger 失敗" -Message "$_" -Level "Error"
    exit 1
}

# Wait 5s for GitHub to register the run, then query latest
Start-Sleep -Seconds 5
$latestRunId = $null
try {
    $latestRun = & gh run list --repo DRwillychiu/CHIP_RADAR_TW --workflow daily-full.yml --limit 1 --json status,conclusion,createdAt,event,databaseId 2>&1
    Add-Content -Path $logFile -Value "[$timestamp] Latest run: $latestRun" -Encoding UTF8
    # Parse run ID for later polling
    $runJson = $latestRun | ConvertFrom-Json
    if ($runJson -and $runJson.Count -gt 0) {
        $latestRunId = $runJson[0].databaseId
    }
} catch {
    Add-Content -Path $logFile -Value "[$timestamp] WARN: could not query latest run: $_" -Encoding UTF8
}

# ── v3.29.3 W2: Poll run until completion, then read daily_audit.json + toast ──
if ($latestRunId) {
    Add-Content -Path $logFile -Value "[$timestamp] === Polling run $latestRunId ===" -Encoding UTF8
    $pollMax = 30  # 30 × 30s = 15 min max
    $polls = 0
    $runDone = $false
    while (-not $runDone -and $polls -lt $pollMax) {
        Start-Sleep -Seconds 30
        $polls++
        try {
            $runInfoRaw = & gh run view $latestRunId --repo DRwillychiu/CHIP_RADAR_TW --json status,conclusion 2>&1
            $runInfo = $runInfoRaw | ConvertFrom-Json
            if ($runInfo.status -eq "completed") {
                $runDone = $true
                $conclusion = $runInfo.conclusion
                Add-Content -Path $logFile -Value "[$(Get-Date -Format 'HH:mm:ss')] Run $latestRunId 完成: $conclusion (polled $polls 次)" -Encoding UTF8

                if ($conclusion -eq "success") {
                    # Pull data/daily_audit.json from GitHub raw
                    try {
                        $auditUrl = "https://raw.githubusercontent.com/DRwillychiu/CHIP_RADAR_TW/main/data/daily_audit.json"
                        $auditJson = Invoke-RestMethod -Uri $auditUrl -TimeoutSec 20 -ErrorAction Stop
                        $verdict = $auditJson.overall_verdict
                        $summary = $auditJson.summary
                        $sheet = $auditJson.sheet
                        Add-Content -Path $logFile -Value "[$(Get-Date -Format 'HH:mm:ss')] Audit $sheet -> ${verdict}: $summary" -Encoding UTF8

                        # Show toast based on verdict
                        switch ($verdict) {
                            "PASS"  { Show-ChipRadarToast -Title "[PASS] Chip Radar $sheet" -Message $summary -Level "Info" }
                            "WARN"  { Show-ChipRadarToast -Title "[WARN] Chip Radar $sheet" -Message $summary -Level "Warning" }
                            "FAIL"  { Show-ChipRadarToast -Title "[FAIL] Chip Radar $sheet" -Message $summary -Level "Error" }
                            "ERROR" { Show-ChipRadarToast -Title "[ERROR] Chip Radar Audit" -Message $summary -Level "Error" }
                            default { Show-ChipRadarToast -Title "Chip Radar $sheet" -Message "$verdict $summary" -Level "Info" }
                        }
                    } catch {
                        Add-Content -Path $logFile -Value "[$(Get-Date -Format 'HH:mm:ss')] daily_audit.json 讀取失敗: $_" -Encoding UTF8
                        Show-ChipRadarToast -Title "[WARN] Chip Radar audit 讀取失敗" -Message "Run success 但 audit json 拉不到" -Level "Warning"
                    }
                } else {
                    Show-ChipRadarToast -Title "[FAIL] Chip Radar Run $conclusion" -Message "daily-full workflow $conclusion (run $latestRunId)" -Level "Error"
                }
            }
        } catch {
            Add-Content -Path $logFile -Value "[$(Get-Date -Format 'HH:mm:ss')] poll 失敗 $_" -Encoding UTF8
        }
    }
    if (-not $runDone) {
        Add-Content -Path $logFile -Value "[$(Get-Date -Format 'HH:mm:ss')] Run $latestRunId 超過 polling 時限 ($pollMax × 30s)" -Encoding UTF8
        Show-ChipRadarToast -Title "[WARN] Chip Radar 跑超時" -Message "$pollMax polls 還在跑, 自己看 Actions 頁" -Level "Warning"
    }
}

Add-Content -Path $logFile -Value "[$(Get-Date -Format 'HH:mm:ss')] === Trigger end ===" -Encoding UTF8
Add-Content -Path $logFile -Value "" -Encoding UTF8
