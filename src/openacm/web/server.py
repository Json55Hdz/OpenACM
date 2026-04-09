"""
FastAPI Web Server for OpenACM Dashboard.

Serves the web UI, REST API, and WebSocket connections.
"""

import asyncio
from pathlib import Path
from typing import Any

import uvicorn
import structlog
from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    Request,
    UploadFile,
    File,
    Form,
    HTTPException,
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
import os
import secrets
from pathlib import Path
import json

from openacm.core.config import AppConfig
from openacm.core.brain import Brain
from openacm.core.commands import CommandProcessor
from openacm.core.events import EventBus
from openacm.storage.database import Database
from openacm.tools.registry import ToolRegistry

log = structlog.get_logger()

# Store connected WebSocket clients
_ws_clients: set[WebSocket] = set()

# Tools that produce shell-like output to show in the terminal panel
_TERMINAL_TOOLS = {"run_command", "run_python", "python_kernel", "execute_command"}

# Global refs (set during startup)
_brain: Brain | None = None
_database: Database | None = None
_event_bus: EventBus | None = None
_tool_registry: ToolRegistry | None = None
_config: AppConfig | None = None
_command_processor: CommandProcessor | None = None
_channels: list = []
_agent_bot_manager = None
_mcp_manager = None
_activity_watcher = None
_cron_scheduler = None
_swarm_manager = None
_content_watcher = None
_custom_provider_ids: set[str] = set()  # IDs of user-defined custom providers
_onboarding_triggered_flags: dict[str, bool] = {}  # Track if onboarding was triggered for a channel


# ─── Custom Provider Helpers (module-level so create_web_server can call them) ──

import re as _re

def _get_custom_providers_path() -> Path:
    from openacm.core.config import _find_project_root
    return _find_project_root() / "config" / "custom_providers.json"


def _load_custom_providers() -> list[dict]:
    path = _get_custom_providers_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_custom_providers(providers: list[dict]) -> None:
    path = _get_custom_providers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(providers, indent=2, ensure_ascii=False), encoding="utf-8")


def _apply_custom_providers(providers: list[dict]) -> None:
    """Inject custom providers into the live config + env and update the tracking set."""
    global _custom_provider_ids, _config
    if not _config:
        return
    for p in providers:
        pid = p["id"]
        _custom_provider_ids.add(pid)
        _config.llm.providers[pid] = {
            "base_url": p["base_url"],
            "default_model": p.get("default_model", ""),
        }
        api_key = p.get("api_key", "")
        if api_key:
            os.environ[f"{pid.upper()}_API_KEY"] = api_key


def _make_provider_id(name: str, existing: list[dict]) -> str:
    """Turn a human name into a unique snake_case provider ID."""
    pid = _re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not pid:
        pid = "custom"
    existing_ids = {p["id"] for p in existing}
    candidate = pid
    counter = 2
    while candidate in existing_ids:
        candidate = f"{pid}_{counter}"
        counter += 1
    return candidate


