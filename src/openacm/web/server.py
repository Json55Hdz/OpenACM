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
from openacm.core.events import EventBus
from openacm.storage.database import Database
from openacm.tools.registry import ToolRegistry

log = structlog.get_logger()

# Store connected WebSocket clients
_ws_clients: set[WebSocket] = set()

# Global refs (set during startup)
_brain: Brain | None = None
_database: Database | None = None
_event_bus: EventBus | None = None
_tool_registry: ToolRegistry | None = None
_config: AppConfig | None = None


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

            # API routes below here require auth (except /api/auth/check)
            if path == "/api/auth/check":
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

    @app.get("/api/config/status")
    async def get_config_status():
        """Check if essential configuration is missing (e.g. LLM API Key)."""
        if not _config or not _brain:
            return {"needs_setup": True}
        provider = _brain.llm_router._current_provider
        api_key_env = f"{provider.upper()}_API_KEY"
        if not os.environ.get(api_key_env):
            return {"needs_setup": True, "provider": provider}
        return {"needs_setup": False}

    @app.post("/api/config/setup")
    async def post_config_setup(request: Request):
        """Update API keys in .env and memory."""
        data = await request.json()
        from dotenv import set_key

        env_path = Path("config/.env")
        if not env_path.parent.exists():
            env_path.parent.mkdir(parents=True, exist_ok=True)

        updated = []
        for key, value in data.items():
            if value and isinstance(value, str):
                safe_key = key.upper()
                set_key(str(env_path), safe_key, value)
                os.environ[safe_key] = value
                updated.append(safe_key)

        return {"status": "ok", "updated": updated}

    @app.post("/api/config/verbose_channels")
    async def set_verbose_channels(request: Request):
        """Set whether external channels receive tool execution logs."""
        data = await request.json()
        enabled = data.get("enabled", True)
        os.environ["OPENACM_VERBOSE_CHANNELS"] = "true" if enabled else "false"
        return {"status": "ok", "enabled": enabled}

    # ─── API: Media & Uploads ─────────────────────────────────

    @app.post("/api/chat/upload")
    async def upload_media(file: UploadFile = File(...)):
        """Upload and encrypt a media file."""
        from openacm.security.crypto import save_encrypted

        file_bytes = await file.read()

        # Keep extension
        ext = "".join(Path(file.filename).suffixes)
        if not ext:
            ext = ".bin"

        file_id = secrets.token_hex(16)
        file_name = f"{file_id}{ext}"
        dest_path = Path("data/media") / file_name

        save_encrypted(file_bytes, dest_path)

        return {
            "file_id": file_name,
            "filename": file.filename,
            "size": len(file_bytes),
            "content_type": file.content_type,
        }

    @app.get("/api/media/{file_name}")
    async def get_media(file_name: str):
        """Retrieve and decrypt a media file."""
        from openacm.security.crypto import decrypt_file

        file_path = Path("data/media") / file_name
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Media not found")

        try:
            decrypted_bytes = decrypt_file(file_path)
        except Exception:
            raise HTTPException(status_code=500, detail="Decryption failed")

        # Basic MIME inference
        ext = file_path.suffix.lower()
        content_type = "application/octet-stream"
        if ext in [".png"]:
            content_type = "image/png"
        elif ext in [".jpg", ".jpeg"]:
            content_type = "image/jpeg"
        elif ext in [".gif"]:
            content_type = "image/gif"
        elif ext in [".webp"]:
            content_type = "image/webp"
        elif ext in [".pdf"]:
            content_type = "application/pdf"
        elif ext in [".mp3"]:
            content_type = "audio/mpeg"

        return Response(content=decrypted_bytes, media_type=content_type)

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
        """Change the LLM model."""
        data = await request.json()
        model = data.get("model", "")
        if model and _brain:
            _brain.llm_router.set_model(model)
            return {"status": "ok", "model": _brain.llm_router.current_model}
        return {"status": "error", "message": "No model specified"}

    # ─── API: Conversations ───────────────────────────────────

    @app.get("/api/conversations")
    async def get_conversations():
        """Get recent conversations."""
        if not _database:
            return []
        # Get distinct user/channel pairs
        stats = await _database.get_channel_stats()
        return stats

    @app.get("/api/conversations/{channel_id}/{user_id}")
    async def get_conversation(channel_id: str, user_id: str, limit: int = 50):
        """Get conversation history."""
        if not _database:
            return []
        return await _database.get_conversation(user_id, channel_id, limit)

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

                if _brain:
                    try:
                        response = await _brain.process_message(
                            content=content,
                            user_id=target_user,
                            channel_id=target_channel,
                            channel_type=target_type,
                            attachments=attachments,
                        )
                        await websocket.send_json(
                            {
                                "type": "response",
                                "content": response,
                            }
                        )
                    except Exception as e:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "content": str(e),
                            }
                        )
                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "content": "Brain not available",
                        }
                    )
        except WebSocketDisconnect:
            pass

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
                # Keep connection alive
                await websocket.receive_text()
        except WebSocketDisconnect:
            _ws_clients.discard(websocket)

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


async def create_web_server(
    config: AppConfig,
    brain: Brain,
    database: Database,
    event_bus: EventBus,
    tool_registry: ToolRegistry,
) -> uvicorn.Server:
    """Create and start the web server."""
    global _brain, _database, _event_bus, _tool_registry, _config
    _brain = brain
    _database = database
    _event_bus = event_bus
    _tool_registry = tool_registry
    _config = config

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
    )

    for evt in [
        EVENT_MESSAGE_RECEIVED,
        EVENT_MESSAGE_SENT,
        EVENT_THINKING,
        EVENT_TOOL_CALLED,
        EVENT_TOOL_RESULT,
        EVENT_LLM_REQUEST,
        EVENT_LLM_RESPONSE,
    ]:
        event_bus.on(evt, on_event)

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
