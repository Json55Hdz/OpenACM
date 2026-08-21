"""Tests for POST /api/agents/{agent_id}/test — dashboard test-chat endpoint."""
from unittest.mock import AsyncMock, MagicMock, patch

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


AGENT_ROW = {"id": 5, "name": "TestAgent", "system_prompt": "Base.", "allowed_tools": "all"}


@pytest.fixture(autouse=True)
def _mock_state(monkeypatch):
    db = MagicMock()
    db.get_agent = AsyncMock(return_value=AGENT_ROW)
    brain = MagicMock()
    monkeypatch.setattr(_state, "database", db)
    monkeypatch.setattr(_state, "brain", brain)
    yield db
    monkeypatch.setattr(_state, "database", None)
    monkeypatch.setattr(_state, "brain", None)


class TestTestAgentEndpoint:
    async def test_default_behavior_unchanged_when_fields_omitted(self, app_client, _mock_state):
        mock_run = AsyncMock(return_value="hola")
        with patch("openacm.core.agent_runner.AgentRunner.run", mock_run):
            async with app_client as ac:
                resp = await ac.post("/api/agents/5/test", json={"message": "hi"})
        assert resp.status_code == 200
        assert resp.json() == {"response": "hola"}
        mock_run.assert_awaited_once()
        kwargs = mock_run.await_args.kwargs
        assert kwargs.get("channel_id") is None
        assert kwargs.get("extra_system_context") is None
        assert kwargs["user_id"] == "dashboard_test"

    async def test_channel_id_and_extra_system_context_forwarded(self, app_client, _mock_state):
        mock_run = AsyncMock(return_value="ok")
        with patch("openacm.core.agent_runner.AgentRunner.run", mock_run):
            async with app_client as ac:
                resp = await ac.post(
                    "/api/agents/5/test",
                    json={
                        "message": "hi",
                        "channel_id": "agent_5_flow_12",
                        "extra_system_context": "editas el flujo X",
                    },
                )
        assert resp.status_code == 200
        kwargs = mock_run.await_args.kwargs
        assert kwargs["channel_id"] == "agent_5_flow_12"
        assert kwargs["extra_system_context"] == "editas el flujo X"

    async def test_missing_message_still_rejected(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/5/test", json={})
        assert resp.status_code == 400
