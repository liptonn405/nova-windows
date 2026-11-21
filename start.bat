@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run install.ps1 first. See README.md.
  pause
  exit /b 1
)
start "NOVA" ".venv\Scripts\pythonw.exe" -m nova.app
