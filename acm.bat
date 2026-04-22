@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\acm.ps1" -Command "%~1"
