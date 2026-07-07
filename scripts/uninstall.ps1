$ErrorActionPreference = "Continue"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "============================================="
Write-Host "  Chip Radar TW - Uninstall (full cleanup)"
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

# ── Remove all scheduled tasks ──
$tasks = @("ChipRadar_Scheduler", "ChipRadar_Backup", "ChipRadar_Startup")
foreach ($task in $tasks) {
    $exists = schtasks /Query /TN $task 2>$null
    if ($exists) {
        schtasks /Delete /TN $task /F 2>$null
        Write-Host "[OK] Removed task: $task" -ForegroundColor Green
    } else {
        Write-Host "[--] $task was not registered"
    }
}

Write-Host ""
Write-Host "============================================="
Write-Host "  All removed. To reinstall: start.bat (as admin)"
Write-Host "============================================="
Write-Host ""
Read-Host "Press Enter to close"
