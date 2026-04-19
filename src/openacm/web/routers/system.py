from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import structlog
import yaml
from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect,
    Request, UploadFile, File, Form, HTTPException,
)
from fastapi.responses import HTMLResponse, FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles


from openacm.web.state import _state
from openacm.web.broadcast import broadcast_event, _safe_ws_send, _broadcast_to_terminal, _verify_ws_token
from openacm.web.server import _get_version, _load_custom_providers, _save_custom_providers, _apply_custom_providers, _make_provider_id, _get_custom_providers_path

log = structlog.get_logger()



def register_routes(app: FastAPI) -> None:
    import sys
    static_dir = Path(__file__).parent.parent / "static"

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
            "messages_encrypted": _state.database.messages_encrypted if _state.database else False,
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
        if not _state.database:
            return {"error": "Database not available"}
        stats = await _state.database.get_stats()

        # Add LLM router stats
        if _state.brain and _state.brain.llm_router:
            llm_stats = _state.brain.llm_router.get_stats()
            stats.update(llm_stats)

        return stats

    @app.get("/api/stats/history")
    async def get_stats_history(days: int = 30):
        """Get daily usage history."""
        if not _state.database:
            return []
        return await _state.database.get_usage_history(days)

    @app.get("/api/stats/channels")
    async def get_channel_stats():
        """Get per-channel stats."""
        if not _state.database:
            return []
        return await _state.database.get_channel_stats()

    @app.get("/api/stats/detailed")
    async def get_detailed_stats(date_from: str | None = None, date_to: str | None = None):
        """Get detailed token/cost breakdown: totals, by_model, today, history.

        Query params:
            date_from: YYYY-MM-DD (inclusive lower bound)
            date_to:   YYYY-MM-DD (inclusive upper bound)
        """
        if not _state.database:
            return {}
        data = await _state.database.get_detailed_stats(date_from=date_from, date_to=date_to)
        # Merge in live router totals (not yet persisted to DB) — only when no date filter
        if _state.brain and _state.brain.llm_router and not date_from and not date_to:
            snap = _state.brain.llm_router.get_usage_snapshot()
            data["live"] = snap
        return data

    @app.get("/api/memory/stats")
    async def get_memory_stats():
        """Return RAG memory stats: total docs, breakdown by type, folder size."""
        from openacm.core.rag import _rag_engine
        if not _rag_engine or not _rag_engine.is_ready:
            return {"status": "unavailable", "total": 0, "by_type": {}, "size_bytes": 0}
        return await _rag_engine.get_stats()

    @app.delete("/api/memory/all")
    async def clear_all_memory():
        """Delete ALL documents from the RAG vector store."""
        from openacm.core.rag import _rag_engine
        if not _rag_engine or not _rag_engine.is_ready:
            return {"status": "unavailable", "deleted": 0}
        deleted = await _rag_engine.clear_all()
        return {"status": "ok", "deleted": deleted}

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
        if not _state.tool_registry:
            return []
        return [
            {
                "name": t.name,
                "description": t.description,
                "risk_level": t.risk_level,
                "parameters": t.parameters,
            }
            for t in _state.tool_registry.tools.values()
        ]

    @app.get("/api/tools/executions")
    async def get_tool_executions(limit: int = 50):
        """Get recent tool execution logs."""
        if not _state.database:
            return []
        return await _state.database.get_tool_executions(limit)

    @app.post("/api/tool/confirm")
    async def confirm_tool(request: Request):
        """Resolve a pending tool confirmation (approve or deny)."""
        data = await request.json()
        confirm_id = data.get("confirm_id", "")
        approved = bool(data.get("approved", False))
        always_session = bool(data.get("always_session", False))
        command = data.get("command", "")

        if approved and always_session and command:
            _state.session_allowed_commands.add(command)

        future = _state.pending_confirmations.get(confirm_id)
        if future and not future.done():
            future.set_result(approved)
        return {"ok": True}

    @app.patch("/api/config/security")
    async def patch_security_config(request: Request):
        """Update security settings (execution_mode)."""
        if not _state.config:
            return {"ok": False, "error": "No config loaded"}
        data = await request.json()
        mode = data.get("execution_mode")
        if mode and mode in ("yolo", "confirmation", "auto"):
            _state.config.security.execution_mode = mode
            if _state.database:
                await _state.database.set_setting("security.execution_mode", mode)
            return {"ok": True, "execution_mode": mode}
        return {"ok": False, "error": "Invalid execution_mode"}

    # ─── Swarm Templates ──────────────────────────────────────

    @app.get("/api/swarm-templates")
    async def list_swarm_templates():
        if not _state.database:
            return []
        return await _state.database.get_all_swarm_templates()

    @app.post("/api/swarm-templates")
    async def create_swarm_template(request: Request):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        body = await request.json()
        if not body.get("name") or not body.get("goal_template"):
            raise HTTPException(400, "name and goal_template are required")
        tmpl_id = await _state.database.create_swarm_template(
            name=body["name"],
            description=body.get("description", ""),
            goal_template=body["goal_template"],
            workers=json.dumps(body.get("workers", [])),
            global_model=body.get("global_model") or None,
        )
        tmpl = await _state.database.get_swarm_template(tmpl_id)
        return tmpl

    @app.delete("/api/swarm-templates/{tmpl_id}")
    async def delete_swarm_template(tmpl_id: int):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        ok = await _state.database.delete_swarm_template(tmpl_id)
        if not ok:
            raise HTTPException(404, "Template not found")
        return {"ok": True}

    # ─── Social Credentials ───────────────────────────────────

    @app.get("/api/social/credentials")
    async def list_social_credentials():
        if not _state.database:
            return []
        # Return without the raw credential values (just status)
        return await _state.database.get_all_social_credentials()

    @app.post("/api/social/credentials")
    async def save_social_credentials(request: Request):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        body = await request.json()
        platform = body.get("platform", "")
        credentials = body.get("credentials", {})
        if platform not in ("facebook", "reddit"):
            raise HTTPException(400, "platform must be 'facebook' or 'reddit'")
        await _state.database.save_social_credentials(platform, json.dumps(credentials))
        return {"ok": True, "platform": platform}

    @app.post("/api/social/credentials/{platform}/verify")
    async def verify_social_credentials(platform: str):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        if platform not in ("facebook", "reddit"):
            raise HTTPException(400, "platform must be 'facebook' or 'reddit'")
        row = await _state.database.get_social_credentials(platform)
        if not row:
            raise HTTPException(404, f"No credentials saved for {platform}")
        creds = json.loads(row["credentials"])

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
                    await _state.database.save_social_credentials(platform, json.dumps(creds), verified=True)
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
                await _state.database.save_social_credentials(platform, json.dumps(creds), verified=True)
                return {"ok": True, "message": f"Authenticated as u/{me.name}"}
            except ImportError:
                return {"ok": False, "message": "praw not installed — run: pip install praw"}
            except Exception as exc:
                return {"ok": False, "message": str(exc)[:300]}

    @app.delete("/api/social/credentials/{platform}")
    async def delete_social_credentials(platform: str):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        ok = await _state.database.delete_social_credentials(platform)
        if not ok:
            raise HTTPException(404, f"No credentials for {platform}")
        return {"ok": True}
