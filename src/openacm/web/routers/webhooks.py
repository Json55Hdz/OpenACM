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
