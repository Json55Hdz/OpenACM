# Webhook Connectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a new signed/authenticated webhook integration be wired up from the dashboard (route, auth, and which Flow to run) instead of writing a new Python plugin per integration.

**Architecture:** A new `webhook_connectors` table holds each connector's config (slug, auth scheme, auth config, target flow). A new public route `POST /api/webhooks/{slug}` looks up the connector, verifies the request with one of three pure auth-verifier functions, runs the connector's Flow via the existing `FlowExecutor`, and returns its result as JSON. Every request (including failed-auth attempts) is logged to a new `webhook_connector_events` table for the dashboard's activity view. Admin CRUD for connectors lives under `/api/webhook-connectors`, protected by the normal dashboard token like any other admin route.

**Tech Stack:** Python (FastAPI, aiosqlite via the existing `Database` class), TypeScript/React (Next.js, `@tanstack/react-query`) for the admin page.

**Spec:** `docs/superpowers/specs/2026-09-09-webhook-connectors-and-agent-flow-node-design.md`

## Global Constraints

- No EnergiChat/EEP-specific naming or logic anywhere in this code — this is generic core infrastructure. (spec, "Contexto y motivación")
- v1 is synchronous only: the HTTP request runs the Flow inline and returns its result. No background-task/async-callback pattern. (spec, "Alcance (YAGNI)")
- Exactly three auth schemes: `hmac_sha256`, `bearer_token`, `static_header_secret`. No pluggable/extensible auth-scheme system. (spec, "Alcance (YAGNI)")
- `webhook_connectors` and `webhook_connector_events` always live in OpenACM's own internal database — no external-Postgres option. (spec, "Dónde vive")
- Success response is always `200 {"result": "<End node template text>"}` — no per-connector status/format config. (spec, §2)
- Never log full request headers (may carry secrets) — only the body and the result/error. (spec, §1.5)

---

## Task 1: Database schema — `webhook_connectors` and `webhook_connector_events`

**Files:**
- Modify: `src/openacm/storage/database.py:171` (`_SCHEMA_VERSION = 36` → `37`)
- Modify: `src/openacm/storage/database.py:1082` (insert new migration block right after Migration 36, before the "Save new version" block at line 1084)
- Test: `tests/unit/test_database_webhook_connectors.py`

**Interfaces:**
- Produces (for Task 2/3/4 to consume):
  - `async def create_webhook_connector(self, slug: str, name: str, auth_scheme: str, auth_config: dict, flow_id: int, dedupe_header: str | None = None) -> int`
  - `async def get_webhook_connector(self, connector_id: int) -> dict[str, Any] | None`
  - `async def get_webhook_connector_by_slug(self, slug: str) -> dict[str, Any] | None`
  - `async def list_webhook_connectors(self) -> list[dict[str, Any]]`
  - `async def update_webhook_connector(self, connector_id: int, **kwargs: Any) -> bool` (allowed kwargs: `name`, `auth_scheme`, `auth_config`, `flow_id`, `enabled`, `dedupe_header`)
  - `async def delete_webhook_connector(self, connector_id: int) -> bool`
  - `async def record_webhook_connector_event(self, connector_id: int, dedupe_key: str | None, body: str, status: str, result: str | None, duration_ms: int) -> int`
  - `async def find_webhook_connector_event_by_dedupe_key(self, connector_id: int, dedupe_key: str) -> dict[str, Any] | None`
  - `async def list_webhook_connector_events(self, connector_id: int, limit: int = 50) -> list[dict[str, Any]]`
  - `async def get_webhook_connector_stats(self, connector_id: int) -> dict[str, Any]` (returns `{"total": int, "by_status": {status: count}}`)

Both `auth_config` (stored) and the dict form returned by getters follow the same in/out convention `create_flow`/`get_flow` use: callers pass a `dict`, the row is stored with `json.dumps`, and returned rows keep `auth_config` as the raw JSON *string* (callers `json.loads` it themselves) — matching how `flows.graph_json` is handled today (see `agents.py:261`, `_parse_and_validate_graph`).

- [ ] **Step 1: Write the failing schema tests**

