@echo off
rem Restore-Backup: double-click on the counter PC. It asks for administrator and puts a
rem Faida backup (.fbk) back on this counter, after a backup of what is here now.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Restore-Backup.ps1"
