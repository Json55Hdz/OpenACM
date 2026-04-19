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
        # Start Telegram bot if token provided
        if _state.agent_bot_manager and agent.get("telegram_token", "").strip():
            asyncio.create_task(_state.agent_bot_manager.start_bot(agent))
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
        allowed_fields = {"name", "description", "system_prompt", "allowed_tools", "is_active", "telegram_token"}
        kwargs = {k: v for k, v in data.items() if k in allowed_fields}
        ok = await _state.database.update_agent(agent_id, **kwargs)
        if not ok:
            raise HTTPException(status_code=404, detail="Agent not found")
        agent = await _state.database.get_agent(agent_id)
        # Restart bot if telegram_token was part of the update
        if _state.agent_bot_manager and ("telegram_token" in kwargs or "is_active" in kwargs):
            asyncio.create_task(_state.agent_bot_manager.restart_bot(agent_id))
        return _agent_public(agent)

    @app.delete("/api/agents/{agent_id}")
    async def delete_agent(agent_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        # Stop bot before deleting
        if _state.agent_bot_manager:
            asyncio.create_task(_state.agent_bot_manager.stop_bot(agent_id))
        ok = await _state.database.delete_agent(agent_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {"status": "ok", "deleted": True}

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
            raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

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

