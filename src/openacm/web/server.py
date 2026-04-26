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
import datetime
import os
import re
import secrets
import signal
import uuid
import json
import yaml

from openacm.constants import DEFAULT_WEB_PORT, DEFAULT_OLLAMA_BASE_URL, TRUNCATE_RAG_CONTEXT_CHARS
from openacm.utils.text import truncate
from openacm.core.config import AppConfig
from openacm.core.brain import Brain
from openacm.core.commands import CommandProcessor
from openacm.core.events import EventBus
from openacm.storage.database import Database
from openacm.tools.registry import ToolRegistry
from openacm.web.state import ServerState, _state
from openacm.web.shell import ChannelShell
from openacm.web.broadcast import broadcast_event, _safe_ws_send, _broadcast_to_terminal

log = structlog.get_logger()

_TERMINAL_TOOLS = {"run_command", "run_python", "python_kernel", "execute_command"}


async def request_tool_confirmation(tool: str, command: str, channel_id: str) -> bool:
    """Emit a confirmation request event and block until the user approves or denies."""
    # Check if this command was already approved for the whole session.
    if command in _state.session_allowed_commands:
        return True

    confirm_id = str(uuid.uuid4())[:8]
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _state.pending_confirmations[confirm_id] = future

    if _state.event_bus:
        await _state.event_bus.emit(
            "tool.confirmation_needed",
            {
                "confirm_id": confirm_id,
                "tool": tool,
                "command": command,
                "channel_id": channel_id,
            },
        )

    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=300.0)
    except asyncio.TimeoutError:
        return False
    finally:
        _state.pending_confirmations.pop(confirm_id, None)


# ─── Custom Provider Helpers (module-level so create_web_server can call them) ──

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
    if not _state.config:
        return
    for p in providers:
        pid = p["id"]
        _state.custom_provider_ids.add(pid)
        _state.config.llm.providers[pid] = {
            "base_url": p["base_url"],
            "default_model": p.get("default_model", ""),
        }
        api_key = p.get("api_key", "")
        if api_key:
            os.environ[f"{pid.upper()}_API_KEY"] = api_key


