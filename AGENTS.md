# OpenACM — Agent Notes

Self-hosted autonomous AI agent. Python 3.12+ backend (FastAPI) + Next.js 16 frontend.

## Dev Commands

| Task | Command |
|---|---|
| Install deps & venv | `uv pip install -e .` (root) |
| Start backend | `uv run python -m openacm` |
| Start frontend (dev) | `cd frontend && npm install && npm run dev` |
| Build frontend (prod) | `cd frontend && npm run deploy` |
| Run all tests | `pytest` |
| Lint Python | `ruff check .` |
| Format Python | `ruff format .` |

- **Frontend dev server** runs on `localhost:3000` and expects backend on `localhost:47821`.
- **Backend** serves the dashboard at `http://{host}:{port}` (default `47821`).

## Architecture

- **Backend entry**: `src/openacm/__main__.py` → `app.py` (`OpenACM` class) orchestrates brain, tools, channels, web server, console loop.
- **Web server**: `src/openacm/web/server.py` (FastAPI) + routers in `web/routers/`.
- **Brain / agent loop**: `src/openacm/core/brain.py`.
- **Tool registry**: `src/openacm/tools/registry.py` — built-in tools live in `src/openacm/tools/`.
- **Frontend**: Next.js **static export** (`output: 'export'`, `distDir: 'dist'`). Built files are copied to `src/openacm/web/static/` by `npm run deploy`.

## Repo-specific Quirks

- **Python `src` layout**: Package root is `src/openacm/`. `pyproject.toml` uses `tool.setuptools.packages.find.where = ["src"]`.
- **Virtual env**: Setup scripts create `.venv/` and **force** its Python/PATH in `run.bat`/`run.sh`. Do not rely on system Python.
- **Windows setup auto-elevates** to Administrator (required for `uv` and Playwright installs).
- **Optional deps are truly optional**: voice, IoT, MCP, Stitch, ChromaDB, etc. are imported inside `try/except` blocks and skipped gracefully at runtime. Do not add hard dependencies for them.
- **Config load order**: `config/default.yaml` → `config/.env` (dotenv) → Pydantic models in `src/openacm/core/config.py`.
- **Debug mode**: Create `data/debug_mode` with contents `true` to enable DEBUG logging on startup.
- **Dashboard token**: Auto-generated on first run and printed to console. Stored via `openacm/security/crypto.py`.
- **Playwright**: Setup installs Chromium only (`playwright install chromium`). Browser automation tool is `src/openacm/tools/browser_agent.py`.

## Frontend Notes

- Next.js 16 with **App Router** (`frontend/app/`).
- TailwindCSS v4 with `@tailwindcss/postcss` (see `postcss.config.mjs`). No `tailwind.config.js`.
- `paths` alias: `@/*` maps to `./*`.
- **No ESLint config file** in repo; uses `eslint-config-next` defaults.

## Testing

- `pytest` config in `pyproject.toml`: `asyncio_mode = auto`, `testpaths = ["tests"]`.
- `tests/conftest.py` provides fixtures: `db` (in-memory SQLite), `mock_llm_router`, `brain`, `tool_registry`, `client` (httpx AsyncClient over ASGI).
- Tests do **not** make real LLM calls — `mock_llm_router` is injected.

## Style & Lint

- **Python**: ruff, line length `100`, target `py312`.
- **TypeScript**: Follow existing patterns; no custom ESLint rules to learn.

## What NOT to Commit

- `config/.env` (contains API keys)
- `data/` (runtime data, logs, DB)
- `frontend/node_modules/`, `.venv/`

## Scripts Reference

- `setup.bat` / `setup.sh` — first-time install (creates venv, installs deps, downloads Playwright).
- `run.bat` / `run.sh` — start OpenACM (builds frontend first, then starts backend).
- `scripts/build-frontend.bat` — called by `run.bat`; runs `npm run deploy` inside `frontend/`.
