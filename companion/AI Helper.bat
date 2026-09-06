@echo off
REM Win11 companion. Leave this window open while you play.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0AI Helper.ps1" %*
if errorlevel 1 pause
