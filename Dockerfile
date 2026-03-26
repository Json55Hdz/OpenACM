FROM python:3.12-slim

WORKDIR /app

# Instalar utilidades de sistema necesarias
RUN apt-get update && apt-get install -y \
    curl build-essential xdotool \
    && rm -rf /var/lib/apt/lists/*

# Instalar `uv` para descargas ultrarrápidas de Python
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="/usr/local/bin" sh

# Copiar configuración de dependencias primero (cache)
COPY pyproject.toml .

# Instalar dependencias a nivel de sistema
RUN uv pip install --system -e .

# Instalar dependencias del sistema y el navegador Chromium para Playwright
RUN playwright install --with-deps chromium

# Copiar el código fuente completo
COPY . .

# Exponer el puerto del Dashboard Web
EXPOSE 8080

# El token se generará y se guardará en /app/config/.env,
# lo verás en los logs de Docker `docker logs openacm`
CMD ["python", "-m", "openacm"]
