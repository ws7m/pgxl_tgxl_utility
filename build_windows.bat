@echo off
rem Build dist\GeniusControl.exe. Double-click this file, or run it from a Command Prompt.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
