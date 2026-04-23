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
        working_path = str(form.get("working_path", "")).strip() or ""

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
            working_path=working_path,
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

    @app.post("/api/swarms/{swarm_id}/clarify")
    async def clarify_swarm(swarm_id: int):
        """Run the clarification phase: LLM reviews context and generates questions for the user."""
        if not _state.swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        swarm = await _state.database.get_swarm(swarm_id)
        if not swarm:
            raise HTTPException(404, "Swarm not found")
        try:
            questions = await _state.swarm_manager.clarify_swarm(swarm_id)
        except Exception as exc:
            raise HTTPException(500, detail=str(exc)) from exc
        return {"questions": questions, "swarm_id": swarm_id}

    @app.post("/api/swarms/{swarm_id}/clarify/answer")
    async def submit_clarification(swarm_id: int, request: Request):
        """Submit user answers to clarification questions, then trigger planning.

        Accepts multipart form data so additional context files can be uploaded alongside answers.
        Form fields: answers (JSON string of [{question, answer}]), files (optional).
        """
        if not _state.swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        swarm = await _state.database.get_swarm(swarm_id)
        if not swarm:
            raise HTTPException(404, "Swarm not found")

        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            form = await request.form()
            answers_raw = str(form.get("answers", "[]"))
            file_contents: list[dict] = []
            for field_name, field_value in form.multi_items():
                if hasattr(field_value, "read"):
                    raw = await field_value.read()
                    try:
                        content = raw.decode("utf-8", errors="replace")
                    except Exception:
                        content = "(binary — skipped)"
                    file_contents.append({"filename": field_value.filename or field_name, "content": content})
        else:
            body = {}
            try:
                body = await request.json()
            except Exception:
                pass
            answers_raw = json.dumps(body.get("answers", []))
            file_contents = []

        # Parse [{question, answer}] pairs and format them into readable text
        try:
            pairs = json.loads(answers_raw)
        except Exception:
            pairs = []

        formatted_answers = "\n\n".join(
            f"Q: {p.get('question', '?')}\nA: {p.get('answer', '(no answer given)')}"
            for p in pairs
            if p.get("answer", "").strip()
        )

        # If extra files were uploaded, append their content to shared_context
        if file_contents:
            existing_ctx = (swarm.get("shared_context") or "").strip()
            existing_files = json.loads(swarm.get("context_files") or "[]")
            swarm_dir = Path(swarm["workspace_path"])
            context_dir = swarm_dir / "context"
            context_dir.mkdir(parents=True, exist_ok=True)
            new_parts: list[str] = []
            for f in file_contents:
                fname = f["filename"]
                (context_dir / fname).write_text(f["content"], encoding="utf-8", errors="replace")
                existing_files.append(fname)
                new_parts.append(f"### {fname}\n{f['content']}")
            new_ctx = (existing_ctx + "\n\n" + "\n\n".join(new_parts)).strip()
            await _state.database.update_swarm(
                swarm_id,
                shared_context=new_ctx,
                context_files=json.dumps(existing_files),
            )

        await _state.database.update_swarm(swarm_id, clarification_answers=formatted_answers)

        # Now plan — the answers are injected into the plan prompt automatically
        try:
            result = await _state.swarm_manager.plan_swarm(swarm_id)
        except Exception as exc:
            raise HTTPException(500, detail=str(exc)) from exc
        workers = await _state.database.get_swarm_workers(swarm_id)
        tasks = await _state.database.get_swarm_tasks(swarm_id)
        return {**result, "workers": workers, "tasks": tasks}

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
    async def start_swarm(swarm_id: int, force: bool = False):
        if not _state.swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        swarm = await _state.database.get_swarm(swarm_id)
        if not swarm:
            raise HTTPException(404, "Swarm not found")
        startable = {"planned", "paused", "failed"}
        if force:
            startable.add("running")  # allow force-restart of stuck swarms
        if swarm["status"] not in startable:
            raise HTTPException(400, f"Cannot start swarm in '{swarm['status']}' status. Plan it first.")
        # Reset failed/stuck-running swarms back to paused before starting
        if swarm["status"] in ("failed", "running") and force or swarm["status"] == "failed":
            await _state.database.update_swarm(swarm_id, status="paused")
        await _state.swarm_manager.start_swarm(swarm_id)
        return {"ok": True, "status": "running"}

    @app.post("/api/swarms/{swarm_id}/tasks/{task_id}/retry")
    async def retry_swarm_task(swarm_id: int, task_id: int, request: Request):
        """Reset a failed task to pending, optionally with user guidance injected into context."""
        if not _state.database or not _state.swarm_manager:
            raise HTTPException(503, "Services not available")
        task = await _state.database.get_swarm_task(task_id)
        if not task or task["swarm_id"] != swarm_id:
            raise HTTPException(404, "Task not found")
        if task["status"] not in ("failed",):
            raise HTTPException(400, f"Task is '{task['status']}' — only failed tasks can be retried")

        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        user_notes = (body.get("user_notes") or "").strip()

        # Save current failed result into retry history before resetting
        import json as _rj
        prev_result = task.get("result") or ""
        prev_fail = (task.get("result") or "")[:200]
        new_entry: dict = {"result": prev_result, "fail_reason": "Manually retried by user"}
        if user_notes:
            new_entry["user_notes"] = user_notes
        try:
            existing = _rj.loads(task.get("retry_history_json") or "[]")
        except Exception:
            existing = []
        history_json = _rj.dumps(existing + [new_entry])

        # Reset this task and any cascade-failed dependents
        all_tasks = await _state.database.get_swarm_tasks(swarm_id)
        to_reset = [task]
        for t in all_tasks:
            if t["status"] == "failed" and f"'{task['title']}'" in (t.get("result") or ""):
                to_reset.append(t)
        for t in to_reset:
            await _state.database.update_swarm_task(
                t["id"], status="pending", result=None,
                retry_history_json=history_json if t["id"] == task_id else t.get("retry_history_json", "[]"),
            )

        # Clear retry counter so it gets full retries again
        if hasattr(_state.swarm_manager, "_task_retries"):
            _state.swarm_manager._task_retries.get(swarm_id, {}).pop(task_id, None)

        # Resume swarm
        swarm = await _state.database.get_swarm(swarm_id)
        if swarm and swarm["status"] in ("paused", "failed", "idle"):
            await _state.database.update_swarm(swarm_id, status="paused")
            await _state.swarm_manager.start_swarm(swarm_id)
        return {"ok": True, "reset_tasks": [t["title"] for t in to_reset]}

    @app.post("/api/swarms/{swarm_id}/tasks/{task_id}/complete")
    async def manually_complete_task(swarm_id: int, task_id: int, request: Request):
        """Mark a failed task as completed with a user-provided result.

        Use this when you want to do the work yourself and let the swarm continue
        with the dependent tasks using your result as their input.
        """
        if not _state.database or not _state.swarm_manager:
            raise HTTPException(503, "Services not available")
        task = await _state.database.get_swarm_task(task_id)
        if not task or task["swarm_id"] != swarm_id:
            raise HTTPException(404, "Task not found")
        if task["status"] not in ("failed", "pending"):
            raise HTTPException(400, f"Task is '{task['status']}' — can only manually complete failed/pending tasks")

        body = await request.json()
        result = (body.get("result") or "").strip()
        if not result:
            raise HTTPException(400, "result is required")

        result_with_marker = result if "TASK_STATUS:" in result else f"{result}\n\nTASK_STATUS: COMPLETED"
        await _state.database.update_swarm_task(
            task_id, status="completed", result=result_with_marker,
        )
        # Unblock cascade-failed dependents
        all_tasks = await _state.database.get_swarm_tasks(swarm_id)
        unblocked = []
        for t in all_tasks:
            if t["status"] == "failed" and f"'{task['title']}'" in (t.get("result") or ""):
                await _state.database.update_swarm_task(t["id"], status="pending", result=None)
                unblocked.append(t["title"])

        # Resume swarm
        swarm = await _state.database.get_swarm(swarm_id)
        if swarm and swarm["status"] in ("paused", "failed", "idle"):
            await _state.database.update_swarm(swarm_id, status="paused")
            await _state.swarm_manager.start_swarm(swarm_id)
        return {"ok": True, "task": task["title"], "unblocked": unblocked}

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

    @app.post("/api/swarms/{swarm_id}/check-reuse")
    async def check_reuse(swarm_id: int, request: Request):
        """Check whether the existing worker team is suitable for a new goal before resetting."""
        if not _state.swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        new_goal = (body.get("goal") or "").strip()
        if not new_goal:
            return {"compatible": True, "reason": "", "suggestion": ""}
        try:
            result = await _state.swarm_manager.check_reuse_compatibility(swarm_id, new_goal)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return result

    @app.post("/api/swarms/{swarm_id}/reset")
    async def reset_swarm(swarm_id: int, request: Request):
        """Reset a swarm for re-use: keeps workers/task definitions, resets results to pending.
        Accepts multipart form data so new context files can be uploaded alongside goal changes."""
        if not _state.swarm_manager:
            raise HTTPException(503, "Swarm manager not initialized")

        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            form = await request.form()
            goal = str(form.get("goal", "")).strip() or None
            working_path = str(form.get("working_path", "")).strip() or None
            file_contents: list[dict] | None = []
            for field_name, field_value in form.multi_items():
                if hasattr(field_value, "read"):
                    raw = await field_value.read()
                    try:
                        content = raw.decode("utf-8", errors="replace")
                    except Exception:
                        content = "(binary file — skipped)"
                    file_contents.append({"filename": field_value.filename or field_name, "content": content})
            if not file_contents:
                file_contents = None
        else:
            body = {}
            try:
                body = await request.json()
            except Exception:
                pass
            goal = (body.get("goal") or "").strip() or None
            working_path = (body.get("working_path") or "").strip() or None
            file_contents = None

        try:
            updated = await _state.swarm_manager.reset_swarm(
                swarm_id, goal=goal, file_contents=file_contents, working_path=working_path,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return updated

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
            import os as _os
            base_root = _os.path.realpath(base) + _os.sep
            session_real = _os.path.realpath(base / date)
            if not session_real.startswith(base_root):
                raise HTTPException(status_code=400, detail="Invalid date format")
            session_dir = _Path(session_real)
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

