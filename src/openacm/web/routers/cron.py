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



_VALID_ACTION_TYPES = {"run_skill", "run_routine", "analyze_patterns", "custom_command"}


def _validate_cron_expr(expr: str) -> bool:
    shortcuts = {"@hourly", "@daily", "@midnight", "@weekly", "@monthly"}
    if expr.strip() in shortcuts:
        return True
    return len(expr.strip().split()) == 5


def register_routes(app: FastAPI) -> None:
    # ─── API: Cron Scheduler ─────────────────────────────────

    @app.get("/api/cron/jobs")
    async def list_cron_jobs():
        """List all cron jobs."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        jobs = await _state.database.get_all_cron_jobs()
        return jobs

    @app.post("/api/cron/jobs")
    async def create_cron_job(request: Request):
        """Create a new cron job."""
        if not _state.database:
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

        job = await _state.database.create_cron_job(
            name=name,
            description=data.get("description", ""),
            cron_expr=cron_expr,
            action_type=action_type,
            action_payload=data.get("action_payload", {}),
            is_enabled=bool(data.get("is_enabled", True)),
            next_run=next_run,
        )
        # Reload scheduler in-memory jobs
        if _state.cron_scheduler:
            await _state.cron_scheduler._sync_jobs()
        return job

    @app.get("/api/cron/jobs/{job_id}")
    async def get_cron_job(job_id: int):
        """Get a single cron job."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        job = await _state.database.get_cron_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Cron job not found")
        return job

    @app.put("/api/cron/jobs/{job_id}")
    async def update_cron_job(job_id: int, request: Request):
        """Update a cron job."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        existing = await _state.database.get_cron_job(job_id)
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

        await _state.database.update_cron_job(job_id, **updates)
        if _state.cron_scheduler:
            await _state.cron_scheduler._sync_jobs()
        return await _state.database.get_cron_job(job_id)

    @app.delete("/api/cron/jobs/{job_id}")
    async def delete_cron_job(job_id: int):
        """Delete a cron job."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        ok = await _state.database.delete_cron_job(job_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Cron job not found")
        if _state.cron_scheduler:
            await _state.cron_scheduler._sync_jobs()
        return {"status": "ok", "deleted": job_id}

    @app.post("/api/cron/jobs/{job_id}/trigger")
    async def trigger_cron_job(job_id: int):
        """Immediately trigger a cron job."""
        if not _state.cron_scheduler:
            raise HTTPException(status_code=503, detail="Cron scheduler not running")
        result = await _state.cron_scheduler.trigger_now(job_id)
        return result

    @app.post("/api/cron/jobs/{job_id}/toggle")
    async def toggle_cron_job(job_id: int):
        """Toggle a cron job enabled/disabled."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        job = await _state.database.get_cron_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Cron job not found")
        new_state = not bool(job.get("is_enabled", 1))
        await _state.database.update_cron_job(job_id, is_enabled=new_state)
        if _state.cron_scheduler:
            await _state.cron_scheduler._sync_jobs()
        return {"status": "ok", "is_enabled": new_state}

    @app.get("/api/cron/runs")
    async def get_cron_runs(job_id: int | None = None, limit: int = 50):
        """Get cron job run history."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        runs = await _state.database.get_cron_runs(job_id=job_id, limit=min(limit, 200))
        return {"runs": runs}

    @app.get("/api/cron/status")
    async def get_cron_status():
        """Return scheduler running status and job summary."""
        if _state.cron_scheduler is None:
            return {"running": False, "job_count": 0, "enabled_count": 0,
                    "next_job_name": None, "next_job_at": None}
        jobs = list(_state.cron_scheduler._jobs.values())
        enabled = [j for j in jobs if j.is_enabled]
        next_job = _state.cron_scheduler.next_due_job()
        return {
            "running": _state.cron_scheduler.is_running,
            "job_count": len(jobs),
            "enabled_count": len(enabled),
            "next_job_name": next_job.name if next_job else None,
            "next_job_at": next_job.next_run if next_job else None,
        }

