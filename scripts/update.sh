#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

echo -e "\033[1;36m==========================================\033[0m"
echo -e "\033[1;36m  OpenACM - Update\033[0m"
echo -e "\033[1;36m==========================================\033[0m"
echo ""

# ── 1. Git pull (only if this is a git checkout) ────────────────────────────
STASHED=0
if [ -d ".git" ] && command -v git &>/dev/null && git rev-parse --is-inside-work-tree &>/dev/null; then
    # Autostash uncommitted changes so the pull doesn't blow up
    if ! git diff --quiet HEAD 2>/dev/null || [ -n "$(git status --porcelain)" ]; then
        echo -e "\033[1;33m[*] Local changes detected — stashing them temporarily...\033[0m"
        git stash push -u -m "openacm-update-autostash-$(date +%s)" &>/dev/null && STASHED=1 || true
    fi

    echo -e "\033[1;33m[*] Fetching latest changes...\033[0m"
    if ! git pull --ff-only; then
        echo -e "\033[1;31m[ERROR] git pull failed.\033[0m"
        echo -e "\033[1;37m    Probably your branch has diverged from the remote.\033[0m"
        echo -e "\033[1;37m    Resolve it manually, then run update again.\033[0m"
        if [ "$STASHED" = "1" ]; then
            echo -e "\033[1;33m[*] Restoring your local changes...\033[0m"
            git stash pop &>/dev/null || true
        fi
        exit 1
    fi
    echo -e "\033[1;32m[OK] Repository updated.\033[0m"

    if [ "$STASHED" = "1" ]; then
        echo -e "\033[1;33m[*] Restoring your local changes...\033[0m"
        if ! git stash pop &>/dev/null; then
            echo -e "\033[1;33m[!] Could not auto-restore stash — there may be conflicts.\033[0m"
            echo -e "\033[1;37m    Run 'git stash list' and resolve manually.\033[0m"
        fi
    fi
else
    echo -e "\033[1;33m[!] This is not a git checkout — skipping 'git pull'.\033[0m"
    echo -e "\033[1;37m    If you want to update the code, download the latest version\033[0m"
    echo -e "\033[1;37m    from GitHub and extract it over this folder, then re-run update.\033[0m"
fi
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

FRONTEND_BUILT=1
if ! command -v node &>/dev/null; then
    echo -e "\033[1;33m[!] Node.js not found, skipping frontend build.\033[0m"
    FRONTEND_BUILT=0
elif [ ! -d "frontend" ]; then
    echo -e "\033[1;33m[!] frontend/ folder not found, skipping build.\033[0m"
    FRONTEND_BUILT=0
else
    echo -e "\033[1;33m[*] Rebuilding frontend...\033[0m"
    pushd frontend >/dev/null
    if ! npm install --silent; then
        popd >/dev/null
        echo -e "\033[1;31m[ERROR] npm install failed. Frontend was NOT updated.\033[0m"
        exit 1
    fi
    if ! npm run build; then
        popd >/dev/null
        echo -e "\033[1;31m[ERROR] Frontend build failed. Frontend was NOT updated.\033[0m"
        exit 1
    fi
    popd >/dev/null
    mkdir -p src/openacm/web/static
    rm -rf src/openacm/web/static/*
    cp -r frontend/dist/* src/openacm/web/static/
    echo -e "\033[1;32m[OK] Frontend rebuilt.\033[0m"
fi
echo ""

echo -e "\033[1;32m==========================================\033[0m"
echo -e "\033[1;32m  Update Complete!\033[0m"
echo -e "\033[1;32m==========================================\033[0m"
if [ "$FRONTEND_BUILT" = "0" ]; then
    echo -e "\033[1;33m  (Note: frontend was not rebuilt — see warnings above.)\033[0m"
fi
echo ""

read -p "Restart OpenACM now? (S/n): " choice
if [[ "$choice" == "" || "$choice" =~ ^[sSyY] ]]; then
    echo ""
    exec scripts/run.sh
else
    echo -e "\033[1;36mRun 'openacm start' to launch.\033[0m"
    echo ""
fi
