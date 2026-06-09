@echo off
TITLE OpenACM - Update

cd /d "%~dp0"
echo ==========================================
echo   OpenACM - Actualizando...
echo ==========================================
echo.

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\update.ps1"
set "UPDATE_RESULT=%ERRORLEVEL%"

if "%UPDATE_RESULT%"=="0" (
    call "%~dp0run.bat"
) else (
    echo.
    echo [ERROR] El update fallo ^(codigo %UPDATE_RESULT%^).
    echo Revisa los mensajes de arriba para ver que salio mal.
    echo.
    pause
)
