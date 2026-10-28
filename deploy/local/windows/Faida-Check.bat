@echo off
rem Faida-Check: double-click on the counter PC. It asks for administrator, checks why
rem Faida isn't working, tries to start it, and saves a report next to this file.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Faida-Check.ps1"
