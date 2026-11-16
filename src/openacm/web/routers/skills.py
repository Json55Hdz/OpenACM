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

    # ─── Skill marketplace ────────────────────────────────────

    async def _catalog_url() -> str:
        from openacm.core.skill_market import DEFAULT_CATALOG_URL

        if _state.database:
            custom = await _state.database.get_setting("skills.marketplace_url")
            if custom:
                return custom
        return DEFAULT_CATALOG_URL

    @app.get("/api/skills/marketplace")
    async def skills_marketplace():
        """The community catalog, marking which skills are already installed."""
        from openacm.core.skill_market import MarketError, fetch_catalog

        url = await _catalog_url()
        installed = set()
        if _state.brain and _state.brain.skill_manager:
            installed = {s["name"] for s in await _state.brain.skill_manager.get_all_skills()}
        try:
            items = await fetch_catalog(url)
            error = ""
        except MarketError as exc:
            items, error = [], str(exc)
        for it in items:
            it["installed"] = it["name"] in installed
        return {"catalog_url": url, "skills": items, "error": error}

    @app.post("/api/skills/market/preview")
    async def skills_market_preview(request: Request):
        """Read a skill from a link (or from pasted text) and report what is in it. Installs nothing."""
        from openacm.core.skill_market import MarketError, fetch_skill, parse_skill

        data = await request.json()
        try:
            if data.get("url"):
                parsed = await fetch_skill(str(data["url"]), sha256=data.get("sha256") or None)
            elif isinstance(data.get("content"), str):
                parsed = parse_skill(data["content"])
            else:
                raise MarketError("Indica una url o pega el contenido de la skill.")
        except MarketError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        exists = bool(_state.brain and _state.brain.skill_manager
                      and await _state.brain.skill_manager.get_skill_by_name(parsed.name))
        return {**parsed.as_dict(), "already_installed": exists}

    @app.post("/api/skills/market/install")
    async def skills_market_install(request: Request):
        """Install what the owner just previewed. Body: {content, sha256, confirm_name}."""
        from openacm.core.skill_market import MarketError, parse_skill

        if not _state.brain or not _state.brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        data = await request.json()
        content = data.get("content")
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail="Falta el contenido.")
        try:
            parsed = parse_skill(content)
        except MarketError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # What is installed is exactly what was shown: the approval carries the hash of the preview
        if str(data.get("sha256", "")).lower() != parsed.sha256:
            raise HTTPException(status_code=409, detail="El contenido cambió desde la vista previa. Vuelve a revisarlo.")
        if parsed.risky and str(data.get("confirm_name", "")).strip() != parsed.name:
            raise HTTPException(status_code=400, detail=f"Esta skill tiene hallazgos graves: escribe «{parsed.name}» para confirmar.")
        if await _state.brain.skill_manager.get_skill_by_name(parsed.name):
            raise HTTPException(status_code=409, detail=f"Ya existe una skill llamada {parsed.name}.")
        skill = await _state.brain.skill_manager.create_skill(
            name=parsed.name, description=parsed.description, content=parsed.content,
            category=parsed.category, source="market",
        )
        log.info("Skill installed from the marketplace", name=parsed.name, sha256=parsed.sha256, risky=parsed.risky)
        return {"ok": True, "skill": skill}

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
            raise HTTPException(status_code=500, detail="Failed to generate skill")

