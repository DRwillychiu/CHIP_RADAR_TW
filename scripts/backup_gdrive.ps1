# =====================================================================
# Chip Radar TW - Weekly Backup to Google Drive
# =====================================================================
# Purpose : Compress local_data/ into a dated zip, upload via rclone
#           to Google Drive, and keep only the latest 2 backups.
#
# Schedule: Windows Task Scheduler - every Sunday 18:00
#
# Prerequisites:
#   1. rclone installed: winget install Rclone.Rclone
#   2. rclone configured with a Google Drive remote named "gdrive":
#        rclone config
#        → New remote → name: gdrive → Storage: Google Drive → ...
#   3. Test: rclone lsd gdrive:
#
# Audit   : Logs to chip_radar_backup.log (same 3-tier fallback).
# =====================================================================
$ErrorActionPreference = "Continue"

# ── Config ──
$remoteName   = "gdrive"
$remotePath   = "ChipRadar/backups"
$keepCount    = 2

# ── Log path ──
$logFile = if ($env:CHIP_RADAR_LOG_DIR) {
    Join-Path $env:CHIP_RADAR_LOG_DIR 'chip_radar_backup.log'
} elseif (Test-Path "$env:USERPROFILE\Desktop") {
    "$env:USERPROFILE\Desktop\chip_radar_backup.log"
} else {
    Join-Path $PSScriptRoot 'chip_radar_backup.log'
}
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# ── Toast helper ──
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

Add-Content -Path $logFile -Value "[$timestamp] === Backup start ===" -Encoding UTF8

# ── Verify rclone ──
$rcloneCheck = Get-Command rclone -ErrorAction SilentlyContinue
if (-not $rcloneCheck) {
    $msg = "rclone not found. Install: winget install Rclone.Rclone"
    Add-Content -Path $logFile -Value "[$timestamp] FATAL: $msg" -Encoding UTF8
    Show-ChipRadarToast -Title "[FAIL] Backup" -Message $msg -Level "Error"
    exit 1
}

# ── Locate local_data ──
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$localData = Join-Path $projectRoot "local_data"

if (-not (Test-Path $localData)) {
    $msg = "local_data/ not found at $localData"
    Add-Content -Path $logFile -Value "[$timestamp] FATAL: $msg" -Encoding UTF8
    Show-ChipRadarToast -Title "[FAIL] Backup" -Message $msg -Level "Error"
    exit 1
}

# ── Compress ──
$dateSuffix = Get-Date -Format "yyyyMMdd"
$zipName = "chip_radar_backup_$dateSuffix.zip"
$zipPath = Join-Path $env:TEMP $zipName

Add-Content -Path $logFile -Value "[$timestamp] Compressing $localData -> $zipPath" -Encoding UTF8

try {
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force -Confirm:$false }
    Compress-Archive -Path "$localData\*" -DestinationPath $zipPath -Force
    $sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Add-Content -Path $logFile -Value "[$timestamp] Compressed: $zipName (${sizeMB} MB)" -Encoding UTF8
} catch {
    Add-Content -Path $logFile -Value "[$timestamp] Compress FAILED: $_" -Encoding UTF8
    Show-ChipRadarToast -Title "[FAIL] Backup" -Message "Compress failed: $_" -Level "Error"
    exit 1
}

# ── Upload ──
$dest = "${remoteName}:${remotePath}"
Add-Content -Path $logFile -Value "[$timestamp] Uploading to $dest" -Encoding UTF8

try {
    & rclone copy $zipPath $dest 2>&1
    $uploadExit = $LASTEXITCODE
    if ($uploadExit -ne 0) { throw "rclone exit $uploadExit" }
    Add-Content -Path $logFile -Value "[$timestamp] Upload OK" -Encoding UTF8
} catch {
    Add-Content -Path $logFile -Value "[$timestamp] Upload FAILED: $_" -Encoding UTF8
    Show-ChipRadarToast -Title "[FAIL] Backup" -Message "Upload failed: $_" -Level "Error"
    exit 1
}

# ── Rotate: keep only latest N backups ──
Add-Content -Path $logFile -Value "[$timestamp] Rotating backups (keep latest $keepCount)" -Encoding UTF8

try {
    $remoteFiles = & rclone lsf $dest --files-only 2>&1
    $backups = $remoteFiles | Where-Object { $_ -match '^chip_radar_backup_\d{8}\.zip$' } | Sort-Object -Descending
    if ($backups.Count -gt $keepCount) {
        $toDelete = $backups | Select-Object -Skip $keepCount
        foreach ($old in $toDelete) {
            & rclone deletefile "${dest}/${old}" 2>&1
            Add-Content -Path $logFile -Value "[$timestamp] Deleted old backup: $old" -Encoding UTF8
        }
    }
    Add-Content -Path $logFile -Value "[$timestamp] Backups remaining: $([math]::Min($backups.Count, $keepCount))" -Encoding UTF8
} catch {
    Add-Content -Path $logFile -Value "[$timestamp] Rotation warning: $_" -Encoding UTF8
}

# ── Cleanup temp zip ──
if (Test-Path $zipPath) { Remove-Item $zipPath -Force -Confirm:$false }

$msg = "Backup done: $zipName (${sizeMB} MB)"
Add-Content -Path $logFile -Value "[$timestamp] === Backup SUCCESS ===" -Encoding UTF8
Show-ChipRadarToast -Title "[OK] Chip Radar Backup" -Message $msg -Level "Info"
exit 0
