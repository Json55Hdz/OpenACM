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
    # ─── Swarms ───────────────────────────────────────────────

    @app.get("/api/swarms")
    async def list_swarms():
        if not _state.database:
            return []
        return await _state.database.list_swarms()

    @app.post("/api/swarms")
    async def create_swarm(request: Request):
        """Create a swarm from multipart form data (name, goal, global_model, files)."""
        if not _state.swarm_manager:
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

        swarm = await _state.swarm_manager.create_swarm(
            name=name,
            goal=goal,
            file_contents=file_contents or None,
            global_model=global_model,
        )
        return swarm

    @app.get("/api/swarms/{swarm_id}")
    async def get_swarm(swarm_id: int):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        swarm = await _state.database.get_swarm(swarm_id)
        if not swarm:
            raise HTTPException(404, "Swarm not found")
        workers = await _state.database.get_swarm_workers(swarm_id)
        tasks = await _state.database.get_swarm_tasks(swarm_id)
        return {**swarm, "workers": workers, "tasks": tasks}

    @app.delete("/api/swarms/{swarm_id}")
    async def delete_swarm(swarm_id: int):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        ok = await _state.database.delete_swarm(swarm_id)
        if not ok:
            raise HTTPException(404, "Swarm not found")
        return {"ok": True}

    @app.post("/api/swarms/{swarm_id}/plan")
    async def plan_swarm(swarm_id: int):
        if not _state.swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        swarm = await _state.database.get_swarm(swarm_id)
        if not swarm:
            raise HTTPException(404, "Swarm not found")
        try:
            result = await _state.swarm_manager.plan_swarm(swarm_id)
        except Exception as exc:
            raise HTTPException(500, detail=str(exc)) from exc
        workers = await _state.database.get_swarm_workers(swarm_id)
        tasks = await _state.database.get_swarm_tasks(swarm_id)
        return {**result, "workers": workers, "tasks": tasks}

    @app.post("/api/swarms/{swarm_id}/start")
    async def start_swarm(swarm_id: int):
        if not _state.swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        swarm = await _state.database.get_swarm(swarm_id)
        if not swarm:
            raise HTTPException(404, "Swarm not found")
        if swarm["status"] not in ("planned", "paused"):
            raise HTTPException(400, f"Cannot start swarm in '{swarm['status']}' status. Plan it first.")
        await _state.swarm_manager.start_swarm(swarm_id)
        return {"ok": True, "status": "running"}

    @app.post("/api/swarms/{swarm_id}/stop")
    async def stop_swarm(swarm_id: int):
        if not _state.swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        await _state.swarm_manager.stop_swarm(swarm_id)
        return {"ok": True, "status": "paused"}

    @app.put("/api/swarms/{swarm_id}/workers/{worker_id}")
    async def update_swarm_worker(swarm_id: int, worker_id: int, request: Request):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        body = await request.json()
        allowed = {"name", "role", "description", "system_prompt", "model", "allowed_tools"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            raise HTTPException(400, "No valid fields to update")
        await _state.database.update_swarm_worker(worker_id, **updates)
        workers = await _state.database.get_swarm_workers(swarm_id)
        return next((w for w in workers if w["id"] == worker_id), {})

    @app.get("/api/swarms/{swarm_id}/messages")
    async def get_swarm_messages(swarm_id: int):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        return await _state.database.get_swarm_messages(swarm_id)

    @app.post("/api/swarms/{swarm_id}/complete")
    async def complete_swarm(swarm_id: int):
        """Mark a swarm as completed (user-initiated)."""
        if not _state.database:
            raise HTTPException(503, "Database not available")
        swarm = await _state.database.get_swarm(swarm_id)
        if not swarm:
            raise HTTPException(404, "Swarm not found")
        await _state.database.update_swarm(swarm_id, status="completed")
        if _state.swarm_manager:
            await _state.swarm_manager._emit_swarm_event(swarm_id, "completed", {"manual": True})
        return {"ok": True, "status": "completed"}

    @app.post("/api/swarms/{swarm_id}/message")
    async def post_swarm_message(swarm_id: int, request: Request):
        """Send a user message to the swarm (feedback, new instructions, etc.)."""
        if not _state.swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        body = await request.json()
        message = str(body.get("message", "")).strip()
        if not message:
            raise HTTPException(400, "message is required")
        result = await _state.swarm_manager.send_user_message(swarm_id, message)
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
                swarm = await _state.database.get_swarm(swarm_id) if _state.database else None
                workers = await _state.database.get_swarm_workers(swarm_id) if _state.database else []
                tasks = await _state.database.get_swarm_tasks(swarm_id) if _state.database else []
                messages = await _state.database.get_swarm_messages(swarm_id) if _state.database else []
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
        if not _state.database:
            return []
        items = await _state.database.get_content_queue(status=status or None, limit=limit)
        pending_count = await _state.database.count_pending_content()
        return {"items": items, "pending_count": pending_count}

    @app.post("/api/content/queue/{item_id}/approve")
    async def approve_content(item_id: int):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        item = await _state.database.get_content_item(item_id)
        if not item:
            raise HTTPException(404, "Content item not found")
        await _state.database.update_content_status(item_id, "approved")
        await broadcast_event("content:approved", {"item_id": item_id})
        return {"ok": True, "status": "approved"}

    @app.post("/api/content/queue/{item_id}/reject")
    async def reject_content(item_id: int):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        item = await _state.database.get_content_item(item_id)
        if not item:
            raise HTTPException(404, "Content item not found")
        await _state.database.update_content_status(item_id, "rejected")
        await broadcast_event("content:rejected", {"item_id": item_id})
        return {"ok": True, "status": "rejected"}

    @app.delete("/api/content/queue/{item_id}")
    async def delete_content_item(item_id: int):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        ok = await _state.database.delete_content_item(item_id)
        if not ok:
            raise HTTPException(404, "Content item not found")
        return {"ok": True}

    @app.get("/api/content/pending-count")
    async def content_pending_count():
        if not _state.database:
            return {"count": 0}
        count = await _state.database.count_pending_content()
        return {"count": count}

    @app.get("/api/content/sessions")
    async def list_content_sessions(date: str = ""):
        import re as _re
        from pathlib import Path as _Path
        workspace = _Path(os.environ.get("OPENACM_WORKSPACE", "workspace"))
        base = workspace / "content" / "sessions"
        if not base.exists():
            return {"dates": [], "sessions": []}
        if date:
            if not _re.match(r'^\d{4}-\d{2}-\d{2}$', date):
                raise HTTPException(status_code=400, detail="Invalid date format")
            session_dir = (base / date).resolve()
            if not session_dir.is_relative_to(base.resolve()):
                raise HTTPException(status_code=400, detail="Invalid date format")
            if not session_dir.exists():
                return {"dates": [], "sessions": []}
            sessions = []
            for f in sorted(session_dir.glob("*.json")):
                try:
                    sessions.append(json.loads(f.read_text()))
                except Exception:
                    pass
            return {"dates": [date], "sessions": sessions}
        dates = sorted(d.name for d in base.iterdir() if d.is_dir())
        return {"dates": dates, "sessions": []}

