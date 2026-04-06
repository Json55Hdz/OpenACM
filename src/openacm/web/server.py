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
_terminal_ws_clients: set[WebSocket] = set()

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


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="OpenACM Dashboard",
        version="0.1.0",
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

    # ─── API: Tools ───────────────────────────────────────────

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

    def _get_provider_status() -> dict[str, bool]:
        """Derive provider status dynamically from config, using {ID}_API_KEY convention."""
        if not _config:
            return {}
        result: dict[str, bool] = {}
        for provider_id in _config.llm.providers:
            if provider_id in _NO_KEY_PROVIDERS:
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
        """Clear conversation history for a user/channel pair."""
        if not _brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        await _brain.memory.clear(user_id, channel_id)
        return {"status": "ok"}

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
                        response = await _brain.process_message(
                            content=content,
                            user_id=target_user,
                            channel_id=target_channel,
                            channel_type=target_type,
                            attachments=attachments,
                        )
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
        """WebSocket endpoint for interactive terminal sessions."""
        import platform
        import json as _json

        if not _verify_ws_token(websocket):
            await websocket.close(code=4001, reason="Unauthorized")
            return
        await websocket.accept()
        _terminal_ws_clients.add(websocket)

        # Pick shell based on OS
        if platform.system() == "Windows":
            shell_cmd = ["cmd.exe"]
        else:
            shell_cmd = ["/bin/bash", "-i"]

        process = None
        stdout_task = asyncio.create_task(asyncio.sleep(0))  # placeholder
        stderr_task = asyncio.create_task(asyncio.sleep(0))  # placeholder
        try:
            # SECURITY: POR DISEÑO — Terminal interactiva para el administrador
            # autenticado del dashboard. Requiere token de dashboard válido.
            process = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def read_stream(stream, stream_type="output"):
                """Read from stdout/stderr and send to WebSocket."""
                try:
                    while True:
                        data = await stream.read(4096)
                        if not data:
                            break
                        text = data.decode("utf-8", errors="replace")
                        await websocket.send_json({"type": stream_type, "data": text})

                        # Track in brain's terminal history
                        if _brain and hasattr(_brain, "terminal_history"):
                            # Append output to last entry if exists
                            if _brain.terminal_history and not _brain.terminal_history[-1].get("_closed"):
                                _brain.terminal_history[-1]["output"] += text
                                # Cap output size per command
                                if len(_brain.terminal_history[-1]["output"]) > 2000:
                                    _brain.terminal_history[-1]["output"] = (
                                        _brain.terminal_history[-1]["output"][:2000] + "\n... (truncated)"
                                    )
                except (asyncio.CancelledError, Exception):
                    pass

            # Launch readers for stdout and stderr
            stdout_task = asyncio.create_task(read_stream(process.stdout, "output"))
            stderr_task = asyncio.create_task(read_stream(process.stderr, "output"))

            # Read from WebSocket and write to process stdin
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = _json.loads(raw)
                except _json.JSONDecodeError:
                    continue

                if msg.get("type") == "input":
                    cmd_data = msg.get("data", "")
                    if process.stdin and not process.stdin.is_closing():
                        process.stdin.write(cmd_data.encode("utf-8"))
                        await process.stdin.drain()

                        # Track command in brain's terminal history
                        if _brain and hasattr(_brain, "terminal_history"):
                            cmd_clean = cmd_data.strip()
                            if cmd_clean:
                                # Close previous entry
                                if _brain.terminal_history:
                                    _brain.terminal_history[-1]["_closed"] = True
                                _brain.terminal_history.append({
                                    "command": cmd_clean,
                                    "output": "",
                                    "_closed": False,
                                })
                                # Keep only last 30 commands
                                if len(_brain.terminal_history) > 30:
                                    _brain.terminal_history[:] = _brain.terminal_history[-30:]

                elif msg.get("type") == "signal":
                    if process and process.returncode is None:
                        try:
                            process.send_signal(2)  # SIGINT
                        except (ProcessLookupError, OSError):
                            pass

        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.error("Terminal WebSocket error", error=str(e))
        finally:
            _terminal_ws_clients.discard(websocket)
            if process and process.returncode is None:
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=3.0)
                except (asyncio.TimeoutError, ProcessLookupError):
                    try:
                        process.kill()
                    except (ProcessLookupError, OSError):
                        pass
            # Cancel reader tasks
            for task in [stdout_task, stderr_task]:
                if not task.done():
                    task.cancel()

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

    # ─── Remote Control ───────────────────────────────────────

    # Signaling state for WebRTC
    _remote_host_ws: list[WebSocket] = []   # only one host at a time
    _remote_clients: dict[str, WebSocket] = {}  # clientId -> ws

    @app.get("/remote/host", response_class=HTMLResponse)
    async def remote_host_page():
        """Serve the Remote Host page (PC side — captures screen)."""
        host_file = static_dir / "remote" / "host.html"
        if host_file.exists():
            return FileResponse(str(host_file))
        return HTMLResponse("<h1>Remote host page not found</h1>")

    @app.get("/remote", response_class=HTMLResponse)
    async def remote_client_page():
        """Serve the Remote Client page (mobile side — viewer + control)."""
        client_file = static_dir / "remote" / "index.html"
        if client_file.exists():
            return FileResponse(str(client_file))
        return HTMLResponse("<h1>Remote client page not found</h1>")

    @app.websocket("/ws/remote")
    async def ws_remote_signaling(websocket: WebSocket):
        """WebSocket for WebRTC signaling between host and client(s)."""
        if not _verify_ws_token(websocket):
            await websocket.close(code=4001, reason="Unauthorized")
            return
        await websocket.accept()

        role = websocket.query_params.get("role", "client")
        client_id = secrets.token_hex(8)

        try:
            if role == "host":
                _remote_host_ws.clear()
                _remote_host_ws.append(websocket)
                log.info("Remote host connected")

                while True:
                    data = await websocket.receive_json()
                    msg_type = data.get("type", "")

                    if msg_type == "offer":
                        # Forward offer to specific client
                        target = data.get("targetId")
                        cws = _remote_clients.get(target)
                        if cws:
                            try:
                                await cws.send_json({
                                    "type": "offer",
                                    "sdp": data.get("sdp"),
                                })
                            except Exception:
                                pass

                    elif msg_type == "ice-candidate":
                        target = data.get("targetId")
                        cws = _remote_clients.get(target)
                        if cws:
                            try:
                                await cws.send_json({
                                    "type": "ice-candidate",
                                    "candidate": data.get("candidate"),
                                })
                            except Exception:
                                pass

            else:  # client
                _remote_clients[client_id] = websocket
                log.info("Remote client connected", client_id=client_id)

                # Notify host that a new client joined
                if _remote_host_ws:
                    try:
                        await _remote_host_ws[0].send_json({
                            "type": "client-join",
                            "clientId": client_id,
                        })
                    except Exception:
                        pass

                while True:
                    data = await websocket.receive_json()
                    msg_type = data.get("type", "")

                    if msg_type == "answer":
                        if _remote_host_ws:
                            try:
                                await _remote_host_ws[0].send_json({
                                    "type": "answer",
                                    "sdp": data.get("sdp"),
                                    "clientId": client_id,
                                })
                            except Exception:
                                pass

                    elif msg_type == "ice-candidate":
                        if _remote_host_ws:
                            try:
                                await _remote_host_ws[0].send_json({
                                    "type": "ice-candidate",
                                    "candidate": data.get("candidate"),
                                    "clientId": client_id,
                                })
                            except Exception:
                                pass

        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.error("Remote signaling error", error=str(e))
        finally:
            if role == "host":
                if websocket in _remote_host_ws:
                    _remote_host_ws.remove(websocket)
                log.info("Remote host disconnected")
            else:
                _remote_clients.pop(client_id, None)
                # Notify host
                if _remote_host_ws:
                    try:
                        await _remote_host_ws[0].send_json({
                            "type": "client-leave",
                            "clientId": client_id,
                        })
                    except Exception:
                        pass
                log.info("Remote client disconnected", client_id=client_id)

    @app.websocket("/ws/remote-control")
    async def ws_remote_control(websocket: WebSocket):
        """WebSocket for receiving control commands from the mobile client."""
        if not _verify_ws_token(websocket):
            await websocket.close(code=4001, reason="Unauthorized")
            return
        await websocket.accept()

        from openacm.web.remote_control import dispatch_command

        log.info("Remote control session started")
        try:
            while True:
                data = await websocket.receive_json()
                result = await dispatch_command(data)
                try:
                    await websocket.send_json(result)
                except Exception:
                    pass
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.error("Remote control error", error=str(e))
        finally:
            log.info("Remote control session ended")

    # ─── API: Remote Control Status ────────────────────────────

    @app.get("/api/remote/status")
    async def get_remote_status():
        """Get current remote control session status."""
        return {
            "host_connected": len(_remote_host_ws) > 0,
            "clients_connected": len(_remote_clients),
            "client_ids": list(_remote_clients.keys()),
        }

    @app.get("/api/remote/url")
    async def get_remote_url(token: str = ""):
        """Get or create the public tunnel URL."""
        try:
            import openacm.tools.remote_tool as rt
            
            # Start tunnel if not running
            port = _config.web.port if _config else 47821
            if not rt._ngrok_tunnel:
                await rt._start_session(port, token, use_tunnel=True, auto_open=False)
                
            if rt._ngrok_tunnel:
                return {"url": f"{rt._ngrok_tunnel.public_url}/remote?token={token}"}
                
            # Fallback to local network IP
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
            except Exception:
                ip = "localhost"
            finally:
                s.close()
                
            return {"url": f"http://{ip}:{port}/remote?token={token}"}
        except Exception as e:
            port = _config.web.port if _config else 47821
            return {"url": f"http://localhost:{port}/remote?token={token}", "error": str(e)}

    @app.get("/api/remote/video_feed")
    async def get_video_feed(token: str = ""):
        """Stream screen capture as MJPEG (headlessly, no host page required)."""
        if _dashboard_token and token != _dashboard_token:
            raise HTTPException(status_code=401, detail="Unauthorized")
            
        import mss
        from PIL import Image
        import io
        
        async def frame_generator():
            try:
                import openacm.web.remote_control as rc
                with mss.mss() as sct:
                    while True:
                        idx = rc.get_current_monitor_index()
                        monitor = sct.monitors[idx]
                        sct_img = sct.grab(monitor)
                        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                        
                        # Resize to 1280p width to save bandwidth for mobile
                        if img.width > 1280:
                            img = img.resize((1280, int(img.height * (1280 / img.width))), Image.Resampling.BILINEAR)
                            
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=65)
                        frame = buf.getvalue()
                        
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n'
                               b'Content-Length: ' + str(len(frame)).encode() + b'\r\n\r\n' + frame + b'\r\n')
                        
                        await asyncio.sleep(0.06) # ~15 FPS
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.error("Video feed error", error=str(e))
                
        from fastapi.responses import StreamingResponse
        return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")

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