```python
"""Tests for the webhook_connectors / webhook_connector_events migration."""
import pytest
from openacm.storage.database import Database


async def _make_db():
    db = Database(":memory:")
    await db.initialize()
    return db


class TestMigration37Schema:
    async def test_webhook_connectors_table_exists(self):
        db = await _make_db()
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='webhook_connectors'"
        )
        assert await cursor.fetchone() is not None

    async def test_webhook_connector_events_table_exists(self):
        db = await _make_db()
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='webhook_connector_events'"
        )
        assert await cursor.fetchone() is not None

    async def test_slug_is_unique(self):
        db = await _make_db()
        cid = await db.create_webhook_connector(
            slug="pagos", name="Pagos", auth_scheme="bearer_token",
            auth_config={"token": "t", "header_name": "Authorization"}, flow_id=1,
        )
        assert cid > 0
        with pytest.raises(Exception):
            await db.create_webhook_connector(
                slug="pagos", name="Pagos 2", auth_scheme="bearer_token",
                auth_config={"token": "t2", "header_name": "Authorization"}, flow_id=2,
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_database_webhook_connectors.py -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'create_webhook_connector'`

- [ ] **Step 3: Bump `_SCHEMA_VERSION` and add the migration**

In `src/openacm/storage/database.py`, change line 171:
```python
    _SCHEMA_VERSION = 37
```

Insert immediately after the Migration 36 block (right before the `# Save new version` comment currently at line 1084):

```python
        # ── Migration 37: webhook connectors ──────────────────────────────
        # A connector = a dashboard-configured, publicly reachable webhook
        # (POST /api/webhooks/{slug}) that verifies its own request per
        # auth_scheme/auth_config and runs flow_id on a valid request. See
        # docs/superpowers/specs/2026-09-09-webhook-connectors-and-agent-flow-node-design.md.
        if current < 37:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS webhook_connectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    auth_scheme TEXT NOT NULL,
                    auth_config TEXT NOT NULL,
                    flow_id INTEGER NOT NULL REFERENCES flows(id) ON DELETE CASCADE,
                    dedupe_header TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS webhook_connector_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    connector_id INTEGER NOT NULL REFERENCES webhook_connectors(id) ON DELETE CASCADE,
                    dedupe_key TEXT,
                    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    body TEXT,
                    status TEXT NOT NULL,
                    result TEXT,
                    duration_ms INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_webhook_connector_events_connector
                    ON webhook_connector_events(connector_id);
                CREATE INDEX IF NOT EXISTS idx_webhook_connector_events_dedupe
                    ON webhook_connector_events(connector_id, dedupe_key);
            """)
            await self._db.commit()
            log.info("Migration 37: webhook connectors (webhook_connectors, webhook_connector_events)")

```

- [ ] **Step 4: Add the CRUD methods**

Add a new section to `database.py`, near the Flows section (after `delete_flow`, before `# ─── Agent Connections ────`):

