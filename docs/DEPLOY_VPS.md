# Guía de Deploy — OpenACM en Ubuntu VPS

## Arquitectura recomendada

```
Internet (80/443)
      │
      ▼
Nginx Proxy Manager   ← Docker, gestiona SSL + proxy desde GUI
      │
      ▼
OpenACM (bare metal)  ← Puerto 47821, gestionado por systemd
      │
      ▼
SQLite  ·  config/.env  ·  data/
```

> **¿Por qué bare metal para OpenACM?**
> Playwright/Chromium (el agente web) tiene problemas en contenedores sin display — necesita flags especiales y más RAM. Correr OpenACM directamente en el host es más simple, más ligero y más fácil de debuggear. NPM maneja la parte "difícil" (SSL, proxy) desde Docker.

---

## Requisitos mínimos del servidor

| Recurso | Mínimo | Recomendado |
|---|---|---|
| **OS** | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| **RAM** | 2 GB | 4 GB |
| **CPU** | 2 vCPUs | 4 vCPUs |
| **Disco** | 20 GB SSD | 40 GB SSD |

> **Con Playwright/Chromium activo**: +1 GB RAM mínimo (el agente web descarga ~500 MB de Chromium).
> **Con Voice (Kokoro)**: necesita GPU o +4 GB RAM. Desactívalo si el VPS no tiene GPU.

---

## Checklist de deploy (en orden)

```
[ ] 1. Preparar el VPS (apt, firewall UFW)
[ ] 2. Instalar Docker + Docker Compose
[ ] 3. Instalar y configurar Nginx Proxy Manager
[ ] 4. Clonar el repositorio
[ ] 5. Configurar config/.env con las API keys
[ ] 6. Instalar OpenACM con setup.sh
[ ] 7. Crear el servicio systemd
[ ] 8. Configurar el Proxy Host en NPM (dominio + SSL)
[ ] 9. Permisos del filesystem
[ ] 10. Configurar backup automático de SQLite
```

---

## Paso 1 — Preparar el VPS

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git sqlite3

# Firewall: solo abrir lo necesario
sudo ufw allow 22/tcp    # SSH — PRIMERO, antes de activar
sudo ufw allow 80/tcp    # HTTP (para certbot/NPM)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
sudo ufw status
```

> El puerto 47821 (OpenACM) **no debe estar abierto al exterior** — NPM hace el proxy.

---

## Paso 2 — Instalar Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
docker --version && docker compose version
```

---

## Paso 3 — Nginx Proxy Manager

```bash
mkdir -p /opt/npm && cd /opt/npm

cat > docker-compose.yml << 'EOF'
services:
  npm:
    image: jc21/nginx-proxy-manager:latest
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "81:81"
    volumes:
      - ./data:/data
      - ./letsencrypt:/etc/letsencrypt
EOF

docker compose up -d
```

La GUI de NPM queda en `http://tu-ip:81`.

**Credenciales iniciales:**
- Email: `admin@example.com`
- Password: `changeme`

> Cambia la contraseña inmediatamente al entrar.

**Después de configurar NPM**, cierra el puerto 81 para que la GUI no quede expuesta:
```bash
sudo ufw deny 81/tcp
```
Para acceder a la GUI después, usa un túnel SSH: `ssh -L 8181:localhost:81 usuario@tu-servidor`

---

## Paso 4 — Instalar OpenACM

```bash
git clone <tu-repo-url> /opt/openacm
cd /opt/openacm
bash setup.sh
```

El script instala todas las dependencias, crea el `.venv` y configura el `config/.env` inicial.

---

## Paso 5 — Configurar config/.env

```bash
nano /opt/openacm/config/.env
```

Valores mínimos:

```env
# Al menos un provider LLM
ANTHROPIC_API_KEY=sk-ant-...

# Token del dashboard — si lo dejas vacío, se auto-genera al primer arranque
# pero DEBES pegarlo aquí después para que persista entre reinicios
DASHBOARD_TOKEN=
```

---

## Paso 6 — Servicio systemd

```bash
sudo nano /etc/systemd/system/openacm.service
```

```ini
[Unit]
Description=OpenACM Autonomous Agent
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/openacm
ExecStart=/opt/openacm/.venv/bin/python -m openacm
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable openacm
sudo systemctl start openacm

# Ver logs (el token aparece aquí la primera vez)
sudo journalctl -u openacm -f
```

Copia el token que aparece en los logs y pégalo en `config/.env` como `DASHBOARD_TOKEN=<valor>`, luego reinicia:

```bash
sudo systemctl restart openacm
```

---

## Paso 7 — Configurar Proxy Host en NPM

1. Abre la GUI de NPM en `http://tu-ip:81`
2. **Proxy Hosts → Add Proxy Host**
3. Configuración:
   - Domain Names: `tu-dominio.com`
   - Scheme: `http`
   - Forward Hostname/IP: `127.0.0.1` (o la IP privada del host)
   - Forward Port: `47821`
   - Activar: **Websockets Support** ← importante para el dashboard en tiempo real
4. Tab **SSL**:
   - SSL Certificate: Request a new SSL Certificate
   - Activar: **Force SSL**, **HTTP/2 Support**
   - Email para Let's Encrypt: tu email
5. Tab **Advanced** — pegar estas directivas para security headers y rate limiting:

