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
    # ─── API: MCP Servers ────────────────────────────────────

    @app.get("/api/mcp/servers")
    async def get_mcp_servers():
        """List all configured MCP servers with their connection status."""
        if not _state.mcp_manager:
            return []
        return _state.mcp_manager.get_status()

    @app.post("/api/mcp/servers")
    async def add_mcp_server(request: Request):
        """Add (or replace) an MCP server configuration."""
        if not _state.mcp_manager:
            raise HTTPException(status_code=503, detail="MCP manager not available")
        data = await request.json()
        name = data.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        try:
            cfg = _state.mcp_manager.add_server(data)
            return {"status": "ok", **cfg.to_dict()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.put("/api/mcp/servers/{server_name}")
    async def update_mcp_server(server_name: str, request: Request):
        """Update an MCP server configuration."""
        if not _state.mcp_manager:
            raise HTTPException(status_code=503, detail="MCP manager not available")
        data = await request.json()
        try:
            cfg = _state.mcp_manager.update_server(server_name, data)
            return {"status": "ok", **cfg.to_dict()}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.delete("/api/mcp/servers/{server_name}")
    async def delete_mcp_server(server_name: str):
        """Remove an MCP server configuration (disconnects if active)."""
        if not _state.mcp_manager:
            raise HTTPException(status_code=503, detail="MCP manager not available")
        _state.mcp_manager.remove_server(server_name)
        return {"status": "ok", "deleted": server_name}

    @app.post("/api/mcp/servers/{server_name}/connect")
    async def connect_mcp_server(server_name: str):
        """Connect to an MCP server."""
        if not _state.mcp_manager:
            raise HTTPException(status_code=503, detail="MCP manager not available")
        if server_name not in _state.mcp_manager.servers:
            raise HTTPException(status_code=404, detail="Server not found")
        conn = await _state.mcp_manager.connect(server_name)
        return {
            "status": "ok" if conn.connected else "error",
            "connected": conn.connected,
            "error": conn.error,
            "tools": conn.tools,
        }

    @app.post("/api/mcp/servers/{server_name}/disconnect")
    async def disconnect_mcp_server(server_name: str):
        """Disconnect from an MCP server."""
        if not _state.mcp_manager:
            raise HTTPException(status_code=503, detail="MCP manager not available")
        await _state.mcp_manager.disconnect(server_name)
        return {"status": "ok", "disconnected": server_name}

