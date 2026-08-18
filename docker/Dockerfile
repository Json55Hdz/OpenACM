# ── Stage 1: compilar el dashboard (Next.js, static export) ─────────────────
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: backend Python + dashboard ya compilado ────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Instalar utilidades de sistema necesarias
RUN apt-get update && apt-get install -y \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# Instalar `uv` para descargas ultrarrápidas de Python
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="/usr/local/bin" sh

# Copiar el código fuente completo — debe ir ANTES del pip install:
# setuptools valida que exista src/ durante el egg_info de una instalación editable.
COPY . .

# Instalar dependencias a nivel de sistema
RUN uv pip install --system -e .

# Instalar dependencias del sistema y el navegador Chromium para Playwright
RUN playwright install --with-deps chromium

# Dashboard compilado (stage 1) — va donde server.py espera encontrar el SPA
COPY --from=frontend-builder /app/frontend/dist ./src/openacm/web/static

# Exponer el puerto del Dashboard Web
EXPOSE 8080

# El token se generará y se guardará en /app/config/.env,
# lo verás en los logs de Docker `docker logs openacm`
CMD ["python", "-m", "openacm"]
