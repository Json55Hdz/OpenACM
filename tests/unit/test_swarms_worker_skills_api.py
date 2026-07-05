"""Tests for per-worker skill API endpoints under the swarms router."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from openacm.web.routers import swarms as swarms_router
from openacm.web.state import _state


@pytest.fixture
def app_client():
    app = FastAPI()
    swarms_router.register_routes(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _mock_brain(monkeypatch):
    db = MagicMock()
    db.get_all_skills = AsyncMock(return_value=[
        {"id": 1, "name": "g1", "description": "d", "content": "c", "category": "general", "is_active": 1, "is_builtin": 0, "worker_id": None},
    ])
    db.get_worker_private_skills = AsyncMock(return_value=[
        {"id": 2, "name": "p1", "description": "d", "content": "c", "category": "custom", "is_active": 1, "is_builtin": 0, "worker_id": 42},
    ])
    db.get_worker_enabled_global_skill_ids = AsyncMock(return_value={1})
    db.get_skill = AsyncMock(return_value=None)
    db.enable_worker_skill = AsyncMock()
    db.disable_worker_skill = AsyncMock()
    monkeypatch.setattr(_state, "database", db)

    skill_manager = MagicMock()
    skill_manager.generate_worker_skill = AsyncMock(return_value={"id": 3, "name": "gen1", "worker_id": 42})
    brain = MagicMock()
    brain.skill_manager = skill_manager
    brain.llm_router = MagicMock()
    monkeypatch.setattr(_state, "brain", brain)
    yield db, skill_manager
    monkeypatch.setattr(_state, "database", None)
    monkeypatch.setattr(_state, "brain", None)


class TestGetWorkerSkills:
    async def test_returns_global_skills_annotated_and_private_skills(self, app_client, _mock_brain):
        async with app_client as ac:
            resp = await ac.get("/api/swarms/1/workers/42/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["global_skills"] == [
            {"id": 1, "name": "g1", "description": "d", "content": "c", "category": "general", "is_active": 1, "is_builtin": 0, "worker_id": None, "enabled": True}
        ]
        assert body["private_skills"][0]["name"] == "p1"


class TestEnableDisableWorkerSkill:
    async def test_enable_calls_database(self, app_client, _mock_brain):
        db, _ = _mock_brain
        async with app_client as ac:
            resp = await ac.post("/api/swarms/1/workers/42/skills/1")
        assert resp.status_code == 200
        db.enable_worker_skill.assert_awaited_once_with(42, 1)

    async def test_disable_calls_database(self, app_client, _mock_brain):
        db, _ = _mock_brain
        async with app_client as ac:
            resp = await ac.delete("/api/swarms/1/workers/42/skills/1")
        assert resp.status_code == 200
        db.disable_worker_skill.assert_awaited_once_with(42, 1)

    async def test_enable_rejects_a_private_skill_id_with_400(self, app_client, _mock_brain):
        db, _ = _mock_brain
        db.get_skill = AsyncMock(return_value={"id": 2, "name": "p1", "worker_id": 42})
        async with app_client as ac:
            resp = await ac.post("/api/swarms/1/workers/42/skills/2")
        assert resp.status_code == 400
        db.enable_worker_skill.assert_not_awaited()


class TestGenerateWorkerSkill:
    async def test_generates_and_returns_the_skill(self, app_client, _mock_brain):
        _, skill_manager = _mock_brain
        async with app_client as ac:
            resp = await ac.post(
                "/api/swarms/1/workers/42/skills/generate",
                json={"name": "gen1", "description": "d", "use_cases": "u"},
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "gen1"
        skill_manager.generate_worker_skill.assert_awaited_once_with(
            worker_id=42, name="gen1", description="d", use_cases="u", llm_router=skill_manager.generate_worker_skill.await_args.kwargs["llm_router"],
        )

    async def test_no_brain_503s(self, app_client, monkeypatch):
        monkeypatch.setattr(_state, "brain", None)
        async with app_client as ac:
            resp = await ac.post(
                "/api/swarms/1/workers/42/skills/generate",
                json={"name": "gen1", "description": "d"},
            )
        assert resp.status_code == 503
