$ErrorActionPreference = "Continue"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "============================================="
Write-Host "  Chip Radar TW - Stopping..."
Write-Host "============================================="
Write-Host ""

# ── Stop HTTP server ──
$pidFile = Join-Path $projectRoot "scripts\.server.pid"

if (Test-Path $pidFile) {
    $serverPid = (Get-Content $pidFile -Raw).Trim()
    try { Stop-Process -Id $serverPid -Force -ErrorAction Stop } catch {}
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Server stopped" -ForegroundColor Green
} else {
    Write-Host "[--] Server was not running"
}

# ── Remove scheduler ──
$taskExists = schtasks /Query /TN "ChipRadar_Scheduler" 2>$null
if ($taskExists) {
    schtasks /Delete /TN "ChipRadar_Scheduler" /F 2>$null
    Write-Host "[OK] Scheduler removed" -ForegroundColor Green
} else {
    Write-Host "[--] Scheduler was not registered"
}

# ── Remove backup task ──
$backupExists = schtasks /Query /TN "ChipRadar_Backup" 2>$null
if ($backupExists) {
    schtasks /Delete /TN "ChipRadar_Backup" /F 2>$null
    Write-Host "[OK] Backup task removed" -ForegroundColor Green
} else {
    Write-Host "[--] Backup was not registered"
}

Write-Host ""
Write-Host "============================================="
Write-Host "  All stopped. To restart: double-click start.bat"
Write-Host "============================================="
Write-Host ""
Read-Host "Press Enter to close"
