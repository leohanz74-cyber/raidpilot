@echo off
setlocal
cd /d "%~dp0"
title RaidPilot
set "VPY=%~dp0.venv\Scripts\python.exe"

if exist "%VPY%" goto deps
echo Erster Start: RaidPilot wird eingerichtet. Das dauert ein paar Minuten.
py -3.12 -m venv .venv >nul 2>&1
if not exist "%VPY%" py -3.13 -m venv .venv >nul 2>&1
if not exist "%VPY%" python -m venv .venv
if not exist "%VPY%" goto nopython

:deps
fc /b requirements.txt ".venv\installiert.txt" >nul 2>&1
if not errorlevel 1 goto run
echo Lade benoetigte Pakete (etwa 120 MB)...
"%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
copy /y requirements.txt ".venv\installiert.txt" >nul

:run
start "" "%~dp0.venv\Scripts\pythonw.exe" -m raidpilot
exit /b 0

:nopython
echo.
echo FEHLER: Python 3.12 wurde nicht gefunden. Installiere es von python.org.
pause
exit /b 1

:failed
echo.
echo FEHLER beim Installieren. Pruefe deine Internetverbindung und die Meldung oben.
pause
exit /b 1
