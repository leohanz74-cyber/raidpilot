@echo off
rem Builds a standalone EXE at dist\RaidPilot\RaidPilot.exe (run START.bat once before)
cd /d "%~dp0"
set "VPY=%~dp0.venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo Please run START.bat first.
  pause
  exit /b 1
)
"%VPY%" -m pip install --disable-pip-version-check pyinstaller
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --name RaidPilot --icon raidpilot\ui\icon.ico --add-data "raidpilot\ui;raidpilot\ui" --add-data "raidpilot\storages.onnx;raidpilot" --collect-all rapidocr --collect-all webview main.py
if errorlevel 1 (echo BUILD FAILED - read the message above) else (echo DONE: %~dp0dist\RaidPilot\RaidPilot.exe)
pause
