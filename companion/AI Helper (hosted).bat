@echo off
REM Hosted Foundry (Forge and similar). Helper stays on this PC.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0AI Helper.ps1" -Hosted %*
if errorlevel 1 pause
