@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting AutoCut...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
pause