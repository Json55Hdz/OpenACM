"""Tests for per-agent flow API endpoints under the agents router."""
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


FLOW_ROW = {
    "id": 7, "agent_id": 42, "name": "check-website", "description": "Checks a URL",
    "graph_json": '{"nodes":[{"id":"start","type":"start","config":{"parameters":[]}},'
                  '{"id":"end","type":"end","config":{"template":"done"}}],'
                  '"edges":[{"from":"start","to":"end","fromHandle":"default"}]}',
    "is_active": 1, "created_at": "2026-01-01", "updated_at": "2026-01-01",
}


@pytest.fixture(autouse=True)
def _mock_state(monkeypatch):
    db = MagicMock()
    db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
    db.get_flow = AsyncMock(return_value=FLOW_ROW)
    db.create_flow = AsyncMock(return_value=8)
    db.update_flow = AsyncMock(return_value=True)
    db.delete_flow = AsyncMock(return_value=True)
    db.get_connection = AsyncMock(return_value=None)
    monkeypatch.setattr(_state, "database", db)
    yield db
    monkeypatch.setattr(_state, "database", None)


class TestListAndGetFlows:
    async def test_list_flows(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/flows")
        assert resp.status_code == 200
        assert resp.json()[0]["name"] == "check-website"

    async def test_get_flow_detail_includes_graph_json(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/flows/7")
        assert resp.status_code == 200
        assert "graph_json" in resp.json()

    async def test_get_missing_flow_404s(self, app_client, _mock_state):
        _mock_state.get_flow.return_value = None
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/flows/999")
        assert resp.status_code == 404


class TestCreateUpdateDeleteFlow:
    async def test_create_flow(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows", json={"name": "new-flow", "description": "d"})
        assert resp.status_code == 200
        _mock_state.create_flow.assert_awaited_once()

    async def test_update_flow(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/flows/7", json={"graph_json": '{"nodes":[],"edges":[]}'})
        assert resp.status_code == 200
        _mock_state.update_flow.assert_awaited_once()

    async def test_update_missing_flow_404s(self, app_client, _mock_state):
        _mock_state.update_flow.return_value = False
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/flows/999", json={"name": "x"})
        assert resp.status_code == 404

    async def test_delete_flow(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.delete("/api/agents/42/flows/7")
        assert resp.status_code == 200
        _mock_state.delete_flow.assert_awaited_once_with(7)


class TestTestFlowEndpoint:
    async def test_runs_the_flow_with_given_params(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/test", json={"params": {}})
        assert resp.status_code == 200
        assert resp.json()["result"] == "done"

    async def test_missing_flow_404s(self, app_client, _mock_state):
        _mock_state.get_flow.return_value = None
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/999/test", json={"params": {}})
        assert resp.status_code == 404
