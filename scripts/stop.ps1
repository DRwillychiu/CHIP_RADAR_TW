# ── Self-elevate if not admin ──
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

$ErrorActionPreference = "Continue"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "============================================="
Write-Host "  Chip Radar TW - Stopping server..."
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

Write-Host ""
Write-Host "  Scheduler and startup tasks are still registered."
Write-Host "  To remove everything: double-click uninstall.bat (as admin)"
Write-Host ""
Write-Host "============================================="
Write-Host "  Server stopped. Scheduler will keep running."
Write-Host "  To restart server: double-click start.bat"
Write-Host "============================================="
Write-Host ""
Read-Host "Press Enter to close"
