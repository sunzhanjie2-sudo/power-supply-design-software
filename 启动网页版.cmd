@echo off
cd /d "%~dp0"
if exist ".venv-web\Scripts\python.exe" (
  ".venv-web\Scripts\python.exe" run_web.py --open
) else (
  python run_web.py --open
)
if errorlevel 1 pause
