"""Test GET /api/tools includes each tool's category."""
from unittest.mock import MagicMock
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from openacm.web.routers import system as system_router
from openacm.web.state import _state

TEST_TOKEN = "test-dashboard-token"


@pytest.fixture
def app_client(monkeypatch):
    # system.py's auth middleware reads DASHBOARD_TOKEN at register_routes()
    # call time — must be set before registering, not just before the request.
    monkeypatch.setenv("DASHBOARD_TOKEN", TEST_TOKEN)
    app = FastAPI()
    system_router.register_routes(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_get_tools_includes_category(app_client, monkeypatch):
    tool = MagicMock()
    tool.name = "ha_control"
    tool.description = "control devices"
    tool.risk_level = "low"
    tool.parameters = {}
    tool.category = "iot"

    registry = MagicMock()
    registry.tools = {"ha_control": tool}
    monkeypatch.setattr(_state, "tool_registry", registry)

    async with app_client as ac:
        resp = await ac.get("/api/tools", headers={"Authorization": f"Bearer {TEST_TOKEN}"})

    assert resp.status_code == 200
    assert resp.json()[0]["category"] == "iot"
    monkeypatch.setattr(_state, "tool_registry", None)


async def test_get_tools_requires_auth(app_client):
    async with app_client as ac:
        resp = await ac.get("/api/tools")

    assert resp.status_code == 401
