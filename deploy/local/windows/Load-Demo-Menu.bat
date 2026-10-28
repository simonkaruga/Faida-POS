@echo off
rem Load-Demo-Menu: double-click on the counter PC. It asks for administrator and loads
rem the sample menu onto a counter whose menu is still empty.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Load-Demo-Menu.ps1"
