# =====================================================================
# Chip Radar TW - Local Windows Execution
# =====================================================================
# Purpose : Run crawler.py locally on Windows, outputting to local_data/.
#           Can be triggered manually or via Windows Task Scheduler.
#
# Env     : Requires CHIP_RADAR_PASSWORD system environment variable.
#           Data directory defaults to local_data/ (via CHIP_RADAR_DATA_DIR).
#
# Setup   : See scripts/README.md "Windows 本機執行" section.
#
# Audit   : Logs every run to chip_radar_local.log. Default location
#           resolves in this order:
#             1. $env:CHIP_RADAR_LOG_DIR (explicit override)
#             2. $env:USERPROFILE\Desktop (typical Windows user)
#             3. $PSScriptRoot (next to this script - fallback)
# =====================================================================
$ErrorActionPreference = "Continue"

# ── Log path (same 3-tier fallback as trigger_chip_radar.ps1) ──
$logFile = if ($env:CHIP_RADAR_LOG_DIR) {
    Join-Path $env:CHIP_RADAR_LOG_DIR 'chip_radar_local.log'
} elseif (Test-Path "$env:USERPROFILE\Desktop") {
    "$env:USERPROFILE\Desktop\chip_radar_local.log"
} else {
    Join-Path $PSScriptRoot 'chip_radar_local.log'
}
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# ── Toast helper (BalloonTip fallback if BurntToast not installed) ──
function Show-ChipRadarToast {
    param(
        [string]$Title,
        [string]$Message,
        [string]$Level = "Info"
    )
    try {
        if (Get-Module -ListAvailable -Name BurntToast) {
            Import-Module BurntToast -ErrorAction Stop
            New-BurntToastNotification -Text $Title, $Message -ErrorAction Stop
            return
        }
    } catch { }
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
        Add-Content -Path $logFile -Value "[$timestamp] Toast failed: $_" -Encoding UTF8
    }
}

Add-Content -Path $logFile -Value "[$timestamp] === Local run start ===" -Encoding UTF8

# ── Verify prerequisites ──
# 1. Password
if (-not $env:CHIP_RADAR_PASSWORD) {
    $msg = "CHIP_RADAR_PASSWORD not set. Please set it as a system environment variable."
    Add-Content -Path $logFile -Value "[$timestamp] FATAL: $msg" -Encoding UTF8
    Show-ChipRadarToast -Title "[FAIL] Chip Radar" -Message $msg -Level "Error"
    exit 1
}

# 2. Python
$pythonCheck = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCheck) {
    $msg = "Python not found on PATH."
    Add-Content -Path $logFile -Value "[$timestamp] FATAL: $msg" -Encoding UTF8
    Show-ChipRadarToast -Title "[FAIL] Chip Radar" -Message $msg -Level "Error"
    exit 1
}

# ── Set data directory to local_data/ ──
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:CHIP_RADAR_DATA_DIR = Join-Path $projectRoot "local_data"
$env:PYTHONIOENCODING = "utf-8"

Add-Content -Path $logFile -Value "[$timestamp] Project root: $projectRoot" -Encoding UTF8
Add-Content -Path $logFile -Value "[$timestamp] Data dir: $env:CHIP_RADAR_DATA_DIR" -Encoding UTF8

# ── Run crawler ──
$crawlerPath = Join-Path $projectRoot "crawler.py"
$startTime = Get-Date

try {
    Add-Content -Path $logFile -Value "[$timestamp] Running: python $crawlerPath" -Encoding UTF8
    $output = & python $crawlerPath 2>&1
    $exitCode = $LASTEXITCODE
    $duration = [math]::Round(((Get-Date) - $startTime).TotalMinutes, 1)

    Add-Content -Path $logFile -Value "[$timestamp] Exit code: $exitCode (${duration} min)" -Encoding UTF8

    if ($exitCode -eq 0) {
        Show-ChipRadarToast -Title "[OK] Chip Radar Local" -Message "Crawler done (${duration} min)" -Level "Info"
        Add-Content -Path $logFile -Value "[$timestamp] === Local run SUCCESS ===" -Encoding UTF8
    } else {
        $lastLines = ($output | Select-Object -Last 5) -join "`n"
        Add-Content -Path $logFile -Value "[$timestamp] FAILED output (last 5 lines):`n$lastLines" -Encoding UTF8
        Show-ChipRadarToast -Title "[FAIL] Chip Radar Local" -Message "Exit $exitCode (${duration} min)" -Level "Error"
        Add-Content -Path $logFile -Value "[$timestamp] === Local run FAILED ===" -Encoding UTF8
    }
    exit $exitCode
} catch {
    $duration = [math]::Round(((Get-Date) - $startTime).TotalMinutes, 1)
    Add-Content -Path $logFile -Value "[$timestamp] EXCEPTION: $_ (${duration} min)" -Encoding UTF8
    Show-ChipRadarToast -Title "[FAIL] Chip Radar Local" -Message "$_" -Level "Error"
    exit 1
}
