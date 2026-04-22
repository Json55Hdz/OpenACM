Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  OpenACM - Update" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $SCRIPT_DIR

# ── 1. Git pull ─────────────────────────────────────────────────────────────
if (!(Get-Command "git" -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] git not found. Install git from https://git-scm.com" -ForegroundColor Red
    pause
    exit 1
}

Write-Host "[*] Fetching latest changes..." -ForegroundColor Yellow
git pull
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] git pull failed. Check your connection and try again." -ForegroundColor Red
    pause
    exit 1
}
Write-Host "[OK] Repository updated." -ForegroundColor Green
Write-Host ""

# ── 2. Sync Python dependencies ──────────────────────────────────────────────
Write-Host "[*] Syncing Python dependencies..." -ForegroundColor Yellow
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    uv pip install -e . --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[!] uv had issues, falling back to pip..." -ForegroundColor Yellow
        if (Test-Path ".venv\Scripts\pip.exe") { .venv\Scripts\pip.exe install -e . -q }
    }
} elseif (Test-Path ".venv\Scripts\pip.exe") {
    .venv\Scripts\pip.exe install -e . -q
} else {
    Write-Host "[ERROR] No virtual environment found. Run setup.bat first." -ForegroundColor Red
    pause
    exit 1
}
Write-Host "[OK] Python dependencies synced." -ForegroundColor Green
Write-Host ""

# ── 3. Rebuild frontend ──────────────────────────────────────────────────────
if (!(Get-Command "node" -ErrorAction SilentlyContinue)) {
    Write-Host "[!] Node.js not found, skipping frontend build." -ForegroundColor Yellow
} elseif (!(Test-Path "frontend")) {
    Write-Host "[!] frontend/ folder not found, skipping build." -ForegroundColor Yellow
} else {
    Write-Host "[*] Rebuilding frontend..." -ForegroundColor Yellow
    Set-Location frontend
    npm install --silent 2>&1 | Out-Null
    npm run build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Frontend build failed." -ForegroundColor Red
        Set-Location $SCRIPT_DIR
        pause
        exit 1
    }
    Set-Location $SCRIPT_DIR

    if (!(Test-Path "src\openacm\web\static")) {
        New-Item -ItemType Directory -Force -Path "src\openacm\web\static" | Out-Null
    }
    Copy-Item -Recurse -Force "frontend\dist\*" "src\openacm\web\static\"
    Write-Host "[OK] Frontend rebuilt." -ForegroundColor Green
}
Write-Host ""

Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Update Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""

$choice = Read-Host "Restart OpenACM now? (Y/n)"
if ($choice -eq "" -or $choice -match "^[yY]") {
    Write-Host ""
    Write-Host "Launching OpenACM..." -ForegroundColor Green
    exit 0   # update.bat will call run.bat
} else {
    Write-Host "Run 'run.bat' or 'acm start' to launch." -ForegroundColor Cyan
    Read-Host "Press Enter to close"
    exit 1
}
