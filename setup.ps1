Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  🚀 Instalando OpenACM Autónomo Tier-1" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if uv is installed, if not, download it
if (!(Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Write-Host "[*] Instalando 'uv' (gestor súper rápido de Python)..." -ForegroundColor Yellow
    Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1" | Invoke-Expression
    $env:Path += ";$HOME\.cargo\bin"
} else {
    Write-Host "[OK] 'uv' ya está instalado." -ForegroundColor Green
}

# Ask uv to make sure python is 3.12+
Write-Host "[*] Preparando el entorno de Python..." -ForegroundColor Yellow
uv python install 3.12 --quiet
uv venv

Write-Host "[*] Revisando configuraciones (.env)..." -ForegroundColor Yellow
if (!(Test-Path "config\.env")) {
    Copy-Item "config\.env.example" "config\.env"
    Write-Host "[OK] Archivo 'config\.env' creado automáticamente." -ForegroundColor Green
}

Write-Host "[*] Instalando todas las dependencias del proyecto (puede tardar un minuto)..." -ForegroundColor Yellow
uv pip install -e .

Write-Host "[*] Descargando navegadores para el Agente Web (Playwright)..." -ForegroundColor Yellow
uv run playwright install chromium

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  ✅ ¡Instalación Completada con Éxito!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Para arrancar OpenACM de ahora en adelante, simplemente" -ForegroundColor White
Write-Host "haz doble clic en 'run.bat' en esta carpeta." -ForegroundColor Cyan
Write-Host ""
