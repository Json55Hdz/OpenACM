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



def register_routes(app: FastAPI) -> None:
    # ─── API: Skills ──────────────────────────────────────────

    @app.get("/api/skills")
    async def get_skills():
        """Get all skills with their status."""
        if not _state.brain or not _state.brain.skill_manager:
            return []
        skills = await _state.brain.skill_manager.get_all_skills()
        return skills

    @app.get("/api/skills/active")
    async def get_active_skills():
        """Get only active skills."""
        if not _state.brain or not _state.brain.skill_manager:
            return []
        skills = await _state.brain.skill_manager.get_all_skills()
        return [s for s in skills if s.get("is_active")]

    @app.post("/api/skills")
    async def create_skill(request: Request):
        """Create a new skill."""
        if not _state.brain or not _state.brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        data = await request.json()
        skill = await _state.brain.skill_manager.create_skill(
            name=data["name"],
            description=data["description"],
            content=data["content"],
            category=data.get("category", "custom"),
        )
        return skill

    @app.post("/api/skills/{skill_id}/toggle")
    async def toggle_skill(skill_id: int):
        """Toggle skill active status."""
        if not _state.brain or not _state.brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        result = await _state.brain.skill_manager.toggle_skill(skill_id)
        if not result:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"status": "ok", "toggled": True}

    @app.put("/api/skills/{skill_id}")
    async def update_skill(skill_id: int, request: Request):
        """Update a skill."""
        if not _state.brain or not _state.brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        data = await request.json()
        result = await _state.brain.skill_manager.update_skill(
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
        if not _state.brain or not _state.brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        result = await _state.brain.skill_manager.delete_skill(skill_id)
        if not result:
            raise HTTPException(status_code=404, detail="Skill not found or is built-in")
        return {"status": "ok", "deleted": True}

    @app.post("/api/skills/generate")
    async def generate_skill(request: Request):
        """Generate a new skill using LLM."""
        if not _state.brain or not _state.brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        data = await request.json()
        try:
            skill = await _state.brain.skill_manager.generate_skill(
                name=data["name"],
                description=data["description"],
                use_cases=data.get("use_cases", ""),
                llm_router=_state.brain.llm_router,
            )
            return skill
        except Exception as e:
            log.error("Failed to generate skill", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))

