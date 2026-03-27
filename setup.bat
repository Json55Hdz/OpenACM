@echo off
TITLE OpenACM - Setup
powershell -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

:: If setup.ps1 exited with 0, the user wants to launch OpenACM
if %ERRORLEVEL% EQU 0 (
    call "%~dp0run.bat"
)
