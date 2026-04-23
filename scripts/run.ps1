$REPO_ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $REPO_ROOT

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Iniciando OpenACM..." -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Verify virtual environment
if (!(Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[ERROR] No se encontro la instalacion." -ForegroundColor Red
    Write-Host ""
    Write-Host "Por favor, ejecuta: openacm install" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# Verify OpenACM package is importable
$testImport = & ".venv\Scripts\python.exe" -c "import openacm; print('OK')" 2>&1
if ($testImport -notmatch "OK") {
    Write-Host "[!] OpenACM package not found. Attempting quick reinstall..." -ForegroundColor Yellow
    if (Get-Command "uv" -ErrorAction SilentlyContinue) {
        uv pip install -e . -q 2>&1 | Out-Null
    } elseif (Test-Path ".venv\Scripts\pip.exe") {
        & ".venv\Scripts\pip.exe" install -e . -q 2>&1 | Out-Null
    }
    $testImport = & ".venv\Scripts\python.exe" -c "import openacm; print('OK')" 2>&1
    if ($testImport -notmatch "OK") {
        Write-Host "[ERROR] Reinstall failed. Run 'openacm install' to repair." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Reinstalled successfully." -ForegroundColor Green
}
Write-Host "[OK] Environment verified." -ForegroundColor Green
Write-Host ""

# Build frontend (optional — skipped if Node.js is not available)
if ((Get-Command "node" -ErrorAction SilentlyContinue) -and (Test-Path "frontend")) {
    Write-Host "[*] Building frontend..." -ForegroundColor Yellow
    Set-Location frontend
    npm install --silent 2>&1 | Out-Null
    npm run build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Frontend build failed. Check errors above." -ForegroundColor Red
        exit 1
    }
    Set-Location $REPO_ROOT

    if (!(Test-Path "src\openacm\web\static")) {
        New-Item -ItemType Directory -Force -Path "src\openacm\web\static" | Out-Null
    }
    Remove-Item -Recurse -Force "src\openacm\web\static\*" -ErrorAction SilentlyContinue
    Copy-Item -Recurse -Force "frontend\dist\*" "src\openacm\web\static\"
    Write-Host "[OK] Frontend built and deployed." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "[!] Node.js not found, skipping frontend build." -ForegroundColor Yellow
    Write-Host ""
}

# Start OpenACM
Write-Host "[OK] Starting OpenACM..." -ForegroundColor Green
Write-Host ""
& ".venv\Scripts\python.exe" -m openacm

$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] OpenACM exited with code $exitCode." -ForegroundColor Red
    Write-Host ""
    Write-Host "If you see 'module not found' errors, run: openacm repair" -ForegroundColor Yellow
    Write-Host "If the error persists, check your API keys in config\.env" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to close"
}
