# ── Self-elevate if not admin ──
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

try {

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

Write-Host "============================================="
Write-Host "  Chip Radar TW - Local Mode"
Write-Host "============================================="
Write-Host ""

# ── Check Python ──
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python not found. Install: winget install Python.Python.3.11" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK] Python found" -ForegroundColor Green

# ── Check password ──
if (-not $env:CHIP_RADAR_PASSWORD) {
    Write-Host "[ERROR] CHIP_RADAR_PASSWORD not set." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Set it once in PowerShell:"
    Write-Host "    [System.Environment]::SetEnvironmentVariable('CHIP_RADAR_PASSWORD','your_password','User')"
    Write-Host ""
    Write-Host "  Or: Win+R > sysdm.cpl > Advanced > Environment Variables > User > New"
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK] Password set" -ForegroundColor Green
Write-Host ""

# ── Setup venv ──
$venvDir = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment ..."
    & python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    & $venvPython -m pip install --upgrade pip 2>$null
    Write-Host "Installing dependencies ..."
    & (Join-Path $venvDir "Scripts\pip.exe") install -r (Join-Path $projectRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install dependencies." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK] Virtual environment created + dependencies installed" -ForegroundColor Green
} else {
    Write-Host "[OK] Virtual environment found" -ForegroundColor Green
}
Write-Host ""

# ── Start local HTTP server ──
$pidFile = Join-Path $projectRoot "scripts\.server.pid"

if (Test-Path $pidFile) {
    $oldPid = (Get-Content $pidFile -Raw).Trim()
    try { Stop-Process -Id $oldPid -Force -ErrorAction Stop } catch {}
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

Write-Host "Starting local server on http://localhost:8080 ..."
$serverScript = Join-Path $projectRoot "scripts\local_server.py"
$pythonw = Join-Path $venvDir "Scripts\pythonw.exe"
if (Test-Path $pythonw) {
    Start-Process -FilePath $pythonw -ArgumentList $serverScript -WindowStyle Hidden
} else {
    Start-Process -FilePath $venvPython -ArgumentList $serverScript -WindowStyle Hidden
}
Start-Sleep -Seconds 2

if (Test-Path $pidFile) {
    Write-Host "[OK] Server started" -ForegroundColor Green
} else {
    Write-Host "[WARN] Server may not have started. Check scripts\local_server.py" -ForegroundColor Yellow
}

# ── Register Task Scheduler ──
Write-Host ""
Write-Host "Registering scheduler (every minute) ..."

$schedulerPath = Join-Path $projectRoot "scripts\scheduler.ps1"
$taskExists = schtasks /Query /TN "ChipRadar_Scheduler" 2>$null
if (-not $taskExists) {
    schtasks /Create /TN "ChipRadar_Scheduler" `
        /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$schedulerPath`"" `
        /SC MINUTE /MO 1 /F 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Scheduler registered" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Failed to register scheduler. Try running as administrator." -ForegroundColor Yellow
    }
} else {
    Write-Host "[OK] Scheduler already registered" -ForegroundColor Green
}

# ── Register backup task ──
$backupPath = Join-Path $projectRoot "scripts\backup_gdrive.ps1"
$backupExists = schtasks /Query /TN "ChipRadar_Backup" 2>$null
if (-not $backupExists) {
    schtasks /Create /TN "ChipRadar_Backup" `
        /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$backupPath`"" `
        /SC WEEKLY /D SUN /ST 18:00 /F 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Weekly backup registered (Sun 18:00)" -ForegroundColor Green
    }
} else {
    Write-Host "[OK] Backup already registered" -ForegroundColor Green
}

# ── Register startup task (server auto-start on logon) ──
$startupScript = Join-Path $projectRoot "scripts\server_start.ps1"
$startupExists = schtasks /Query /TN "ChipRadar_Startup" 2>$null
if (-not $startupExists) {
    schtasks /Create /TN "ChipRadar_Startup" `
        /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$startupScript`"" `
        /SC ONLOGON /F 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Startup registered (auto-start on logon)" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Failed to register startup task." -ForegroundColor Yellow
    }
} else {
    Write-Host "[OK] Startup already registered" -ForegroundColor Green
}

# ── Open browser ──
Write-Host ""
Write-Host "Opening dashboard ..."
Start-Process "http://localhost:8080"
Write-Host ""
Write-Host "============================================="
Write-Host "  All running! You can close this window."
Write-Host ""
Write-Host "  Dashboard: http://localhost:8080"
Write-Host "  Data dir:  $projectRoot\local_data\"
Write-Host "  Log:       Desktop\chip_radar_scheduler.log"
Write-Host ""
Write-Host "  To stop:   double-click stop.bat"
Write-Host "============================================="

} catch {
    Write-Host ""
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Location: $($_.InvocationInfo.PositionMessage)" -ForegroundColor Red
}

Write-Host ""
Read-Host "Press Enter to close"