def _get_version() -> str:
    """Read version from pyproject.toml — single source of truth."""
    try:
        import tomllib
        pyproject = Path(__file__).parent.parent.parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except Exception:
        return "0.0.0"


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="OpenACM Dashboard",
        version=_get_version(),
        docs_url="/api/docs",
    )

    # Static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        # Mount Next.js assets from static/_next to /_next
        next_dir = static_dir / "_next"
        if next_dir.exists():
            app.mount("/_next", StaticFiles(directory=str(next_dir)), name="_next")

    # ─── Auth Middleware ──────────────────────────────────────

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    # SECURITY: POR DISEÑO - Carga segura de token desde variables de entorno
    _dashboard_token: str = os.environ.get("DASHBOARD_TOKEN", "")

    # Paths that don't need authentication
    # Everything except API and WebSocket is public (React SPA handles auth)
    PUBLIC_PATHS = {"/", "/api/auth/check"}
    PUBLIC_PREFIXES = ("/static/", "/_next/", "/favicon.ico")

    class TokenAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path

            # WebSocket paths are handled in their own endpoints with their own auth
            if path.startswith("/ws/"):
                return await call_next(request)

            # Everything that's not API is public (SPA routes, assets)
            if not path.startswith("/api/"):
                return await call_next(request)

            # API routes below here require auth (except public ones)
            if path in ("/api/auth/check", "/api/ping", "/api/config/google/callback"):
                return await call_next(request)

            # Check token for other API routes
            token = None
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            if not token:
                token = request.query_params.get("token")

            if not token or token != _dashboard_token:
                return JSONResponse(
                    status_code=401, content={"error": "Unauthorized. Provide a valid token."}
                )

            return await call_next(request)

    if _dashboard_token:
        app.add_middleware(TokenAuthMiddleware)

    def _verify_ws_token(websocket: WebSocket) -> bool:
        """Verify token from WebSocket query parameters."""
        token = websocket.query_params.get("token", "")
        return token == _dashboard_token if _dashboard_token else True

    # ─── Auth API ─────────────────────────────────────────────

    @app.post("/api/auth/check")
    async def check_auth(request: Request):
        """Verify a dashboard token is valid."""
        data = await request.json()
        token = data.get("token", "")
        if token == _dashboard_token:
            return {"valid": True}
        return JSONResponse(status_code=401, content={"valid": False})

    @app.get("/api/auth/check")
    async def check_auth_get(token: str = ""):
        """Verify a dashboard token via GET."""
        if token == _dashboard_token:
            return {"valid": True}
        return JSONResponse(status_code=401, content={"valid": False})

    @app.get("/api/ping")
    async def ping():
        """Public health check — used by frontend to detect restarts."""
        return {"ok": True}

    @app.get("/api/system/info")
    async def system_info():
        """Basic system info flags (encryption status, etc.)."""
        return {
            "version": _get_version(),
            "messages_encrypted": _database.messages_encrypted if _database else False,
        }

    @app.post("/api/system/restart")
    async def restart_system():
        """Restart the OpenACM process (replaces process image via os.execv)."""
        import sys

        async def _do_restart():
            await asyncio.sleep(0.6)  # Let the HTTP response go out first
            log.info("Restarting OpenACM process...")
            os.execv(sys.executable, [sys.executable] + sys.argv)

        asyncio.create_task(_do_restart())
        return {"status": "restarting"}

    # ─── Pages ────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the main dashboard page."""
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return HTMLResponse("<h1>OpenACM</h1><p>Static files not found. Run build first.</p>")

    # ─── API: Stats ───────────────────────────────────────────

    @app.get("/api/stats")
    async def get_stats():
        """Get usage statistics."""
        if not _database:
            return {"error": "Database not available"}
        stats = await _database.get_stats()

        # Add LLM router stats
        if _brain and _brain.llm_router:
            llm_stats = _brain.llm_router.get_stats()
            stats.update(llm_stats)

        return stats

    @app.get("/api/stats/history")
    async def get_stats_history(days: int = 30):
        """Get daily usage history."""
        if not _database:
            return []
        return await _database.get_usage_history(days)

    @app.get("/api/stats/channels")
    async def get_channel_stats():
        """Get per-channel stats."""
        if not _database:
            return []
        return await _database.get_channel_stats()

    @app.get("/api/stats/detailed")
    async def get_detailed_stats(date_from: str | None = None, date_to: str | None = None):
        """Get detailed token/cost breakdown: totals, by_model, today, history.

        Query params:
            date_from: YYYY-MM-DD (inclusive lower bound)
            date_to:   YYYY-MM-DD (inclusive upper bound)
        """
        if not _database:
            return {}
        data = await _database.get_detailed_stats(date_from=date_from, date_to=date_to)
        # Merge in live router totals (not yet persisted to DB) — only when no date filter
        if _brain and _brain.llm_router and not date_from and not date_to:
            snap = _brain.llm_router.get_usage_snapshot()
            data["live"] = snap
        return data

    # ─── API: Tools ───────────────────────────────────────────

    @app.get("/api/plugins/nav")
    async def get_plugin_nav():
        """Return nav items contributed by all active plugins (for dynamic sidebar)."""
        try:
            from openacm.plugins import plugin_manager
            return plugin_manager.get_nav_items()
        except Exception:
            return []

    @app.get("/api/plugins")
    async def list_plugins():
        """Return metadata for all loaded plugins."""
        try:
            from openacm.plugins import plugin_manager
            return [
                {"name": p.name, "version": p.version, "description": p.description, "author": p.author}
                for p in plugin_manager.plugins
            ]
        except Exception:
            return []

    @app.get("/api/tools")
    async def get_tools():
        """List available tools."""
        if not _tool_registry:
            return []
        return [
            {
                "name": t.name,
                "description": t.description,
                "risk_level": t.risk_level,
                "parameters": t.parameters,
            }
            for t in _tool_registry.tools.values()
        ]

    @app.get("/api/tools/executions")
    async def get_tool_executions(limit: int = 50):
        """Get recent tool execution logs."""
        if not _database:
            return []
        return await _database.get_tool_executions(limit)

    # ─── API: Config ──────────────────────────────────────────

    @app.get("/api/config")
    async def get_config():
        """Get current configuration (sanitized)."""
        if not _config:
            return {}
        config_dict = _config.model_dump()
        # Remove sensitive data
        for provider in config_dict.get("llm", {}).get("providers", {}).values():
            if "api_key" in provider:
                provider["api_key"] = "***"
        if "token" in config_dict.get("channels", {}).get("discord", {}):
            config_dict["channels"]["discord"]["token"] = (
                "***" if config_dict["channels"]["discord"]["token"] else ""
            )
        if "token" in config_dict.get("channels", {}).get("telegram", {}):
            config_dict["channels"]["telegram"]["token"] = (
                "***" if config_dict["channels"]["telegram"]["token"] else ""
            )
        return config_dict

    @app.get("/api/config/model")
    async def get_current_model():
        """Get current LLM model."""
        if not _brain:
            return {"model": "unknown"}
        return {
            "model": _brain.llm_router.current_model,
            "provider": _brain.llm_router._current_provider,
        }

    # Providers that don't need an API key
    _NO_KEY_PROVIDERS = {"ollama"}

    def _is_cli_provider_id(provider_id: str) -> bool:
        """Return True if a provider_id is a CLI-type provider in config."""
        if not _config:
            return False
        return _config.llm.providers.get(provider_id, {}).get("type") == "cli"

    def _get_provider_status() -> dict[str, bool]:
        """Derive provider status dynamically from config, using {ID}_API_KEY convention."""
        if not _config:
            return {}
        result: dict[str, bool] = {}
        for provider_id in _config.llm.providers:
            if provider_id in _NO_KEY_PROVIDERS or _is_cli_provider_id(provider_id):
                result[provider_id] = True
            elif provider_id in _custom_provider_ids:
                # Custom providers are always "configured" — user added them deliberately.
                # For keyless local endpoints (LM Studio etc.) they just work.
                result[provider_id] = True
            else:
                env_var = f"{provider_id.upper()}_API_KEY"
                result[provider_id] = _is_real_key(env_var)
        return result

    def _is_real_key(env_var: str) -> bool:
        """Check if an env var has a real value (not empty or placeholder)."""
        val = os.environ.get(env_var, "").strip()
        if not val:
            return False
        # Reject common placeholder patterns
        lower = val.lower()
        if lower.startswith("your-") or lower.startswith("your_"):
            return False
        if "here" in lower and ("-" in lower or "_" in lower):
            return False  # e.g. "sk-your-openai-key-here"
        if lower in ("change-me", "change-me-please", "changeme", "placeholder"):
            return False
        return True

    def _find_env_path() -> Path:
        """Find the .env path using project root."""
        from openacm.core.config import _find_project_root
        return _find_project_root() / "config" / ".env"

    @app.get("/api/config/status")
    async def get_config_status():
        """Check if essential configuration is missing (e.g. LLM API Key)."""
        if not _config or not _brain:
            return {"needs_setup": True}
        # Check if ANY provider has a real key configured (derived dynamically from config)
        provider_statuses = _get_provider_status()
        # Ollama alone doesn't count as "configured" — but API-key providers and CLI providers do
        keyed_configured = any(
            ok for pid, ok in provider_statuses.items() if pid not in _NO_KEY_PROVIDERS
        )
        if not keyed_configured:
            return {"needs_setup": True, "provider": _brain.llm_router._current_provider}
        return {"needs_setup": False}

    # Pending OAuth2 flow state (flow object keyed by state string)
    _google_oauth_flows: dict[str, Any] = {}

    @app.get("/api/config/google")
    async def get_google_status():
        """Check if Google credentials and OAuth token exist."""
        from openacm.core.config import _find_project_root
        root = _find_project_root()
        creds_path = root / "config" / "google_credentials.json"
        token_path = root / "config" / "google_token.json"
        return {
            "credentials_exist": creds_path.exists(),
            "token_exist": token_path.exists(),
        }

    @app.post("/api/config/google")
    async def save_google_credentials(request: Request):
        """Save Google OAuth2 credentials JSON file."""
        import json as _json
        from openacm.core.config import _find_project_root

        data = await request.json()
        credentials_json = data.get("credentials_json", "")
        if not credentials_json:
            raise HTTPException(status_code=400, detail="credentials_json required")

        try:
            parsed = _json.loads(credentials_json) if isinstance(credentials_json, str) else credentials_json
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

        root = _find_project_root()
        creds_path = root / "config" / "google_credentials.json"
        creds_path.parent.mkdir(parents=True, exist_ok=True)
        with open(creds_path, "w", encoding="utf-8") as f:
            _json.dump(parsed, f, indent=2)

        return {"status": "ok"}

    @app.delete("/api/config/google")
    async def delete_google_credentials():
        """Remove Google credentials and token (disconnect)."""
        from openacm.core.config import _find_project_root
        root = _find_project_root()
        for fname in ("google_credentials.json", "google_token.json"):
            p = root / "config" / fname
            if p.exists():
                p.unlink()
        # Clear cached credentials in the tools module too
        try:
            import openacm.tools.google_services as _gs
            _gs._credentials_cache = None
        except Exception:
            pass
        return {"status": "ok"}

    @app.post("/api/config/google/start_auth")
    async def start_google_auth(request: Request):
        """
        Begin the OAuth2 authorization flow.
        Returns the Google authorization URL to open in a browser tab.
        The redirect_uri points back to this server's /api/config/google/callback endpoint.
        """
        from openacm.core.config import _find_project_root
        SCOPES = [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/youtube.readonly",
        ]
        try:
            from google_auth_oauthlib.flow import Flow
        except ImportError:
            raise HTTPException(status_code=500, detail="google-auth-oauthlib not installed. Run: pip install -e .")

        root = _find_project_root()
        creds_path = root / "config" / "google_credentials.json"
        if not creds_path.exists():
            raise HTTPException(status_code=400, detail="Upload google_credentials.json first")

        port = _config.web.port if _config else 47821
        redirect_uri = f"http://localhost:{port}/api/config/google/callback"

        flow = Flow.from_client_secrets_file(
            str(creds_path),
            scopes=SCOPES,
            redirect_uri=redirect_uri,
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        _google_oauth_flows[state] = flow
        return {"url": auth_url, "state": state}

    @app.get("/api/config/google/callback")
    async def google_oauth_callback(request: Request):
        """
        Receives the OAuth2 callback from Google after the user authorizes.
        Exchanges the authorization code for tokens and saves them.
        Returns a friendly HTML page so the user can close the tab.
        """
        from openacm.core.config import _find_project_root
        state = request.query_params.get("state", "")
        code = request.query_params.get("code", "")
        error = request.query_params.get("error", "")

        if error:
            return HTMLResponse(f"""
            <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f172a;color:#f87171">
            <h2>❌ Google Authorization Failed</h2>
            <p>{error}</p>
            <p>You can close this tab.</p>
            </body></html>""")

        flow = _google_oauth_flows.pop(state, None)
        if not flow:
            return HTMLResponse("""
            <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f172a;color:#f87171">
            <h2>❌ Invalid or expired authorization session</h2>
            <p>Please try again from the OpenACM settings.</p>
            <p>You can close this tab.</p>
            </body></html>""")

        try:
            flow.fetch_token(code=code)
            creds = flow.credentials

            root = _find_project_root()
            token_path = root / "config" / "google_token.json"
            token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

            # Invalidate the in-memory credentials cache so next call reloads
            try:
                import openacm.tools.google_services as _gs
                _gs._credentials_cache = None
            except Exception:
                pass

            log.info("Google OAuth2 token saved successfully")
        except Exception as e:
            log.error("Google OAuth2 token exchange failed", error=str(e))
            return HTMLResponse(f"""
            <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f172a;color:#f87171">
            <h2>❌ Token Exchange Failed</h2>
            <p>{e}</p>
            <p>You can close this tab.</p>
            </body></html>""")

        return HTMLResponse("""
        <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f172a;color:#34d399">
        <h2>✅ Google Connected Successfully!</h2>
        <p style="color:#94a3b8">Gmail, Calendar, Drive and YouTube are now available.</p>
        <p style="color:#64748b">You can close this tab and return to OpenACM.</p>
        <script>setTimeout(()=>window.close(),3000)</script>
        </body></html>""")

    @app.get("/api/config/providers")
    async def get_provider_status():
        """Return boolean status for each LLM provider (no keys exposed)."""
        providers = _get_provider_status()
        telegram_configured = _is_real_key("TELEGRAM_TOKEN")
        stitch_configured = _is_real_key("STITCH_API_KEY")
        return {"providers": providers, "telegram_configured": telegram_configured, "stitch_configured": stitch_configured}

    @app.post("/api/config/setup")
    async def post_config_setup(request: Request):
        """Update API keys in .env and memory."""
        data = await request.json()
        from dotenv import set_key

        env_path = _find_env_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure the file exists (set_key requires it)
        if not env_path.exists():
            env_path.touch()

        updated = []
        for key, value in data.items():
            if value and isinstance(value, str):
                safe_key = key.upper()
                set_key(str(env_path), safe_key, value)
                os.environ[safe_key] = value
                updated.append(safe_key)

        # Restart Telegram bot if its token was updated
        if "TELEGRAM_TOKEN" in updated:
            from openacm.channels.telegram_channel import TelegramChannel

            new_token = os.environ.get("TELEGRAM_TOKEN", "")

            # Stop and remove ALL existing Telegram channel instances first
            # (prevents stale duplicates accumulating across wizard re-runs)
            existing = [ch for ch in _channels if isinstance(ch, TelegramChannel)]
            for ch in existing:
                asyncio.create_task(ch.stop())
                _channels.remove(ch)

            # Create a fresh channel with the new token
            if _config and _brain and _event_bus and new_token:
                _config.channels.telegram.enabled = True
                _config.channels.telegram.token = new_token
                ch = TelegramChannel(
                    _config.channels.telegram, _brain, _event_bus, _database
                )
                _channels.append(ch)
                asyncio.create_task(ch.start())
                log.info("Telegram bot (re)created with updated token")

        return {"status": "ok", "updated": updated}

    # ─── Custom Providers CRUD ────────────────────────────────

    @app.get("/api/config/custom_providers")
    async def get_custom_providers_list():
        """List user-defined custom OpenAI-compatible providers (api_key masked)."""
        providers = _load_custom_providers()
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "base_url": p["base_url"],
                "default_model": p.get("default_model", ""),
                "suggested_models": p.get("suggested_models", []),
                "has_key": bool(p.get("api_key", "")),
            }
            for p in providers
        ]

    @app.post("/api/config/custom_providers")
    async def add_custom_provider(request: Request):
        """Add a new custom OpenAI-compatible provider."""
        data = await request.json()
        name = (data.get("name") or "").strip()
        base_url = (data.get("base_url") or "").strip()
        if not name or not base_url:
            raise HTTPException(status_code=400, detail="name and base_url are required")

        providers = _load_custom_providers()
        pid = _make_provider_id(name, providers)
        provider = {
            "id": pid,
            "name": name,
            "base_url": base_url.rstrip("/"),
            "api_key": (data.get("api_key") or "").strip(),
            "default_model": (data.get("default_model") or "").strip(),
            "suggested_models": data.get("suggested_models") or [],
        }
        providers.append(provider)
        _save_custom_providers(providers)
        _apply_custom_providers([provider])
        log.info("Custom provider added", id=pid, name=name)
        return {"status": "ok", "id": pid}

    @app.put("/api/config/custom_providers/{provider_id}")
    async def update_custom_provider(provider_id: str, request: Request):
        """Update an existing custom provider."""
        data = await request.json()
        providers = _load_custom_providers()
        for i, p in enumerate(providers):
            if p["id"] == provider_id:
                if "name" in data:
                    p["name"] = data["name"].strip()
                if "base_url" in data:
                    p["base_url"] = data["base_url"].strip().rstrip("/")
                if data.get("api_key"):
                    p["api_key"] = data["api_key"].strip()
                if "default_model" in data:
                    p["default_model"] = data["default_model"].strip()
                if "suggested_models" in data:
                    p["suggested_models"] = data["suggested_models"]
                providers[i] = p
                _save_custom_providers(providers)
                _apply_custom_providers([p])
                return {"status": "ok"}
        raise HTTPException(status_code=404, detail="Provider not found")

    @app.delete("/api/config/custom_providers/{provider_id}")
    async def delete_custom_provider(provider_id: str):
        """Remove a custom provider."""
        global _custom_provider_ids
        providers = _load_custom_providers()
        new_providers = [p for p in providers if p["id"] != provider_id]
        if len(new_providers) == len(providers):
            raise HTTPException(status_code=404, detail="Provider not found")
        _save_custom_providers(new_providers)
        _custom_provider_ids.discard(provider_id)
        if _config and provider_id in _config.llm.providers:
            del _config.llm.providers[provider_id]
        env_key = f"{provider_id.upper()}_API_KEY"
        os.environ.pop(env_key, None)
        log.info("Custom provider deleted", id=provider_id)
        return {"status": "ok"}

    @app.get("/api/config/local_router")
    async def get_local_router_config():
        """Get LocalRouter configuration and live stats."""
        if not _brain:
            return {"enabled": False}
        stats = _brain.local_router.get_stats()
        return {
            "enabled": not _brain.local_router.observation_mode,
            "observation_mode": _brain.local_router.observation_mode,
            "confidence_threshold": _brain.local_router.confidence_threshold,
            **stats,
        }

    @app.post("/api/config/local_router")
    async def set_local_router_config(request: Request):
        """Update LocalRouter settings at runtime (no restart needed)."""
        if not _brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        data = await request.json()
        if "enabled" in data:
            _brain.local_router.observation_mode = not bool(data["enabled"])
        if "confidence_threshold" in data:
            val = float(data["confidence_threshold"])
            if 0.5 <= val <= 1.0:
                _brain.local_router.confidence_threshold = val
        return {
            "status": "ok",
            "enabled": not _brain.local_router.observation_mode,
            "confidence_threshold": _brain.local_router.confidence_threshold,
        }

    # ─── Code Resurrection API ────────────────────────────────

    @app.get("/api/config/resurrection_paths")
    async def get_resurrection_paths():
        """Get current Code Resurrection paths and watcher status."""
        if not _config:
            return {"paths": [], "indexed_files": 0}
        paths = list(getattr(_config, "resurrection_paths", []))
        # Read progress from state file
        indexed_count = 0
        try:
            state_file = Path("data/resurrection_state.json")
            if state_file.exists():
                with open(state_file, "r") as f:
                    indexed_count = len(json.load(f))
        except Exception:
            pass
        return {"paths": paths, "indexed_files": indexed_count}

    @app.post("/api/config/resurrection_paths")
    async def add_resurrection_path_api(request: Request):
        """Add a path to Code Resurrection."""
        if not _config:
            raise HTTPException(status_code=503, detail="Config not available")
        data = await request.json()
        new_path = data.get("path", "").strip()
        if not new_path:
            raise HTTPException(status_code=400, detail="path is required")
        p = Path(new_path).resolve()
        if not p.exists() or not p.is_dir():
            raise HTTPException(status_code=400, detail=f"Path does not exist or is not a directory: {new_path}")
        str_path = str(p)
        if str_path not in _config.resurrection_paths:
            _config.resurrection_paths.append(str_path)
            # Persist to YAML
            try:
                from openacm.core.config import _find_project_root
                import yaml
                config_file = _find_project_root() / "config" / "default.yaml"
                cfg_data = {}
                if config_file.exists():
                    with open(config_file, "r", encoding="utf-8") as f:
                        cfg_data = yaml.safe_load(f) or {}
                cfg_data["resurrection_paths"] = list(_config.resurrection_paths)
                config_file.parent.mkdir(parents=True, exist_ok=True)
                with open(config_file, "w", encoding="utf-8") as f:
                    yaml.safe_dump(cfg_data, f, default_flow_style=False, allow_unicode=True)
            except Exception as e:
                log.warning("Failed to persist resurrection paths", error=str(e))
        return {"paths": list(_config.resurrection_paths)}

    @app.delete("/api/config/resurrection_paths")
    async def remove_resurrection_path_api(request: Request):
        """Remove a path from Code Resurrection."""
        if not _config:
            raise HTTPException(status_code=503, detail="Config not available")
        data = await request.json()
        rm_path = data.get("path", "").strip()
        if not rm_path:
            raise HTTPException(status_code=400, detail="path is required")
        _config.resurrection_paths = [p for p in _config.resurrection_paths if p != rm_path]
        # Persist to YAML
        try:
            from openacm.core.config import _find_project_root
            import yaml
            config_file = _find_project_root() / "config" / "default.yaml"
            cfg_data = {}
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg_data = yaml.safe_load(f) or {}
            cfg_data["resurrection_paths"] = list(_config.resurrection_paths)
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg_data, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            log.warning("Failed to persist resurrection paths", error=str(e))
        return {"paths": list(_config.resurrection_paths)}

    @app.post("/api/config/verbose_channels")
    async def set_verbose_channels(request: Request):
        """Set whether external channels receive tool execution logs."""
        data = await request.json()
        enabled = data.get("enabled", True)
        os.environ["OPENACM_VERBOSE_CHANNELS"] = "true" if enabled else "false"
        return {"status": "ok", "enabled": enabled}

    @app.get("/api/ollama/status")
    async def get_ollama_status():
        """Check if Ollama is running and return installed models."""
        import httpx
        base = "http://localhost:11434"
        if _config:
            base = _config.llm.providers.get("ollama", {}).get("base_url", base)
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{base}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return {"running": True, "models": models}
        except Exception:
            pass
        return {"running": False, "models": []}

    @app.get("/api/cli/status")
    async def get_cli_status(binary: str = "claude"):
        """Check if a CLI binary is installed and on PATH."""
        import shutil
        available = shutil.which(binary) is not None
        return {"binary": binary, "available": available}

    _DEBUG_MODE_FILE = Path("data/debug_mode")

    def _read_debug_mode() -> bool:
        try:
            return _DEBUG_MODE_FILE.read_text().strip() == "true"
        except Exception:
            return False

    def _write_debug_mode(enabled: bool):
        _DEBUG_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DEBUG_MODE_FILE.write_text("true" if enabled else "false")

    def _apply_debug_mode(enabled: bool):
        import logging as _logging
        level = _logging.DEBUG if enabled else _logging.INFO
        root = _logging.getLogger()
        root.setLevel(level)
        # Must also update all handlers — they filter independently
        for handler in root.handlers:
            handler.setLevel(level)
        for name in ("openacm", "uvicorn", "fastapi"):
            _logging.getLogger(name).setLevel(level)

    @app.get("/api/config/debug_mode")
    async def get_debug_mode():
        """Return current debug mode state."""
        return {"enabled": _read_debug_mode()}

    @app.post("/api/config/debug_mode")
    async def set_debug_mode(request: Request):
        """Toggle debug mode — enables DEBUG-level logging when ON."""
        data = await request.json()
        enabled = bool(data.get("enabled", False))
        _write_debug_mode(enabled)
        _apply_debug_mode(enabled)
        log.info("Debug mode changed", enabled=enabled, log_level="DEBUG" if enabled else "INFO")
        return {"status": "ok", "enabled": enabled}

    # ─── API: Media & Uploads ─────────────────────────────────

    @app.post("/api/chat/upload")
    async def upload_media(file: UploadFile = File(...)):
        """Upload a media file (plain, no encryption)."""
        file_bytes = await file.read()

        from openacm.security.crypto import get_media_dir
        ext = "".join(Path(file.filename).suffixes) or ".bin"
        file_id = secrets.token_hex(16)
        file_name = f"{file_id}{ext}"
        dest_path = get_media_dir() / file_name
        dest_path.write_bytes(file_bytes)

        return {
            "file_id": file_name,
            "filename": file.filename,
            "size": len(file_bytes),
            "content_type": file.content_type,
        }

    @app.get("/api/media")
    async def list_media():
        """List all files in data/media/ for the dashboard file browser."""
        import datetime
        from openacm.security.crypto import get_media_dir
        media_dir = get_media_dir()
        files = []
        for f in sorted(media_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file():
                stat = f.stat()
                files.append({
                    "name": f.name,
                    "size": stat.st_size,
                    "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "ext": f.suffix.lower(),
                })
        return files

    @app.get("/api/media/{file_name}")
    async def get_media(file_name: str, download: bool = False):
        """Retrieve a media file. Handles legacy Fernet-encrypted files transparently."""
        from openacm.security.crypto import decrypt_file, get_media_dir

        file_path = get_media_dir() / file_name
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Media not found")

        try:
            file_bytes = decrypt_file(file_path)
        except Exception:
            raise HTTPException(status_code=500, detail="Could not read file")

        ext = file_path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
            ".mp3": "audio/mpeg",
            ".mp4": "video/mp4",
            ".glb": "model/gltf-binary",
            ".gltf": "model/gltf+json",
            ".obj": "text/plain",
            ".stl": "model/stl",
            ".blend": "application/octet-stream",
            ".txt": "text/plain",
            ".json": "application/json",
            ".html": "text/html",
            ".htm": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".jsx": "application/javascript",
            ".vue": "text/plain",
            ".svg": "image/svg+xml",
        }
        content_type = mime_map.get(ext, "application/octet-stream")

        # Files that render inline in the browser (no forced download)
        inline_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".mp4", ".html", ".htm", ".svg"}
        headers = {}
        if download or ext not in inline_exts:
            headers["Content-Disposition"] = f'attachment; filename="{file_name}"'

        return Response(content=file_bytes, media_type=content_type, headers=headers)

    @app.get("/api/config/available_models")
    async def get_available_models():
        """Fetch available models from the current provider's API."""
        if not _brain or not _config:
            return []

        provider = _brain.llm_router._current_provider
        settings = _config.llm.providers.get(provider, {})
        base_url = settings.get("base_url")

        import os

        api_key_env = f"{provider.upper()}_API_KEY"
        api_key = os.environ.get(api_key_env, "")

        if provider == "openai" and not base_url:
            base_url = "https://api.openai.com/v1"
        elif provider == "ollama" and not base_url:
            base_url = "http://localhost:11434/v1"

        if not base_url:
            return []

        models_url = f"{base_url.rstrip('/')}/models"

        try:
            import httpx

            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            async with httpx.AsyncClient() as client:
                resp = await client.get(models_url, headers=headers, timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    models = []
                    # Handle OpenAI format
                    if "data" in data and isinstance(data["data"], list):
                        models = [m["id"] for m in data["data"] if "id" in m]
                    # Handle Ollama format
                    elif "models" in data and isinstance(data["models"], list):
                        models = [m.get("name", m.get("model")) for m in data["models"]]

                    models = list(filter(bool, models))
                    models.sort()
                    return models
                return []
        except Exception as e:
            log.error("Failed to fetch available models", error=str(e))
            return []

    @app.post("/api/config/model")
    async def set_model(request: Request):
        """Change the LLM model and optionally the provider."""
        data = await request.json()
        model = data.get("model", "")
        provider = data.get("provider", None)
        if model and _brain:
            _brain.llm_router.set_model(model, provider=provider)
            # Persist model choice to database
            if _database:
                await _database.set_setting("llm.current_model", _brain.llm_router.current_model)
                await _database.set_setting("llm.current_provider", _brain.llm_router._current_provider)
            return {
                "status": "ok",
                "model": _brain.llm_router.current_model,
                "provider": _brain.llm_router._current_provider,
            }
        return {"status": "error", "message": "No model specified"}

    # ─── API: Conversations ───────────────────────────────────

    @app.get("/api/conversations")
    async def get_conversations():
        """Get recent conversations."""
        if not _database:
            return []
        stats = await _database.get_channel_stats()
        # Map DB field names to what the frontend expects
        for row in stats:
            if "last_updated" in row and "last_timestamp" not in row:
                row["last_timestamp"] = row.pop("last_updated")
            if "title" not in row:
                row["title"] = f"{row.get('channel_id', '')} - {row.get('user_id', '')}"
        return stats

    @app.get("/api/conversations/{channel_id}/{user_id}")
    async def get_conversation(channel_id: str, user_id: str, limit: int = 50):
        """Get conversation history."""
        if not _database:
            return []
        return await _database.get_conversation(user_id, channel_id, limit)

    @app.delete("/api/conversations/{channel_id}/{user_id}")
    async def delete_conversation(channel_id: str, user_id: str):
        """Delete conversation history for a user/channel pair (memory + database)."""
        if not _brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        # Clear in-memory cache
        await _brain.memory.clear(user_id, channel_id)
        # Delete from database so it doesn't reload on next access
        deleted_rows = 0
        if _database:
            deleted_rows = await _database.delete_conversation_messages(user_id, channel_id)
        return {"status": "ok", "deleted_rows": deleted_rows}

    # ─── API: Commands ────────────────────────────────────────

    @app.post("/api/chat/command")
    async def run_command(request: Request):
        """Execute a slash command via REST (used by dashboard buttons)."""
        if not _command_processor:
            raise HTTPException(status_code=503, detail="Command processor not available")
        data = await request.json()
        command = data.get("command", "").strip()
        user_id = data.get("user_id", "web")
        channel_id = data.get("channel_id", "web")

        if not command:
            raise HTTPException(status_code=400, detail="No command provided")

        parts = command.split(maxsplit=1)
        cmd = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        result = await _command_processor.handle(cmd, args, user_id, channel_id)
        if not result.handled:
            return {"text": f"Unknown command: {cmd}", "data": None}
        return {"text": result.text, "data": result.data}

    # ─── WebSocket: Chat ──────────────────────────────────────

    @app.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket):
        """WebSocket endpoint for real-time chat from the dashboard."""
        if not _verify_ws_token(websocket):
            await websocket.close(code=4001, reason="Unauthorized")
            return
        await websocket.accept()
        
        # Auto-trigger Onboarding Greeting if disabled (even for existing users)
        # Note: at connect time we don't have the explicit target channel from the JSON payload, 
        # so we assume the default 'web' context.
        session_key = "web-web"
        if not _onboarding_triggered_flags.get(session_key, False):
            if _config and getattr(_config.assistant, "onboarding_completed", False) is False:
                _onboarding_triggered_flags[session_key] = True
                if _brain and _database:
                    async def _trigger_onboarding_greeting():
                        try:
                            # Determine if user is completely new or if this is a post-update flow
                            hist = await _database.get_conversation(target_user, target_channel, limit=1)
                            is_new_user = len(hist) == 0
                            
                            if is_new_user:
                                prompt_text = "[SYSTEM]: The user just booted you up for the very first time. Step into character: you are an advanced AI entity awakening on their local machine. Introduce yourself with a touch of narrative 'lore' (e.g., systems initializing, neural pathways connecting). Explain that to finalize synchronization, you need to establish 3 core parameters. Ask them ONLY the FIRST question for now: What is their designation/name? Wait for their response before asking the next."
                            else:
                                prompt_text = "[SYSTEM]: Start the Onboarding interview NOW. Step into character: tell the user that a recent major system architecture update has scrambled your core identity matrix. To re-synchronize, you need to recalibrate your behavioral invariants in 3 steps. Ask them ONLY the FIRST question for now: What is their designation/name? Wait for their response before asking the next."

                            # Let the frontend mount before sending the message
                            await asyncio.sleep(1.0)
                            response = await _brain.process_message(
                                content=prompt_text,
                                user_id=target_user,
                                channel_id=target_channel,
                                channel_type=target_type,
                                is_transparent=True
                            )
                            from fastapi.websockets import WebSocketState
                            if websocket.client_state == WebSocketState.CONNECTED:
                                await websocket.send_json({
                                    "type": "response",
                                    "content": response,
                                    "attachments": [],
                                    "usage": {}
                                })
                        except Exception as e:
                            log.error("Failed to auto-trigger onboarding greeting", error=str(e))
                    
                    asyncio.create_task(_trigger_onboarding_greeting())

        try:
            while True:
                data = await websocket.receive_json()
                content = data.get("message", "")
                attachments = data.get("attachments", [])

                # Context routing (defaults to web)
                target_user = data.get("target_user_id", "web")
                target_channel = data.get("target_channel_id", "web")
                target_type = (
                    "web"
                    if target_channel == "web"
                    else target_channel.split("-")[0]
                    if "-" in target_channel
                    else "telegram"
                )

                # Cancel request — forward a cancel keyword to the brain
                if data.get("type") == "cancel":
                    if _brain:
                        asyncio.create_task(_brain.process_message(
                            content="cancelar",
                            user_id=target_user,
                            channel_id=target_channel,
                            channel_type=target_type,
                        ))
                    continue

                if not content and not attachments:
                    continue

                # Intercept slash commands before sending to brain
                if content.startswith("/") and _command_processor:
                    parts = content.split(maxsplit=1)
                    cmd = parts[0]
                    args = parts[1] if len(parts) > 1 else ""
                    result = await _command_processor.handle(
                        cmd, args, target_user, target_channel
                    )
                    if result.handled:
                        try:
                            await websocket.send_json({
                                "type": "command",
                                "content": result.text,
                                "data": result.data,
                            })
                        except (WebSocketDisconnect, Exception):
                            return
                        continue

                if _brain:
                    try:
                        # Snapshot usage counters before the call to compute per-turn delta
                        _router = _brain.llm_router if _brain else None
                        usage_before = _router.get_usage_snapshot() if _router else {}

                        response = await _brain.process_message(
                            content=content,
                            user_id=target_user,
                            channel_id=target_channel,
                            channel_type=target_type,
                            attachments=attachments,
                        )

                        # Compute usage delta for this turn
                        turn_usage: dict = {}
                        if _router:
                            usage_after = _router.get_usage_snapshot()
                            turn_usage = {
                                "prompt_tokens": usage_after["prompt_tokens"] - usage_before.get("prompt_tokens", 0),
                                "completion_tokens": usage_after["completion_tokens"] - usage_before.get("completion_tokens", 0),
                                "total_tokens": usage_after["total_tokens"] - usage_before.get("total_tokens", 0),
                                "cost": round(usage_after["cost"] - usage_before.get("cost", 0.0), 6),
                                "requests": usage_after["requests"] - usage_before.get("requests", 0),
                                "model": _router.current_model or "",
                            }

                        # Strip ATTACHMENT: lines from visible content and send as structured array
                        resp_lines = response.split("\n")
                        attachment_names: list[str] = []
                        clean_lines: list[str] = []
                        for line in resp_lines:
                            if line.startswith("ATTACHMENT:"):
                                fname = line[len("ATTACHMENT:"):].strip()
                                if fname:
                                    attachment_names.append(fname)
                            else:
                                clean_lines.append(line)
                        clean_response = "\n".join(clean_lines).strip()

                        await websocket.send_json(
                            {
                                "type": "response",
                                "content": clean_response,
                                "attachments": attachment_names,
                                "usage": turn_usage,
                            }
                        )
                    except WebSocketDisconnect:
                        return
                    except Exception as e:
                        try:
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "content": str(e),
                                }
                            )
                        except (WebSocketDisconnect, Exception):
                            # Client already gone — nothing to do
                            return
                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "content": "Brain not available",
                        }
                    )
        except WebSocketDisconnect:
            pass

    # ─── WebSocket: Terminal ─────────────────────────────────

    @app.websocket("/ws/terminal")
    async def ws_terminal(websocket: WebSocket):
        """WebSocket endpoint for interactive terminal sessions — one persistent PTY per channel."""
        import json as _json

        if not _verify_ws_token(websocket):
            await websocket.close(code=4001, reason="Unauthorized")
            return

        channel_id = websocket.query_params.get("channel", "web")
        await websocket.accept()

        # Get or create the persistent PTY shell for this channel
        shell = _channel_shells.get(channel_id)
        if not shell or not shell._alive:
            shell = ChannelShell(channel_id)
            try:
                await shell.start()
            except Exception as e:
                log.error("Failed to start PTY shell", channel=channel_id, error=str(e))
                await websocket.send_json({"type": "error", "data": f"Failed to start shell: {e}"})
                await websocket.close()
                return
            _channel_shells[channel_id] = shell

        shell.clients.add(websocket)

        # Prod the shell so the current prompt re-appears in the freshly connected xterm
        asyncio.create_task(shell.write("\r\n"))

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = _json.loads(raw)
                except _json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                if msg_type == "input":
                    data = msg.get("data", "")
                    await shell.write(data)
                    # Track printable commands in brain history
                    if _brain and hasattr(_brain, "terminal_history"):
                        cmd_clean = data.strip()
                        if cmd_clean and cmd_clean != "\n" and len(cmd_clean) > 1:
                            if _brain.terminal_history:
                                _brain.terminal_history[-1]["_closed"] = True
                            _brain.terminal_history.append({
                                "command": cmd_clean, "output": "", "_closed": False,
                            })
                            if len(_brain.terminal_history) > 30:
                                _brain.terminal_history[:] = _brain.terminal_history[-30:]

                elif msg_type == "signal":
                    # Ctrl+C
                    await shell.write("\x03")

                elif msg_type == "resize":
                    cols = int(msg.get("cols", 220))
                    rows = int(msg.get("rows", 50))
                    shell.resize(cols, rows)

        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.error("Terminal WebSocket error", channel=channel_id, error=str(e))
        finally:
            # Detach client — shell stays alive for the channel
            shell.clients.discard(websocket)

    # ─── WebSocket: Events ────────────────────────────────────

    @app.websocket("/ws/events")
    async def ws_events(websocket: WebSocket):
        """WebSocket endpoint for real-time events stream."""
        if not _verify_ws_token(websocket):
            await websocket.close(code=4001, reason="Unauthorized")
            return
        await websocket.accept()
        _ws_clients.add(websocket)

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            _ws_clients.discard(websocket)

    # ─── API: Terminal ─────────────────────────────────────────

    @app.get("/api/terminal/history")
    async def get_terminal_history():
        """Get recent terminal command history (used by AI as context)."""
        if not _brain:
            return []
        history = [
            {"command": e.get("command", ""), "output": e.get("output", "")[:500]}
            for e in _brain.terminal_history[-20:]
            if e.get("command")
        ]
        return history

    # ─── API: Skills ──────────────────────────────────────────

    @app.get("/api/skills")
    async def get_skills():
        """Get all skills with their status."""
        if not _brain or not _brain.skill_manager:
            return []
        skills = await _brain.skill_manager.get_all_skills()
        return skills

    @app.get("/api/skills/active")
    async def get_active_skills():
        """Get only active skills."""
        if not _brain or not _brain.skill_manager:
            return []
        skills = await _brain.skill_manager.get_all_skills()
        return [s for s in skills if s.get("is_active")]

    @app.post("/api/skills")
    async def create_skill(request: Request):
        """Create a new skill."""
        if not _brain or not _brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        data = await request.json()
        skill = await _brain.skill_manager.create_skill(
            name=data["name"],
            description=data["description"],
            content=data["content"],
            category=data.get("category", "custom"),
        )
        return skill

    @app.post("/api/skills/{skill_id}/toggle")
    async def toggle_skill(skill_id: int):
        """Toggle skill active status."""
        if not _brain or not _brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        result = await _brain.skill_manager.toggle_skill(skill_id)
        if not result:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"status": "ok", "toggled": True}

    @app.put("/api/skills/{skill_id}")
    async def update_skill(skill_id: int, request: Request):
        """Update a skill."""
        if not _brain or not _brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        data = await request.json()
        result = await _brain.skill_manager.update_skill(
            skill_id,
            description=data.get("description"),
            content=data.get("content"),
            category=data.get("category"),
        )
        if not result:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"status": "ok", "updated": True}

    @app.delete("/api/skills/{skill_id}")
    async def delete_skill(skill_id: int):
        """Delete a custom skill."""
        if not _brain or not _brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        result = await _brain.skill_manager.delete_skill(skill_id)
        if not result:
            raise HTTPException(status_code=404, detail="Skill not found or is built-in")
        return {"status": "ok", "deleted": True}

    @app.post("/api/skills/generate")
    async def generate_skill(request: Request):
        """Generate a new skill using LLM."""
        if not _brain or not _brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        data = await request.json()
        try:
            skill = await _brain.skill_manager.generate_skill(
                name=data["name"],
                description=data["description"],
                use_cases=data.get("use_cases", ""),
                llm_router=_brain.llm_router,
            )
            return skill
        except Exception as e:
            log.error("Failed to generate skill", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))

    # ─── API: Agents ──────────────────────────────────────────

    def _agent_public(agent: dict) -> dict:
        """Strip webhook_secret from agent dict before sending to frontend."""
        a = dict(agent)
        a.pop("webhook_secret", None)
        return a

    @app.get("/api/agents")
    async def get_agents():
        """List all agents."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        agents = await _database.get_all_agents()
        return [_agent_public(a) for a in agents]

    @app.post("/api/agents")
    async def create_agent(request: Request):
        """Create a new agent."""
        import secrets as _secrets
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        if not data.get("name") or not data.get("system_prompt"):
            raise HTTPException(status_code=400, detail="name and system_prompt required")
        agent_id = await _database.create_agent(
            name=data["name"],
            description=data.get("description", ""),
            system_prompt=data["system_prompt"],
            allowed_tools=data.get("allowed_tools", "all"),
            webhook_secret=_secrets.token_urlsafe(32),
            telegram_token=data.get("telegram_token", ""),
        )
        agent = await _database.get_agent(agent_id)
        # Start Telegram bot if token provided
        if _agent_bot_manager and agent.get("telegram_token", "").strip():
            import asyncio as _asyncio
            _asyncio.create_task(_agent_bot_manager.start_bot(agent))
        return agent  # include secret on creation so user can copy it

    @app.get("/api/agents/{agent_id}")
    async def get_agent(agent_id: int):
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return _agent_public(agent)

    @app.put("/api/agents/{agent_id}")
    async def update_agent(agent_id: int, request: Request):
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        allowed_fields = {"name", "description", "system_prompt", "allowed_tools", "is_active", "telegram_token"}
        kwargs = {k: v for k, v in data.items() if k in allowed_fields}
        ok = await _database.update_agent(agent_id, **kwargs)
        if not ok:
            raise HTTPException(status_code=404, detail="Agent not found")
        agent = await _database.get_agent(agent_id)
        # Restart bot if telegram_token was part of the update
        if _agent_bot_manager and ("telegram_token" in kwargs or "is_active" in kwargs):
            import asyncio as _asyncio
            _asyncio.create_task(_agent_bot_manager.restart_bot(agent_id))
        return _agent_public(agent)

    @app.delete("/api/agents/{agent_id}")
    async def delete_agent(agent_id: int):
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        # Stop bot before deleting
        if _agent_bot_manager:
            import asyncio as _asyncio
            _asyncio.create_task(_agent_bot_manager.stop_bot(agent_id))
        ok = await _database.delete_agent(agent_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {"status": "ok", "deleted": True}

    @app.get("/api/agents/{agent_id}/secret")
    async def get_agent_secret(agent_id: int):
        """Return the webhook secret (used once after creation)."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {"webhook_secret": agent["webhook_secret"]}

    @app.post("/api/agents/{agent_id}/chat")
    async def agent_webhook(agent_id: int, request: Request):
        """
        Public webhook — send a message to an agent and get a response.

        Required header: X-Agent-Secret: <webhook_secret>
        Body: { "message": "...", "user_id": "anonymous" }
        """
        if not _database or not _brain:
            raise HTTPException(status_code=503, detail="Service not ready")

        agent = await _database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if not agent.get("is_active"):
            raise HTTPException(status_code=403, detail="Agent is disabled")

        # Verify secret
        secret = request.headers.get("X-Agent-Secret", "")
        if secret != agent["webhook_secret"]:
            raise HTTPException(status_code=401, detail="Invalid agent secret")

        data = await request.json()
        message = data.get("message", "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message required")
        user_id = data.get("user_id", "webhook_user")

        from openacm.core.agent_runner import AgentRunner
        runner = AgentRunner(
            llm_router=_brain.llm_router,
            tool_registry=_brain.tool_registry,
            memory=_brain.memory,
            event_bus=_brain.event_bus,
        )
        response = await runner.run(agent=agent, message=message, user_id=user_id)
        return {"response": response, "agent": agent["name"]}

    @app.post("/api/agents/generate")
    async def generate_agent(request: Request):
        """
        Use the LLM to generate an agent name, description, and system prompt.

        Accepts multipart/form-data:
          - description: str  (what the agent should do)
          - file: optional PDF / TXT / MD document for extra context
        """
        if not _brain:
            raise HTTPException(status_code=503, detail="Service not ready")

        from fastapi import Form, UploadFile, File as FastAPIFile
        import io

        content_type = request.headers.get("content-type", "")
        description = ""
        doc_text = ""

        if "multipart/form-data" in content_type:
            form = await request.form()
            description = str(form.get("description", "")).strip()
            # Support multiple files: fields named "file", "file0", "file1", … or repeated "file"
            file_fields = form.getlist("file") if hasattr(form, "getlist") else []
            if not file_fields:
                single = form.get("file")
                if single:
                    file_fields = [single]
            doc_parts: list[str] = []
            for file_field in file_fields:
                if not (file_field and hasattr(file_field, "read")):
                    continue
                raw = await file_field.read()
                fname = getattr(file_field, "filename", "") or ""
                ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                if ext == "pdf":
                    try:
                        import pypdf
                        reader = pypdf.PdfReader(io.BytesIO(raw))
                        pages = [p.extract_text() or "" for p in reader.pages]
                        part = "\n\n".join(p for p in pages if p.strip())
                        doc_parts.append(f"[{fname}]\n{part}")
                    except Exception as e:
                        doc_parts.append(f"[{fname} — PDF extraction error: {e}]")
                elif ext in ("txt", "md", "csv", "yaml", "yml", "json"):
                    doc_parts.append(f"[{fname}]\n{raw.decode('utf-8', errors='replace')}")
            if doc_parts:
                combined = "\n\n---\n\n".join(doc_parts)
                doc_text = combined[:12000]
        else:
            data = await request.json()
            description = str(data.get("description", "")).strip()

        if not description:
            raise HTTPException(status_code=400, detail="description required")

        # Build prompt for generation
        doc_section = (
            f"\n\nADDITIONAL DOCUMENT CONTEXT:\n{doc_text}" if doc_text else ""
        )
        generation_prompt = (
            f"Generate a configuration for an autonomous AI agent based on this description:\n\n"
            f"{description}{doc_section}\n\n"
            f"Return ONLY a valid JSON object with these fields:\n"
            f"- name: short agent name (2-4 words)\n"
            f"- description: one-sentence description\n"
            f"- system_prompt: detailed system prompt with rules, personality, and behavior guidelines "
            f"(be specific and thorough, use the document context if provided)\n\n"
            f"JSON only, no markdown, no explanation."
        )

        try:
            import json as _json
            response = await _brain.llm_router.chat(
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that generates AI agent configurations. Always respond with valid JSON only."},
                    {"role": "user", "content": generation_prompt},
                ],
                tools=None,
            )
            content = response["content"].strip()
            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            generated = _json.loads(content)
            return {
                "name": generated.get("name", "New Agent"),
                "description": generated.get("description", ""),
                "system_prompt": generated.get("system_prompt", ""),
            }
        except Exception as e:
            log.error("Agent generation failed", error=str(e))
            raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    @app.post("/api/agents/{agent_id}/test")
    async def test_agent(agent_id: int, request: Request):
        """Test an agent from the UI (no secret needed, uses dashboard auth)."""
        if not _database or not _brain:
            raise HTTPException(status_code=503, detail="Service not ready")
        agent = await _database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        data = await request.json()
        message = data.get("message", "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message required")

        from openacm.core.agent_runner import AgentRunner
        runner = AgentRunner(
            llm_router=_brain.llm_router,
            tool_registry=_brain.tool_registry,
            memory=_brain.memory,
            event_bus=_brain.event_bus,
        )
        response = await runner.run(agent=agent, message=message, user_id="dashboard_test")
        return {"response": response}

    # ─── API: Debug Traces ───────────────────────────────────

    @app.get("/api/debug/traces")
    async def get_brain_traces(limit: int = 20):
        """Return the last N agentic loop traces for debugging."""
        if not _brain:
            return []
        traces = list(reversed(_brain._traces[-limit:]))
        return traces

    @app.delete("/api/debug/traces")
    async def clear_brain_traces():
        """Clear all stored traces."""
        if _brain:
            _brain._traces.clear()
        return {"status": "ok"}

    # ─── API: MCP Servers ────────────────────────────────────

    @app.get("/api/mcp/servers")
    async def get_mcp_servers():
        """List all configured MCP servers with their connection status."""
        if not _mcp_manager:
            return []
        return _mcp_manager.get_status()

    @app.post("/api/mcp/servers")
    async def add_mcp_server(request: Request):
        """Add (or replace) an MCP server configuration."""
        if not _mcp_manager:
            raise HTTPException(status_code=503, detail="MCP manager not available")
        data = await request.json()
        name = data.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        try:
            cfg = _mcp_manager.add_server(data)
            return {"status": "ok", **cfg.to_dict()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.put("/api/mcp/servers/{server_name}")
    async def update_mcp_server(server_name: str, request: Request):
        """Update an MCP server configuration."""
        if not _mcp_manager:
            raise HTTPException(status_code=503, detail="MCP manager not available")
        data = await request.json()
        try:
            cfg = _mcp_manager.update_server(server_name, data)
            return {"status": "ok", **cfg.to_dict()}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.delete("/api/mcp/servers/{server_name}")
    async def delete_mcp_server(server_name: str):
        """Remove an MCP server configuration (disconnects if active)."""
        if not _mcp_manager:
            raise HTTPException(status_code=503, detail="MCP manager not available")
        _mcp_manager.remove_server(server_name)
        return {"status": "ok", "deleted": server_name}

    @app.post("/api/mcp/servers/{server_name}/connect")
    async def connect_mcp_server(server_name: str):
        """Connect to an MCP server."""
        if not _mcp_manager:
            raise HTTPException(status_code=503, detail="MCP manager not available")
        if server_name not in _mcp_manager.servers:
            raise HTTPException(status_code=404, detail="Server not found")
        conn = await _mcp_manager.connect(server_name)
        return {
            "status": "ok" if conn.connected else "error",
            "connected": conn.connected,
            "error": conn.error,
            "tools": conn.tools,
        }

    @app.post("/api/mcp/servers/{server_name}/disconnect")
    async def disconnect_mcp_server(server_name: str):
        """Disconnect from an MCP server."""
        if not _mcp_manager:
            raise HTTPException(status_code=503, detail="MCP manager not available")
        await _mcp_manager.disconnect(server_name)
        return {"status": "ok", "disconnected": server_name}

    # ─── API: Routines ───────────────────────────────────────

    def _routine_cron_expr(trigger_data: dict) -> str:
        """Build a cron expression from a routine's trigger_data dict.
        Days stored as Python weekday (0=Mon); converted to cron (0=Sun, 1=Mon)."""
        hour = int(trigger_data.get("hour", 9))
        minute = int(trigger_data.get("minute", 0))
        days = trigger_data.get("days_of_week", [])
        if days:
            cron_days = ",".join(str((d + 1) % 7) for d in sorted(days))
            return f"{minute} {hour} * * {cron_days}"
        return f"{minute} {hour} * * *"

    @app.get("/api/routines")
    async def get_routines():
        """List all detected routines."""
        if not _database:
            return []
        return await _database.get_all_routines()

    @app.post("/api/routines/{routine_id}/execute")
    async def execute_routine(routine_id: int):
        """Execute a routine (launch its apps)."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        routine = await _database.get_routine(routine_id)
        if not routine:
            raise HTTPException(status_code=404, detail="Routine not found")
        try:
            from openacm.watchers.routine_executor import RoutineExecutor
            executor = RoutineExecutor()
            results = await executor.execute(routine)
            await _database.record_routine_run(routine_id)
            return {"status": "ok", "results": results}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.put("/api/routines/{routine_id}")
    async def update_routine(routine_id: int, request: Request):
        """Update a routine (name, status, trigger_data, apps).
        Auto-creates or deletes a cron job when the status changes to/from active."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")

        current = await _database.get_routine(routine_id)
        if not current:
            raise HTTPException(status_code=404, detail="Routine not found")

        import json as _json
        data = await request.json()
        allowed = {"name", "status", "trigger_type", "trigger_data", "apps"}
        kwargs = {k: v for k, v in data.items() if k in allowed}
        if "trigger_data" in kwargs and isinstance(kwargs["trigger_data"], dict):
            kwargs["trigger_data"] = _json.dumps(kwargs["trigger_data"])
        if "apps" in kwargs and isinstance(kwargs["apps"], list):
            kwargs["apps"] = _json.dumps(kwargs["apps"])

        ok = await _database.update_routine(routine_id, **kwargs)
        if not ok:
            raise HTTPException(status_code=404, detail="Routine not found")

        updated = await _database.get_routine(routine_id)

        # ── Auto cron management on activate / deactivate ─────────────────────
        new_status = kwargs.get("status", current.get("status"))
        old_status = current.get("status")

        if _cron_scheduler and new_status != old_status:
            if new_status in ("inactive", "pending") and old_status == "active":
                # Delete the cron job that was driving this routine
                existing_cron_id = current.get("cron_job_id")
                if existing_cron_id:
                    await _database.delete_cron_job(int(existing_cron_id))
                    await _database.update_routine(routine_id, cron_job_id=None)
                    await _cron_scheduler._sync_jobs()
                    updated = await _database.get_routine(routine_id)

            elif new_status == "active":
                # Create a cron job if the trigger is time-based
                trigger_type = updated.get("trigger_type", "manual")
                if trigger_type == "time_based":
                    try:
                        trigger_data = _json.loads(updated.get("trigger_data") or "{}")
                        cron_expr = _routine_cron_expr(trigger_data)
                        job = await _database.create_cron_job(
                            name=f"Rutina: {updated.get('name', 'Rutina')}",
                            description=f"Ejecuta automáticamente la rutina #{routine_id}",
                            cron_expr=cron_expr,
                            action_type="run_routine",
                            action_payload={"routine_id": routine_id},
                            is_enabled=True,
                        )
                        if job:
                            await _database.update_routine(routine_id, cron_job_id=job["id"])
                            await _cron_scheduler._sync_jobs()
                            updated = await _database.get_routine(routine_id)
                    except Exception as _exc:
                        log.warning("Failed to create cron job for routine", error=str(_exc))

        return updated

    @app.delete("/api/routines/{routine_id}")
    async def delete_routine(routine_id: int):
        """Delete a routine."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        ok = await _database.delete_routine(routine_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Routine not found")
        return {"status": "ok", "deleted": routine_id}

    @app.post("/api/routines/analyze")
    async def analyze_routines():
        """Trigger pattern analysis and return newly created routines."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        try:
            from openacm.watchers.pattern_analyzer import PatternAnalyzer
            llm = _brain.llm_router if _brain else None
            analyzer = PatternAnalyzer(_database, llm_router=llm)
            new_routines = await analyzer.analyze()
            return {"status": "ok", "new_routines": len(new_routines), "routines": new_routines}
        except Exception as exc:
            log.error("Pattern analysis failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))

    # ─── API: Activity Stats ─────────────────────────────────

    @app.get("/api/activity/stats")
    async def get_activity_stats():
        """Return per-app usage stats, total hours tracked, and session count."""
        if not _database:
            return {"apps": [], "total_hours": 0, "session_count": 0}
        app_stats = await _database.get_app_stats()
        total_hours = await _database.get_activity_hours()
        session_count = await _database.get_activity_count()
        return {
            "apps": app_stats,
            "total_hours": round(total_hours, 2),
            "session_count": session_count,
        }

    @app.get("/api/activity/sessions")
    async def get_recent_sessions(limit: int = 30):
        """Return recent app focus sessions."""
        if not _database:
            return []
        return await _database.get_recent_app_sessions(limit)

    @app.get("/api/watcher/status")
    async def get_watcher_status():
        """Return activity watcher running status and encryption info."""
        encrypted = _database._enc is not None if _database else False
        key_path = _database._enc.key_path if (encrypted and _database) else None
        if _activity_watcher is None:
            return {"running": False, "current_app": None, "sessions_recorded": 0,
                    "encrypted": encrypted, "key_path": key_path}
        return {
            "running": _activity_watcher.is_running,
            "current_app": _activity_watcher.current_app,
            "current_title": _activity_watcher.current_title,
            "sessions_recorded": _activity_watcher.sessions_recorded,
            "encrypted": encrypted,
            "key_path": key_path,
        }

    # ─── API: Cron Scheduler ─────────────────────────────────

    _VALID_ACTION_TYPES = {"run_skill", "run_routine", "analyze_patterns", "custom_command"}

    def _validate_cron_expr(expr: str) -> bool:
        shortcuts = {"@hourly", "@daily", "@midnight", "@weekly", "@monthly"}
        if expr.strip() in shortcuts:
            return True
        return len(expr.strip().split()) == 5

    @app.get("/api/cron/jobs")
    async def list_cron_jobs():
        """List all cron jobs."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        jobs = await _database.get_all_cron_jobs()
        return {"jobs": jobs}

    @app.post("/api/cron/jobs")
    async def create_cron_job(request: Request):
        """Create a new cron job."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        name = data.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        cron_expr = data.get("cron_expr", "").strip()
        if not _validate_cron_expr(cron_expr):
            raise HTTPException(status_code=400, detail="Invalid cron_expr (need 5 fields or @shortcut)")
        action_type = data.get("action_type", "")
        if action_type not in _VALID_ACTION_TYPES:
            raise HTTPException(status_code=400, detail=f"action_type must be one of {_VALID_ACTION_TYPES}")

        from openacm.watchers.cron_scheduler import compute_next_run
        next_run = compute_next_run(cron_expr)

        job = await _database.create_cron_job(
            name=name,
            description=data.get("description", ""),
            cron_expr=cron_expr,
            action_type=action_type,
            action_payload=data.get("action_payload", {}),
            is_enabled=bool(data.get("is_enabled", True)),
            next_run=next_run,
        )
        # Reload scheduler in-memory jobs
        if _cron_scheduler:
            await _cron_scheduler._sync_jobs()
        return job

    @app.get("/api/cron/jobs/{job_id}")
    async def get_cron_job(job_id: int):
        """Get a single cron job."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        job = await _database.get_cron_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Cron job not found")
        return job

    @app.put("/api/cron/jobs/{job_id}")
    async def update_cron_job(job_id: int, request: Request):
        """Update a cron job."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        existing = await _database.get_cron_job(job_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Cron job not found")
        data = await request.json()
        allowed = {"name", "description", "cron_expr", "action_type", "action_payload", "is_enabled"}
        updates = {k: v for k, v in data.items() if k in allowed}

        if "cron_expr" in updates:
            if not _validate_cron_expr(updates["cron_expr"]):
                raise HTTPException(status_code=400, detail="Invalid cron_expr")
            from openacm.watchers.cron_scheduler import compute_next_run
            updates["next_run"] = compute_next_run(updates["cron_expr"])
        if "action_type" in updates and updates["action_type"] not in _VALID_ACTION_TYPES:
            raise HTTPException(status_code=400, detail=f"action_type must be one of {_VALID_ACTION_TYPES}")

        await _database.update_cron_job(job_id, **updates)
        if _cron_scheduler:
            await _cron_scheduler._sync_jobs()
        return await _database.get_cron_job(job_id)

    @app.delete("/api/cron/jobs/{job_id}")
    async def delete_cron_job(job_id: int):
        """Delete a cron job."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        ok = await _database.delete_cron_job(job_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Cron job not found")
        if _cron_scheduler:
            await _cron_scheduler._sync_jobs()
        return {"status": "ok", "deleted": job_id}

    @app.post("/api/cron/jobs/{job_id}/trigger")
    async def trigger_cron_job(job_id: int):
        """Immediately trigger a cron job."""
        if not _cron_scheduler:
            raise HTTPException(status_code=503, detail="Cron scheduler not running")
        result = await _cron_scheduler.trigger_now(job_id)
        return result

    @app.post("/api/cron/jobs/{job_id}/toggle")
    async def toggle_cron_job(job_id: int):
        """Toggle a cron job enabled/disabled."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        job = await _database.get_cron_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Cron job not found")
        new_state = not bool(job.get("is_enabled", 1))
        await _database.update_cron_job(job_id, is_enabled=new_state)
        if _cron_scheduler:
            await _cron_scheduler._sync_jobs()
        return {"status": "ok", "is_enabled": new_state}

    @app.get("/api/cron/runs")
    async def get_cron_runs(job_id: int | None = None, limit: int = 50):
        """Get cron job run history."""
        if not _database:
            raise HTTPException(status_code=503, detail="Database not available")
        runs = await _database.get_cron_runs(job_id=job_id, limit=min(limit, 200))
        return {"runs": runs}

    @app.get("/api/cron/status")
    async def get_cron_status():
        """Return scheduler running status and job summary."""
        if _cron_scheduler is None:
            return {"running": False, "job_count": 0, "enabled_count": 0,
                    "next_job_name": None, "next_job_at": None}
        jobs = list(_cron_scheduler._jobs.values())
        enabled = [j for j in jobs if j.is_enabled]
        next_job = _cron_scheduler.next_due_job()
        return {
            "running": _cron_scheduler.is_running,
            "job_count": len(jobs),
            "enabled_count": len(enabled),
            "next_job_name": next_job.name if next_job else None,
            "next_job_at": next_job.next_run if next_job else None,
        }

    # ─── Swarms ───────────────────────────────────────────────

    @app.get("/api/swarms")
    async def list_swarms():
        if not _database:
            return []
        return await _database.list_swarms()

    @app.post("/api/swarms")
    async def create_swarm(request: Request):
        """Create a swarm from multipart form data (name, goal, global_model, files)."""
        if not _swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        form = await request.form()
        name = str(form.get("name", "New Swarm"))
        goal = str(form.get("goal", ""))
        global_model = str(form.get("global_model", "")) or None

        if not goal.strip():
            raise HTTPException(400, "goal is required")

        # Collect uploaded files
        file_contents: list[dict] = []
        for field_name, field_value in form.multi_items():
            if hasattr(field_value, "read"):
                raw = await field_value.read()
                try:
                    content = raw.decode("utf-8", errors="replace")
                except Exception:
                    content = "(binary file — skipped)"
                file_contents.append({"filename": field_value.filename or field_name, "content": content})

        swarm = await _swarm_manager.create_swarm(
            name=name,
            goal=goal,
            file_contents=file_contents or None,
            global_model=global_model,
        )
        return swarm

    @app.get("/api/swarms/{swarm_id}")
    async def get_swarm(swarm_id: int):
        if not _database:
            raise HTTPException(503, "Database not available")
        swarm = await _database.get_swarm(swarm_id)
        if not swarm:
            raise HTTPException(404, "Swarm not found")
        workers = await _database.get_swarm_workers(swarm_id)
        tasks = await _database.get_swarm_tasks(swarm_id)
        return {**swarm, "workers": workers, "tasks": tasks}

    @app.delete("/api/swarms/{swarm_id}")
    async def delete_swarm(swarm_id: int):
        if not _database:
            raise HTTPException(503, "Database not available")
        ok = await _database.delete_swarm(swarm_id)
        if not ok:
            raise HTTPException(404, "Swarm not found")
        return {"ok": True}

    @app.post("/api/swarms/{swarm_id}/plan")
    async def plan_swarm(swarm_id: int):
        if not _swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        swarm = await _database.get_swarm(swarm_id)
        if not swarm:
            raise HTTPException(404, "Swarm not found")
        result = await _swarm_manager.plan_swarm(swarm_id)
        workers = await _database.get_swarm_workers(swarm_id)
        tasks = await _database.get_swarm_tasks(swarm_id)
        return {**result, "workers": workers, "tasks": tasks}

    @app.post("/api/swarms/{swarm_id}/start")
    async def start_swarm(swarm_id: int):
        if not _swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        swarm = await _database.get_swarm(swarm_id)
        if not swarm:
            raise HTTPException(404, "Swarm not found")
        if swarm["status"] not in ("planned", "paused"):
            raise HTTPException(400, f"Cannot start swarm in '{swarm['status']}' status. Plan it first.")
        await _swarm_manager.start_swarm(swarm_id)
        return {"ok": True, "status": "running"}

    @app.post("/api/swarms/{swarm_id}/stop")
    async def stop_swarm(swarm_id: int):
        if not _swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        await _swarm_manager.stop_swarm(swarm_id)
        return {"ok": True, "status": "paused"}

    @app.put("/api/swarms/{swarm_id}/workers/{worker_id}")
    async def update_swarm_worker(swarm_id: int, worker_id: int, request: Request):
        if not _database:
            raise HTTPException(503, "Database not available")
        body = await request.json()
        allowed = {"name", "role", "description", "system_prompt", "model", "allowed_tools"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            raise HTTPException(400, "No valid fields to update")
        await _database.update_swarm_worker(worker_id, **updates)
        workers = await _database.get_swarm_workers(swarm_id)
        return next((w for w in workers if w["id"] == worker_id), {})

    @app.get("/api/swarms/{swarm_id}/messages")
    async def get_swarm_messages(swarm_id: int):
        if not _database:
            raise HTTPException(503, "Database not available")
        return await _database.get_swarm_messages(swarm_id)

    @app.post("/api/swarms/{swarm_id}/message")
    async def post_swarm_message(swarm_id: int, request: Request):
        """Send a user message to the swarm (feedback, new instructions, etc.)."""
        if not _swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        body = await request.json()
        message = str(body.get("message", "")).strip()
        if not message:
            raise HTTPException(400, "message is required")
        result = await _swarm_manager.send_user_message(swarm_id, message)
        return {"ok": True, "result": result}

    @app.websocket("/ws/swarms/{swarm_id}")
    async def ws_swarm(websocket: WebSocket, swarm_id: int):
        """Real-time updates for a specific swarm."""
        if not _verify_ws_token(websocket):
            await websocket.close(code=4001, reason="Unauthorized")
            return
        await websocket.accept()
        try:
            while True:
                swarm = await _database.get_swarm(swarm_id) if _database else None
                workers = await _database.get_swarm_workers(swarm_id) if _database else []
                tasks = await _database.get_swarm_tasks(swarm_id) if _database else []
                messages = await _database.get_swarm_messages(swarm_id) if _database else []
                await websocket.send_json({
                    "swarm": swarm,
                    "workers": workers,
                    "tasks": tasks,
                    "messages": messages,
                })
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    # ─── Content Queue ────────────────────────────────────────

    @app.get("/api/content/queue")
    async def list_content_queue(status: str = "", limit: int = 50):
        if not _database:
            return []
        items = await _database.get_content_queue(status=status or None, limit=limit)
        pending_count = await _database.count_pending_content()
        return {"items": items, "pending_count": pending_count}

    @app.post("/api/content/queue/{item_id}/approve")
    async def approve_content(item_id: int):
        if not _database:
            raise HTTPException(503, "Database not available")
        item = await _database.get_content_item(item_id)
        if not item:
            raise HTTPException(404, "Content item not found")
        await _database.update_content_status(item_id, "approved")
        await broadcast_event("content:approved", {"item_id": item_id})
        return {"ok": True, "status": "approved"}

    @app.post("/api/content/queue/{item_id}/reject")
    async def reject_content(item_id: int):
        if not _database:
            raise HTTPException(503, "Database not available")
        item = await _database.get_content_item(item_id)
        if not item:
            raise HTTPException(404, "Content item not found")
        await _database.update_content_status(item_id, "rejected")
        await broadcast_event("content:rejected", {"item_id": item_id})
        return {"ok": True, "status": "rejected"}

    @app.delete("/api/content/queue/{item_id}")
    async def delete_content_item(item_id: int):
        if not _database:
            raise HTTPException(503, "Database not available")
        ok = await _database.delete_content_item(item_id)
        if not ok:
            raise HTTPException(404, "Content item not found")
        return {"ok": True}

    @app.get("/api/content/pending-count")
    async def content_pending_count():
        if not _database:
            return {"count": 0}
        count = await _database.count_pending_content()
        return {"count": count}

    @app.get("/api/content/sessions")
    async def list_content_sessions(date: str = ""):
        import os as _os
        from pathlib import Path as _Path
        workspace = _Path(_os.environ.get("OPENACM_WORKSPACE", "workspace"))
        base = workspace / "content" / "sessions"
        if not base.exists():
            return {"dates": [], "sessions": []}
        if date:
            session_dir = base / date
            if not session_dir.exists():
                return {"dates": [], "sessions": []}
            import json as _json
            sessions = []
            for f in sorted(session_dir.glob("*.json")):
                try:
                    sessions.append(_json.loads(f.read_text()))
                except Exception:
                    pass
            return {"dates": [date], "sessions": sessions}
        dates = sorted(d.name for d in base.iterdir() if d.is_dir())
        return {"dates": dates, "sessions": []}

    # ─── Swarm Templates ──────────────────────────────────────

    @app.get("/api/swarm-templates")
    async def list_swarm_templates():
        if not _database:
            return []
        return await _database.get_all_swarm_templates()

    @app.post("/api/swarm-templates")
    async def create_swarm_template(request: Request):
        if not _database:
            raise HTTPException(503, "Database not available")
        body = await request.json()
        if not body.get("name") or not body.get("goal_template"):
            raise HTTPException(400, "name and goal_template are required")
        import json as _json
        tmpl_id = await _database.create_swarm_template(
            name=body["name"],
            description=body.get("description", ""),
            goal_template=body["goal_template"],
            workers=_json.dumps(body.get("workers", [])),
            global_model=body.get("global_model") or None,
        )
        tmpl = await _database.get_swarm_template(tmpl_id)
        return tmpl

    @app.delete("/api/swarm-templates/{tmpl_id}")
    async def delete_swarm_template(tmpl_id: int):
        if not _database:
            raise HTTPException(503, "Database not available")
        ok = await _database.delete_swarm_template(tmpl_id)
        if not ok:
            raise HTTPException(404, "Template not found")
        return {"ok": True}

    # ─── Social Credentials ───────────────────────────────────

    @app.get("/api/social/credentials")
    async def list_social_credentials():
        if not _database:
            return []
        # Return without the raw credential values (just status)
        return await _database.get_all_social_credentials()

    @app.post("/api/social/credentials")
    async def save_social_credentials(request: Request):
        if not _database:
            raise HTTPException(503, "Database not available")
        import json as _json
        body = await request.json()
        platform = body.get("platform", "")
        credentials = body.get("credentials", {})
        if platform not in ("facebook", "reddit"):
            raise HTTPException(400, "platform must be 'facebook' or 'reddit'")
        await _database.save_social_credentials(platform, _json.dumps(credentials))
        return {"ok": True, "platform": platform}

    @app.post("/api/social/credentials/{platform}/verify")
    async def verify_social_credentials(platform: str):
        if not _database:
            raise HTTPException(503, "Database not available")
        if platform not in ("facebook", "reddit"):
            raise HTTPException(400, "platform must be 'facebook' or 'reddit'")
        import json as _json
        row = await _database.get_social_credentials(platform)
        if not row:
            raise HTTPException(404, f"No credentials saved for {platform}")
        creds = _json.loads(row["credentials"])

        if platform == "facebook":
            token = creds.get("page_access_token", "")
            if not token:
                raise HTTPException(400, "page_access_token missing from saved credentials")
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get("https://graph.facebook.com/me", params={"access_token": token})
                if r.status_code == 200:
                    name = r.json().get("name", "?")
                    await _database.save_social_credentials(platform, _json.dumps(creds), verified=True)
                    return {"ok": True, "message": f"Authenticated as '{name}'"}
                err = r.json().get("error", {}).get("message", r.text[:200])
                return {"ok": False, "message": err}
            except Exception as exc:
                return {"ok": False, "message": str(exc)}

        elif platform == "reddit":
            try:
                import praw  # type: ignore[import]
                reddit = praw.Reddit(
                    client_id=creds["client_id"],
                    client_secret=creds["client_secret"],
                    username=creds["username"],
                    password=creds["password"],
                    user_agent=creds.get("user_agent", "OpenACM/1.0"),
                )
                me = reddit.user.me()
                await _database.save_social_credentials(platform, _json.dumps(creds), verified=True)
                return {"ok": True, "message": f"Authenticated as u/{me.name}"}
            except ImportError:
                return {"ok": False, "message": "praw not installed — run: pip install praw"}
            except Exception as exc:
                return {"ok": False, "message": str(exc)[:300]}

    @app.delete("/api/social/credentials/{platform}")
    async def delete_social_credentials(platform: str):
        if not _database:
            raise HTTPException(503, "Database not available")
        ok = await _database.delete_social_credentials(platform)
        if not ok:
            raise HTTPException(404, f"No credentials for {platform}")
        return {"ok": True}

    # ─── Catch-all SPA route (MUST be last) ─────────────────

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def serve_spa(full_path: str):
        """Serve the correct per-page index.html for Next.js static export."""
        # Strip trailing slashes for path lookup
        clean_path = full_path.strip("/")

        # Try the exact per-page index.html (e.g. dashboard/index.html)
        if clean_path:
            page_index = static_dir / clean_path / "index.html"
            if page_index.exists():
                return FileResponse(str(page_index))

        # Fallback to root index.html
        root_index = static_dir / "index.html"
        if root_index.exists():
            return FileResponse(str(root_index))
        return HTMLResponse("<h1>OpenACM</h1><p>Static files not found. Run build first.</p>")

    # ─── Plugin API routes ────────────────────────────────────
    # Plugins are started before create_app() is called, so their routers
    # are already available here. Each router is mounted under /api/.
    try:
        from openacm.plugins import plugin_manager
        for router in plugin_manager.get_api_routers():
            app.include_router(router, prefix="/api")
            log.debug("Plugin API router mounted", prefix="/api")
    except Exception as exc:
        log.warning("Failed to mount plugin API routers", error=str(exc))

    return app


async def broadcast_event(event_type: str, data: dict[str, Any]):
    """Broadcast an event to all connected WebSocket clients."""
    global _ws_clients
    if not _ws_clients:
        return

    message = {"type": event_type, **data}
    disconnected = set()

    for client in _ws_clients:
        try:
            await client.send_json(message)
        except Exception:
            disconnected.add(client)

    _ws_clients -= disconnected


class ChannelShell:
    """Persistent PTY shell for one channel. Survives WS reconnects."""

    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id
        self.clients: set[WebSocket] = set()
        self._platform: str = ""
        self._pty = None          # winpty.PtyProcess (Windows) or (master_fd, proc) tuple (Unix)
        self._alive = False
        self._reader_task: asyncio.Task | None = None
        self._output_listeners: list[asyncio.Queue] = []  # for run_command_capture
        self._cmd_lock = asyncio.Lock()                    # one command at a time

    async def start(self, cols: int = 220, rows: int = 50) -> None:
        import platform as _plat
        self._platform = _plat.system()
        loop = asyncio.get_event_loop()

        if self._platform == "Windows":
            from winpty import PtyProcess  # pywinpty
            self._pty = await loop.run_in_executor(
                None, lambda: PtyProcess.spawn("cmd.exe", dimensions=(rows, cols))
            )
        else:
            import pty as _pty_mod, os, subprocess, fcntl, termios, struct
            master_fd, slave_fd = _pty_mod.openpty()
            # Set terminal size
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            proc = subprocess.Popen(
                ["/bin/bash", "-i"],
                stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                close_fds=True, preexec_fn=os.setsid,
            )
            os.close(slave_fd)
            self._pty = (master_fd, proc)

        self._alive = True
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        loop = asyncio.get_event_loop()
        consecutive_errors = 0
        while self._alive:
            try:
                chunk = await loop.run_in_executor(None, self._read_chunk)
                consecutive_errors = 0
                if chunk is None:
                    # Process died
                    self._alive = False
                    await self._broadcast_json({"type": "exit", "data": "shell exited"})
                    break
                if chunk:
                    await self._broadcast_json({"type": "output", "data": chunk})
            except asyncio.CancelledError:
                break
            except Exception:
                consecutive_errors += 1
                if consecutive_errors > 20:
                    # Too many errors in a row — consider shell dead
                    self._alive = False
                    await self._broadcast_json({"type": "exit", "data": "shell read error"})
                    break
                await asyncio.sleep(0.05)

    def _read_chunk(self) -> str | None:
        """Blocking read — runs in thread executor. Returns None when process dies."""
        try:
            if self._platform == "Windows":
                if not self._pty.isalive():
                    return None
                data = self._pty.read(4096)  # blocks until data available; no timeout param
                return data if data else ""
            else:
                import select, os
                master_fd, proc = self._pty
                if proc.poll() is not None:
                    return None
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if r:
                    return os.read(master_fd, 4096).decode("utf-8", errors="replace")
                return ""
        except EOFError:
            return None  # process exited cleanly
        except Exception:
            return None

    async def write(self, data: str) -> None:
        if not self._alive:
            return
        loop = asyncio.get_event_loop()
        try:
            if self._platform == "Windows":
                await loop.run_in_executor(None, self._pty.write, data)
            else:
                import os
                master_fd, _ = self._pty
                await loop.run_in_executor(None, os.write, master_fd, data.encode("utf-8"))
        except Exception:
            pass

    def resize(self, cols: int, rows: int) -> None:
        try:
            if self._platform == "Windows":
                self._pty.setwinsize(rows, cols)
            else:
                import fcntl, termios, struct
                master_fd, _ = self._pty
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except Exception:
            pass

    async def _broadcast_json(self, data: dict[str, Any]) -> None:
        dead: set[WebSocket] = set()
        for ws in list(self.clients):
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        self.clients -= dead
        # Push to any active run_command_capture listeners
        for q in list(self._output_listeners):
            try:
                q.put_nowait(data)
            except Exception:
                pass

    async def run_command_capture(self, command: str, timeout: float = 30.0) -> str:
        """Write a command to the PTY and capture output. Serialized — one command at a time."""
        import re as _re

        _ANSI = _re.compile(r'\x1b(?:\[[0-9;]*[mGKHFABCDJsSu]|\][^\x07]*\x07|[()][AB012])')

        # Hard cap: stop collecting after this many characters.
        # Prevents unbounded RAM growth and terminal flooding from commands like dir /s.
        MAX_CAPTURE_CHARS = 80_000

        def strip_ansi(t: str) -> str:
            return _ANSI.sub("", t).replace("\r", "")

        def looks_like_prompt(text: str) -> bool:
            clean = strip_ansi(text).rstrip()
            if not clean:
                return False
            last = clean.splitlines()[-1] if "\n" in clean else clean
            return bool(_re.search(r"[>$#]\s*$", last))

        async def _interrupt_pty() -> None:
            """Send Ctrl+C to the PTY to kill the currently running command."""
            try:
                await self.write("\x03")   # ETX = Ctrl+C
                await asyncio.sleep(0.3)   # give the shell time to print ^C and show prompt
            except Exception:
                pass

        async with self._cmd_lock:
            queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
            self._output_listeners.append(queue)
            parts: list[str] = []
            total_chars = 0
            output_capped = False

            try:
                await self.write(command + "\r\n")
                deadline = asyncio.get_event_loop().time() + timeout
                prompt_seen = False

                while True:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        # Timeout reached — send Ctrl+C so the process dies and the
                        # terminal stops flooding. Without this the PTY keeps streaming
                        # output after we stop listening, overlapping with the next command.
                        await _interrupt_pty()
                        break
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=min(remaining, 0.5))
                        if msg.get("type") == "output":
                            chunk = msg.get("data", "")
                            total_chars += len(chunk)

                            if total_chars <= MAX_CAPTURE_CHARS:
                                parts.append(chunk)
                            elif not output_capped:
                                # Hit the cap — interrupt the command immediately
                                output_capped = True
                                await _interrupt_pty()
                                break

                            combined = "".join(parts)
                            if looks_like_prompt(combined) and len(strip_ansi(combined).strip()) > len(command) + 2:
                                prompt_seen = True
                                break
                    except asyncio.TimeoutError:
                        # Only break on silence if we've already seen the shell prompt —
                        # avoids cutting off slow network commands (SSH, docker, etc.)
                        combined = "".join(parts)
                        if prompt_seen or (parts and looks_like_prompt(combined)):
                            break
                        # Otherwise keep waiting — command still running
            finally:
                try:
                    self._output_listeners.remove(queue)
                except ValueError:
                    pass

            combined = strip_ansi("".join(parts)).strip()
            if combined.lower().startswith(command.strip().lower()):
                combined = combined[len(command.strip()):].strip()

            if output_capped:
                combined += f"\n[output truncated — exceeded {MAX_CAPTURE_CHARS:,} chars. Command was interrupted.]"

            return combined or "(sin salida)"

    async def stop(self) -> None:
        self._alive = False
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        try:
            if self._platform == "Windows":
                if self._pty:
                    self._pty.terminate(force=True)
            else:
                if self._pty:
                    import os, signal
                    master_fd, proc = self._pty
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        os.close(master_fd)
                    except OSError:
                        pass
        except Exception:
            pass