```python
    # ─── Webhook Connectors ───────────────────────────────────

    async def create_webhook_connector(
        self,
        slug: str,
        name: str,
        auth_scheme: str,
        auth_config: dict[str, Any],
        flow_id: int,
        dedupe_header: str | None = None,
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO webhook_connectors (slug, name, auth_scheme, auth_config, flow_id, dedupe_header) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (slug, name, auth_scheme, json.dumps(auth_config), flow_id, dedupe_header),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_webhook_connector(self, connector_id: int) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM webhook_connectors WHERE id = ?", (connector_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_webhook_connector_by_slug(self, slug: str) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM webhook_connectors WHERE slug = ?", (slug,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_webhook_connectors(self) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute("SELECT * FROM webhook_connectors ORDER BY name")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_webhook_connector(self, connector_id: int, **kwargs: Any) -> bool:
        if not self._db:
            return False
        allowed = {"name", "auth_scheme", "auth_config", "flow_id", "enabled", "dedupe_header"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key not in allowed:
                continue
            if key == "auth_config" and isinstance(val, dict):
                val = json.dumps(val)
            updates.append(f"{key} = ?")
            params.append(val)
        if not updates:
            return False
        query = f"UPDATE webhook_connectors SET {', '.join(updates)} WHERE id = ?"
        params.append(connector_id)
        cursor = await self._db.execute(query, params)
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_webhook_connector(self, connector_id: int) -> bool:
        if not self._db:
            return False
        cursor = await self._db.execute("DELETE FROM webhook_connectors WHERE id = ?", (connector_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def record_webhook_connector_event(
        self,
        connector_id: int,
        dedupe_key: str | None,
        body: str,
        status: str,
        result: str | None,
        duration_ms: int,
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO webhook_connector_events "
            "(connector_id, dedupe_key, body, status, result, duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
            (connector_id, dedupe_key, body, status, result, duration_ms),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def find_webhook_connector_event_by_dedupe_key(
        self, connector_id: int, dedupe_key: str
    ) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM webhook_connector_events WHERE connector_id = ? AND dedupe_key = ? "
            "ORDER BY received_at ASC LIMIT 1",
            (connector_id, dedupe_key),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_webhook_connector_events(self, connector_id: int, limit: int = 50) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM webhook_connector_events WHERE connector_id = ? "
            "ORDER BY received_at DESC LIMIT ?",
            (connector_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_webhook_connector_stats(self, connector_id: int) -> dict[str, Any]:
        if not self._db:
            return {"total": 0, "by_status": {}}
        total_cursor = await self._db.execute(
            "SELECT COUNT(*) AS c FROM webhook_connector_events WHERE connector_id = ?", (connector_id,)
        )
        total_row = await total_cursor.fetchone()
        by_status_cursor = await self._db.execute(
            "SELECT status, COUNT(*) AS c FROM webhook_connector_events "
            "WHERE connector_id = ? GROUP BY status",
            (connector_id,),
        )
        by_status_rows = await by_status_cursor.fetchall()
        return {
            "total": total_row["c"],
            "by_status": {r["status"]: r["c"] for r in by_status_rows},
        }

```

- [ ] **Step 5: Add more CRUD/dedupe/stats tests, run everything, and commit**

Append to `tests/unit/test_database_webhook_connectors.py`:

```python
class TestCrud:
    async def test_get_by_slug(self):
        db = await _make_db()
        await db.create_webhook_connector(
            slug="pagos", name="Pagos", auth_scheme="bearer_token",
            auth_config={"token": "t", "header_name": "Authorization"}, flow_id=1,
        )
        row = await db.get_webhook_connector_by_slug("pagos")
        assert row is not None
        assert row["name"] == "Pagos"
        assert row["enabled"] == 1

    async def test_get_by_slug_missing_returns_none(self):
        db = await _make_db()
        assert await db.get_webhook_connector_by_slug("nope") is None

    async def test_update_toggles_enabled(self):
        db = await _make_db()
        cid = await db.create_webhook_connector(
            slug="pagos", name="Pagos", auth_scheme="bearer_token",
            auth_config={"token": "t", "header_name": "Authorization"}, flow_id=1,
        )
        ok = await db.update_webhook_connector(cid, enabled=0)
        assert ok is True
        row = await db.get_webhook_connector(cid)
        assert row["enabled"] == 0

    async def test_delete(self):
        db = await _make_db()
        cid = await db.create_webhook_connector(
            slug="pagos", name="Pagos", auth_scheme="bearer_token",
            auth_config={"token": "t", "header_name": "Authorization"}, flow_id=1,
        )
        assert await db.delete_webhook_connector(cid) is True
        assert await db.get_webhook_connector(cid) is None


class TestEventsAndStats:
    async def test_record_and_list_events(self):
        db = await _make_db()
        cid = await db.create_webhook_connector(
            slug="pagos", name="Pagos", auth_scheme="bearer_token",
            auth_config={"token": "t", "header_name": "Authorization"}, flow_id=1,
        )
        await db.record_webhook_connector_event(cid, None, '{"a":1}', "ok", "done", 12)
        events = await db.list_webhook_connector_events(cid)
        assert len(events) == 1
        assert events[0]["status"] == "ok"

    async def test_find_by_dedupe_key(self):
        db = await _make_db()
        cid = await db.create_webhook_connector(
            slug="pagos", name="Pagos", auth_scheme="bearer_token",
            auth_config={"token": "t", "header_name": "Authorization"}, flow_id=1,
        )
        await db.record_webhook_connector_event(cid, "evt-1", "{}", "ok", "done", 5)
        found = await db.find_webhook_connector_event_by_dedupe_key(cid, "evt-1")
        assert found is not None
        assert await db.find_webhook_connector_event_by_dedupe_key(cid, "evt-2") is None

    async def test_stats(self):
        db = await _make_db()
        cid = await db.create_webhook_connector(
            slug="pagos", name="Pagos", auth_scheme="bearer_token",
            auth_config={"token": "t", "header_name": "Authorization"}, flow_id=1,
        )
        await db.record_webhook_connector_event(cid, None, "{}", "ok", "done", 5)
        await db.record_webhook_connector_event(cid, None, "{}", "auth_failed", None, 1)
        stats = await db.get_webhook_connector_stats(cid)
        assert stats["total"] == 2
        assert stats["by_status"] == {"ok": 1, "auth_failed": 1}
```

