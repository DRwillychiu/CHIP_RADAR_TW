@echo off
chcp 65001 >nul 2>&1
title Chip Radar TW - Stop

echo =============================================
echo   Chip Radar TW - Stopping...
echo =============================================
echo.

:: ── Stop HTTP server ──
set "PROJECT_ROOT=%~dp0"
set "PID_FILE=%PROJECT_ROOT%scripts\.server.pid"

if exist "%PID_FILE%" (
    set /p SERVER_PID=<"%PID_FILE%"
    taskkill /PID %SERVER_PID% /F >nul 2>&1
    del "%PID_FILE%" >nul 2>&1
    echo [OK] Server stopped
) else (
    echo [--] Server was not running
)

:: ── Remove scheduler ──
schtasks /Query /TN "ChipRadar_Scheduler" >nul 2>&1
if not errorlevel 1 (
    schtasks /Delete /TN "ChipRadar_Scheduler" /F >nul 2>&1
    echo [OK] Scheduler removed
) else (
    echo [--] Scheduler was not registered
)

:: ── Remove backup task ──
schtasks /Query /TN "ChipRadar_Backup" >nul 2>&1
if not errorlevel 1 (
    schtasks /Delete /TN "ChipRadar_Backup" /F >nul 2>&1
    echo [OK] Backup task removed
) else (
    echo [--] Backup was not registered
)

echo.
echo =============================================
echo   All stopped. To restart: double-click start.bat
echo =============================================
echo.
pause
