@echo off
TITLE OpenACM - Build Frontend

:: ==========================================
::   Build React Frontend and copy to static
:: ==========================================

echo ==========================================
echo   Building OpenACM Frontend...
echo ==========================================
echo.

:: Check if Node.js is installed
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js is not installed.
    echo.
    echo Please install Node.js from https://nodejs.org/
    echo.
    pause
    exit /b 1
)

:: Check if frontend folder exists
if not exist "frontend\" (
    echo [ERROR] Frontend folder not found.
    echo.
    pause
    exit /b 1
)

echo [*] Node.js version:
node --version
echo.

:: Install dependencies
echo [*] Installing frontend dependencies...
cd frontend
call npm install
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    cd ..
    pause
    exit /b 1
)
echo [OK] Dependencies installed.
echo.

:: Build the frontend
echo [*] Building React app...
call npm run build
if errorlevel 1 (
    echo [ERROR] Build failed.
    cd ..
    pause
    exit /b 1
)
echo [OK] Build completed.
echo.

cd ..

:: Copy dist to static
echo [*] Copying build to static folder...
if exist "src\openacm\web\static\" (
    rmdir /s /q "src\openacm\web\static\*" 2>nul
)
if not exist "src\openacm\web\static\" mkdir "src\openacm\web\static"

xcopy /s /e /y /q "frontend\dist\*" "src\openacm\web\static\" >nul
echo [OK] Files copied.
echo.

echo ==========================================
echo   Frontend Build Complete!
echo ==========================================
echo.