Run: `pytest tests/unit/test_database_webhook_connectors.py -v`
Expected: all PASS.

```bash
git add src/openacm/storage/database.py tests/unit/test_database_webhook_connectors.py
git commit -m "feat(webhooks): add webhook_connectors + webhook_connector_events schema and CRUD"
```

---

## Task 2: Auth verifiers

**Files:**
- Create: `src/openacm/core/webhook_auth.py`
- Test: `tests/unit/test_webhook_auth.py`

**Interfaces:**
- Consumes: nothing from other tasks — pure functions.
- Produces (for Task 3 to consume):
  - `def verify_hmac_sha256(auth_config: dict, headers: dict[str, str], raw_body: bytes, *, now: float | None = None) -> bool`
  - `def verify_bearer_token(auth_config: dict, headers: dict[str, str]) -> bool`
  - `def verify_static_header_secret(auth_config: dict, headers: dict[str, str]) -> bool`
  - `def verify_request(auth_scheme: str, auth_config: dict, headers: dict[str, str], raw_body: bytes) -> bool` (dispatches to the three above; returns `False` for an unknown `auth_scheme` instead of raising)

`headers` is expected pre-lowercased-key or looked up case-insensitively by
the caller (FastAPI's `Request.headers` is already case-insensitive) — these
functions just do plain dict `.get(name)` with whatever header names are in
`auth_config`, so the caller passes `request.headers` directly (a
`starlette.datastructures.Headers`, which behaves like a case-insensitive
dict and satisfies `.get`).

`auth_config` shapes (already the spec's, repeated here for the implementer):
- `hmac_sha256`: `{"secret": str, "timestamp_header": str, "signature_header": str, "max_skew_seconds": int}`
- `bearer_token`: `{"token": str, "header_name": str}`
- `static_header_secret`: `{"header_name": str, "secret": str}`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the three generic webhook auth verifiers."""
import hashlib
import hmac as hmac_stdlib
import time

from openacm.core.webhook_auth import (
    verify_bearer_token,
    verify_hmac_sha256,
    verify_request,
    verify_static_header_secret,
)


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac_stdlib.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


HMAC_CONFIG = {
    "secret": "test-secret-32-characters-long!!",
    "timestamp_header": "X-Timestamp",
    "signature_header": "X-Signature",
    "max_skew_seconds": 300,
}


class TestVerifyHmacSha256:
    def test_valid_signature_passes(self):
        now = 1788361200.0
        body = b'{"a":1}'
        ts = "1788361200"
        headers = {"X-Timestamp": ts, "X-Signature": _sign(HMAC_CONFIG["secret"], ts, body)}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, body, now=now) is True

    def test_tampered_body_fails(self):
        now = 1788361200.0
        ts = "1788361200"
        headers = {"X-Timestamp": ts, "X-Signature": _sign(HMAC_CONFIG["secret"], ts, b'{"a":1}')}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, b'{"a":2}', now=now) is False

    def test_wrong_secret_fails(self):
        now = 1788361200.0
        ts = "1788361200"
        body = b'{"a":1}'
        headers = {"X-Timestamp": ts, "X-Signature": _sign("wrong-secret", ts, body)}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, body, now=now) is False

    def test_expired_timestamp_fails(self):
        ts = "1788361200"
        body = b'{"a":1}'
        headers = {"X-Timestamp": ts, "X-Signature": _sign(HMAC_CONFIG["secret"], ts, body)}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, body, now=1788361200.0 + 301) is False

    def test_missing_signature_header_fails(self):
        headers = {"X-Timestamp": "1788361200"}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, b"{}", now=1788361200.0) is False

    def test_missing_timestamp_header_fails(self):
        headers = {"X-Signature": "sha256=" + "0" * 64}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, b"{}", now=1788361200.0) is False


BEARER_CONFIG = {"token": "s3cr3t-token", "header_name": "Authorization"}


class TestVerifyBearerToken:
    def test_valid_token_passes(self):
        assert verify_bearer_token(BEARER_CONFIG, {"Authorization": "Bearer s3cr3t-token"}) is True

    def test_wrong_token_fails(self):
        assert verify_bearer_token(BEARER_CONFIG, {"Authorization": "Bearer nope"}) is False

    def test_missing_header_fails(self):
        assert verify_bearer_token(BEARER_CONFIG, {}) is False

    def test_missing_bearer_prefix_fails(self):
        assert verify_bearer_token(BEARER_CONFIG, {"Authorization": "s3cr3t-token"}) is False


STATIC_CONFIG = {"header_name": "X-Api-Secret", "secret": "s3cr3t"}


class TestVerifyStaticHeaderSecret:
    def test_matching_secret_passes(self):
        assert verify_static_header_secret(STATIC_CONFIG, {"X-Api-Secret": "s3cr3t"}) is True

    def test_wrong_secret_fails(self):
        assert verify_static_header_secret(STATIC_CONFIG, {"X-Api-Secret": "nope"}) is False

    def test_missing_header_fails(self):
        assert verify_static_header_secret(STATIC_CONFIG, {}) is False


class TestVerifyRequestDispatch:
    def test_dispatches_to_hmac(self):
        now = 1788361200.0
        ts = "1788361200"
        body = b"{}"
        headers = {"X-Timestamp": ts, "X-Signature": _sign(HMAC_CONFIG["secret"], ts, body)}
        assert verify_request("hmac_sha256", HMAC_CONFIG, headers, body) is False  # no `now` override -> real clock, expired

    def test_dispatches_to_bearer(self):
        assert verify_request("bearer_token", BEARER_CONFIG, {"Authorization": "Bearer s3cr3t-token"}, b"{}") is True

    def test_dispatches_to_static_header(self):
        assert verify_request("static_header_secret", STATIC_CONFIG, {"X-Api-Secret": "s3cr3t"}, b"{}") is True

    def test_unknown_scheme_returns_false(self):
        assert verify_request("something_else", {}, {}, b"{}") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_webhook_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'openacm.core.webhook_auth'`

- [ ] **Step 3: Implement `webhook_auth.py`**

```python
"""
Generic, provider-agnostic verifiers for webhook connectors (see
docs/superpowers/specs/2026-09-09-webhook-connectors-and-agent-flow-node-design.md).

Each function takes a connector's `auth_config` dict (shape depends on the
scheme — see the spec) plus the incoming request's headers (and raw body,
for HMAC) and returns a plain bool. No exceptions for "invalid" — only for
genuinely malformed input the caller couldn't have avoided (there is none
here; every failure mode returns False).
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any


