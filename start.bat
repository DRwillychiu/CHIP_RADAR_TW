@echo off
chcp 65001 >nul 2>&1
title Chip Radar TW - Local Setup

echo =============================================
echo   Chip Radar TW - Local Mode
echo =============================================
echo.

:: ── Check Python ──
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install: winget install Python.Python.3.11
    pause
    exit /b 1
)

:: ── Check password ──
if "%CHIP_RADAR_PASSWORD%"=="" (
    echo [ERROR] CHIP_RADAR_PASSWORD not set.
    echo.
    echo   Please set it as a system environment variable:
    echo     1. Win+R ^> sysdm.cpl ^> Advanced ^> Environment Variables
    echo     2. User variables ^> New
    echo     3. Name: CHIP_RADAR_PASSWORD   Value: your password
    echo.
    echo   Or run in PowerShell:
    echo     [System.Environment]::SetEnvironmentVariable('CHIP_RADAR_PASSWORD','your_password','User')
    echo.
    pause
    exit /b 1
)

echo [OK] Python found
echo [OK] Password set
echo.

:: ── Start local HTTP server ──
set "PROJECT_ROOT=%~dp0"
set "PID_FILE=%PROJECT_ROOT%scripts\.server.pid"

:: Kill existing server if running
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    taskkill /PID %OLD_PID% /F >nul 2>&1
    del "%PID_FILE%" >nul 2>&1
)

echo Starting local server on http://localhost:8080 ...
start "" /B pythonw "%PROJECT_ROOT%scripts\local_server.py"
timeout /t 2 /nobreak >nul

if exist "%PID_FILE%" (
    echo [OK] Server started
) else (
    echo [WARN] Server may not have started. Check scripts\local_server.py
)

:: ── Register Task Scheduler ──
echo.
echo Registering scheduler (every minute, Mon-Sun) ...

:: Check if task already exists
schtasks /Query /TN "ChipRadar_Scheduler" >nul 2>&1
if errorlevel 1 (
    schtasks /Create /TN "ChipRadar_Scheduler" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%PROJECT_ROOT%scripts\scheduler.ps1\"" /SC MINUTE /MO 1 /F >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Failed to register scheduler. Try running as administrator.
    ) else (
        echo [OK] Scheduler registered
    )
) else (
    echo [OK] Scheduler already registered
)

:: ── Register backup task ──
schtasks /Query /TN "ChipRadar_Backup" >nul 2>&1
if errorlevel 1 (
    schtasks /Create /TN "ChipRadar_Backup" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%PROJECT_ROOT%scripts\backup_gdrive.ps1\"" /SC WEEKLY /D SUN /ST 18:00 /F >nul 2>&1
    if not errorlevel 1 (
        echo [OK] Weekly backup registered (Sun 18:00)
    )
) else (
    echo [OK] Backup already registered
)

:: ── Open browser ──
echo.
echo Opening dashboard ...
start http://localhost:8080
echo.
echo =============================================
echo   All running! You can close this window.
echo.
echo   Dashboard: http://localhost:8080
echo   Data dir:  %PROJECT_ROOT%local_data\
echo   Log:       Desktop\chip_radar_scheduler.log
echo.
echo   To stop:   double-click stop.bat
echo =============================================
echo.
pause
