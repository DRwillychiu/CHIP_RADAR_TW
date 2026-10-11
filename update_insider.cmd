@echo off
rem v3.96.0 insider radar: manual monthly update (owner 2026-10-11). Same rules and checks as the automatic run.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python scripts\update_insider_monthly.py %*
pause
