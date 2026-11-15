"""A session approval is remembered under what the server asked, not what the client claims."""
import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from openacm.web.routers import system
from openacm.web.state import _state


async def test_the_client_cannot_choose_what_gets_approved_for_the_session(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "tok")
    app = FastAPI()
    system.register_routes(app) if hasattr(system, "register_routes") else None
    fut = asyncio.get_running_loop().create_future()
    monkeypatch.setattr(_state, "pending_confirmations", {"abc": fut})
    monkeypatch.setattr(_state, "pending_confirmation_commands", {"abc": "write_file → /safe/*"})
    monkeypatch.setattr(_state, "session_allowed_commands", set())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/tool/confirm", json={
            "confirm_id": "abc", "approved": True, "always_session": True, "command": "rm -rf /"},
            headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200 and fut.result() is True
    assert _state.session_allowed_commands == {"write_file → /safe/*"}
