@echo off
rem ============================================================
rem  CM UU (Port 8001) — Cloudflare Public Tunnel
rem  Double-click to start or get your https://xxxx.trycloudflare.com link.
rem  Admin panel: /admin (Password: Lord@1234)
rem  To stop:  share_site.bat stop
rem ============================================================
setlocal
cd /d "%~dp0"
set PY=C:\Users\Administrator\AppData\Local\Python\pythoncore-3.15-64\python.exe
if "%1"=="" (
  "%PY%" -X utf8 inspection\public_hosting.py start
) else (
  "%PY%" -X utf8 inspection\public_hosting.py %1
)
echo.
pause
