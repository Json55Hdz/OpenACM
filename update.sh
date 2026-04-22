#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "\033[1;36m==========================================\033[0m"
echo -e "\033[1;36m  OpenACM - Update\033[0m"
echo -e "\033[1;36m==========================================\033[0m"
echo ""

# ── 1. Git pull ─────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    echo -e "\033[1;31m[ERROR] git not found. Install it from https://git-scm.com\033[0m"
    exit 1
fi

echo -e "\033[1;33m[*] Fetching latest changes...\033[0m"
git pull
echo -e "\033[1;32m[OK] Repository updated.\033[0m"
echo ""

# ── 2. Sync Python dependencies ──────────────────────────────────────────────
echo -e "\033[1;33m[*] Syncing Python dependencies...\033[0m"
if command -v uv &>/dev/null; then
    uv pip install -e . --quiet
elif [ -f ".venv/bin/pip" ]; then
    .venv/bin/pip install -e . -q
else
    echo -e "\033[1;31m[ERROR] No virtual environment found. Run ./setup.sh first.\033[0m"
    exit 1
fi
echo -e "\033[1;32m[OK] Python dependencies synced.\033[0m"
echo ""

# ── 3. Rebuild frontend ──────────────────────────────────────────────────────
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"
export PATH="/opt/homebrew/opt/node@20/bin:/usr/local/opt/node@20/bin:$PATH"

if ! command -v node &>/dev/null; then
    echo -e "\033[1;33m[!] Node.js not found, skipping frontend build.\033[0m"
elif [ ! -d "frontend" ]; then
    echo -e "\033[1;33m[!] frontend/ folder not found, skipping build.\033[0m"
else
    echo -e "\033[1;33m[*] Rebuilding frontend...\033[0m"
    cd frontend
    npm install --silent
    npm run build
    cd "$SCRIPT_DIR"
    rm -rf src/openacm/web/static/*
    mkdir -p src/openacm/web/static
    cp -r frontend/dist/* src/openacm/web/static/
    echo -e "\033[1;32m[OK] Frontend rebuilt.\033[0m"
fi
echo ""

echo -e "\033[1;32m==========================================\033[0m"
echo -e "\033[1;32m  Update Complete!\033[0m"
echo -e "\033[1;32m==========================================\033[0m"
echo ""

read -p "Restart OpenACM now? (S/n): " choice
if [[ "$choice" == "" || "$choice" =~ ^[sSyY] ]]; then
    echo ""
    exec ./run.sh
else
    echo -e "\033[1;36mRun ./run.sh or './acm start' to launch.\033[0m"
    echo ""
fi
