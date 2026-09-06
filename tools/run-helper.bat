@echo off
REM Win11 launcher for the AI helper. Leave this window open while you play.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%~dp0run-helper.py" %*
  goto :after
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%~dp0run-helper.py" %*
  goto :after
)

echo Python 3 not found. Install it and tick Add python.exe to PATH.
pause
exit /b 1

:after
if errorlevel 1 pause