async def _broadcast_to_terminal(data: dict[str, Any]):
    """Broadcast a message to all connected terminal WebSocket clients."""
    global _terminal_ws_clients
    if not _terminal_ws_clients:
        return
    disconnected = set()
    for client in _terminal_ws_clients:
        try:
            await client.send_json(data)
        except Exception:
            disconnected.add(client)
    _terminal_ws_clients -= disconnected


async def create_web_server(
    config: AppConfig,
    brain: Brain,
    database: Database,
    event_bus: EventBus,
    tool_registry: ToolRegistry,
    channels: list | None = None,
    agent_bot_manager=None,
    mcp_manager=None,
) -> uvicorn.Server:
    """Create and start the web server."""
    global _brain, _database, _event_bus, _tool_registry, _config, _command_processor, _channels, _agent_bot_manager, _mcp_manager
    _brain = brain
    _database = database
    _event_bus = event_bus
    _tool_registry = tool_registry
    _config = config
    _command_processor = CommandProcessor(brain, database)
    _channels = channels or []
    _agent_bot_manager = agent_bot_manager
    _mcp_manager = mcp_manager

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
    ]:
        event_bus.on(evt, on_event)

    # Mirror AI tool calls to the terminal panel
    async def on_tool_called(event_type: str, data: dict[str, Any]):
        tool_name = data.get("tool", "")
        if tool_name not in _TERMINAL_TOOLS:
            return
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
        })

    async def on_tool_result(event_type: str, data: dict[str, Any]):
        tool_name = data.get("tool", "")
        if tool_name not in _TERMINAL_TOOLS:
            return
        result = data.get("result", "")
        await _broadcast_to_terminal({
            "type": "ai_output",
            "tool": tool_name,
            "data": str(result),
        })

    event_bus.on(EVENT_TOOL_CALLED, on_tool_called)
    event_bus.on(EVENT_TOOL_RESULT, on_tool_result)

    from openacm.core.events import EVENT_TOOL_OUTPUT_STREAM

    async def on_tool_output_stream(event_type: str, data: dict[str, Any]):
        chunk = data.get("chunk", "")
        tool = data.get("tool", "")
        if chunk:
            await _broadcast_to_terminal({"type": "ai_output", "tool": tool, "data": chunk})

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
