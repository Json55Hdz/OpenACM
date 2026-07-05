"""Tests for per-agent connection API endpoints — credentials must never
appear in a response after creation."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from openacm.web.routers import agents as agents_router
from openacm.web.state import _state


@pytest.fixture
def app_client():
    app = FastAPI()
    agents_router.register_routes(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _mock_state(monkeypatch):
    db = MagicMock()
    db.get_agent_connections = AsyncMock(return_value=[{"id": 1, "agent_id": 42, "name": "Mi Tienda", "type": "woocommerce", "created_at": "2026-01-01"}])
    db.create_connection = AsyncMock(return_value=2)
    db.update_connection = AsyncMock(return_value=True)
    db.delete_connection = AsyncMock(return_value=True)
    monkeypatch.setattr(_state, "database", db)
    yield db
    monkeypatch.setattr(_state, "database", None)


class TestListConnections:
    async def test_list_never_includes_config(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/connections")
        assert resp.status_code == 200
        body = resp.json()
        assert "config" not in body[0]
        assert body[0]["name"] == "Mi Tienda"


class TestCreateUpdateDeleteConnection:
    async def test_create_connection(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post(
                "/api/agents/42/connections",
                json={"name": "Mi Tienda", "type": "woocommerce", "url": "https://x.com", "consumer_key": "ck", "consumer_secret": "cs"},
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == 2
        # The created response must not echo the credentials back either.
        assert "consumer_secret" not in resp.json()
        _mock_state.create_connection.assert_awaited_once()

    async def test_update_connection(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/connections/1", json={"name": "Nueva Tienda"})
        assert resp.status_code == 200
        _mock_state.update_connection.assert_awaited_once()

    async def test_update_missing_connection_404s(self, app_client, _mock_state):
        _mock_state.update_connection.return_value = False
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/connections/999", json={"name": "x"})
        assert resp.status_code == 404

    async def test_delete_connection(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.delete("/api/agents/42/connections/1")
        assert resp.status_code == 200
        _mock_state.delete_connection.assert_awaited_once_with(1, agent_id=42)