def verify_hmac_sha256(
    auth_config: dict[str, Any],
    headers: Any,
    raw_body: bytes,
    *,
    now: float | None = None,
) -> bool:
    """firma = HMAC-SHA256(secret, "<timestamp>.<raw body bytes>"),
    header value "sha256=<hex>". Rejects a timestamp more than
    max_skew_seconds away from now (either direction)."""
    timestamp = headers.get(auth_config["timestamp_header"])
    signature = headers.get(auth_config["signature_header"])
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = now if now is not None else time.time()
    if abs(current - ts) > auth_config.get("max_skew_seconds", 300):
        return False
    message = f"{timestamp}.".encode("utf-8") + raw_body
    digest = hmac.new(auth_config["secret"].encode("utf-8"), message, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, signature)


def verify_bearer_token(auth_config: dict[str, Any], headers: Any) -> bool:
    header_name = auth_config.get("header_name", "Authorization")
    value = headers.get(header_name, "")
    if not value.startswith("Bearer "):
        return False
    return hmac.compare_digest(value[len("Bearer "):], auth_config["token"])


def verify_static_header_secret(auth_config: dict[str, Any], headers: Any) -> bool:
    value = headers.get(auth_config["header_name"], "")
    if not value:
        return False
    return hmac.compare_digest(value, auth_config["secret"])