# Per-channel persistent shell sessions
_channel_shells: dict[str, ChannelShell] = {}


async def _broadcast_to_terminal(data: dict[str, Any], channel_id: str = "web") -> None:
    """Broadcast a structured message to the terminal for a specific channel."""
    shell = _channel_shells.get(channel_id)
    if shell and shell._alive:
        await shell._broadcast_json(data)


async def create_web_server(
    config: AppConfig,
    brain: Brain,
    database: Database,
    event_bus: EventBus,
    tool_registry: ToolRegistry,
    channels: list | None = None,
    agent_bot_manager=None,
    mcp_manager=None,
    activity_watcher=None,
    cron_scheduler=None,
    swarm_manager=None,
    content_watcher=None,
) -> uvicorn.Server:
    """Create and start the web server."""
    global _brain, _database, _event_bus, _tool_registry, _config, _command_processor, _channels, _agent_bot_manager, _mcp_manager, _activity_watcher, _cron_scheduler, _swarm_manager, _content_watcher
    _brain = brain
    _database = database
    _event_bus = event_bus
    _tool_registry = tool_registry
    _activity_watcher = activity_watcher
    _cron_scheduler = cron_scheduler
    _swarm_manager = swarm_manager
    _content_watcher = content_watcher
    _config = config
    _command_processor = CommandProcessor(brain, database)
    _channels = channels or []
    _agent_bot_manager = agent_bot_manager
    _mcp_manager = mcp_manager

    # Load and apply user-defined custom providers on startup
    _apply_custom_providers(_load_custom_providers())

    # Register event bus handler for WebSocket broadcasting
    async def on_event(event_type: str, data: dict[str, Any]):
        await broadcast_event(event_type, data)

    from openacm.core.events import (
        EVENT_MESSAGE_RECEIVED,
        EVENT_MESSAGE_SENT,
        EVENT_THINKING,
        EVENT_TOOL_CALLED,
        EVENT_TOOL_RESULT,
        EVENT_LLM_REQUEST,
        EVENT_LLM_RESPONSE,
        EVENT_ROUTER_LEARNED,
        EVENT_TOOL_VALIDATION,
    )

    for evt in [
        EVENT_MESSAGE_RECEIVED,
        EVENT_MESSAGE_SENT,
        EVENT_THINKING,
        EVENT_TOOL_CALLED,
        EVENT_TOOL_RESULT,
        EVENT_LLM_REQUEST,
        EVENT_LLM_RESPONSE,
        EVENT_ROUTER_LEARNED,
        EVENT_TOOL_VALIDATION,
        "memory.recall",
        # Swarm events — emitted by SwarmManager for every state change
        "swarm:updated",
        "swarm:worker_status",
        "swarm:task_updated",
        "swarm:message",
        "swarm:running",
        "swarm:paused_mid_run",
        "swarm:stalled",
        "swarm:round",
        "swarm:worker_thinking",
        "swarm:worker_done",
        "swarm:worker_error",
        "swarm:plan_ready",
        "swarm:synthesizing",
        "swarm:completed",
        "swarm:user_message",
        "swarm:task_created",
        "swarm:orchestrator_reacted",
        # Content pipeline events
        "content:session_screenshot",
        "content:approved",
        "content:rejected",
    ]:
        event_bus.on(evt, on_event)

    # Mirror AI tool calls to the correct channel's terminal
    async def on_tool_called(event_type: str, data: dict[str, Any]):
        tool_name = data.get("tool", "")
        if tool_name not in _TERMINAL_TOOLS:
            return
        channel_id = data.get("channel_id", "web")
        args_raw = data.get("arguments", "")
        try:
            import json as _j
            args = _j.loads(args_raw) if isinstance(args_raw, str) else args_raw
            command = args.get("command") or args.get("code") or args_raw
        except Exception:
            command = str(args_raw)
        await _broadcast_to_terminal({
            "type": "ai_command",
            "tool": tool_name,
            "data": str(command),
        }, channel_id=channel_id)

    event_bus.on(EVENT_TOOL_CALLED, on_tool_called)

    from openacm.core.events import EVENT_TOOL_OUTPUT_STREAM

    async def on_tool_output_stream(event_type: str, data: dict[str, Any]):
        chunk = data.get("chunk", "")
        tool = data.get("tool", "")
        channel_id = data.get("channel_id", "web")
        if chunk:
            await _broadcast_to_terminal(
                {"type": "ai_output", "tool": tool, "data": chunk},
                channel_id=channel_id,
            )

    event_bus.on(EVENT_TOOL_OUTPUT_STREAM, on_tool_output_stream)

    app = create_app()

    uv_config = uvicorn.Config(
        app=app,
        host=config.web.host,
        port=config.web.port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(uv_config)

    # Run server in background
    asyncio.create_task(server.serve())

    return server
