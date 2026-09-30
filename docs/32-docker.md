# Docker

OpenACM ships a Docker setup in `docker/`:

- `docker/Dockerfile` — multi-stage build: stage 1 builds the Next.js dashboard with Node 20 (`npm ci && npm run build`); stage 2 is `python:3.12-slim` with `uv`, the Python package (`uv pip install --system -e .`), Playwright's Chromium, and the built dashboard copied into `src/openacm/web/static`. Runs `python -m openacm`.
- `docker/docker-compose.yml` — one `openacm` service that publishes port **8080**, mounts `../data` and `../config`, restarts `unless-stopped`, and health-checks `http://localhost:8080/api/ping`.
- `.dockerignore` (repo root) — keeps `.venv/`, `.git/`, secrets in `config/`, `data/`, `node_modules`, builds, `docs/` and `tests/` out of the image.

---

## Quick Start

```bash
git clone https://github.com/Json55Hdz/OpenACM.git
cd OpenACM

# 1. Make OpenACM listen on 0.0.0.0:8080 inside the container
cat > config/local.yaml <<'EOF'
web:
  host: 0.0.0.0
  port: 8080
features:
  voice: false        # no microphone in a container
EOF

# 2. Build and start
docker compose -f docker/docker-compose.yml up -d --build

# 3. Get the dashboard token
docker logs openacm
```

Open `http://localhost:8080` and paste the token.

> **Why step 1?** OpenACM binds to `127.0.0.1:47821` by default, which is unreachable from outside the container and doesn't match the port the compose file publishes and health-checks. `config/` is mounted from the host, so `config/local.yaml` is picked up by the container.

---

## Data and Configuration

| Host path | Container path | Contents |
|-----------|----------------|----------|
| `./data` | `/app/data` | SQLite database, vector store, media, logs |
| `./config` | `/app/config` | `default.yaml`, `local.yaml`, `.env` (API keys + `DASHBOARD_TOKEN`), `activity.key`, MCP/custom providers, Google OAuth files |

On first start OpenACM generates the dashboard token and writes it to `config/.env`, so it survives container re-creation. Add your API keys to `config/.env` (or through the onboarding wizard) and restart the container.

Useful commands:

```bash
docker compose -f docker/docker-compose.yml logs -f      # follow logs
docker compose -f docker/docker-compose.yml restart      # restart after config changes
docker compose -f docker/docker-compose.yml up -d --build   # rebuild after git pull
```

Without a TTY the interactive console is skipped; the process stays up for the web server and channels and shuts down cleanly on `SIGTERM` (`docker stop`).

---

## Notes and Limits

- **Browser agent:** Chromium is installed in the image and runs headless. If you don't need it, set `features.browser_agent: false` to save memory.
- **Voice:** there is no audio device in a container — keep `features.voice: false`.
- **Activity watcher / screenshots:** these observe a desktop session and do nothing useful in a headless container.
- **Shell commands** run inside the container, not on the host.
- **Memory:** plan for ~2 GB for the container (see [Getting Started → Requirements](./02-getting-started.md#requirements)).
- For HTTPS and a public domain, put a reverse proxy in front and bind the port to localhost (`"127.0.0.1:8080:8080"`) — see [Deploy on a VPS](./DEPLOY_VPS.md#alternativa-deploy-con-docker).

---

## Versioned Client Images

For client deployments the repository publishes versioned images instead of having servers `git pull`:

1. Tag a release: `git tag vX.Y.Z && git push origin vX.Y.Z`.
2. `.github/workflows/release-image.yml` builds `docker/Dockerfile` and pushes `ghcr.io/<owner>/openacm:X.Y.Z` and `:latest` to GitHub Container Registry (keep the package **private**; check its visibility after the first publish).
3. A client's own Dockerfile does `FROM ghcr.io/<owner>/openacm:X.Y.Z`, adds its plugin package and config, and builds the client image.
4. The client server only `docker pull`s its own image; updating means bumping the base tag explicitly.

Trim the product for a client with `features` (disable `browser_agent` / `voice`) and `client_profile` (restrict dashboard pages) in `config/local.yaml` — see [Configuration](./11-configuration.md#client-deployments-features-and-client_profile). Release steps are also described in [Contributing](./CONTRIBUTING.md#releasing).