_VERIFIERS = {
    "hmac_sha256": lambda cfg, headers, raw_body: verify_hmac_sha256(cfg, headers, raw_body),
    "bearer_token": lambda cfg, headers, raw_body: verify_bearer_token(cfg, headers),
    "static_header_secret": lambda cfg, headers, raw_body: verify_static_header_secret(cfg, headers),
}


def verify_request(auth_scheme: str, auth_config: dict[str, Any], headers: Any, raw_body: bytes) -> bool:
    verifier = _VERIFIERS.get(auth_scheme)
    if verifier is None:
        return False
    return verifier(auth_config, headers, raw_body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_webhook_auth.py -v`
Expected: all PASS (18 tests).

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/webhook_auth.py tests/unit/test_webhook_auth.py
git commit -m "feat(webhooks): add generic hmac_sha256/bearer_token/static_header_secret verifiers"
```

---

## Task 3: Generic public route `POST /api/webhooks/{slug}`

**Files:**
- Create: `src/openacm/web/routers/webhooks.py`
- Modify: `src/openacm/web/server.py:164` (import) and `:176` (register call)
- Modify: `src/openacm/web/routers/system.py` (TokenAuthMiddleware exemption)
- Test: `tests/unit/test_webhooks_router.py`

**Interfaces:**
- Consumes:
  - `Database.get_webhook_connector_by_slug`, `.record_webhook_connector_event`, `.find_webhook_connector_event_by_dedupe_key`, `.get_flow` (Task 1)
  - `webhook_auth.verify_request` (Task 2)
  - `FlowExecutor`, `is_error_result` from `openacm.core.flow_executor` (existing)
- Produces: `register_routes(app: FastAPI) -> None` — same pattern every router module uses (see `agents.register_routes`).

- [ ] **Step 1: Write the failing router tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_webhooks_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'openacm.web.routers.webhooks'`

- [ ] **Step 3: Implement `webhooks.py`**

```python
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
```

- [ ] **Step 4: Register the router in `server.py`**

In `src/openacm/web/server.py:164`, add `webhooks` to the import:
```python
    from openacm.web.routers import system, config, chat, skills, agents, mcp, activity, cron, swarms, voice as voice_router, whatsapp_webhook, webhooks
```
And after line 176 (`whatsapp_webhook.register_routes(app)`), add:
```python
    webhooks.register_routes(app)
```

- [ ] **Step 5: Exempt `/api/webhooks/` from the dashboard-token check**

In `src/openacm/web/routers/system.py`, right after the plugin-declared-public-paths block (after the line currently reading `except Exception:` / `pass` around line 70-71, before the `# Check token for other API routes` comment at line 73), add:

```python
            # Webhook connectors verify their own request authenticity per
            # their configured auth_scheme (see webhook_auth.py) — never
            # the dashboard token.
            if path.startswith("/api/webhooks/"):
                return await call_next(request)

```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_webhooks_router.py -v`
Expected: all PASS (9 tests).

- [ ] **Step 7: Commit**

```bash
git add src/openacm/web/routers/webhooks.py src/openacm/web/server.py src/openacm/web/routers/system.py tests/unit/test_webhooks_router.py
git commit -m "feat(webhooks): add generic POST /api/webhooks/{slug} trigger route"
```

---

## Task 4: Admin CRUD endpoints `/api/webhook-connectors`

**Files:**
- Modify: `src/openacm/web/routers/webhooks.py` (add to the same `register_routes`)
- Test: `tests/unit/test_webhooks_router.py` (append)

**Interfaces:**
- Consumes: the same `Database` CRUD methods from Task 1.
- Produces: standard REST endpoints, protected by the normal dashboard token (no special exemption — these are NOT under `/api/webhooks/`, they're under `/api/webhook-connectors`, so `TokenAuthMiddleware`'s default deny already covers them; only the trigger route in Task 3 needed the explicit prefix exemption).

Response shape for a connector always **omits the auth secret value** except
right after creation (mirrors `get_agent_secret` — `webhook_secret` returned
once) — for `bearer_token`/`static_header_secret`/`hmac_sha256` the secret
field inside `auth_config` is masked to `"***"` on every read after creation,
same masking convention already used by the EEP plugin's own
`get_plugin_config` (`"***" if saved.get(key) else ""` for password fields).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_webhooks_router.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_webhooks_router.py::TestAdminCrud -v`
Expected: FAIL (404s / AttributeErrors — routes and mocked methods don't exist yet).

- [ ] **Step 3: Implement the admin endpoints**

Add to `webhooks.py`'s `register_routes(app)`, alongside `trigger_connector`:

```python
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
```

Note: `create_connector`/`update_connector` intentionally do **not** mask the
secret before storing — `_mask_secret` is applied only to what's returned to
the client, never to what's saved. A `PATCH` sending back a previously-masked
`"***"` value would silently corrupt the stored secret; the frontend (Task 5)
must never send `auth_config` back on update unless the user actually typed
a new secret in the form (same convention `plugin-config-form.tsx`'s `"***"`
password-field handling already uses — see `save_plugin_config` in
`system.py`, which special-cases `"***"` to mean "unchanged").

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_webhooks_router.py -v`
Expected: all PASS (16 tests total for the file).

- [ ] **Step 5: Commit**

```bash
git add src/openacm/web/routers/webhooks.py tests/unit/test_webhooks_router.py
git commit -m "feat(webhooks): add admin CRUD endpoints for webhook connectors"
```

---

## Task 5: Frontend — Connectors admin page

**Files:**
- Create: `frontend/hooks/use-webhook-connectors.ts`
- Create: `frontend/app/webhook-connectors/page.tsx`
- Modify: `frontend/components/layout/sidebar.tsx` (add a nav entry)

**Interfaces:**
- Consumes: the REST endpoints from Task 4 (`GET/POST /api/webhook-connectors`, `PATCH/DELETE /api/webhook-connectors/{id}`, `GET /api/webhook-connectors/{id}/events`).
- Produces: a page reachable from the sidebar where an admin creates/edits/enables/disables a connector and views its recent activity + stats.

- [ ] **Step 1: Write the hooks file**

```typescript
'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

export interface WebhookConnector {
  id: number;
  slug: string;
  name: string;
  auth_scheme: 'hmac_sha256' | 'bearer_token' | 'static_header_secret';
  auth_config: string; // JSON string, secret fields masked as "***" except right after create
  flow_id: number;
  dedupe_header: string | null;
  enabled: number;
  created_at: string;
}

export interface WebhookConnectorEvent {
  id: number;
  received_at: string;
  status: 'ok' | 'auth_failed' | 'bad_request' | 'flow_error';
  result: string | null;
  duration_ms: number;
}

export interface WebhookConnectorStats {
  total: number;
  by_status: Record<string, number>;
}

export function useWebhookConnectors() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  return useQuery<WebhookConnector[]>({
    queryKey: ['webhook-connectors'],
    queryFn: () => fetchAPI('/api/webhook-connectors'),
    enabled: isAuthenticated,
  });
}

export function useWebhookConnectorEvents(connectorId: number | null) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();
  return useQuery<{ events: WebhookConnectorEvent[]; stats: WebhookConnectorStats }>({
    queryKey: ['webhook-connector-events', connectorId],
    queryFn: () => fetchAPI(`/api/webhook-connectors/${connectorId}/events`),
    enabled: isAuthenticated && connectorId !== null,
  });
}

