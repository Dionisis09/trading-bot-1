@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\vps\open_dashboard.ps1"
if errorlevel 1 pause
