# Bootstrap installer for Windows — run without cloning first:
#   iwr -useb https://raw.githubusercontent.com/Json55Hdz/OpenACM/main/install.ps1 | iex

$ErrorActionPreference = "Stop"

$REPO_URL   = "https://github.com/Json55Hdz/OpenACM.git"
$INSTALL_DIR = if ($env:OPENACM_DIR) { $env:OPENACM_DIR } else { "$env:USERPROFILE\OpenACM" }

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  OpenACM - Bootstrap Installer" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# ── Requirements ─────────────────────────────────────────────────────────────
if (!(Get-Command "git" -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] git is required. Install it from https://git-scm.com" -ForegroundColor Red
    Write-Host "        Then re-run this script." -ForegroundColor Yellow
    pause
    exit 1
}

# ── Clone or pull ─────────────────────────────────────────────────────────────
if (Test-Path "$INSTALL_DIR\.git") {
    Write-Host "[*] OpenACM already exists at $INSTALL_DIR — pulling latest..." -ForegroundColor Yellow
    Set-Location $INSTALL_DIR
    git pull
} else {
    Write-Host "[*] Cloning OpenACM to $INSTALL_DIR..." -ForegroundColor Yellow
    git clone $REPO_URL $INSTALL_DIR
    Set-Location $INSTALL_DIR
}

Write-Host "[OK] Repository ready." -ForegroundColor Green
Write-Host ""

# ── Run setup ─────────────────────────────────────────────────────────────────
Write-Host "[*] Launching setup..." -ForegroundColor Yellow
& cmd /c "`"$INSTALL_DIR\setup.bat`""
