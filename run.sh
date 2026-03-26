#!/bin/bash
echo "=========================================="
echo "  Iniciando OpenACM..."
echo "=========================================="

if [ ! -f ".venv/bin/activate" ]; then
    echo -e "\033[1;31m[ERROR] No hemos encontrado la instalacion.\033[0m"
    echo "Por favor, ejecuta ./setup.sh primero."
    exit 1
fi

source .venv/bin/activate
python -m openacm
