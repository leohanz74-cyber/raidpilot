@echo off
rem Baut eine eigenstaendige EXE nach dist\RaidPilot\RaidPilot.exe (vorher einmal START.bat ausfuehren)
cd /d "%~dp0"
set "VPY=%~dp0.venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo Bitte zuerst START.bat ausfuehren.
  pause
  exit /b 1
)
"%VPY%" -m pip install --disable-pip-version-check pyinstaller
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --name RaidPilot --icon raidpilot\ui\icon.ico --add-data "raidpilot\ui;raidpilot\ui" --collect-all rapidocr --collect-all webview main.py
if errorlevel 1 (echo FEHLER beim Bauen - Meldung oben lesen) else (echo FERTIG: %~dp0dist\RaidPilot\RaidPilot.exe)
pause
