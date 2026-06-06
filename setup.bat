@echo off
TITLE OpenACM - Setup

:: ── Auto-elevate to Administrator ────────────────────────────────────────────
:: Some Windows 10 / corporate setups block uv install or Playwright without admin.
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [*] OpenACM setup needs administrator privileges.
    echo     A UAC prompt will appear — accept it.
    echo.
    powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/c pushd \"%~dp0\" ^&^& \"%~f0\"' -Verb RunAs"
    if errorlevel 1 (
        echo.
        echo [ERROR] Could not request administrator privileges, or UAC was denied.
        echo         Right-click setup.bat and choose "Run as administrator".
        echo.
        pause
    )
    exit /b 0
)

TITLE OpenACM - Setup [Admin]
cd /d "%~dp0"

:: ── Run PowerShell setup ──────────────────────────────────────────────────────
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\setup.ps1"

:: Save ERRORLEVEL immediately — any other command (echo, if, etc.) would reset it
set "SETUP_RESULT=%ERRORLEVEL%"

if "%SETUP_RESULT%"=="0" (
    call "%~dp0run.bat"
) else (
    echo.
    echo [ERROR] Setup did not finish successfully ^(exit code %SETUP_RESULT%^).
    echo         Scroll up to see the failing step.
    echo.
    pause
)
