@echo off
TITLE OpenACM - Update

cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0update.ps1"
set "UPDATE_RESULT=%ERRORLEVEL%"

if "%UPDATE_RESULT%"=="0" (
    call "%~dp0run.bat"
)
