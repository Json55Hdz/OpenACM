"""Tests for /api/agents/{id}/channels endpoints."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


def _make_app(db=None, mgr=None):
    from openacm.web.routers import agents as agents_router
    from openacm.web.state import _state
    app = FastAPI()
    agents_router.register_routes(app)
    _state.database = db
    _state.agent_channel_manager = mgr
    return app


def _make_db(agent=None, channels=None, created_id=1):
    db = MagicMock()
    db.get_agent = AsyncMock(return_value=agent)
    db.get_all_agents = AsyncMock(return_value=[agent] if agent else [])
    db.get_agent_channels = AsyncMock(return_value=channels or [])
    db.get_agent_channel = AsyncMock(return_value=(channels[0] if channels else None))
    db.create_agent_channel = AsyncMock(return_value=created_id)
    db.update_agent_channel = AsyncMock(return_value=True)
    db.delete_agent_channel = AsyncMock(return_value=True)
    return db


_AGENT = {"id": 1, "name": "Bot", "is_active": 1, "system_prompt": "hi",
          "allowed_tools": "none", "telegram_token": ""}
_TG_ROW = {"id": 1, "agent_id": 1, "type": "telegram",
            "config": '{"token":"abcdefgh_secret"}', "is_active": 1,
            "created_at": "2026-06-16T10:00:00"}


class TestGetChannels:
    async def test_returns_list_with_masked_config(self):
        db = _make_db(agent=_AGENT, channels=[_TG_ROW])
        mgr = MagicMock()
        mgr.get_status = MagicMock(return_value=[{"agent_id": 1, "type": "telegram", "connected": True}])
        app = _make_app(db=db, mgr=mgr)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/agents/1/channels")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["is_connected"] is True
        # Token must be masked
        token_val = data[0]["config"]["token"]
        assert token_val.endswith("...")
        assert len(token_val) < len("abcdefgh_secret")

    async def test_returns_404_when_agent_not_found(self):
        db = _make_db(agent=None)
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/agents/99/channels")
        assert r.status_code == 404


class TestCreateChannel:
    async def test_creates_telegram_channel(self):
        db = _make_db(agent=_AGENT, channels=[], created_id=5)
        new_row = {"id": 5, "agent_id": 1, "type": "telegram",
                   "config": '{"token":"tok123"}', "is_active": 1,
                   "created_at": "2026-06-16T10:00:00"}
        db.get_agent_channel = AsyncMock(return_value=new_row)
        mgr = MagicMock()
        mgr.get_status = MagicMock(return_value=[])
        mgr.start_channel = AsyncMock()
        app = _make_app(db=db, mgr=mgr)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/agents/1/channels",
                             json={"type": "telegram", "config": {"token": "tok123"}})
        assert r.status_code == 200
        db.create_agent_channel.assert_awaited_once()

    async def test_returns_400_on_duplicate_type(self):
        db = _make_db(agent=_AGENT, channels=[_TG_ROW])
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/agents/1/channels",
                             json={"type": "telegram", "config": {"token": "new"}})
        assert r.status_code == 400

    async def test_returns_422_on_missing_token(self):
        db = _make_db(agent=_AGENT, channels=[])
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/agents/1/channels",
                             json={"type": "telegram", "config": {}})
        assert r.status_code == 422

    async def test_returns_404_when_agent_not_found(self):
        db = _make_db(agent=None)
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/agents/99/channels",
                             json={"type": "telegram", "config": {"token": "x"}})
        assert r.status_code == 404


class TestDeleteChannel:
    async def test_deletes_and_stops(self):
        db = _make_db(agent=_AGENT, channels=[_TG_ROW])
        mgr = MagicMock()
        mgr.stop_channel = AsyncMock()
        app = _make_app(db=db, mgr=mgr)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete("/api/agents/1/channels/1")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        mgr.stop_channel.assert_awaited_once_with(1, "telegram")

    async def test_returns_404_when_channel_not_found(self):
        db = _make_db(agent=_AGENT, channels=[])
        db.get_agent_channel = AsyncMock(return_value=None)
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete("/api/agents/1/channels/99")
        assert r.status_code == 404


class TestRestartChannel:
    async def test_restart_returns_connected(self):
        db = _make_db(agent=_AGENT, channels=[_TG_ROW])
        mgr = MagicMock()
        mgr.restart_channel = AsyncMock()
        mgr.get_status = MagicMock(return_value=[
            {"agent_id": 1, "type": "telegram", "connected": True}
        ])
        app = _make_app(db=db, mgr=mgr)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/agents/1/channels/1/restart")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["connected"] is True


class TestPatchChannel:
    async def test_patch_merges_config_and_restarts(self):
        row_before = {"id": 1, "agent_id": 1, "type": "telegram",
                      "config": '{"token":"oldtoken"}', "is_active": 1,
                      "created_at": "2026-06-16T10:00:00"}
        row_after = {"id": 1, "agent_id": 1, "type": "telegram",
                     "config": '{"token":"newtoken"}', "is_active": 1,
                     "created_at": "2026-06-16T10:00:00"}
        db = _make_db(agent=_AGENT, channels=[row_before])
        db.get_agent_channel = AsyncMock(side_effect=[row_before, row_after])
        mgr = MagicMock()
        mgr.restart_channel = AsyncMock()
        mgr.get_status = MagicMock(return_value=[])
        app = _make_app(db=db, mgr=mgr)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch("/api/agents/1/channels/1",
                              json={"config": {"token": "newtoken"}})
        assert r.status_code == 200
        # Allow background task time to be scheduled
        await asyncio.sleep(0.01)
        db.update_agent_channel.assert_awaited_once()
        mgr.restart_channel.assert_awaited_once_with(1, "telegram")

    async def test_patch_returns_404_when_channel_not_found(self):
        db = _make_db(agent=_AGENT, channels=[])
        db.get_agent_channel = AsyncMock(return_value=None)
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch("/api/agents/1/channels/99",
                              json={"config": {"token": "x"}})
        assert r.status_code == 404

    async def test_patch_returns_422_when_required_field_cleared(self):
        row = {"id": 1, "agent_id": 1, "type": "telegram",
               "config": '{"token":"validtoken"}', "is_active": 1,
               "created_at": "2026-06-16T10:00:00"}
        db = _make_db(agent=_AGENT, channels=[row])
        db.get_agent_channel = AsyncMock(return_value=row)
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch("/api/agents/1/channels/1",
                              json={"config": {"token": ""}})
        assert r.status_code == 422
