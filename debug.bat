@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.ps1 first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m nova.app
pause
