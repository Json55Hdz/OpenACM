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

log = structlog.get_logger()



def register_routes(app: FastAPI) -> None:
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
        if not _state.brain or not _state.config:
            return []

        provider = _state.brain.llm_router._current_provider
        settings = _state.config.llm.providers.get(provider, {})
        base_url = settings.get("base_url")


        api_key_env = f"{provider.upper()}_API_KEY"
        api_key = os.environ.get(api_key_env, "")

        if provider == "openai" and not base_url:
            base_url = "https://api.openai.com/v1"
        elif provider == "ollama" and not base_url:
            base_url = DEFAULT_OLLAMA_BASE_URL + "/v1"

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
        if model and _state.brain:
            _state.brain.llm_router.set_model(model, provider=provider)
            # Persist model choice to database
            if _state.database:
                await _state.database.set_setting("llm.current_model", _state.brain.llm_router.current_model)
                await _state.database.set_setting("llm.current_provider", _state.brain.llm_router._current_provider)
            return {
                "status": "ok",
                "model": _state.brain.llm_router.current_model,
                "provider": _state.brain.llm_router._current_provider,
            }
        return {"status": "error", "message": "No model specified"}

    # ─── API: Conversations ───────────────────────────────────

    @app.get("/api/conversations")
    async def get_conversations():
        """Get recent conversations."""
        if not _state.database:
            return []
        stats = await _state.database.get_channel_stats()
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
        if not _state.database:
            return []
        return await _state.database.get_conversation(user_id, channel_id, limit)

    @app.delete("/api/conversations/{channel_id}/{user_id}")
    async def delete_conversation(channel_id: str, user_id: str):
        """Delete conversation history for a user/channel pair (memory + database)."""
        if not _state.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        # Clear in-memory cache
        await _state.brain.memory.clear(user_id, channel_id)
        # Delete from database so it doesn't reload on next access
        deleted_rows = 0
        if _state.database:
            deleted_rows = await _state.database.delete_conversation_messages(user_id, channel_id)
        return {"status": "ok", "deleted_rows": deleted_rows}

    # ─── API: Commands ────────────────────────────────────────

    @app.post("/api/chat/command")
    async def run_command(request: Request):
        """Execute a slash command via REST (used by dashboard buttons)."""
        if not _state.command_processor:
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

        result = await _state.command_processor.handle(cmd, args, user_id, channel_id)
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
        _state.chat_ws_clients.add(websocket)

        # Replay any response buffered while no client was connected
        if _state.pending_chat_response is not None:
            try:
                await websocket.send_json(_state.pending_chat_response)
                _state.pending_chat_response = None
            except Exception:
                pass

        # Auto-trigger Onboarding Greeting if disabled (even for existing users)
        # Note: at connect time we don't have the explicit target channel from the JSON payload, 
        # so we assume the default 'web' context.
        session_key = "web-web"
        if not _state.onboarding_triggered_flags.get(session_key, False):
            if _state.config and getattr(_state.config.assistant, "onboarding_completed", False) is False:
                if _state.brain and _state.database:
                    _state.onboarding_triggered_flags[session_key] = True
                    async def _trigger_onboarding_greeting():
                        _user = "web"
                        _channel = "web"
                        _channel_type = "web"
                        try:
                            # Determine if user is completely new or if this is a post-update flow
                            hist = await _state.database.get_conversation(_user, _channel, limit=1)
                            is_new_user = len(hist) == 0

                            if is_new_user:
                                user_instruction = "Introduce yourself as OpenACM. Be brief and natural — no bullet points, no agenda. Just say hi, mention what you are in one sentence, and ask the user their name casually at the end."
                            else:
                                user_instruction = "Greet the user. Mention briefly that after a system update you need to re-learn a few things about them. Then casually ask their name."

                            # Call the LLM directly — bypasses RAG recall and conversation history
                            # so stale memory can't pollute the first onboarding message.
                            onboarding_system = (
                                "[SETUP MODE]: You are meeting your user for the first time. "
                                "Be natural and conversational — no agendas, no lists, no robotic structure. "
                                "Collect their name, what they want to call you, and how they want you to behave "
                                "across the conversation, one thing at a time through normal chat. "
                                "Never announce that you have 'N questions' or a setup process."
                            )
                            # Let the frontend mount before sending the message
                            await asyncio.sleep(1.0)
                            result = await _state.brain.llm_router.chat(
                                messages=[
                                    {"role": "system", "content": onboarding_system},
                                    {"role": "user", "content": user_instruction},
                                ]
                            )
                            response = result.get("content", "")
                            from fastapi.websockets import WebSocketState
                            if websocket.client_state == WebSocketState.CONNECTED:
                                await websocket.send_json({
                                    "type": "onboarding.greeting",
                                    "content": response,
                                    "channel_id": _channel,
                                    "user_id": _user,
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
                    if _state.brain:
                        asyncio.create_task(_state.brain.process_message(
                            content="cancelar",
                            user_id=target_user,
                            channel_id=target_channel,
                            channel_type=target_type,
                        ))
                    continue

                if not content and not attachments:
                    continue

                # Intercept slash commands before sending to brain
                if content.startswith("/") and _state.command_processor:
                    parts = content.split(maxsplit=1)
                    cmd = parts[0]
                    args = parts[1] if len(parts) > 1 else ""
                    result = await _state.command_processor.handle(
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

                if _state.brain:
                    try:
                        # Snapshot usage counters before the call to compute per-turn delta
                        _router = _state.brain.llm_router if _state.brain else None
                        usage_before = _router.get_usage_snapshot() if _router else {}

                        response = await _state.brain.process_message(
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

                        payload = {
                            "type": "response",
                            "content": clean_response,
                            "attachments": attachment_names,
                            "usage": turn_usage,
                            "user_id": target_user,
                            "channel_id": target_channel,
                        }
                        delivered = False
                        # Try original connection first, then any other active client
                        for target in [websocket] + [c for c in _state.chat_ws_clients if c is not websocket]:
                            try:
                                await _safe_ws_send(target, payload)
                                delivered = True
                                break
                            except Exception:
                                continue
                        if not delivered:
                            # No live client at all — buffer for the next connect
                            _state.pending_chat_response = payload
                        if target is not websocket:
                            # Original WS is dead — exit its handler
                            return
                    except WebSocketDisconnect:
                        return
                    except Exception as e:
                        try:
                            await _safe_ws_send(websocket, {
                                "type": "error",
                                "content": str(e),
                                "user_id": target_user,
                                "channel_id": target_channel,
                            })
                        except (WebSocketDisconnect, Exception):
                            # Client already gone — nothing to do
                            return
                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "content": "Brain not available",
                            "user_id": target_user,
                            "channel_id": target_channel,
                        }
                    )
        except WebSocketDisconnect:
            pass
        finally:
            _state.chat_ws_clients.discard(websocket)

    # ─── WebSocket: Terminal ─────────────────────────────────

    @app.websocket("/ws/terminal")
    async def ws_terminal(websocket: WebSocket):
        """WebSocket endpoint for interactive terminal sessions — one persistent PTY per channel."""

        if not _verify_ws_token(websocket):
            await websocket.close(code=4001, reason="Unauthorized")
            return

        channel_id = websocket.query_params.get("channel", "web")
        await websocket.accept()

        # Get or create the persistent PTY shell for this channel
        shell = _state.channel_shells.get(channel_id)
        if not shell or not shell._alive:
            shell = ChannelShell(channel_id)
            try:
                await shell.start()
            except Exception as e:
                log.error("Failed to start PTY shell", channel=channel_id, error=str(e))
                await websocket.send_json({"type": "error", "data": f"Failed to start shell: {e}"})
                await websocket.close()
                return
            _state.channel_shells[channel_id] = shell

        shell.clients.add(websocket)

        # Prod the shell so the current prompt re-appears in the freshly connected xterm
        asyncio.create_task(shell.write("\r\n"))

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                if msg_type == "input":
                    data = msg.get("data", "")
                    await shell.write(data)
                    # Track printable commands in brain history
                    if _state.brain and hasattr(_state.brain, "terminal_history"):
                        cmd_clean = data.strip()
                        if cmd_clean and cmd_clean != "\n" and len(cmd_clean) > 1:
                            if _state.brain.terminal_history:
                                _state.brain.terminal_history[-1]["_closed"] = True
                            _state.brain.terminal_history.append({
                                "command": cmd_clean, "output": "", "_closed": False,
                            })
                            if len(_state.brain.terminal_history) > 30:
                                _state.brain.terminal_history[:] = _state.brain.terminal_history[-30:]

                elif msg_type == "chat_input":
                    # Route message to the LLM brain (chat mode in terminal)
                    if _state.brain:
                        text = msg.get("data", "").strip()
                        if text:
                            asyncio.create_task(
                                _state.brain.process_message(text, "web", channel_id, "web")
                            )

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
        _state.ws_clients.add(websocket)

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            _state.ws_clients.discard(websocket)

    # ─── API: Terminal ─────────────────────────────────────────

    @app.get("/api/terminal/history")
    async def get_terminal_history():
        """Get recent terminal command history (used by AI as context)."""
        if not _state.brain:
            return []
        history = [
            {"command": e.get("command", ""), "output": e.get("output", "")[:500]}
            for e in _state.brain.terminal_history[-20:]
            if e.get("command")
        ]
        return history

