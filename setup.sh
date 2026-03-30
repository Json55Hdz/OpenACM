#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "\033[1;36m==========================================\033[0m"
echo -e "\033[1;36m  OpenACM Tier-1 Autonomous Agent Setup\033[0m"
echo -e "\033[1;36m==========================================\033[0m"
echo ""

# Check if uv is installed
if ! command -v uv &>/dev/null; then
    echo -e "\033[1;33m[*] Instalando 'uv' (gestor de dependencias ultrarrápido)...\033[0m"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
else
    echo -e "\033[1;32m[OK] 'uv' ya está instalado.\033[0m"
fi

# Install system dependencies (Linux only)
if command -v apt-get &>/dev/null; then
    echo -e "\033[1;33m[*] Instalando utilidades base del sistema...\033[0m"
    sudo apt-get update -qq
    sudo apt-get install -y build-essential python3-dev libssl-dev libffi-dev xdotool python3.12-venv
fi

# ── Node.js 20+ ────────────────────────────────────────────────────────────
echo -e "\033[1;33m[*] Verificando Node.js...\033[0m"
NODE_OK=false
if command -v node &>/dev/null; then
    NODE_VER=$(node -e "process.stdout.write(String(process.versions.node.split('.')[0]))" 2>/dev/null)
    if [ "${NODE_VER:-0}" -ge 20 ] 2>/dev/null; then
        echo -e "\033[1;32m[OK] Node.js $(node --version) encontrado.\033[0m"
        NODE_OK=true
    else
        echo -e "\033[1;33m[!] Node.js $(node --version) es muy antiguo. Se necesita v20+.\033[0m"
    fi
fi

if [ "$NODE_OK" = false ]; then
    # Try nvm
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    if [ -s "$NVM_DIR/nvm.sh" ]; then
        source "$NVM_DIR/nvm.sh"
        echo -e "\033[1;33m[*] Instalando Node.js 20 via nvm...\033[0m"
        nvm install 20 && nvm use 20 && nvm alias default 20
        NODE_OK=true
    # Try Homebrew (macOS)
    elif command -v brew &>/dev/null; then
        echo -e "\033[1;33m[*] Instalando Node.js 20 via Homebrew...\033[0m"
        brew install node@20
        brew link --overwrite --force node@20
        export PATH="/opt/homebrew/opt/node@20/bin:/usr/local/opt/node@20/bin:$PATH"
        NODE_OK=true
    # Try apt (Linux)
    elif command -v apt-get &>/dev/null; then
        echo -e "\033[1;33m[*] Instalando Node.js 20 via apt...\033[0m"
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y nodejs
        NODE_OK=true
    else
        echo -e "\033[1;31m[!] No se pudo instalar Node.js automáticamente.\033[0m"
        echo -e "\033[1;37m    Instala Node.js 20+ manualmente desde: https://nodejs.org\033[0m"
        echo -e "\033[1;37m    O usa nvm: https://github.com/nvm-sh/nvm\033[0m"
    fi
fi

# Install Python 3.12 via uv
echo -e "\033[1;33m[*] Configurando Python 3.12...\033[0m"
uv python install 3.12 2>/dev/null || echo -e "\033[1;33m[!] No se pudo instalar Python 3.12 via uv, intentando continuar...\033[0m"

# Create virtual environment with seed packages (ensures pip is available)
echo -e "\033[1;33m[*] Creando entorno virtual...\033[0m"

# Remove old venv if it has no pip
if [ -f ".venv/bin/python" ] && [ ! -f ".venv/bin/pip" ]; then
    echo -e "\033[1;33m[!] venv sin pip detectado. Recreando...\033[0m"
    rm -rf .venv
fi

uv venv --seed
echo -e "\033[1;32m[OK] Entorno virtual creado con pip.\033[0m"

# Setup .env config
echo -e "\033[1;33m[*] Revisando configuración (.env)...\033[0m"
if [ ! -f "config/.env" ]; then
    if [ -f "config/.env.example" ]; then
        cp config/.env.example config/.env
        echo -e "\033[1;32m[OK] 'config/.env' creado desde el ejemplo.\033[0m"
    else
        mkdir -p config
        echo "# OpenACM Configuration" > config/.env
        echo -e "\033[1;32m[OK] 'config/.env' creado (vacío).\033[0m"
    fi
else
    echo -e "\033[1;32m[OK] 'config/.env' ya existe.\033[0m"
fi

# Install Python dependencies
echo -e "\033[1;33m[*] Instalando dependencias del proyecto (puede tardar unos minutos)...\033[0m"
uv pip install -e .
echo -e "\033[1;32m[OK] Dependencias instaladas.\033[0m"

# Install Playwright browsers
echo -e "\033[1;33m[*] Descargando navegadores para el Agente Web (Playwright)...\033[0m"
uv run playwright install --with-deps chromium || echo -e "\033[1;33m[!] No se pudo instalar Playwright automáticamente. Puedes instalarlo después: uv run playwright install chromium\033[0m"

# Final verification
echo ""
echo -e "\033[1;33m[*] Verificando instalación...\033[0m"
if uv run python -c "import openacm; print('OK')" 2>/dev/null | grep -q "OK"; then
    echo -e "\033[1;32m[OK] OpenACM importa correctamente.\033[0m"
else
    echo -e "\033[1;33m[!] Advertencia: Hubo problemas al verificar la instalación.\033[0m"
fi

echo ""
echo -e "\033[1;32m==========================================\033[0m"
echo -e "\033[1;32m  ✅ ¡Instalación Completada con Éxito!\033[0m"
echo -e "\033[1;32m==========================================\033[0m"
echo ""
echo -e "\033[1;37m  Antes de iniciar, asegúrate de configurar\033[0m"
echo -e "\033[1;37m  tus API keys en: \033[1;36mconfig/.env\033[0m"
echo ""
echo -e "\033[1;37m  Docs:\033[0m"
echo -e "\033[0;37m  - README.md - Guía de inicio rápido\033[0m"
echo -e "\033[0;37m  - SKILLS_TOOLS_GUIDE.md - Cómo crear skills y tools\033[0m"
echo ""
echo -e "\033[1;36m==========================================\033[0m"
echo ""

read -p "¿Lanzar OpenACM ahora? (S/n): " choice
if [[ "$choice" == "" || "$choice" =~ ^[sSyY] ]]; then
    echo ""
    echo -e "\033[1;32mIniciando OpenACM...\033[0m"
    echo ""
    exec ./run.sh
else
    echo ""
    echo -e "\033[1;36mPara iniciar más tarde, ejecuta: ./run.sh\033[0m"
    echo ""
fi