export function useWebhookConnectorMutations() {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['webhook-connectors'] });

  const create = useMutation({
    mutationFn: (data: Omit<WebhookConnector, 'id' | 'created_at' | 'enabled'> & { auth_config: object }) =>
      fetchAPI('/api/webhook-connectors', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: ({ id, ...data }: { id: number; [key: string]: unknown }) =>
      fetchAPI(`/api/webhook-connectors/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: number) => fetchAPI(`/api/webhook-connectors/${id}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  });

  return { create, update, remove };
}
```

- [ ] **Step 2: Write the page**

```typescript
'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import {
  useWebhookConnectors, useWebhookConnectorEvents, useWebhookConnectorMutations,
  type WebhookConnector,
} from '@/hooks/use-webhook-connectors';

export default function WebhookConnectorsPage() {
  const { data: connectors, isLoading } = useWebhookConnectors();
  const { update } = useWebhookConnectorMutations();
  const [selected, setSelected] = useState<number | null>(null);
  const { data: eventsData } = useWebhookConnectorEvents(selected);

  return (
    <AppLayout>
      <div style={{ padding: 32, maxWidth: 1000, margin: '0 auto' }}>
        <h1 className="font-bold" style={{ fontSize: 24, marginBottom: 20 }}>Conectores de Webhook</h1>
        {isLoading ? (
          <p>Cargando…</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {(connectors ?? []).map((c: WebhookConnector) => (
              <div
                key={c.id}
                className="acm-card"
                style={{ padding: 16, cursor: 'pointer' }}
                onClick={() => setSelected(c.id)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <strong>{c.name}</strong>
                    <div className="mono" style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>
                      /api/webhooks/{c.slug} · {c.auth_scheme}
                    </div>
                  </div>
                  <button
                    className="btn-secondary"
                    onClick={(e) => { e.stopPropagation(); update.mutate({ id: c.id, enabled: c.enabled ? 0 : 1 }); }}
                  >
                    {c.enabled ? 'Apagar' : 'Encender'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {selected && eventsData && (
          <div style={{ marginTop: 24 }}>
            <h2 style={{ fontSize: 16, marginBottom: 8 }}>
              Actividad — total {eventsData.stats.total}
            </h2>
            <table style={{ width: '100%', fontSize: 13 }}>
              <tbody>
                {eventsData.events.map((e) => (
                  <tr key={e.id}>
                    <td>{e.received_at}</td>
                    <td>{e.status}</td>
                    <td>{e.result}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
```

- [ ] **Step 3: Add the sidebar nav entry**

In `frontend/components/layout/sidebar.tsx`, add to the `coreNavItems` array (same array `{ href: '/plugins', label: t.plugins, icon: Puzzle }` lives in — reuse the existing `Plug` icon import already used for `/mcp`, or `Webhook` from `lucide-react` if available):
```typescript
  { href: '/webhook-connectors', label: 'Conectores', icon: Webhook },
```
(Add `Webhook` to the `lucide-react` import list at the top of the file if it isn't already imported.)

- [ ] **Step 4: Manual verification**

Run the frontend dev server (`npm run dev` in `frontend/`), log in, navigate to
`/webhook-connectors`. Confirm the page loads without console errors (an
empty list is fine — no connector exists yet). Confirm the sidebar entry
appears and links there.

- [ ] **Step 5: Build and deploy the frontend**

```bash
cd frontend
npm run build
```
Expected: build succeeds with no new TypeScript errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/hooks/use-webhook-connectors.ts frontend/app/webhook-connectors/page.tsx frontend/components/layout/sidebar.tsx
git commit -m "feat(webhooks): add Connectors admin page"
```

---

## Final verification

- [ ] Run the full backend test suite: `pytest` from the repo root — no regressions.
- [ ] Run `npm run build` in `frontend/` — no new errors.
- [ ] Manually create a test connector (via the new page or `curl -X POST /api/webhook-connectors`) pointing at a trivial Flow (Start → End with a fixed template), then `curl -X POST /api/webhooks/<slug>` with the right auth header and confirm a `200 {"result": "..."}` comes back, and that the event shows up under `GET /api/webhook-connectors/{id}/events`.
