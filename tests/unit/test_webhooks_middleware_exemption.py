"""The security boundary itself: the real TokenAuthMiddleware standing next
to the webhooks router.

`POST /api/webhooks/{slug}` is deliberately exempt from the dashboard token
(each connector verifies its own request per its configured auth_scheme), while
the `/api/webhook-connectors*` admin routes are NOT. Everything else about the
feature is tested with the middleware absent, so this file is the only place
that proves the exemption is exactly as wide as intended.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from openacm.web.routers import system as system_router
from openacm.web.routers import webhooks as webhooks_router
from openacm.web.state import _state

DASHBOARD_TOKEN = "dash-token-for-tests"

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


@pytest.fixture
def app_client(monkeypatch):
    # Read at register_routes() time, so it has to be set before the call.
    monkeypatch.setenv("DASHBOARD_TOKEN", DASHBOARD_TOKEN)

    db = MagicMock()
    db.get_webhook_connector_by_slug = AsyncMock(return_value=CONNECTOR_ROW)
    db.get_flow = AsyncMock(return_value={"id": 7, "graph_json": SIMPLE_FLOW_GRAPH})
    db.find_webhook_connector_event_by_dedupe_key = AsyncMock(return_value=None)
    db.record_webhook_connector_event = AsyncMock(return_value=1)
    db.list_webhook_connectors = AsyncMock(return_value=[CONNECTOR_ROW])
    monkeypatch.setattr(_state, "database", db)

    app = FastAPI()
    system_router.register_routes(app)   # installs the real TokenAuthMiddleware
    webhooks_router.register_routes(app)
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    monkeypatch.setattr(_state, "database", None)


class TestMiddlewareExemption:
    async def test_public_webhook_route_is_not_blocked_by_the_dashboard_token(self, app_client):
        # No Authorization header at all. The connector's own bearer_token
        # verifier rejects it with 401 {"error": "Invalid credentials"} — the
        # point is that it reached the route, i.e. the middleware's generic
        # "Unauthorized. Provide a valid token." never fired.
        async with app_client as ac:
            resp = await ac.post("/api/webhooks/pagos", json={"a": 1})
        assert resp.json().get("error") != "Unauthorized. Provide a valid token."
        assert resp.json() == {"error": "Invalid credentials"}

    async def test_public_webhook_route_runs_with_its_own_credentials(self, app_client):
        # The connector's own scheme is what gates it: with the connector's
        # token (and no dashboard token) the request gets past auth entirely.
        async with app_client as ac:
            resp = await ac.post(
                "/api/webhooks/pagos", headers={"Authorization": "Bearer s3cr3t"}, json={"a": 1},
            )
        assert resp.status_code != 401

    async def test_admin_route_without_token_401s(self, app_client):
        async with app_client as ac:
            resp = await ac.get("/api/webhook-connectors")
        assert resp.status_code == 401
        assert resp.json() == {"error": "Unauthorized. Provide a valid token."}

    async def test_admin_route_with_wrong_token_401s(self, app_client):
        async with app_client as ac:
            resp = await ac.get(
                "/api/webhook-connectors", headers={"Authorization": "Bearer not-the-token"},
            )
        assert resp.status_code == 401
        assert resp.json() == {"error": "Unauthorized. Provide a valid token."}

    async def test_admin_route_with_valid_token_passes(self, app_client):
        async with app_client as ac:
            resp = await ac.get(
                "/api/webhook-connectors", headers={"Authorization": f"Bearer {DASHBOARD_TOKEN}"},
            )
        assert resp.status_code == 200
        assert resp.json()[0]["slug"] == "pagos"
