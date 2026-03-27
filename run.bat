@echo off
TITLE OpenACM - Autonomous Agent

:: ==========================================
::   Force use of Python from .venv
:: ==========================================

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "VENV_PIP=%~dp0.venv\Scripts\pip.exe"
set "VENV_UV=%~dp0.venv\Scripts\uv.exe"

echo ==========================================
echo   Starting OpenACM...
echo ==========================================
echo.

:: Verify virtual environment exists
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Installation not found.
    echo.
    echo Please double-click 'setup.bat' first.
    echo.
    pause
    exit /b 1
)

:: Build frontend (ensures latest code is always served)
echo [*] Building frontend...
call "%~dp0build-frontend.bat"
if errorlevel 1 (
    echo [ERROR] Frontend build failed.
    pause
    exit /b 1
)

:: Deactivate any previously active virtual environment
if defined VIRTUAL_ENV (
    call "%~dp0.venv\Scripts\deactivate.bat" 2>nul
)

:: Force PATH to use only the virtual environment
set "PATH=%~dp0.venv\Scripts;%PATH%"

:: Verify Python version in the environment
echo [*] Verifying virtual environment...
for /f "tokens=*" %%a in ('"%VENV_PYTHON%" --version 2^>^&1') do set PYTHON_VERSION=%%a
echo [OK] Using: %PYTHON_VERSION% from .venv

:: Verify that openacm is installed
echo [*] Verifying OpenACM installation...
"%VENV_PYTHON%" -c "import openacm" 2>nul
if errorlevel 1 (
    echo [ERROR] OpenACM is not installed correctly.
    echo.
    echo Try running setup.bat again.
    echo.
    pause
    exit /b 1
)

echo [OK] All good. Starting...
echo.

:: Start OpenACM with the virtual environment Python
cd /d "%~dp0"
"%VENV_PYTHON%" -m openacm

if errorlevel 1 (
    echo.
    echo [ERROR] OpenACM exited with an error.
    echo.
    echo If you see 'module not found' errors, run setup.bat
    echo If the error persists, check that config\.env has your API keys
    echo.
    pause
)
