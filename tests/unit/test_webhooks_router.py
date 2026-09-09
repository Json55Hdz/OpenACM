"""Tests for the generic public webhook connector route."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from openacm.web.routers import webhooks as webhooks_router
from openacm.web.state import _state

SIMPLE_FLOW_GRAPH = json.dumps({
    "nodes": [
        {"id": "start", "type": "start", "config": {"parameters": []}},
        {"id": "end", "type": "end", "config": {"template": "hola {{body}}"}},
    ],
    "edges": [{"from": "start", "to": "end", "fromHandle": "default"}],
})

CONNECTOR_ROW = {
    "id": 1, "slug": "pagos", "name": "Pagos", "auth_scheme": "bearer_token",
    "auth_config": json.dumps({"token": "s3cr3t", "header_name": "Authorization"}),
    "flow_id": 7, "dedupe_header": None, "enabled": 1,
}
FLOW_ROW = {"id": 7, "graph_json": SIMPLE_FLOW_GRAPH}


@pytest.fixture
def app_client():
    app = FastAPI()
    webhooks_router.register_routes(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _mock_state(monkeypatch):
    db = MagicMock()
    db.get_webhook_connector_by_slug = AsyncMock(return_value=CONNECTOR_ROW)
    db.get_flow = AsyncMock(return_value=FLOW_ROW)
    db.record_webhook_connector_event = AsyncMock(return_value=1)
    db.find_webhook_connector_event_by_dedupe_key = AsyncMock(return_value=None)
    monkeypatch.setattr(_state, "database", db)
    yield db
    monkeypatch.setattr(_state, "database", None)


class TestHappyPath:
    async def test_valid_request_returns_200_with_flow_result(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post(
                "/api/webhooks/pagos",
                headers={"Authorization": "Bearer s3cr3t"},
                json={"matricula": "511659"},
            )
        assert resp.status_code == 200
        assert "result" in resp.json()

    async def test_logs_the_event(self, app_client, _mock_state):
        async with app_client as ac:
            await ac.post("/api/webhooks/pagos", headers={"Authorization": "Bearer s3cr3t"}, json={"a": 1})
        _mock_state.record_webhook_connector_event.assert_awaited_once()
        call = _mock_state.record_webhook_connector_event.call_args
        assert call.args[0] == 1  # connector_id
        assert call.args[3] == "ok"  # status


class TestConnectorLookup:
    async def test_unknown_slug_404s(self, app_client, _mock_state):
        _mock_state.get_webhook_connector_by_slug.return_value = None
        async with app_client as ac:
            resp = await ac.post("/api/webhooks/nope", json={})
        assert resp.status_code == 404

    async def test_disabled_connector_404s(self, app_client, _mock_state):
        _mock_state.get_webhook_connector_by_slug.return_value = {**CONNECTOR_ROW, "enabled": 0}
        async with app_client as ac:
            resp = await ac.post("/api/webhooks/pagos", json={})
        assert resp.status_code == 404


class TestAuth:
    async def test_invalid_auth_401s_and_is_logged(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/webhooks/pagos", headers={"Authorization": "Bearer wrong"}, json={})
        assert resp.status_code == 401
        call = _mock_state.record_webhook_connector_event.call_args
        assert call.args[3] == "auth_failed"


class TestBody:
    async def test_invalid_json_body_400s(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post(
                "/api/webhooks/pagos", headers={"Authorization": "Bearer s3cr3t"}, content=b"not json",
            )
        assert resp.status_code == 400


class TestFlowError:
    async def test_malformed_graph_500s_without_running_the_flow(self, app_client, _mock_state):
        # No End node — a structural problem validate_graph() catches before
        # the flow ever runs. Our config mistake, not the caller's -> 500,
        # never 502 (see the comment in trigger_connector for why these two
        # must be told apart before calling FlowExecutor.run()).
        bad_graph = json.dumps({
            "nodes": [{"id": "start", "type": "start", "config": {"parameters": []}}],
            "edges": [],
        })
        _mock_state.get_flow.return_value = {"id": 7, "graph_json": bad_graph}
        async with app_client as ac:
            resp = await ac.post("/api/webhooks/pagos", headers={"Authorization": "Bearer s3cr3t"}, json={})
        assert resp.status_code == 500

    async def test_runtime_flow_failure_502s(self, app_client, _mock_state):
        # Structurally valid (has Start, Http, End) but the Http node's
        # target genuinely fails at runtime -> FlowExecutor.run() catches
        # the node handler's exception and returns "Error in node ...",
        # which the router maps to 502.
        from unittest.mock import patch

        http_graph = json.dumps({
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.invalid", "method": "GET"}},
                {"id": "end", "type": "end", "config": {"template": "{{http1}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default"},
                {"from": "http1", "to": "end", "fromHandle": "default"},
            ],
        })
        _mock_state.get_flow.return_value = {"id": 7, "graph_json": http_graph}

        with patch("openacm.core.flow_executor.httpx.AsyncClient", side_effect=RuntimeError("connection refused")):
            async with app_client as ac:
                resp = await ac.post("/api/webhooks/pagos", headers={"Authorization": "Bearer s3cr3t"}, json={})
        assert resp.status_code == 502


class TestDedupe:
    async def test_repeat_dedupe_key_returns_saved_result_without_rerunning_flow(self, app_client, _mock_state):
        connector = {**CONNECTOR_ROW, "dedupe_header": "X-Event-Id"}
        _mock_state.get_webhook_connector_by_slug.return_value = connector
        _mock_state.find_webhook_connector_event_by_dedupe_key.return_value = {
            "result": "hola old-body", "status": "ok",
        }
        async with app_client as ac:
            resp = await ac.post(
                "/api/webhooks/pagos",
                headers={"Authorization": "Bearer s3cr3t", "X-Event-Id": "evt-1"},
                json={"a": 1},
            )
        assert resp.status_code == 200
        assert resp.json()["result"] == "hola old-body"
        _mock_state.get_flow.assert_not_awaited()


class TestAdminCrud:
    async def test_list_connectors(self, app_client, _mock_state):
        _mock_state.list_webhook_connectors = AsyncMock(return_value=[CONNECTOR_ROW])
        async with app_client as ac:
            resp = await ac.get("/api/webhook-connectors")
        assert resp.status_code == 200
        assert resp.json()[0]["slug"] == "pagos"

    async def test_list_masks_secrets(self, app_client, _mock_state):
        _mock_state.list_webhook_connectors = AsyncMock(return_value=[CONNECTOR_ROW])
        async with app_client as ac:
            resp = await ac.get("/api/webhook-connectors")
        auth_config = json.loads(resp.json()[0]["auth_config"])
        assert auth_config["token"] == "***"

    async def test_create_connector(self, app_client, _mock_state):
        _mock_state.create_webhook_connector = AsyncMock(return_value=9)
        _mock_state.get_webhook_connector = AsyncMock(return_value={**CONNECTOR_ROW, "id": 9})
        async with app_client as ac:
            resp = await ac.post("/api/webhook-connectors", json={
                "slug": "pagos", "name": "Pagos", "auth_scheme": "bearer_token",
                "auth_config": {"token": "s3cr3t", "header_name": "Authorization"}, "flow_id": 7,
            })
        assert resp.status_code == 200
        assert resp.json()["id"] == 9

    async def test_update_connector(self, app_client, _mock_state):
        _mock_state.update_webhook_connector = AsyncMock(return_value=True)
        _mock_state.get_webhook_connector = AsyncMock(return_value=CONNECTOR_ROW)
        async with app_client as ac:
            resp = await ac.patch("/api/webhook-connectors/1", json={"enabled": False})
        assert resp.status_code == 200

    async def test_update_missing_connector_404s(self, app_client, _mock_state):
        _mock_state.update_webhook_connector = AsyncMock(return_value=False)
        async with app_client as ac:
            resp = await ac.patch("/api/webhook-connectors/999", json={"enabled": False})
        assert resp.status_code == 404

    async def test_update_with_masked_placeholder_preserves_real_secret(self, app_client, _mock_state):
        # A client that GETs a connector (masked "***" secret) and PATCHes
        # it straight back must never overwrite the real stored secret with
        # the literal placeholder string.
        _mock_state.update_webhook_connector = AsyncMock(return_value=True)
        _mock_state.get_webhook_connector = AsyncMock(return_value=CONNECTOR_ROW)
        async with app_client as ac:
            resp = await ac.patch("/api/webhook-connectors/1", json={
                "auth_config": {"token": "***", "header_name": "X-Other"},
            })
        assert resp.status_code == 200
        call = _mock_state.update_webhook_connector.call_args
        written_auth_config = call.kwargs["auth_config"]
        assert written_auth_config["token"] == "s3cr3t"  # real secret from CONNECTOR_ROW, not "***"
        assert written_auth_config["header_name"] == "X-Other"  # non-secret field still updates

    async def test_update_with_new_secret_writes_it_through(self, app_client, _mock_state):
        # A genuinely new secret (not the "***" placeholder) must be written
        # as-is — the guard only intercepts the literal placeholder.
        _mock_state.update_webhook_connector = AsyncMock(return_value=True)
        _mock_state.get_webhook_connector = AsyncMock(return_value=CONNECTOR_ROW)
        async with app_client as ac:
            resp = await ac.patch("/api/webhook-connectors/1", json={
                "auth_config": {"token": "brand-new-secret", "header_name": "Authorization"},
            })
        assert resp.status_code == 200
        call = _mock_state.update_webhook_connector.call_args
        written_auth_config = call.kwargs["auth_config"]
        assert written_auth_config["token"] == "brand-new-secret"

    async def test_delete_connector(self, app_client, _mock_state):
        _mock_state.delete_webhook_connector = AsyncMock(return_value=True)
        async with app_client as ac:
            resp = await ac.delete("/api/webhook-connectors/1")
        assert resp.status_code == 200

    async def test_get_connector_events(self, app_client, _mock_state):
        _mock_state.get_webhook_connector = AsyncMock(return_value=CONNECTOR_ROW)
        _mock_state.list_webhook_connector_events = AsyncMock(return_value=[
            {"id": 1, "status": "ok", "result": "hola", "received_at": "2026-09-09T00:00:00"}
        ])
        _mock_state.get_webhook_connector_stats = AsyncMock(return_value={"total": 1, "by_status": {"ok": 1}})
        async with app_client as ac:
            resp = await ac.get("/api/webhook-connectors/1/events")
        assert resp.status_code == 200
        body = resp.json()
        assert body["stats"]["total"] == 1
        assert body["events"][0]["status"] == "ok"
