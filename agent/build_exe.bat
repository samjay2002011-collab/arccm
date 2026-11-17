@echo off
setlocal
cd /d "%~dp0.."
echo Building CMSync.exe (one file, no console, run-as-admin)...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name CMSync ^
  --uac-admin --icon "%~dp0cmsync.ico" --add-data "%~dp0cmsync.ico;." --paths agent --hidden-import pystray._win32 ^
  --distpath agent\dist --workpath agent\build --specpath agent agent\fahmy_agent.py
if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)
copy /Y agent\dist\CMSync.exe CMSync.exe >nul
echo OK: %cd%\CMSync.exe
echo Run it once with: CMSync.exe --install
endlocal
