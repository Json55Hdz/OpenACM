"""Tests for the per-flow skill API endpoints under the agents router."""
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
    "graph_json": '{"nodes":[],"edges":[]}', "is_active": 1,
    "created_at": "2026-01-01", "updated_at": "2026-01-01",
}

SKILL_ROW = {
    "id": 3, "flow_id": 7, "name": "cuando-usar", "description": "d", "content": "c",
    "category": "custom", "is_active": 1, "is_builtin": 0, "worker_id": None, "agent_id": None,
}


@pytest.fixture(autouse=True)
def _mock_state(monkeypatch):
    db = MagicMock()
    db.get_flow = AsyncMock(return_value=FLOW_ROW)
    db.get_flow_skill = AsyncMock(return_value=None)
    db.update_skill = AsyncMock(return_value=True)
    db.delete_skill = AsyncMock(return_value=True)
    monkeypatch.setattr(_state, "database", db)

    brain = MagicMock()
    brain.skill_manager = MagicMock()
    brain.skill_manager.create_flow_skill = AsyncMock(return_value=SKILL_ROW)
    brain.skill_manager.generate_flow_skill = AsyncMock(return_value=SKILL_ROW)
    brain.llm_router = MagicMock()
    monkeypatch.setattr(_state, "brain", brain)

    yield db
    monkeypatch.setattr(_state, "database", None)
    monkeypatch.setattr(_state, "brain", None)


class TestGetFlowSkill:
    async def test_no_skill_returns_null(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/flows/7/skill")
        assert resp.status_code == 200
        assert resp.json() is None

    async def test_existing_skill_is_returned(self, app_client, _mock_state):
        _mock_state.get_flow_skill.return_value = SKILL_ROW
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/flows/7/skill")
        assert resp.status_code == 200
        assert resp.json()["name"] == "cuando-usar"

    async def test_flow_belonging_to_a_different_agent_404s(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.get("/api/agents/999/flows/7/skill")
        assert resp.status_code == 404


class TestCreateFlowSkill:
    async def test_create_when_none_exists(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/skill", json={"name": "n", "description": "d", "content": "c"})
        assert resp.status_code == 200
        _state.brain.skill_manager.create_flow_skill.assert_awaited_once()

    async def test_create_when_one_already_exists_is_rejected(self, app_client, _mock_state):
        _mock_state.get_flow_skill.return_value = SKILL_ROW
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/skill", json={"name": "n", "description": "d", "content": "c"})
        assert resp.status_code == 409

    async def test_toctou_race_is_rejected_as_409(self, app_client, _mock_state):
        """Two near-simultaneous POSTs can both pass the get_flow_skill()
        pre-check (both see None) before either insert commits. The DB-layer
        partial unique index (idx_skills_one_per_flow, migration 36) rejects
        the loser with sqlite3.IntegrityError — the endpoint must translate
        that into the same clean 409 the pre-check already returns, not a
        500."""
        import sqlite3
        _state.brain.skill_manager.create_flow_skill.side_effect = sqlite3.IntegrityError(
            "UNIQUE constraint failed: skills.flow_id"
        )
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/skill", json={"name": "n", "description": "d", "content": "c"})
        assert resp.status_code == 409


class TestUpdateDeleteFlowSkill:
    async def test_update_existing_skill(self, app_client, _mock_state):
        _mock_state.get_flow_skill.return_value = SKILL_ROW
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/flows/7/skill", json={"content": "new content"})
        assert resp.status_code == 200
        _mock_state.update_skill.assert_awaited_once()

    async def test_update_when_none_exists_404s(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/flows/7/skill", json={"content": "x"})
        assert resp.status_code == 404

    async def test_delete_existing_skill(self, app_client, _mock_state):
        _mock_state.get_flow_skill.return_value = SKILL_ROW
        async with app_client as ac:
            resp = await ac.delete("/api/agents/42/flows/7/skill")
        assert resp.status_code == 200
        _mock_state.delete_skill.assert_awaited_once_with(3)


class TestGenerateFlowSkill:
    async def test_generate_calls_skill_manager(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/skill/generate", json={"name": "n", "description": "d"})
        assert resp.status_code == 200
        _state.brain.skill_manager.generate_flow_skill.assert_awaited_once()

    async def test_generate_when_one_already_exists_is_rejected(self, app_client, _mock_state):
        """generate_flow_skill_endpoint inserts a new skill row just like
        create_flow_skill_endpoint, so it must carry the same existing-skill
        guard — otherwise clicking "Generar con IA" on a flow that already
        has a skill hits idx_skills_one_per_flow and surfaces as a bare 500
        instead of the clean 409 the create path already returns."""
        _mock_state.get_flow_skill.return_value = SKILL_ROW
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/skill/generate", json={"name": "n", "description": "d"})
        assert resp.status_code == 409
        _state.brain.skill_manager.generate_flow_skill.assert_not_awaited()
