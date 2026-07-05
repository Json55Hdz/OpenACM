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
from openacm.constants import TRUNCATE_RAG_CONTEXT_CHARS
from openacm.utils.text import truncate

log = structlog.get_logger()



def register_routes(app: FastAPI) -> None:
    # ─── API: Agents ──────────────────────────────────────────

    def _agent_public(agent: dict) -> dict:
        """Strip webhook_secret from agent dict before sending to frontend."""
        a = dict(agent)
        a.pop("webhook_secret", None)
        return a

    @app.get("/api/agents")
    async def get_agents():
        """List all agents."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agents = await _state.database.get_all_agents()
        return [_agent_public(a) for a in agents]

    @app.post("/api/agents")
    async def create_agent(request: Request):
        """Create a new agent."""
        import secrets as _secrets
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        if not data.get("name") or not data.get("system_prompt"):
            raise HTTPException(status_code=400, detail="name and system_prompt required")
        agent_id = await _state.database.create_agent(
            name=data["name"],
            description=data.get("description", ""),
            system_prompt=data["system_prompt"],
            allowed_tools=data.get("allowed_tools", "all"),
            webhook_secret=_secrets.token_urlsafe(32),
            telegram_token=data.get("telegram_token", ""),
        )
        agent = await _state.database.get_agent(agent_id)
        return agent  # include secret on creation so user can copy it

    @app.get("/api/agents/{agent_id}")
    async def get_agent(agent_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return _agent_public(agent)

    @app.put("/api/agents/{agent_id}")
    async def update_agent(agent_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        allowed_fields = {"name", "description", "system_prompt", "allowed_tools", "is_active"}
        kwargs = {k: v for k, v in data.items() if k in allowed_fields}
        ok = await _state.database.update_agent(agent_id, **kwargs)
        if not ok:
            raise HTTPException(status_code=404, detail="Agent not found")

        # When is_active changes, restart all channels for this agent
        if _state.agent_channel_manager and "is_active" in kwargs:
            for ch_type in ["telegram", "whatsapp"]:
                asyncio.create_task(
                    _state.agent_channel_manager.restart_channel(agent_id, ch_type)
                )

        agent = await _state.database.get_agent(agent_id)
        return _agent_public(agent)

    @app.delete("/api/agents/{agent_id}")
    async def delete_agent(agent_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        if _state.agent_channel_manager:
            for ch_type in ["telegram", "whatsapp"]:
                asyncio.create_task(
                    _state.agent_channel_manager.stop_channel(agent_id, ch_type)
                )
        ok = await _state.database.delete_agent(agent_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {"status": "ok", "deleted": True}

    # ─── Skills ─────────────────────────────────────────────

    @app.get("/api/agents/{agent_id}/skills")
    async def get_agent_skills(agent_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        global_skills = await _state.database.get_all_skills()
        enabled_ids = await _state.database.get_agent_enabled_global_skill_ids(agent_id)
        annotated = [{**s, "enabled": s["id"] in enabled_ids} for s in global_skills]
        private_skills = await _state.database.get_agent_private_skills(agent_id)
        return {"global_skills": annotated, "private_skills": private_skills}

    @app.post("/api/agents/{agent_id}/skills/generate")
    async def generate_agent_skill_endpoint(agent_id: int, request: Request):
        if not _state.brain or not _state.brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        data = await request.json()
        try:
            skill = await _state.brain.skill_manager.generate_agent_skill(
                agent_id=agent_id,
                name=data["name"],
                description=data["description"],
                use_cases=data.get("use_cases", ""),
                llm_router=_state.brain.llm_router,
            )
            return skill
        except Exception as e:
            log.error("Failed to generate agent skill", error=str(e))
            raise HTTPException(status_code=500, detail="Failed to generate skill")

    @app.post("/api/agents/{agent_id}/skills/{skill_id}")
    async def enable_agent_skill(agent_id: int, skill_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        skill = await _state.database.get_skill(skill_id)
        if skill and skill.get("agent_id") is not None:
            raise HTTPException(400, "Cannot enable a private skill as a global one")
        await _state.database.enable_agent_skill(agent_id, skill_id)
        return {"status": "ok", "enabled": True}

    @app.delete("/api/agents/{agent_id}/skills/{skill_id}")
    async def disable_agent_skill(agent_id: int, skill_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        await _state.database.disable_agent_skill(agent_id, skill_id)
        return {"status": "ok", "enabled": False}

    # ─── Knowledge Base ───────────────────────────────────────

    def _knowledge_public(item: dict) -> dict:
        """Omit content from list responses but include char_count for the UI counter."""
        return {k: v for k, v in item.items() if k != "content"} | {
            "char_count": len(item.get("content", ""))
        }

    @app.get("/api/agents/{agent_id}/knowledge")
    async def list_agent_knowledge(agent_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        items = await _state.database.get_agent_knowledge(agent_id)
        return [_knowledge_public(i) for i in items]

    @app.post("/api/agents/{agent_id}/knowledge/text")
    async def add_knowledge_text(agent_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        data = await request.json()
        title = (data.get("title") or "").strip()
        content = (data.get("content") or "").strip()
        if not title or not content:
            raise HTTPException(status_code=400, detail="title and content required")
        kid = await _state.database.create_agent_knowledge(
            agent_id=agent_id, type="text", title=title, content=content
        )
        items = await _state.database.get_agent_knowledge(agent_id)
        item = next((i for i in items if i["id"] == kid), None)
        return _knowledge_public(item)

    @app.post("/api/agents/{agent_id}/knowledge/file")
    async def add_knowledge_file(agent_id: int, file: UploadFile = File(...), title: str = Form("")):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        from openacm.utils.knowledge_file import extract_text
        data = await file.read()
        try:
            content = await extract_text(file.filename or "file", data)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if not content:
            raise HTTPException(status_code=422, detail="El archivo no contiene texto extraíble")
        item_title = title.strip() or (Path(file.filename or "file").stem if file.filename else "Archivo")
        kid = await _state.database.create_agent_knowledge(
            agent_id=agent_id, type="file", title=item_title,
            content=content, filename=file.filename,
        )
        items = await _state.database.get_agent_knowledge(agent_id)
        item = next((i for i in items if i["id"] == kid), None)
        return _knowledge_public(item)

    @app.patch("/api/agents/{agent_id}/knowledge/{kid}")
    async def update_knowledge_item(agent_id: int, kid: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        data = await request.json()
        updates = {}
        if "title" in data:
            updates["title"] = (data["title"] or "").strip()
        if "content" in data:
            updates["content"] = (data["content"] or "").strip()
        if not updates:
            raise HTTPException(status_code=400, detail="title or content required")
        ok = await _state.database.update_agent_knowledge(kid, **updates)
        if not ok:
            raise HTTPException(status_code=404, detail="Knowledge item not found")
        items = await _state.database.get_agent_knowledge(agent_id)
        item = next((i for i in items if i["id"] == kid), None)
        if item is None:
            raise HTTPException(status_code=404, detail="Knowledge item not found")
        return _knowledge_public(item)

    @app.delete("/api/agents/{agent_id}/knowledge/{kid}")
    async def delete_knowledge_item(agent_id: int, kid: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        ok = await _state.database.delete_agent_knowledge(kid)
        if not ok:
            raise HTTPException(status_code=404, detail="Knowledge item not found")
        return {"ok": True}

    # ─── Agent Channels ───────────────────────────────────────

    _MASKED_KEYS = {"token", "access_token", "app_secret"}
    _REQUIRED_CONFIG = {
        "telegram": {"token"},
        "whatsapp": {"access_token", "phone_number_id"},
        "whatsapp_web": {"bridge_url"},
    }

    def _mask_config(config_data: dict) -> dict:
        """Mask sensitive credential fields, keeping first 8 chars."""
        result = {}
        for k, v in config_data.items():
            if k in _MASKED_KEYS and isinstance(v, str) and len(v) > 8:
                result[k] = v[:8] + "..."
            else:
                result[k] = v
        return result

    def _channel_public(row: dict, is_connected: bool = False) -> dict:
        config_data = json.loads(row.get("config", "{}"))
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "type": row["type"],
            "config": _mask_config(config_data),
            "is_active": bool(row.get("is_active", 1)),
            "is_connected": is_connected,
            "created_at": row.get("created_at", ""),
        }

    def _get_connected_set() -> set:
        """Return set of (agent_id, type) tuples that are currently connected."""
        if not _state.agent_channel_manager:
            return set()
        return {
            (s["agent_id"], s["type"])
            for s in _state.agent_channel_manager.get_status()
            if s["connected"]
        }

    @app.get("/api/agents/{agent_id}/channels")
    async def list_agent_channels(agent_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        rows = await _state.database.get_agent_channels(agent_id)
        connected = _get_connected_set()
        return [_channel_public(r, (agent_id, r["type"]) in connected) for r in rows]

    @app.post("/api/agents/{agent_id}/channels")
    async def create_agent_channel(agent_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        data = await request.json()
        channel_type = data.get("type", "")
        config_data = data.get("config", {})

        if channel_type not in ("telegram", "whatsapp", "whatsapp_web"):
            raise HTTPException(status_code=422, detail=f"Invalid channel type: {channel_type}")

        required = _REQUIRED_CONFIG.get(channel_type, set())
        missing = [k for k in required if not str(config_data.get(k) or "").strip()]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required config fields: {', '.join(missing)}"
            )

        # Check for duplicate active channel of same type
        existing = await _state.database.get_agent_channels(agent_id)
        if any(r["type"] == channel_type and r.get("is_active") for r in existing):
            raise HTTPException(
                status_code=400,
                detail=f"Este agente ya tiene un canal de tipo {channel_type}"
            )

        cid = await _state.database.create_agent_channel(
            agent_id=agent_id,
            type=channel_type,
            config_json=json.dumps(config_data),
            is_active=1,
        )

        row = await _state.database.get_agent_channel(cid)

        # Start the channel if agent is active
        if _state.agent_channel_manager and agent.get("is_active"):
            asyncio.create_task(
                _state.agent_channel_manager.start_channel(agent, row)
            )

        connected = _get_connected_set()
        return _channel_public(row, (agent_id, channel_type) in connected)

    @app.patch("/api/agents/{agent_id}/channels/{channel_id}")
    async def update_agent_channel(agent_id: int, channel_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        row = await _state.database.get_agent_channel(channel_id)
        if not row or row["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Channel not found")

        data = await request.json()
        updates = {}

        if "config" in data:
            existing_config = json.loads(row.get("config", "{}"))
            merged = {**existing_config, **data["config"]}
            # Validate merged config still satisfies required fields
            required = _REQUIRED_CONFIG.get(row["type"], set())
            missing = [k for k in required if not str(merged.get(k) or "").strip()]
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail=f"Missing required config fields after merge: {', '.join(missing)}"
                )
            updates["config"] = json.dumps(merged)

        if "is_active" in data:
            updates["is_active"] = int(bool(data["is_active"]))

        if updates:
            await _state.database.update_agent_channel(channel_id, **updates)
            if _state.agent_channel_manager:
                asyncio.create_task(
                    _state.agent_channel_manager.restart_channel(agent_id, row["type"])
                )

        updated = await _state.database.get_agent_channel(channel_id)
        connected = _get_connected_set()
        return _channel_public(updated, (agent_id, row["type"]) in connected)

    @app.delete("/api/agents/{agent_id}/channels/{channel_id}")
    async def delete_agent_channel(agent_id: int, channel_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        row = await _state.database.get_agent_channel(channel_id)
        if not row or row["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Channel not found")

        if _state.agent_channel_manager:
            await _state.agent_channel_manager.stop_channel(agent_id, row["type"])

        await _state.database.delete_agent_channel(channel_id)
        return {"ok": True}

    @app.post("/api/agents/{agent_id}/channels/{channel_id}/restart")
    async def restart_agent_channel(agent_id: int, channel_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        row = await _state.database.get_agent_channel(channel_id)
        if not row or row["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Channel not found")

        if _state.agent_channel_manager:
            await _state.agent_channel_manager.restart_channel(agent_id, row["type"])

        connected = _get_connected_set()
        is_connected = (agent_id, row["type"]) in connected
        return {"ok": True, "connected": is_connected}

    @app.get("/api/agents/{agent_id}/secret")
    async def get_agent_secret(agent_id: int):
        """Return the webhook secret (used once after creation)."""
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {"webhook_secret": agent["webhook_secret"]}

    @app.post("/api/agents/{agent_id}/chat")
    async def agent_webhook(agent_id: int, request: Request):
        """
        Public webhook — send a message to an agent and get a response.

        Required header: X-Agent-Secret: <webhook_secret>
        Body: { "message": "...", "user_id": "anonymous" }
        """
        if not _state.database or not _state.brain:
            raise HTTPException(status_code=503, detail="Service not ready")

        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if not agent.get("is_active"):
            raise HTTPException(status_code=403, detail="Agent is disabled")

        # Verify secret
        secret = request.headers.get("X-Agent-Secret", "")
        if secret != agent["webhook_secret"]:
            raise HTTPException(status_code=401, detail="Invalid agent secret")

        data = await request.json()
        message = data.get("message", "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message required")
        user_id = data.get("user_id", "webhook_user")

        from openacm.core.agent_runner import AgentRunner
        runner = AgentRunner(
            llm_router=_state.brain.llm_router,
            tool_registry=_state.brain.tool_registry,
            memory=_state.brain.memory,
            event_bus=_state.brain.event_bus,
            database=_state.database,
        )
        response = await runner.run(agent=agent, message=message, user_id=user_id)
        return {"response": response, "agent": agent["name"]}

    @app.post("/api/agents/generate")
    async def generate_agent(request: Request):
        """
        Use the LLM to generate an agent name, description, and system prompt.

        Accepts multipart/form-data:
          - description: str  (what the agent should do)
          - file: optional PDF / TXT / MD document for extra context
        """
        if not _state.brain:
            raise HTTPException(status_code=503, detail="Service not ready")

        from fastapi import Form, UploadFile, File as FastAPIFile
        import io

        content_type = request.headers.get("content-type", "")
        description = ""
        doc_text = ""

        if "multipart/form-data" in content_type:
            form = await request.form()
            description = str(form.get("description", "")).strip()
            # Support multiple files: fields named "file", "file0", "file1", … or repeated "file"
            file_fields = form.getlist("file") if hasattr(form, "getlist") else []
            if not file_fields:
                single = form.get("file")
                if single:
                    file_fields = [single]
            doc_parts: list[str] = []
            for file_field in file_fields:
                if not (file_field and hasattr(file_field, "read")):
                    continue
                raw = await file_field.read()
                fname = getattr(file_field, "filename", "") or ""
                ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                if ext == "pdf":
                    try:
                        import pypdf
                        reader = pypdf.PdfReader(io.BytesIO(raw))
                        pages = [p.extract_text() or "" for p in reader.pages]
                        part = "\n\n".join(p for p in pages if p.strip())
                        doc_parts.append(f"[{fname}]\n{part}")
                    except Exception as e:
                        doc_parts.append(f"[{fname} — PDF extraction error: {e}]")
                elif ext in ("txt", "md", "csv", "yaml", "yml", "json"):
                    doc_parts.append(f"[{fname}]\n{raw.decode('utf-8', errors='replace')}")
            if doc_parts:
                combined = "\n\n---\n\n".join(doc_parts)
                doc_text = truncate(combined, TRUNCATE_RAG_CONTEXT_CHARS)
        else:
            data = await request.json()
            description = str(data.get("description", "")).strip()

        if not description:
            raise HTTPException(status_code=400, detail="description required")

        # Build prompt for generation
        doc_section = (
            f"\n\nADDITIONAL DOCUMENT CONTEXT:\n{doc_text}" if doc_text else ""
        )
        generation_prompt = (
            f"Generate a configuration for an autonomous AI agent based on this description:\n\n"
            f"{description}{doc_section}\n\n"
            f"Return ONLY a valid JSON object with these fields:\n"
            f"- name: short agent name (2-4 words)\n"
            f"- description: one-sentence description\n"
            f"- system_prompt: detailed system prompt with rules, personality, and behavior guidelines "
            f"(be specific and thorough, use the document context if provided)\n\n"
            f"JSON only, no markdown, no explanation."
        )

        try:
            response = await _state.brain.llm_router.chat(
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that generates AI agent configurations. Always respond with valid JSON only."},
                    {"role": "user", "content": generation_prompt},
                ],
                tools=None,
            )
            content = response["content"].strip()
            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            generated = json.loads(content)
            return {
                "name": generated.get("name", "New Agent"),
                "description": generated.get("description", ""),
                "system_prompt": generated.get("system_prompt", ""),
            }
        except Exception as e:
            log.error("Agent generation failed", error=str(e))
            raise HTTPException(status_code=500, detail="Agent generation failed")

    @app.post("/api/agents/{agent_id}/test")
    async def test_agent(agent_id: int, request: Request):
        """Test an agent from the UI (no secret needed, uses dashboard auth)."""
        if not _state.database or not _state.brain:
            raise HTTPException(status_code=503, detail="Service not ready")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        data = await request.json()
        message = data.get("message", "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message required")

        from openacm.core.agent_runner import AgentRunner
        runner = AgentRunner(
            llm_router=_state.brain.llm_router,
            tool_registry=_state.brain.tool_registry,
            memory=_state.brain.memory,
            event_bus=_state.brain.event_bus,
            database=_state.database,
        )
        response = await runner.run(agent=agent, message=message, user_id="dashboard_test")
        return {"response": response}

    # ─── API: Debug Traces ───────────────────────────────────

    @app.get("/api/debug/traces")
    async def get_brain_traces(limit: int = 20):
        """Return the last N agentic loop traces for debugging."""
        if not _state.brain:
            return []
        traces = list(reversed(_state.brain._traces[-limit:]))
        return traces

    @app.delete("/api/debug/traces")
    async def clear_brain_traces():
        """Clear all stored traces."""
        if _state.brain:
            _state.brain._traces.clear()
        return {"status": "ok"}

