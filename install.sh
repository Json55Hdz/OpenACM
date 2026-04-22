#!/bin/bash
# Bootstrap installer — run without cloning the repo first:
#   curl -fsSL https://raw.githubusercontent.com/Json55Hdz/OpenACM/main/install.sh | bash

set -e

REPO_URL="https://github.com/Json55Hdz/OpenACM.git"
INSTALL_DIR="${OPENACM_DIR:-$HOME/OpenACM}"

echo -e "\033[1;36m==========================================\033[0m"
echo -e "\033[1;36m  OpenACM - Bootstrap Installer\033[0m"
echo -e "\033[1;36m==========================================\033[0m"
echo ""

# ── Requirements ─────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    echo -e "\033[1;31m[ERROR] git is required. Install it from https://git-scm.com\033[0m"
    exit 1
fi

# ── Clone ─────────────────────────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "\033[1;33m[*] OpenACM already exists at $INSTALL_DIR — pulling latest...\033[0m"
    cd "$INSTALL_DIR"
    git pull
else
    echo -e "\033[1;33m[*] Cloning OpenACM to $INSTALL_DIR...\033[0m"
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo -e "\033[1;32m[OK] Repository ready.\033[0m"
echo ""

# ── Run setup ─────────────────────────────────────────────────────────────────
chmod +x setup.sh run.sh update.sh acm.sh 2>/dev/null || true
exec ./setup.sh
