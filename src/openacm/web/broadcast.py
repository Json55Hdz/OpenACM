"""Shared WebSocket broadcast helpers used by route handlers and server internals."""
from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import WebSocket

from openacm.web.state import _state


async def _safe_ws_send(client: WebSocket, message: dict) -> bool:
    """Send a JSON message to a WebSocket client, serializing writes with a per-connection lock."""
    lock = _state.ws_send_locks.get(client)
    if lock is None:
        lock = asyncio.Lock()
        try:
            _state.ws_send_locks[client] = lock
        except TypeError:
            pass
    async with lock:
        await client.send_json(message)


async def broadcast_event(event_type: str, data: dict[str, Any]) -> None:
    """Broadcast an event to all connected WebSocket clients."""
    if not _state.ws_clients:
        return
    message = {"type": event_type, **data}
    disconnected = set()
    for client in list(_state.ws_clients):
        try:
            await _safe_ws_send(client, message)
        except Exception:
            disconnected.add(client)
    _state.ws_clients -= disconnected


async def _broadcast_to_terminal(data: dict[str, Any], channel_id: str = "web") -> None:
    """Broadcast a structured message to the terminal for a specific channel."""
    shell = _state.channel_shells.get(channel_id)
    if shell and shell._alive:
        await shell._broadcast_json(data)


def _verify_ws_token(websocket: WebSocket) -> bool:
    """Verify token from WebSocket query parameters."""
    token = websocket.query_params.get("token", "")
    dashboard_token = os.environ.get("DASHBOARD_TOKEN", "")
    return token == dashboard_token if dashboard_token else True
