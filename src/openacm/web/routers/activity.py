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
from openacm.web.broadcast import broadcast_event, _safe_ws_send, _broadcast_to_terminal

log = structlog.get_logger()



def _routine_cron_expr(trigger_data: dict) -> str:
    """Build a cron expression from a routine's trigger_data dict."""
    hour = int(trigger_data.get("hour", 9))
    minute = int(trigger_data.get("minute", 0))
    days = trigger_data.get("days_of_week", [])
    if days:
        cron_days = ",".join(str((d + 1) % 7) for d in sorted(days))
        return f"{minute} {hour} * * {cron_days}"
    return f"{minute} {hour} * * *"


def register_routes(app: FastAPI) -> None:
    # ─── API: Routines ───────────────────────────────────────

    @app.get("/api/routines")
    async def get_routines():
        """List all detected routines."""
        if not _state.database:
            return []
        return await _state.database.get_all_routines()

    @app.post("/api/routines/{routine_id}/execute")
    async def execute_routine(routine_id: int):
        """Execute a routine (launch its apps)."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        routine = await _state.database.get_routine(routine_id)
        if not routine:
            raise HTTPException(status_code=404, detail="Routine not found")
        try:
            from openacm.watchers.routine_executor import RoutineExecutor
            executor = RoutineExecutor()
            results = await executor.execute(routine)
            await _state.database.record_routine_run(routine_id)
            return {"status": "ok", "results": results}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.put("/api/routines/{routine_id}")
    async def update_routine(routine_id: int, request: Request):
        """Update a routine (name, status, trigger_data, apps).
        Auto-creates or deletes a cron job when the status changes to/from active."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")

        current = await _state.database.get_routine(routine_id)
        if not current:
            raise HTTPException(status_code=404, detail="Routine not found")

        data = await request.json()
        allowed = {"name", "status", "trigger_type", "trigger_data", "apps"}
        kwargs = {k: v for k, v in data.items() if k in allowed}
        if "trigger_data" in kwargs and isinstance(kwargs["trigger_data"], dict):
            kwargs["trigger_data"] = json.dumps(kwargs["trigger_data"])
        if "apps" in kwargs and isinstance(kwargs["apps"], list):
            kwargs["apps"] = json.dumps(kwargs["apps"])

        ok = await _state.database.update_routine(routine_id, **kwargs)
        if not ok:
            raise HTTPException(status_code=404, detail="Routine not found")

        updated = await _state.database.get_routine(routine_id)

        # ── Auto cron management on activate / deactivate ─────────────────────
        new_status = kwargs.get("status", current.get("status"))
        old_status = current.get("status")

        if _state.cron_scheduler and new_status != old_status:
            if new_status in ("inactive", "pending") and old_status == "active":
                # Delete the cron job that was driving this routine
                existing_cron_id = current.get("cron_job_id")
                if existing_cron_id:
                    await _state.database.delete_cron_job(int(existing_cron_id))
                    await _state.database.update_routine(routine_id, cron_job_id=None)
                    await _state.cron_scheduler._sync_jobs()
                    updated = await _state.database.get_routine(routine_id)

            elif new_status == "active":
                # Create a cron job if the trigger is time-based
                trigger_type = updated.get("trigger_type", "manual")
                if trigger_type == "time_based":
                    try:
                        trigger_data = json.loads(updated.get("trigger_data") or "{}")
                        cron_expr = _routine_cron_expr(trigger_data)
                        job = await _state.database.create_cron_job(
                            name=f"Rutina: {updated.get('name', 'Rutina')}",
                            description=f"Ejecuta automáticamente la rutina #{routine_id}",
                            cron_expr=cron_expr,
                            action_type="run_routine",
                            action_payload={"routine_id": routine_id},
                            is_enabled=True,
                        )
                        if job:
                            await _state.database.update_routine(routine_id, cron_job_id=job["id"])
                            await _state.cron_scheduler._sync_jobs()
                            updated = await _state.database.get_routine(routine_id)
                    except Exception as _exc:
                        log.warning("Failed to create cron job for routine", error=str(_exc))

        return updated

    @app.delete("/api/routines/{routine_id}")
    async def delete_routine(routine_id: int):
        """Delete a routine."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        ok = await _state.database.delete_routine(routine_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Routine not found")
        return {"status": "ok", "deleted": routine_id}

    @app.post("/api/routines/analyze")
    async def analyze_routines():
        """Trigger pattern analysis and return newly created routines."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        try:
            from openacm.watchers.pattern_analyzer import PatternAnalyzer
            llm = _state.brain.llm_router if _state.brain else None
            analyzer = PatternAnalyzer(_state.database, llm_router=llm)
            new_routines = await analyzer.analyze()
            return {"status": "ok", "new_routines": len(new_routines), "routines": new_routines}
        except Exception as exc:
            log.error("Pattern analysis failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))

    # ─── API: Activity Stats ─────────────────────────────────

    @app.get("/api/activity/stats")
    async def get_activity_stats():
        """Return per-app usage stats, total hours tracked, and session count."""
        if not _state.database:
            return {"apps": [], "total_hours": 0, "session_count": 0}
        app_stats = await _state.database.get_app_stats()
        total_hours = await _state.database.get_activity_hours()
        session_count = await _state.database.get_activity_count()
        return {
            "apps": app_stats,
            "total_hours": round(total_hours, 2),
            "session_count": session_count,
        }

    @app.get("/api/activity/sessions")
    async def get_recent_sessions(limit: int = 30):
        """Return recent app focus sessions."""
        if not _state.database:
            return []
        return await _state.database.get_recent_app_sessions(limit)

    @app.get("/api/watcher/status")
    async def get_watcher_status():
        """Return activity watcher running status and encryption info."""
        encrypted = _state.database._enc is not None if _state.database else False
        key_path = _state.database._enc.key_path if (encrypted and _state.database) else None
        if _state.activity_watcher is None:
            return {"running": False, "current_app": None, "sessions_recorded": 0,
                    "encrypted": encrypted, "key_path": key_path}
        return {
            "running": _state.activity_watcher.is_running,
            "current_app": _state.activity_watcher.current_app,
            "current_title": _state.activity_watcher.current_title,
            "sessions_recorded": _state.activity_watcher.sessions_recorded,
            "encrypted": encrypted,
            "key_path": key_path,
        }