```nginx
# Security headers
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Content-Security-Policy "default-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; connect-src 'self' wss: https:; img-src 'self' data: blob: https:;" always;

# Rate limiting
limit_req_zone $binary_remote_addr zone=openacm:10m rate=20r/s;
limit_req zone=openacm burst=40 nodelay;
client_max_body_size 20M;
```

6. Guardar → NPM obtiene el certificado automáticamente.

---

## Paso 8 — Permisos del filesystem

```bash
sudo chown -R ubuntu:ubuntu /opt/openacm
chmod 700 /opt/openacm/config /opt/openacm/data 2>/dev/null || true
chmod 600 /opt/openacm/config/.env
chmod 600 /opt/openacm/config/google_credentials.json 2>/dev/null || true
chmod 600 /opt/openacm/config/google_token.json 2>/dev/null || true
```

Reemplaza `ubuntu` con el usuario real de tu VPS.

---

## Paso 9 — Backup automático de SQLite

```bash
sudo tee /opt/openacm/scripts/backup.sh > /dev/null << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/openacm/backups"
DB_PATH="/opt/openacm/data/openacm.db"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_PATH" ".backup $BACKUP_DIR/openacm_$DATE.db"

# Mantener solo los últimos 7 backups
ls -t "$BACKUP_DIR"/openacm_*.db | tail -n +8 | xargs rm -f 2>/dev/null || true
echo "Backup OK: openacm_$DATE.db"
EOF

sudo chmod +x /opt/openacm/scripts/backup.sh

# Cron: backup diario a las 3am
(crontab -l 2>/dev/null; echo "0 3 * * * /opt/openacm/scripts/backup.sh >> /var/log/openacm-backup.log 2>&1") | crontab -
```

---

## Comandos de operación

```bash
# Estado del servicio
sudo systemctl status openacm

# Ver logs en tiempo real
sudo journalctl -u openacm -f

# Reiniciar
sudo systemctl restart openacm

# Actualizar a nueva versión
cd /opt/openacm
git pull
uv pip install -e .          # actualizar deps si cambiaron
sudo systemctl restart openacm
```

---

## Verificación post-deploy

```bash
# HTTPS responde
curl -I https://tu-dominio.com/api/ping

# HTTP redirige a HTTPS
curl -I http://tu-dominio.com/api/ping

# Puerto 47821 NO accesible desde fuera
curl --connect-timeout 3 http://tu-dominio.com:47821/api/ping  # debe fallar

# Security headers presentes
curl -sI https://tu-dominio.com | grep -E "X-Frame|X-Content|Strict-Transport"

# Firewall
sudo ufw status
```

---

## Problemas de seguridad pendientes en el código

Estos requieren cambios en el código fuente (no en infra):

| Problema | Impacto | Estado |
|---|---|---|
| OAuth tokens de Google en plaintext en SQLite | Medio | Pendiente |
| Tokens de Telegram/WhatsApp en plaintext en DB | Medio | Pendiente |
| Token del dashboard imprimido en logs de arranque | Bajo | Pendiente |
| WebSocket auth via query param (visible en logs de nginx) | Bajo | Aceptable con HTTPS |

---

---

## Alternativa: Deploy con Docker

> Usa esta sección si prefieres todo contenedorizado o si no vas a usar Playwright en el servidor.

### Preparar el Docker setup

**Crear `.dockerignore`** en la raíz del proyecto:

```
.venv/
.git/
__pycache__/
*.pyc
*.pyo
config/.env
config/google_token.json
config/google_credentials.json
data/
*.db
*.sqlite
frontend/node_modules/
frontend/.next/
frontend/dist/
docs/
tests/
```

**Editar `docker/docker-compose.yml`**:

```yaml
services:
  openacm:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    container_name: openacm
    ports:
      - "127.0.0.1:8080:8080"   # solo localhost — NPM hace el proxy
    volumes:
      - ../data:/app/data
      - ../config:/app/config
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '2.0'
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/api/ping"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

**Quitar `xdotool` del `docker/Dockerfile`** (herramienta de GUI X11, inútil en VPS headless):

```dockerfile
RUN apt-get update && apt-get install -y \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*
```

### Arrancar con Docker

```bash
cd /opt/openacm/docker
docker compose build
docker compose up -d
docker logs openacm   # ver el token la primera vez
```

En NPM, el Forward Port sería `8080` en lugar de `47821`.

---

## Distribución para clientes: imagen privada versionada

Para deployments de cliente (ver `docs/superpowers/specs/2026-08-18-client-deployment-strategy-design.md`),
el server del cliente **nunca** clona este repo ni corre `git pull` en producción.
En su lugar:

1. Se etiqueta un release en este repo: `git tag vX.Y.Z && git push origin vX.Y.Z`.
2. El workflow `.github/workflows/release-image.yml` construye la imagen y la
   sube a `ghcr.io/<owner>/openacm:X.Y.Z` (registry **privado** — verifica en
   GitHub → Packages → openacm → Package settings que la visibilidad quedó en
   Private la primera vez que se publica).
3. El `Dockerfile` del cliente (en su propio repo privado, fuera de este repo)
   hace `FROM ghcr.io/<owner>/openacm:X.Y.Z`, copia su plugin package y su
   config, y construye su propia imagen.
4. El server del cliente solo hace `docker pull` de la imagen de **su** cliente,
   nunca de este repo.

Actualizar un cliente = subir el tag base que usa su `Dockerfile` a mano,
reconstruir su imagen, hacer push, y que el server haga `docker pull` del tag
nuevo. Nunca automático, nunca sigue `main`.
