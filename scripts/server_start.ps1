# Headless server startup — called by ChipRadar_Startup task on logon
$ErrorActionPreference = "Continue"
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

# ── Start server if not already running ──
$pidFile = Join-Path $projectRoot "scripts\.server.pid"
if (Test-Path $pidFile) {
    $oldPid = (Get-Content $pidFile -Raw).Trim()
    $running = $false
    try { Get-Process -Id $oldPid -ErrorAction Stop | Out-Null; $running = $true } catch {}
    if ($running) { exit 0 }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$venvDir = Join-Path $projectRoot ".venv"
$pythonw = Join-Path $venvDir "Scripts\pythonw.exe"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$serverScript = Join-Path $projectRoot "scripts\local_server.py"

if (Test-Path $pythonw) {
    Start-Process -FilePath $pythonw -ArgumentList $serverScript -WindowStyle Hidden
} elseif (Test-Path $venvPython) {
    Start-Process -FilePath $venvPython -ArgumentList $serverScript -WindowStyle Hidden
}
