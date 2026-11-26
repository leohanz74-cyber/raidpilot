@echo off
setlocal
cd /d "%~dp0"
title RaidPilot
set "VPY=%~dp0.venv\Scripts\python.exe"

if exist "%VPY%" goto deps
echo First start: setting up RaidPilot. This takes a few minutes.
py -3.12 -m venv .venv >nul 2>&1
if not exist "%VPY%" py -3.13 -m venv .venv >nul 2>&1
if not exist "%VPY%" python -m venv .venv
if not exist "%VPY%" goto nopython

:deps
fc /b requirements.txt ".venv\installed.txt" >nul 2>&1
if not errorlevel 1 goto run
echo Downloading required packages (about 120 MB)...
"%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
copy /y requirements.txt ".venv\installed.txt" >nul

:run
start "" "%~dp0.venv\Scripts\pythonw.exe" -m raidpilot
rem "exit" without /b also closes the window that the update restart opens
exit

:nopython
echo.
echo ERROR: Python 3.12 was not found. Install it from python.org.
pause
exit /b 1

:failed
echo.
echo ERROR during installation. Check your internet connection and the message above.
pause
exit /b 1
