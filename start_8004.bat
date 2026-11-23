@echo off
rem ============================================================
rem  TT (Port 8004) — isolated experiment launcher
rem  Double-click to start (keep this window open).
rem  To stop:  start_8004.bat stop
rem ============================================================
setlocal
cd /d "%~dp0"
set PY=C:\Users\Administrator\AppData\Local\Python\pythoncore-3.15-64\python.exe
set PORT=8004

if "%1"=="stop" (
  "%PY%" -X utf8 inspection\port_ctl.py kill %PORT%
  pause
  exit /b 0
)

set RAMPART_LOCAL_HOST=0.0.0.0
set RAMPART_LOCAL_PORT=%PORT%
echo Starting isolated site on http://127.0.0.1:%PORT%
"%PY%" -X utf8 -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT% --log-level warning
