@echo off
TITLE OpenACM - Agente Autonomo
echo ==========================================
echo   Iniciando OpenACM...
echo ==========================================

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No hemos encontrado la instalacion. Por favor, haz doble clic en 'setup.bat' primero.
    pause
    exit /b
)

call .venv\Scripts\activate.bat
python -m openacm

pause
