@echo off
rem ============================================================
rem  CM UU (Port 8002) — local site launcher
rem  Double-click to start (keep this window open).
rem  To stop:  start_8002.bat stop
rem ============================================================
setlocal
cd /d "%~dp0"
set PY=C:\Users\Administrator\AppData\Local\Python\pythoncore-3.15-64\python.exe
set PORT=8002

if "%1"=="stop" (
  "%PY%" -X utf8 inspection\port_ctl.py kill %PORT%
  pause
  exit /b 0
)

"%PY%" -X utf8 inspection\port_ctl.py check %PORT%
if not errorlevel 1 (
  echo.
  echo Site is already running on port %PORT%. To restart: start_8002.bat stop
  pause
  exit /b 0
)

set RAMPART_LOCAL_HOST=0.0.0.0
set RAMPART_LOCAL_PORT=%PORT%
echo Starting site on http://127.0.0.1:%PORT%  ^(LAN: any device on this network^)
echo Close this window or run start_8002.bat stop to shut it down.
echo.
"%PY%" -X utf8 -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT% --log-level warning
pause
