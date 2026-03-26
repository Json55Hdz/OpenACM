#!/bin/bash
set -e

echo -e "\033[1;36m==========================================\033[0m"
echo -e "\033[1;36m  🚀 Instalando OpenACM Autónomo Tier-1\033[0m"
echo -e "\033[1;36m==========================================\033[0m\n"

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo -e "\033[1;33m[*] Instalando 'uv' (gestor de dependencias ultrarrápido)...\033[0m"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
else
    echo -e "\033[1;32m[OK] 'uv' ya está instalado.\033[0m"
fi

echo -e "\033[1;33m[*] Instalando utilidades base del sistema...\033[0m"
if command -v apt-get &> /dev/null; then
    sudo apt update
    sudo apt install -y build-essential python3-dev libssl-dev libffi-dev xdotool python3.12-venv
fi

echo -e "\033[1;33m[*] Preparando el entorno virtual y Python 3.12...\033[0m"
uv python install 3.12 2>/dev/null || true
uv venv

echo -e "\033[1;33m[*] Revisando configuraciones (.env)...\033[0m"
if [ ! -f "config/.env" ]; then
    cp config/.env.example config/.env
    echo -e "\033[1;32m[OK] Archivo 'config/.env' creado automáticamente.\033[0m"
fi

echo -e "\033[1;33m[*] Instalando todas las dependencias del proyecto...\033[0m"
uv pip install -e .

echo -e "\033[1;33m[*] Instalando navegadores para el Agente Web (Playwright)...\033[0m"
uv run playwright install --with-deps chromium

echo -e "\n\033[1;32m==========================================\033[0m"
echo -e "\033[1;32m  ✅ ¡Instalación Completada con Éxito!\033[0m"
echo -e "\033[1;32m==========================================\033[0m\n"
echo -e "\033[1;37mPara arrancar OpenACM de ahora en adelante, simplemente ejecuta:\033[0m"
echo -e "\033[1;36m./run.sh\033[0m\n"
