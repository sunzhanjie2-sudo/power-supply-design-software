@echo off
setlocal
cd /d "%~dp0"
"%~dp0PowerDesignWeb.exe" --open
if errorlevel 1 pause
