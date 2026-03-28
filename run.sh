#!/bin/bash
echo "=========================================="
echo "  Iniciando OpenACM..."
echo "=========================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Verify virtual environment exists
if [ ! -f ".venv/bin/activate" ]; then
    echo "[ERROR] No se encontró la instalación."
    echo ""
    echo "Por favor, ejecuta ./setup.sh primero."
    echo ""
    exit 1
fi

# Verify OpenACM is installed
source .venv/bin/activate
python -c "import openacm" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "[ERROR] OpenACM no está instalado correctamente."
    echo ""
    echo "Intenta ejecutar ./setup.sh de nuevo."
    echo ""
    exit 1
fi
echo "[OK] Entorno verificado."
echo ""

# Build frontend (ensures latest code is always served)
if command -v node &>/dev/null && [ -d "frontend" ]; then
    echo "[*] Construyendo el frontend..."
    cd frontend
    npm install --silent 2>/dev/null
    npm run build 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "[ERROR] El build del frontend falló."
        exit 1
    fi
    cd ..

    # Copy dist to static
    if [ -d "src/openacm/web/static" ]; then
        rm -rf src/openacm/web/static/*
    else
        mkdir -p src/openacm/web/static
    fi
    cp -r frontend/dist/* src/openacm/web/static/
    echo "[OK] Frontend construido y copiado."
    echo ""
else
    echo "[!] Node.js no encontrado, omitiendo build del frontend."
    echo ""
fi

# Start OpenACM
echo "[OK] Todo listo. Iniciando..."
echo ""
python -m openacm

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "[ERROR] OpenACM terminó con un error (código $EXIT_CODE)."
    echo ""
    echo "Si ves errores de 'module not found', ejecuta ./setup.sh"
    echo "Si el error persiste, revisa que config/.env tenga tus API keys"
    echo ""
fi
