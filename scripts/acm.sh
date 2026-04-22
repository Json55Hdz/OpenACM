#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CMD="${1:-help}"
PORT=47821

show_help() {
    echo ""
    echo "  OpenACM CLI"
    echo ""
    echo "  Usage: ./acm <command>"
    echo ""
    echo "  Commands:"
    echo "    install   First-time setup (create venv, install deps, build frontend)"
    echo "    update    Pull latest changes + sync deps + rebuild frontend"
    echo "    start     Start OpenACM"
    echo "    stop      Stop OpenACM"
    echo "    status    Check if OpenACM is running"
    echo "    repair    Reinstall Python dependencies (no git pull)"
    echo ""
}

get_pid() {
    lsof -ti tcp:$PORT 2>/dev/null | head -1 || \
    fuser ${PORT}/tcp 2>/dev/null | tr -d ' ' || \
    true
}

case "$CMD" in
    install)
        exec ./setup.sh
        ;;
    update)
        exec ./update.sh
        ;;
    start)
        exec ./run.sh
        ;;
    stop)
        PID=$(get_pid)
        if [ -n "$PID" ]; then
            echo "[*] Stopping OpenACM (PID $PID)..."
            kill "$PID"
            echo "[OK] OpenACM stopped."
        else
            echo "[!] OpenACM is not running."
        fi
        ;;
    status)
        PID=$(get_pid)
        if [ -n "$PID" ]; then
            echo -e "\033[1;32m[OK] OpenACM is running (PID $PID)\033[0m"
            echo "     Web: http://127.0.0.1:$PORT"
        else
            echo "[--] OpenACM is not running."
        fi
        ;;
    repair)
        echo "[*] Reinstalling Python dependencies..."
        if command -v uv &>/dev/null; then
            uv pip install -e .
        elif [ -f ".venv/bin/pip" ]; then
            .venv/bin/pip install -e .
        else
            echo "[ERROR] No virtual environment found. Run './acm install' first."
            exit 1
        fi
        echo "[OK] Repair complete. Run './acm start' to launch."
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "[!] Unknown command: $CMD"
        show_help
        exit 1
        ;;
esac