def _make_provider_id(name: str, existing: list[dict]) -> str:
    """Turn a human name into a unique snake_case provider ID."""
    pid = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
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


    # Register all route domains
    from openacm.web.routers import system, config, chat, skills, agents, mcp, activity, cron, swarms, voice as voice_router
    from openacm.voice import TTSRouter

    system.register_routes(app)
    config.register_routes(app)
    chat.register_routes(app)
    skills.register_routes(app)
    agents.register_routes(app)
    mcp.register_routes(app)
    activity.register_routes(app)
    cron.register_routes(app)
    swarms.register_routes(app)
    voice_router.register_routes(app, tts_router=TTSRouter(database=_state.database))

    # Plugin API routes (before SPA catch-all)
    try:
        from openacm.plugins import plugin_manager
        for router in plugin_manager.get_api_routers():
            app.include_router(router, prefix="/api")
    except Exception as exc:
        log.warning("Failed to mount plugin API routers", error=str(exc))

    # SPA catch-all MUST be last — any earlier registration intercepts API routes.
    # Serve actual files from the static dir first (Next.js RSC payloads, page HTMLs, etc.),
    # then fall back to index.html for unknown SPA routes.
    @app.api_route("/{full_path:path}", methods=["GET", "HEAD", "POST", "OPTIONS"], response_class=HTMLResponse)
    async def serve_spa(full_path: str):
        import os as _os
        static_root = _os.path.realpath(static_dir) + _os.sep
        candidate_real = _os.path.realpath(static_dir / full_path)
        # Reject any path that escapes the static directory
        if not candidate_real.startswith(static_root):
            candidate_real = _os.path.realpath(static_dir)
        from pathlib import Path as _Path
        candidate = _Path(candidate_real)
        if candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        # Try with trailing index.html (e.g. /dashboard/ → /dashboard/index.html)
        if candidate.is_dir():
            idx = candidate / "index.html"
            if idx.exists():
                return FileResponse(str(idx))
        # Fall back to SPA root for unknown client-side routes
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return HTMLResponse("<h1>OpenACM</h1><p>Static files not found. Run build first.</p>")

    return app


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
    voice_daemon=None,
) -> uvicorn.Server:
    """Create and start the web server."""
    _state.brain = brain
    _state.database = database
    _state.event_bus = event_bus
    _state.tool_registry = tool_registry
    _state.activity_watcher = activity_watcher
    _state.cron_scheduler = cron_scheduler
    _state.swarm_manager = swarm_manager
    _state.content_watcher = content_watcher
    _state.voice_daemon = voice_daemon
    _state.config = config
    _state.command_processor = CommandProcessor(brain, database)
    _state.channels = channels or []
    _state.agent_bot_manager = agent_bot_manager
    _state.mcp_manager = mcp_manager

    # Load and apply user-defined custom providers on startup
    _apply_custom_providers(_load_custom_providers())

    # Inject the confirmation callback so tools can request user approval
    tool_registry.confirm_callback = request_tool_confirmation

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
        EVENT_TOOL_CONFIRMATION,
        EVENT_SKILL_ACTIVE,
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
        EVENT_TOOL_CONFIRMATION,
        EVENT_SKILL_ACTIVE,
        "memory.recall",
        "memory.compacted",
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
        # Voice daemon state changes
        "voice:daemon_state",
    ]:
        event_bus.on(evt, on_event)

    # Handle server-side voice utterances → brain → broadcast response
    async def on_voice_utterance(event_type: str, data: dict[str, Any]):
        import random as _random
        text = data.get("text", "")
        if not text.strip() or not _state.brain:
            return

        # Show user's spoken message in all connected browser chat windows
        user_payload = {
            "type":       "voice_user_message",
            "content":    text,
            "channel_id": "web",
            "user_id":    "web",
        }
        _dead: set = set()
        for client in list(_state.chat_ws_clients):
            try:
                await _safe_ws_send(client, user_payload)
            except Exception:
                _dead.add(client)
        _state.chat_ws_clients -= _dead

        # Quick acknowledgment so the user hears something immediately while the LLM thinks.
        # speak_quiet() plays without changing daemon state — the lock serializes it with
        # the real speak() call that follows, so they never overlap.
        _daemon = _state.voice_daemon
        if _daemon and _daemon.is_running:
            from openacm.voice.voice_daemon import _ACKS
            asyncio.create_task(_daemon.speak_quiet(_random.choice(_ACKS)))

        # Process through brain (same pipeline as typed web chat)
        try:
            response = await _state.brain.process_message(
                content=text,
                user_id="web",
                channel_id="web",
                channel_type="web",
            )
        except Exception as exc:
            log.error("Voice utterance processing failed", error=str(exc))
            # Restore daemon listening state even on error
            if _daemon and _daemon.is_running:
                asyncio.create_task(_daemon.speak(""))
            return

        # If edge-tts is installed the daemon will speak on the server's speakers.
        # If absent the daemon is silent and the browser handles TTS via voice_response event.
        from openacm.voice.voice_daemon import VoiceDaemon
        edge_tts_ok = VoiceDaemon.edge_tts_available()
        resp_payload = {
            "type":               "voice_response",
            "content":            response or "",
            "channel_id":         "web",
            "user_id":            "web",
            "browser_tts_needed": not edge_tts_ok,
        }
        # speak() handles both the audio and state restoration (including the empty-response case)
        if _daemon and _daemon.is_running:
            asyncio.create_task(_daemon.speak(response or ""))
        _dead2: set = set()
        for client in list(_state.chat_ws_clients):
            try:
                await _safe_ws_send(client, resp_payload)
            except Exception:
                _dead2.add(client)
        _state.chat_ws_clients -= _dead2

    event_bus.on("voice:utterance", on_voice_utterance)

    # Mirror AI tool calls to the correct channel's terminal
    async def on_tool_called(event_type: str, data: dict[str, Any]):
        tool_name = data.get("tool", "")
        if tool_name not in _TERMINAL_TOOLS:
            return
        channel_id = data.get("channel_id", "web")
        args_raw = data.get("arguments", "")
        try:
            import json as _j
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            command = args.get("command") or args.get("code") or args_raw
        except Exception:
            command = str(args_raw)
        await _broadcast_to_terminal({
            "type": "ai_command",
            "tool": tool_name,
            "data": str(command),
        }, channel_id=channel_id)

    event_bus.on(EVENT_TOOL_CALLED, on_tool_called)

    # Broadcast tool confirmation requests to the terminal so the user can see them there too
    async def on_tool_confirmation(event_type: str, data: dict[str, Any]):
        channel_id = data.get("channel_id", "web")
        confirm_id = data.get("confirm_id", "")
        tool_name = data.get("tool", "")
        command = data.get("command", "")
        await _broadcast_to_terminal(
            {
                "type": "tool_confirm",
                "confirm_id": confirm_id,
                "tool": tool_name,
                "data": command,
            },
            channel_id=channel_id,
        )

    event_bus.on(EVENT_TOOL_CONFIRMATION, on_tool_confirmation)

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

    # Mirror LLM text responses to the terminal so the conversation is visible there
    async def on_message_sent(event_type: str, data: dict[str, Any]):
        channel_id = data.get("channel_id", "web")
        content = data.get("content", "")
        if not content or not content.strip():
            return
        await _broadcast_to_terminal(
            {"type": "ai_text", "data": content},
            channel_id=channel_id,
        )

    event_bus.on(EVENT_MESSAGE_SENT, on_message_sent)

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