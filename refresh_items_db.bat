@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  Refresh item database from arctracker.io (read-only, no game writes)
echo  Output: data\items_db.json + assets\items\arctracker\*.png
echo ============================================================
python inspection\build_items_db.py
if errorlevel 1 (
  echo [!] Failed - the old items_db.json is still in use.
  goto :eof
)
echo [OK] Done. The running site picks up the new file automatically.
endlocal
