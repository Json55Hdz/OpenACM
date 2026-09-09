"""
Generic public webhook trigger: POST /api/webhooks/{slug} looks up a
dashboard-configured connector, verifies the request per its own
auth_scheme, runs its Flow, and returns the Flow's result. See
docs/superpowers/specs/2026-09-09-webhook-connectors-and-agent-flow-node-design.md.

Deliberately synchronous (v1): the Flow runs inline within the request.
"""
from __future__ import annotations

import json
import time
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from openacm.web.state import _state

log = structlog.get_logger()


def register_routes(app: FastAPI) -> None:
    @app.post("/api/webhooks/{slug}")
    async def trigger_connector(slug: str, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")

        connector = await _state.database.get_webhook_connector_by_slug(slug)
        if not connector or not connector.get("enabled"):
            raise HTTPException(status_code=404, detail="Connector not found")

        raw_body = await request.body()

        from openacm.core.webhook_auth import verify_request

        auth_config = json.loads(connector["auth_config"])
        if not verify_request(connector["auth_scheme"], auth_config, request.headers, raw_body):
            await _state.database.record_webhook_connector_event(
                connector["id"], None, raw_body.decode("utf-8", errors="replace"), "auth_failed", None, 0,
            )
            return JSONResponse(status_code=401, content={"error": "Invalid credentials"})

        try:
            body: dict[str, Any] = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

        dedupe_key = None
        if connector.get("dedupe_header"):
            dedupe_key = request.headers.get(connector["dedupe_header"])
            if dedupe_key:
                existing = await _state.database.find_webhook_connector_event_by_dedupe_key(
                    connector["id"], dedupe_key
                )
                if existing is not None:
                    return JSONResponse(status_code=200, content={"result": existing["result"]})

        flow = await _state.database.get_flow(connector["flow_id"])
        if not flow:
            await _state.database.record_webhook_connector_event(
                connector["id"], dedupe_key, raw_body.decode("utf-8", errors="replace"),
                "flow_error", "Configured flow not found", 0,
            )
            raise HTTPException(status_code=500, detail="Connector's flow is missing")

        from openacm.core.flow_executor import FlowExecutor, is_error_result, validate_graph

        graph = json.loads(flow["graph_json"])

        # Structural problems (no Start/End node, unknown node type, a cycle)
        # are OUR configuration mistake, not a runtime failure — caught here,
        # before ever running the flow, so they map to 500 and never get
        # confused with a genuine runtime error (e.g. an HTTP call inside the
        # flow failing), which maps to 502 below. FlowExecutor.run() itself
        # can't tell these apart — both surface as the same "Error: ..."
        # string via is_error_result() — so the distinction has to happen here.
        graph_errors = validate_graph(graph)
        if graph_errors:
            await _state.database.record_webhook_connector_event(
                connector["id"], dedupe_key, raw_body.decode("utf-8", errors="replace"),
                "flow_error", "; ".join(graph_errors), 0,
            )
            raise HTTPException(status_code=500, detail="Connector's flow is misconfigured: " + "; ".join(graph_errors))

        start = time.monotonic()
        executor = FlowExecutor()
        result, _outputs = await executor.run(graph, {"headers": dict(request.headers), "body": body})
        duration_ms = int((time.monotonic() - start) * 1000)

        if is_error_result(result):
            await _state.database.record_webhook_connector_event(
                connector["id"], dedupe_key, raw_body.decode("utf-8", errors="replace"),
                "flow_error", result, duration_ms,
            )
            return JSONResponse(status_code=502, content={"error": result})

        await _state.database.record_webhook_connector_event(
            connector["id"], dedupe_key, raw_body.decode("utf-8", errors="replace"),
            "ok", result, duration_ms,
        )
        return JSONResponse(status_code=200, content={"result": result})

    def _mask_secret(connector: dict) -> dict:
        masked = dict(connector)
        auth_config = json.loads(masked["auth_config"])
        for key in ("secret", "token"):
            if auth_config.get(key):
                auth_config[key] = "***"
        masked["auth_config"] = json.dumps(auth_config)
        return masked

    @app.get("/api/webhook-connectors")
    async def list_connectors():
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        rows = await _state.database.list_webhook_connectors()
        return [_mask_secret(r) for r in rows]

    @app.get("/api/webhook-connectors/{connector_id}")
    async def get_connector(connector_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        row = await _state.database.get_webhook_connector(connector_id)
        if not row:
            raise HTTPException(status_code=404, detail="Connector not found")
        return _mask_secret(row)

    @app.post("/api/webhook-connectors")
    async def create_connector(request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        for field in ("slug", "name", "auth_scheme", "auth_config", "flow_id"):
            if field not in data:
                raise HTTPException(status_code=400, detail=f"Missing field: {field}")
        connector_id = await _state.database.create_webhook_connector(
            slug=data["slug"], name=data["name"], auth_scheme=data["auth_scheme"],
            auth_config=data["auth_config"], flow_id=data["flow_id"],
            dedupe_header=data.get("dedupe_header"),
        )
        row = await _state.database.get_webhook_connector(connector_id)
        return _mask_secret(row)

    @app.patch("/api/webhook-connectors/{connector_id}")
    async def update_connector(connector_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        if isinstance(data.get("auth_config"), dict):
            existing = await _state.database.get_webhook_connector(connector_id)
            if existing:
                # "***" means "leave this field unchanged" — same convention
                # save_plugin_config() uses for masked password fields — so a
                # client that round-trips the masked read-back response
                # (list/get always return "***" for secret/token) can never
                # clobber the real stored secret.
                existing_auth_config = json.loads(existing["auth_config"])
                for key in ("secret", "token"):
                    if data["auth_config"].get(key) == "***":
                        data["auth_config"][key] = existing_auth_config.get(key)
        ok = await _state.database.update_webhook_connector(connector_id, **data)
        if not ok:
            raise HTTPException(status_code=404, detail="Connector not found")
        row = await _state.database.get_webhook_connector(connector_id)
        return _mask_secret(row)

    @app.delete("/api/webhook-connectors/{connector_id}")
    async def delete_connector(connector_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        ok = await _state.database.delete_webhook_connector(connector_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Connector not found")
        return {"status": "ok", "deleted": True}

    @app.get("/api/webhook-connectors/{connector_id}/events")
    async def get_connector_events(connector_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        connector = await _state.database.get_webhook_connector(connector_id)
        if not connector:
            raise HTTPException(status_code=404, detail="Connector not found")
        events = await _state.database.list_webhook_connector_events(connector_id)
        stats = await _state.database.get_webhook_connector_stats(connector_id)
        return {"events": events, "stats": stats}
