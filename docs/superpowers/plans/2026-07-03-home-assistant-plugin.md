# Home Assistant Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace OpenACM's hardcoded IoT drivers (Tuya, LG TV, Miio) with one plugin, `home_assistant`, that controls smart-home devices through a running Home Assistant instance's REST + WebSocket API, with chat/voice tools, a dashboard page, and real-time state.

**Architecture:** `HomeAssistantClient` (REST for service calls + WebSocket for live state, no per-vendor driver code) is owned by `HomeAssistantPlugin`, shared with `tools.py` (chat/voice) and `router.py` (dashboard REST endpoints) via module-level globals — the same pattern `gmail_classifier` already uses. Real-time browser updates reuse the existing `EventBus` → WebSocket broadcast pipeline (one new event type added to an existing list in `web/server.py`, not a new transport). `tools/iot/` (drivers, discovery, registry) is deleted once the replacement is in place.

**Tech Stack:** Python 3.12, FastAPI, `httpx` (REST), `websockets` (WS) — both already project dependencies, no new ones. Next.js + React Query + Zustand on the frontend.

## Global Constraints

- No new Python or npm dependencies — `httpx>=0.27` and `websockets>=13.0` are already in `pyproject.toml`.
- Every `@tool`-decorated function in `home_assistant/tools.py` uses `category="iot"` — this is the same category label `tools/iot/iot_tool.py` used, kept so `tests/unit/test_tool_registry.py`'s category expectations keep meaning "device control," just plugin-backed now instead of driver-backed (Task 9 updates that test to source "iot" from the plugin instead of the static keyword file).
- Intent keywords for Home Assistant are registered dynamically via `HomeAssistantPlugin.get_intent_keywords()` (merged at runtime by `ToolRegistry.register_plugin_keywords()`, `src/openacm/tools/registry.py:163`) — not added to the static `src/openacm/tools/intent_keywords.py`. That file's `"iot": [...]` block is removed in Task 9, not repurposed.
- Any plugin overriding `on_start()` must call `await super().on_start(**app_context)` first (Phase 1 convention, `src/openacm/plugins/__init__.py` — this is what makes `get_setting()` work).
- Module-level plugin globals (`_client` in both `tools.py` and `router.py`) are set directly by `HomeAssistantPlugin.on_start()` — same pattern `gmail_classifier` uses for `_processor`/`_db` in its own `router.py`/`processor.py`.
- Test DB/event_bus fixtures are `db`/`event_bus`/`client` from `tests/conftest.py` — reuse them, don't build new ones. The `client` fixture's `dashboard_token` fixture must be listed **before** `client` in any test signature that needs it (env var must be set before `create_web_server()` runs) — this only matters for Task 8's test, which uses the shared `client` fixture; Task 6's router tests use an isolated local `FastAPI()` app instead and don't need `dashboard_token` at all.
- Test file naming follows the flat convention already used for every other plugin (`tests/unit/test_gmail_classifier.py`, `tests/unit/test_plugins_api.py`, ...): `tests/unit/test_home_assistant_client.py`, `test_home_assistant_tools.py`, `test_home_assistant_router.py`, `test_home_assistant_plugin.py`, `test_home_assistant_broadcast.py`.

---

### Task 1: `HomeAssistantClient` — REST layer

**Files:**
- Create: `src/openacm/plugins/home_assistant/__init__.py` (empty placeholder — populated in Task 7; create it now just so `home_assistant` is a real package other tasks can import from)
- Create: `src/openacm/plugins/home_assistant/client.py`
- Test: `tests/unit/test_home_assistant_client.py`

**Interfaces:**
- Produces: `HomeAssistantClient(base_url: str, token: str, event_bus: Any = None)`, `.call_service(domain, service, entity_id=None, area_id=None, **data) -> dict` (async, never raises — returns `{"success": True, "result": ...}` or `{"success": False, "error": "..."}`), `.fetch_states() -> list[dict]` (async), `.get_state(entity_id) -> dict | None`, `.list_states(domain: str = "") -> list[dict]`, `.find_entity(name_or_id: str) -> dict | None` (exact `entity_id` match, then case-insensitive `friendly_name`/partial-id match).

- [ ] **Step 1: Create the empty package**

```bash
mkdir -p src/openacm/plugins/home_assistant
```

Create `src/openacm/plugins/home_assistant/__init__.py` with just:

```python
"""Home Assistant Plugin — populated in a later task."""
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_home_assistant_client.py`:

```python
"""Unit tests for HomeAssistantClient — REST layer."""
from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest


def _make_client():
    from openacm.plugins.home_assistant.client import HomeAssistantClient
    client = HomeAssistantClient(base_url="http://ha.local:8123", token="tok123")
    client._http = MagicMock()
    return client


class TestCallService:
    async def test_call_service_success(self):
        client = _make_client()
        resp = MagicMock(status_code=200)
        resp.json.return_value = [{"entity_id": "light.sala", "state": "on"}]
        client._http.post = AsyncMock(return_value=resp)

        result = await client.call_service("light", "turn_on", entity_id="light.sala", brightness_pct=80)

        assert result == {"success": True, "result": [{"entity_id": "light.sala", "state": "on"}]}
        client._http.post.assert_awaited_once_with(
            "/api/services/light/turn_on",
            json={"entity_id": "light.sala", "brightness_pct": 80},
        )

    async def test_call_service_with_area_id(self):
        client = _make_client()
        resp = MagicMock(status_code=200)
        resp.json.return_value = []
        client._http.post = AsyncMock(return_value=resp)

        await client.call_service("light", "turn_off", area_id="sala")

        client._http.post.assert_awaited_once_with(
            "/api/services/light/turn_off", json={"area_id": "sala"}
        )

    async def test_call_service_invalid_token_returns_friendly_error(self):
        client = _make_client()
        resp = MagicMock(status_code=401, text="Unauthorized")
        client._http.post = AsyncMock(return_value=resp)

        result = await client.call_service("light", "turn_on", entity_id="light.sala")

        assert result["success"] is False
        assert "token" in result["error"].lower()

    async def test_call_service_http_error_returns_friendly_error(self):
        client = _make_client()
        client._http.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        result = await client.call_service("light", "turn_on", entity_id="light.sala")

        assert result["success"] is False
        assert "Home Assistant" in result["error"]

    async def test_call_service_server_error_returns_friendly_error(self):
        client = _make_client()
        resp = MagicMock(status_code=500, text="Internal Server Error")
        client._http.post = AsyncMock(return_value=resp)

        result = await client.call_service("light", "turn_on", entity_id="light.sala")

        assert result["success"] is False
        assert "500" in result["error"]


class TestFetchStates:
    async def test_fetch_states_populates_cache(self):
        client = _make_client()
        resp = MagicMock(status_code=200)
        resp.json.return_value = [
            {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz Sala"}},
            {"entity_id": "switch.tv", "state": "off", "attributes": {"friendly_name": "TV"}},
        ]
        client._http.get = AsyncMock(return_value=resp)

        states = await client.fetch_states()

        assert len(states) == 2
        assert client.get_state("light.sala")["state"] == "on"

    async def test_fetch_states_non_200_returns_empty(self):
        client = _make_client()
        resp = MagicMock(status_code=500)
        client._http.get = AsyncMock(return_value=resp)

        states = await client.fetch_states()

        assert states == []

    async def test_fetch_states_connection_error_returns_empty(self):
        client = _make_client()
        client._http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        states = await client.fetch_states()

        assert states == []


class TestCacheReads:
    async def test_get_state_unknown_entity_returns_none(self):
        client = _make_client()
        assert client.get_state("light.nonexistent") is None

    async def test_list_states_filters_by_domain(self):
        client = _make_client()
        resp = MagicMock(status_code=200)
        resp.json.return_value = [
            {"entity_id": "light.sala", "state": "on", "attributes": {}},
            {"entity_id": "switch.tv", "state": "off", "attributes": {}},
        ]
        client._http.get = AsyncMock(return_value=resp)
        await client.fetch_states()

        lights = client.list_states(domain="light")

        assert len(lights) == 1
        assert lights[0]["entity_id"] == "light.sala"

    async def test_list_states_no_filter_returns_all(self):
        client = _make_client()
        resp = MagicMock(status_code=200)
        resp.json.return_value = [
            {"entity_id": "light.sala", "state": "on", "attributes": {}},
            {"entity_id": "switch.tv", "state": "off", "attributes": {}},
        ]
        client._http.get = AsyncMock(return_value=resp)
        await client.fetch_states()

        assert len(client.list_states()) == 2

    async def test_find_entity_by_exact_id(self):
        client = _make_client()
        resp = MagicMock(status_code=200)
        resp.json.return_value = [
            {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz Sala"}},
        ]
        client._http.get = AsyncMock(return_value=resp)
        await client.fetch_states()

        found = client.find_entity("light.sala")

        assert found["entity_id"] == "light.sala"

    async def test_find_entity_by_friendly_name_case_insensitive(self):
        client = _make_client()
        resp = MagicMock(status_code=200)
        resp.json.return_value = [
            {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz Sala"}},
        ]
        client._http.get = AsyncMock(return_value=resp)
        await client.fetch_states()

        found = client.find_entity("luz sala")

        assert found["entity_id"] == "light.sala"

    async def test_find_entity_no_match_returns_none(self):
        client = _make_client()
        assert client.find_entity("nonexistent") is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_home_assistant_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'openacm.plugins.home_assistant.client'`

- [ ] **Step 4: Create `client.py`'s REST layer**

Create `src/openacm/plugins/home_assistant/client.py`:

```python
"""Home Assistant Client — REST + WebSocket wrapper around a Home Assistant instance.

No device-specific driver code — Home Assistant's own domain/service model
(light.turn_on, climate.set_temperature, ...) is the abstraction layer this
client exposes as-is.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import structlog

log = structlog.get_logger()


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str, event_bus: Any = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.event_bus = event_bus
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
        self._states: dict[str, dict[str, Any]] = {}
        self._ws_task: asyncio.Task | None = None
        self._stop = False

    # ── REST ─────────────────────────────────────────────────────

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str | list[str] | None = None,
        area_id: str | None = None,
        **data: Any,
    ) -> dict[str, Any]:
        """Call a Home Assistant service. Never raises — always returns
        {"success": True, "result": [...]} or {"success": False, "error": "..."}.
        """
        target: dict[str, Any] = {}
        if entity_id:
            target["entity_id"] = entity_id
        if area_id:
            target["area_id"] = area_id

        try:
            resp = await self._http.post(
                f"/api/services/{domain}/{service}", json={**target, **data}
            )
        except httpx.HTTPError as exc:
            return {"success": False, "error": f"No se pudo conectar a Home Assistant: {exc}"}

        if resp.status_code == 401:
            return {
                "success": False,
                "error": "Token de Home Assistant inválido o expirado. Actualízalo en /plugins.",
            }
        if resp.status_code >= 400:
            return {"success": False, "error": f"Home Assistant respondió {resp.status_code}: {resp.text}"}

        return {"success": True, "result": resp.json()}

    async def fetch_states(self) -> list[dict[str, Any]]:
        """Seed/refresh the in-memory state cache from GET /api/states."""
        try:
            resp = await self._http.get("/api/states")
        except httpx.HTTPError as exc:
            log.warning("HA fetch_states failed", error=str(exc))
            return []
        if resp.status_code != 200:
            log.warning("HA fetch_states non-200", status=resp.status_code)
            return []
        states = resp.json()
        for s in states:
            self._states[s["entity_id"]] = s
        return states

    # ── Cache reads ──────────────────────────────────────────────

    def get_state(self, entity_id: str) -> dict[str, Any] | None:
        return self._states.get(entity_id)

    def list_states(self, domain: str = "") -> list[dict[str, Any]]:
        states = list(self._states.values())
        if domain:
            states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]
        return states

    def find_entity(self, name_or_id: str) -> dict[str, Any] | None:
        """Exact entity_id match first, then case-insensitive friendly_name/partial-id match."""
        if name_or_id in self._states:
            return self._states[name_or_id]
        q = name_or_id.lower()
        for state in self._states.values():
            friendly = state.get("attributes", {}).get("friendly_name", "")
            if q == friendly.lower() or q in state["entity_id"].lower():
                return state
        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_home_assistant_client.py -v`
Expected: PASS (14 tests)

- [ ] **Step 6: Commit**

```bash
git add src/openacm/plugins/home_assistant/__init__.py src/openacm/plugins/home_assistant/client.py tests/unit/test_home_assistant_client.py
git commit -m "feat(home-assistant): HomeAssistantClient REST layer (call_service, state cache)"
```

---

### Task 2: `HomeAssistantClient` — WebSocket layer

**Files:**
- Modify: `src/openacm/plugins/home_assistant/client.py` (add `start()`, `stop()`, `_ws_loop()`)
- Test: `tests/unit/test_home_assistant_client.py` (append)

**Interfaces:**
- Consumes: `self.fetch_states()`, `self._states`, `self.event_bus` from Task 1.
- Produces: `.start() -> None` (spawns the background listener task), `.stop() -> None` (async, cancels the listener and closes the HTTP client cleanly). Emits `"ha:state_changed"` on `self.event_bus` (if set) with `{"entity_id": str, "state": dict}` on every `state_changed` event from Home Assistant.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_home_assistant_client.py`:

```python
import asyncio
from unittest.mock import patch


class _FakeWebSocket:
    """Minimal async context manager + async iterator standing in for a
    websockets connection. Blocks forever on __anext__ once the queue is
    empty, so the listener loop doesn't reconnect mid-test — the test ends
    the loop itself via client.stop()."""

    def __init__(self, recv_queue):
        self._recv_queue = list(recv_queue)
        self.sent: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def recv(self):
        return self._recv_queue.pop(0)

    async def send(self, data):
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._recv_queue:
            await asyncio.sleep(3600)
        return self._recv_queue.pop(0)


def _make_ws_client(event_bus=None):
    from openacm.plugins.home_assistant.client import HomeAssistantClient
    client = HomeAssistantClient(base_url="http://ha.local:8123", token="tok123", event_bus=event_bus)
    client._http = MagicMock()
    resp = MagicMock(status_code=200)
    resp.json.return_value = []
    client._http.get = AsyncMock(return_value=resp)
    return client


class TestWebSocketLifecycle:
    async def test_connect_sends_auth_and_subscribes(self):
        client = _make_ws_client()
        fake_ws = _FakeWebSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True}),
        ])
        with patch("websockets.connect", return_value=fake_ws):
            client.start()
            await asyncio.sleep(0.05)
            await client.stop()

        sent_types = [json.loads(s)["type"] for s in fake_ws.sent]
        assert "auth" in sent_types
        assert "subscribe_events" in sent_types

    async def test_state_changed_event_updates_cache_and_emits(self):
        event_bus = MagicMock()
        event_bus.emit = AsyncMock()
        client = _make_ws_client(event_bus=event_bus)
        state_event = {
            "type": "event",
            "event": {
                "data": {
                    "entity_id": "light.sala",
                    "new_state": {"entity_id": "light.sala", "state": "on", "attributes": {}},
                }
            },
        }
        fake_ws = _FakeWebSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True}),
            json.dumps(state_event),
        ])
        with patch("websockets.connect", return_value=fake_ws):
            client.start()
            await asyncio.sleep(0.05)
            await client.stop()

        assert client.get_state("light.sala")["state"] == "on"
        event_bus.emit.assert_awaited_with(
            "ha:state_changed",
            {"entity_id": "light.sala", "state": {"entity_id": "light.sala", "state": "on", "attributes": {}}},
        )

    async def test_auth_failure_does_not_retry(self):
        client = _make_ws_client()
        fake_ws = _FakeWebSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_invalid"}),
        ])
        connect_calls = []

        def _connect(url):
            connect_calls.append(url)
            return fake_ws

        with patch("websockets.connect", side_effect=_connect):
            client.start()
            await asyncio.sleep(0.05)
            await client.stop()

        assert len(connect_calls) == 1

    async def test_stop_cancels_the_listener_task_cleanly(self):
        client = _make_ws_client()
        fake_ws = _FakeWebSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True}),
        ])
        with patch("websockets.connect", return_value=fake_ws):
            client.start()
            await asyncio.sleep(0.05)
            await client.stop()

        assert client._ws_task.cancelled() or client._ws_task.done()

    async def test_no_event_bus_does_not_raise_on_state_change(self):
        client = _make_ws_client(event_bus=None)
        state_event = {
            "type": "event",
            "event": {
                "data": {
                    "entity_id": "switch.tv",
                    "new_state": {"entity_id": "switch.tv", "state": "off", "attributes": {}},
                }
            },
        }
        fake_ws = _FakeWebSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True}),
            json.dumps(state_event),
        ])
        with patch("websockets.connect", return_value=fake_ws):
            client.start()
            await asyncio.sleep(0.05)
            await client.stop()

        assert client.get_state("switch.tv")["state"] == "off"
```

Also add `import json` and `from unittest.mock import AsyncMock, MagicMock, patch` and `import asyncio` to the top of the test file if not already present from Task 1 (Task 1's version already has `AsyncMock, MagicMock` — add `patch` and `asyncio`, `json`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_home_assistant_client.py -v -k WebSocket`
Expected: FAIL — `AttributeError: 'HomeAssistantClient' object has no attribute 'start'`

- [ ] **Step 3: Implement the WebSocket layer**

Add `import json` near the top of `src/openacm/plugins/home_assistant/client.py` (next to `import asyncio`), then add these methods to `HomeAssistantClient`, right after `find_entity`:

```python
    # ── WebSocket (real-time) ────────────────────────────────────

    def start(self) -> None:
        """Start the background WebSocket listener (fetches initial state
        itself once connected)."""
        self._stop = False
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def stop(self) -> None:
        self._stop = True
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        await self._http.aclose()

    async def _ws_loop(self) -> None:
        import websockets

        ws_url = (
            self.base_url.replace("http://", "ws://").replace("https://", "wss://")
            + "/api/websocket"
        )
        backoff = 5

        while not self._stop:
            try:
                async with websockets.connect(ws_url) as ws:
                    await ws.recv()  # auth_required
                    await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                    auth_result = json.loads(await ws.recv())
                    if auth_result.get("type") != "auth_ok":
                        log.warning("HA WebSocket auth failed — not retrying", result=auth_result)
                        return

                    await self.fetch_states()
                    backoff = 5

                    await ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
                    await ws.recv()  # subscription ack

                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("type") != "event":
                            continue
                        event_data = msg.get("event", {}).get("data", {})
                        new_state = event_data.get("new_state")
                        entity_id = event_data.get("entity_id")
                        if not entity_id or new_state is None:
                            continue
                        self._states[entity_id] = new_state
                        if self.event_bus:
                            await self.event_bus.emit("ha:state_changed", {
                                "entity_id": entity_id,
                                "state": new_state,
                            })
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("HA WebSocket error, reconnecting", error=str(exc), wait=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_home_assistant_client.py -v`
Expected: PASS (19 tests total)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/home_assistant/client.py tests/unit/test_home_assistant_client.py
git commit -m "feat(home-assistant): WebSocket real-time listener with reconnect backoff"
```

---

### Task 3: `tools.py` — `ha_devices`, `ha_status`

**Files:**
- Create: `src/openacm/plugins/home_assistant/tools.py`
- Test: `tests/unit/test_home_assistant_tools.py`

**Interfaces:**
- Consumes: `HomeAssistantClient.list_states(domain)`, `.find_entity(name_or_id)` from Task 1.
- Produces: module-level `_client: Any = None` (set later by `HomeAssistantPlugin.on_start()` in Task 7), `@tool`-decorated `ha_devices(domain="", **kwargs) -> str`, `ha_status(entity_id, **kwargs) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_home_assistant_tools.py`:

```python
"""Unit tests for Home Assistant tools — ha_devices, ha_status."""
from unittest.mock import MagicMock
import pytest
from openacm.plugins.home_assistant import tools as ha_tools

STATES = [
    {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz Sala", "brightness": 200}},
    {"entity_id": "switch.tv", "state": "off", "attributes": {"friendly_name": "TV"}},
]


def _make_client_with_states(states):
    client = MagicMock()

    def _list(domain=""):
        if domain:
            return [s for s in states if s["entity_id"].startswith(f"{domain}.")]
        return list(states)

    def _find(name_or_id):
        for s in states:
            if s["entity_id"] == name_or_id:
                return s
            if s.get("attributes", {}).get("friendly_name", "").lower() == name_or_id.lower():
                return s
        return None

    client.list_states.side_effect = _list
    client.find_entity.side_effect = _find
    return client


class TestHaDevices:
    async def test_not_configured_returns_friendly_message(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", None)
        result = await ha_tools.ha_devices()
        assert "no está configurado" in result

    async def test_lists_all_devices(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_devices()
        assert "light.sala" in result
        assert "switch.tv" in result

    async def test_filters_by_domain(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_devices(domain="light")
        assert "light.sala" in result
        assert "switch.tv" not in result

    async def test_no_devices_of_domain_returns_friendly_message(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_devices(domain="climate")
        assert "No hay dispositivos" in result


class TestHaStatus:
    async def test_not_configured_returns_friendly_message(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", None)
        result = await ha_tools.ha_status("light.sala")
        assert "no está configurado" in result

    async def test_status_by_entity_id(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_status("light.sala")
        assert "Luz Sala" in result
        assert "on" in result

    async def test_status_by_friendly_name(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_status("TV")
        assert "switch.tv" in result

    async def test_unknown_entity_suggests_alternatives(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_status("nonexistent")
        assert "No encontré" in result
        assert "light.sala" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_home_assistant_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'openacm.plugins.home_assistant.tools'`

- [ ] **Step 3: Create `tools.py`**

Create `src/openacm/plugins/home_assistant/tools.py`:

```python
"""Home Assistant Tools — AI interface for smart-home control via Home Assistant.

_client is None until HomeAssistantPlugin.on_start() sets it (once the user
has configured ha_url/ha_token from the /plugins dashboard).
"""
from __future__ import annotations

from typing import Any

from openacm.tools.base import tool

_client: Any = None

_NOT_CONFIGURED_MSG = "Home Assistant no está configurado. Configúralo desde el dashboard en /plugins."


@tool(
    name="ha_devices",
    description=(
        "List Home Assistant entities (lights, switches, climate, covers, "
        "media players, etc.), optionally filtered by domain "
        "(e.g. 'light', 'switch', 'climate', 'cover', 'media_player', 'vacuum')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Filter by Home Assistant domain, e.g. 'light'. Empty = all.",
                "default": "",
            },
        },
        "required": [],
    },
    risk_level="low",
    category="iot",
)
async def ha_devices(domain: str = "", **kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    states = _client.list_states(domain=domain)
    if not states:
        scope = f" del tipo '{domain}'" if domain else ""
        return f"No hay dispositivos{scope} registrados en Home Assistant."

    lines = [f"{len(states)} dispositivos:\n"]
    for s in states:
        name = s.get("attributes", {}).get("friendly_name", s["entity_id"])
        lines.append(f"  {s['entity_id']:30s}  {s['state']:12s}  {name}")
    return "\n".join(lines)


@tool(
    name="ha_status",
    description=(
        "Get the current state and attributes of one Home Assistant entity. "
        "Accepts an exact entity_id (e.g. 'light.sala') or a friendly name (e.g. 'Luz Sala')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Entity ID or friendly name."},
        },
        "required": ["entity_id"],
    },
    risk_level="low",
    category="iot",
)
async def ha_status(entity_id: str, **kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    state = _client.find_entity(entity_id)
    if state is None:
        candidates = [s["entity_id"] for s in _client.list_states()][:8]
        suggestion = f" ¿Quisiste decir uno de estos? {', '.join(candidates)}" if candidates else ""
        return f"No encontré '{entity_id}'.{suggestion}"

    name = state.get("attributes", {}).get("friendly_name", state["entity_id"])
    attrs = {k: v for k, v in state.get("attributes", {}).items() if k != "friendly_name"}
    return f"{name} ({state['entity_id']}): {state['state']}\nAtributos: {attrs}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_home_assistant_tools.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/home_assistant/tools.py tests/unit/test_home_assistant_tools.py
git commit -m "feat(home-assistant): ha_devices and ha_status tools"
```

---

### Task 4: `tools.py` — `ha_control`

**Files:**
- Modify: `src/openacm/plugins/home_assistant/tools.py`
- Test: `tests/unit/test_home_assistant_tools.py`

**Interfaces:**
- Consumes: `_client.find_entity()`, `_client.call_service()` from Tasks 1 and 3.
- Produces: `@tool`-decorated `ha_control(entity_id=None, action="", area="", brightness=None, kelvin=None, temperature=None, volume=None, **kwargs) -> str`.

**Design note (why turn_on/off/toggle are special-cased):** Home Assistant has a generic `homeassistant.turn_on` / `homeassistant.turn_off` / `homeassistant.toggle` service that works across *any* entity domain, and across a mixed list of entities or a whole area, in one call. Every other action (`set_brightness`, `set_temperature`, ...) is domain-specific and requires all targeted entities to share one domain.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_home_assistant_tools.py`:

```python
from unittest.mock import AsyncMock


def _make_control_client(states, service_result=None):
    client = MagicMock()

    def _find(name_or_id):
        for s in states:
            if s["entity_id"] == name_or_id:
                return s
            if s.get("attributes", {}).get("friendly_name", "").lower() == name_or_id.lower():
                return s
        return None

    client.find_entity.side_effect = _find
    client.call_service = AsyncMock(return_value=service_result or {"success": True, "result": []})
    return client


CONTROL_STATES = [
    {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz Sala"}},
    {"entity_id": "light.cocina", "state": "off", "attributes": {"friendly_name": "Luz Cocina"}},
    {"entity_id": "switch.tv", "state": "off", "attributes": {"friendly_name": "TV"}},
]


class TestHaControlValidation:
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", None)
        result = await ha_tools.ha_control(entity_id="light.sala", action="turn_on")
        assert "no está configurado" in result

    async def test_requires_entity_id_or_area(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_control_client(CONTROL_STATES))
        result = await ha_tools.ha_control(action="turn_on")
        assert "entity_id" in result and "area" in result

    async def test_unknown_entity_returns_error(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_control_client(CONTROL_STATES))
        result = await ha_tools.ha_control(entity_id="light.nonexistent", action="turn_on")
        assert "No encontré" in result


class TestHaControlGenericActions:
    async def test_turn_off_single_entity(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="light.sala", action="turn_off")

        client.call_service.assert_awaited_once_with("homeassistant", "turn_off", entity_id=["light.sala"])
        assert "✓" in result

    async def test_turn_off_multiple_mixed_domain_entities_in_one_call(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id=["light.sala", "switch.tv"], action="turn_off")

        client.call_service.assert_awaited_once_with(
            "homeassistant", "turn_off", entity_id=["light.sala", "switch.tv"]
        )
        assert "✓" in result

    async def test_turn_off_whole_area(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(area="sala", action="turn_off")

        client.call_service.assert_awaited_once_with("homeassistant", "turn_off", area_id="sala")
        assert "✓" in result

    async def test_generic_action_failure_reports_error(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES, service_result={"success": False, "error": "no responde"})
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="light.sala", action="turn_off")

        assert "✗" in result and "no responde" in result


class TestHaControlDomainActions:
    async def test_set_brightness(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="light.sala", action="set_brightness", brightness=80)

        client.call_service.assert_awaited_once_with(
            "light", "turn_on", entity_id=["light.sala"], brightness_pct=80
        )
        assert "✓" in result

    async def test_set_brightness_missing_param(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="light.sala", action="set_brightness")

        assert "necesita el parámetro 'brightness'" in result
        client.call_service.assert_not_awaited()

    async def test_domain_action_needs_entity_id_not_area(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(area="sala", action="set_brightness", brightness=80)

        assert "necesita 'entity_id'" in result

    async def test_domain_action_rejects_mixed_domains(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(
            entity_id=["light.sala", "switch.tv"], action="set_brightness", brightness=80
        )

        assert "mismo tipo" in result
        client.call_service.assert_not_awaited()

    async def test_action_not_valid_for_domain(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="switch.tv", action="set_brightness", brightness=80)

        assert "no es válido para 'switch'" in result

    async def test_set_temperature(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES + [
            {"entity_id": "climate.termostato", "state": "heat", "attributes": {}}
        ])
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="climate.termostato", action="set_temperature", temperature=22)

        client.call_service.assert_awaited_once_with(
            "climate", "set_temperature", entity_id=["climate.termostato"], temperature=22
        )
        assert "✓" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_home_assistant_tools.py -v -k Control`
Expected: FAIL — `AttributeError: module 'openacm.plugins.home_assistant.tools' has no attribute 'ha_control'`

- [ ] **Step 3: Implement `ha_control`**

Add to `src/openacm/plugins/home_assistant/tools.py`, after `ha_status`:

```python
_GENERIC_ACTIONS = {"turn_on", "turn_off", "toggle"}

# domain -> { verb: (ha_service, caller_param_name | None, ha_field_name | None) }
# Actions not in _GENERIC_ACTIONS need a single, consistent domain across all
# targeted entities so we know which service to call.
_DOMAIN_ACTIONS: dict[str, dict[str, tuple[str, str | None, str | None]]] = {
    "light": {
        "set_brightness": ("turn_on", "brightness", "brightness_pct"),
        "set_color_temp": ("turn_on", "kelvin", "color_temp_kelvin"),
    },
    "climate": {
        "set_temperature": ("set_temperature", "temperature", "temperature"),
    },
    "cover": {
        "open": ("open_cover", None, None),
        "close": ("close_cover", None, None),
        "stop": ("stop_cover", None, None),
    },
    "media_player": {
        "set_volume": ("volume_set", "volume", "volume_level"),
    },
}


@tool(
    name="ha_control",
    description=(
        "Control one or more Home Assistant entities. Actions: turn_on, turn_off, "
        "toggle (any domain, can target multiple entities or a whole area at once); "
        "set_brightness (light, param 'brightness' 0-100); "
        "set_color_temp (light, param 'kelvin' 2000-6500); "
        "set_temperature (climate, param 'temperature'); "
        "open, close, stop (cover); set_volume (media_player, param 'volume' 0.0-1.0). "
        "entity_id can be a single id, a list of ids, or use `area` to target every "
        "entity in a Home Assistant area at once (e.g. area='sala' turns off every "
        "device in the living room in one call) — area only works with turn_on/off/toggle."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "description": "Entity ID or list of entity IDs, e.g. 'light.sala' or ['light.sala', 'light.cocina']. Omit if using 'area'.",
            },
            "action": {
                "type": "string",
                "description": "turn_on, turn_off, toggle, set_brightness, set_color_temp, set_temperature, open, close, stop, set_volume",
            },
            "area": {
                "type": "string",
                "description": "Home Assistant area name to target every entity in it (only with turn_on/turn_off/toggle). Use instead of entity_id.",
                "default": "",
            },
            "brightness": {"type": "integer", "description": "0-100, for set_brightness"},
            "kelvin": {"type": "integer", "description": "2000-6500, for set_color_temp"},
            "temperature": {"type": "number", "description": "Target temperature, for set_temperature"},
            "volume": {"type": "number", "description": "0.0-1.0, for set_volume"},
        },
        "required": ["action"],
    },
    risk_level="low",
    category="iot",
)
async def ha_control(
    entity_id: str | list[str] | None = None,
    action: str = "",
    area: str = "",
    brightness: int | None = None,
    kelvin: int | None = None,
    temperature: float | None = None,
    volume: float | None = None,
    **kwargs,
) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    if not entity_id and not area:
        return "Debes indicar 'entity_id' o 'area'."

    caller_params = {"brightness": brightness, "kelvin": kelvin, "temperature": temperature, "volume": volume}

    ids: list[str] = []
    if entity_id:
        raw_ids = entity_id if isinstance(entity_id, list) else [entity_id]
        for raw in raw_ids:
            state = _client.find_entity(raw)
            if state is None:
                return f"No encontré '{raw}'. Usa ha_devices() para ver los dispositivos disponibles."
            ids.append(state["entity_id"])

    if action in _GENERIC_ACTIONS:
        if ids:
            result = await _client.call_service("homeassistant", action, entity_id=ids)
            target_desc = ", ".join(ids)
        else:
            result = await _client.call_service("homeassistant", action, area_id=area)
            target_desc = f"área '{area}'"
        return f"✓ {action} aplicado a {target_desc}." if result["success"] else f"✗ {result['error']}"

    if not ids:
        return f"La acción '{action}' necesita 'entity_id' (no funciona solo con 'area')."

    domains = {i.split(".")[0] for i in ids}
    if len(domains) > 1:
        return f"'{action}' necesita que todas las entidades sean del mismo tipo (encontré: {', '.join(sorted(domains))})."
    domain = domains.pop()

    domain_actions = _DOMAIN_ACTIONS.get(domain, {})
    if action not in domain_actions:
        available = ", ".join(sorted(_GENERIC_ACTIONS | set(domain_actions)))
        return f"'{action}' no es válido para '{domain}'. Acciones disponibles: {available}."

    service, caller_key, ha_key = domain_actions[action]
    data: dict[str, Any] = {}
    if caller_key:
        value = caller_params.get(caller_key)
        if value is None:
            return f"La acción '{action}' necesita el parámetro '{caller_key}'."
        data[ha_key] = value

    result = await _client.call_service(domain, service, entity_id=ids, **data)
    target_desc = ", ".join(ids)
    return f"✓ {action} aplicado a {target_desc}." if result["success"] else f"✗ {result['error']}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_home_assistant_tools.py -v`
Expected: PASS (21 tests total)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/home_assistant/tools.py tests/unit/test_home_assistant_tools.py
git commit -m "feat(home-assistant): ha_control with multi-entity/area targeting"
```

---

### Task 5: `tools.py` — `ha_scenes`, `ha_activate_scene`

**Files:**
- Modify: `src/openacm/plugins/home_assistant/tools.py`
- Test: `tests/unit/test_home_assistant_tools.py`

**Interfaces:**
- Consumes: `_client.list_states(domain="scene")`, `_client.find_entity()`, `_client.call_service()`.
- Produces: `@tool`-decorated `ha_scenes(**kwargs) -> str`, `ha_activate_scene(name, **kwargs) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_home_assistant_tools.py`:

```python
SCENE_STATES = [
    {"entity_id": "scene.modo_noche", "state": "scening", "attributes": {"friendly_name": "Modo Noche"}},
    {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz Sala"}},
]


def _make_scene_client(states, service_result=None):
    client = MagicMock()

    def _list(domain=""):
        if domain:
            return [s for s in states if s["entity_id"].startswith(f"{domain}.")]
        return list(states)

    def _find(name_or_id):
        for s in states:
            if s["entity_id"] == name_or_id:
                return s
            if s.get("attributes", {}).get("friendly_name", "").lower() == name_or_id.lower():
                return s
        return None

    client.list_states.side_effect = _list
    client.find_entity.side_effect = _find
    client.call_service = AsyncMock(return_value=service_result or {"success": True, "result": []})
    return client


class TestHaScenes:
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", None)
        result = await ha_tools.ha_scenes()
        assert "no está configurado" in result

    async def test_lists_scenes_only(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_scene_client(SCENE_STATES))
        result = await ha_tools.ha_scenes()
        assert "Modo Noche" in result

    async def test_no_scenes_configured(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_scene_client([SCENE_STATES[1]]))
        result = await ha_tools.ha_scenes()
        assert "No hay escenas" in result


class TestHaActivateScene:
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", None)
        result = await ha_tools.ha_activate_scene("Modo Noche")
        assert "no está configurado" in result

    async def test_activates_by_friendly_name(self, monkeypatch):
        client = _make_scene_client(SCENE_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_activate_scene("Modo Noche")

        client.call_service.assert_awaited_once_with("scene", "turn_on", entity_id="scene.modo_noche")
        assert "✓" in result and "Modo Noche" in result

    async def test_unknown_scene_lists_alternatives(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_scene_client(SCENE_STATES))
        result = await ha_tools.ha_activate_scene("Nonexistent")
        assert "No encontré" in result
        assert "Modo Noche" in result

    async def test_rejects_non_scene_entity(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_scene_client(SCENE_STATES))
        result = await ha_tools.ha_activate_scene("Luz Sala")
        assert "No encontré la escena" in result

    async def test_activation_failure_reports_error(self, monkeypatch):
        client = _make_scene_client(SCENE_STATES, service_result={"success": False, "error": "timeout"})
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_activate_scene("Modo Noche")

        assert "✗" in result and "timeout" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_home_assistant_tools.py -v -k Scene`
Expected: FAIL — `AttributeError: module 'openacm.plugins.home_assistant.tools' has no attribute 'ha_scenes'`

- [ ] **Step 3: Implement `ha_scenes` and `ha_activate_scene`**

Add to `src/openacm/plugins/home_assistant/tools.py`, after `ha_control`:

```python
@tool(
    name="ha_scenes",
    description="List Home Assistant scenes available to activate.",
    parameters={"type": "object", "properties": {}, "required": []},
    risk_level="low",
    category="iot",
)
async def ha_scenes(**kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    scenes = _client.list_states(domain="scene")
    if not scenes:
        return "No hay escenas configuradas en Home Assistant."

    lines = ["Escenas disponibles:\n"]
    for s in scenes:
        name = s.get("attributes", {}).get("friendly_name", s["entity_id"])
        lines.append(f"  {name}")
    return "\n".join(lines)


@tool(
    name="ha_activate_scene",
    description="Activate a Home Assistant scene by name, e.g. 'Modo Noche'.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Scene name or entity_id."},
        },
        "required": ["name"],
    },
    risk_level="low",
    category="iot",
)
async def ha_activate_scene(name: str, **kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    state = _client.find_entity(name)
    if state is None or not state["entity_id"].startswith("scene."):
        scenes = [
            s.get("attributes", {}).get("friendly_name", s["entity_id"])
            for s in _client.list_states(domain="scene")
        ]
        suggestion = f" Escenas disponibles: {', '.join(scenes)}" if scenes else ""
        return f"No encontré la escena '{name}'.{suggestion}"

    result = await _client.call_service("scene", "turn_on", entity_id=state["entity_id"])
    if result["success"]:
        friendly = state.get("attributes", {}).get("friendly_name", state["entity_id"])
        return f"✓ Escena '{friendly}' activada."
    return f"✗ {result['error']}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_home_assistant_tools.py -v`
Expected: PASS (29 tests total)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/home_assistant/tools.py tests/unit/test_home_assistant_tools.py
git commit -m "feat(home-assistant): ha_scenes and ha_activate_scene tools"
```

---

### Task 6: `router.py` — dashboard REST endpoints

**Files:**
- Create: `src/openacm/plugins/home_assistant/router.py`
- Test: `tests/unit/test_home_assistant_router.py`

**Interfaces:**
- Consumes: `_client.list_states()`, `_client.call_service()` (same `HomeAssistantClient` interface as `tools.py`, set independently on this module by `HomeAssistantPlugin.on_start()` in Task 7).
- Produces: `router = APIRouter(prefix="/home-assistant", ...)` with `GET /devices`, `POST /devices/{entity_id}/control`, `GET /scenes`, `POST /scenes/{entity_id}/activate`.

**Test approach:** this router doesn't need the full app/auth stack to unit-test its own logic (auth middleware coverage is already proven generically in Phase 1's tests) — build a minimal standalone `FastAPI()` app with just this router mounted, using `httpx.AsyncClient` + `ASGITransport` directly.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_home_assistant_router.py`:

```python
"""Unit tests for the Home Assistant router endpoints."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from openacm.plugins.home_assistant import router as ha_router


@pytest.fixture
def app_client():
    app = FastAPI()
    app.include_router(ha_router.router, prefix="/api")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _mock_ha_client(monkeypatch):
    client = MagicMock()
    client.list_states.side_effect = lambda domain="": (
        [{"entity_id": "light.sala", "state": "on", "attributes": {}}] if domain in ("", "light") else []
    )
    client.call_service = AsyncMock(return_value={"success": True, "result": []})
    monkeypatch.setattr(ha_router, "_client", client)
    yield client
    monkeypatch.setattr(ha_router, "_client", None)


class TestListDevicesEndpoint:
    async def test_list_devices(self, app_client, _mock_ha_client):
        async with app_client as ac:
            resp = await ac.get("/api/home-assistant/devices")
        assert resp.status_code == 200
        assert resp.json()["devices"][0]["entity_id"] == "light.sala"

    async def test_not_configured_503s(self, app_client, monkeypatch):
        monkeypatch.setattr(ha_router, "_client", None)
        async with app_client as ac:
            resp = await ac.get("/api/home-assistant/devices")
        assert resp.status_code == 503


class TestControlDeviceEndpoint:
    async def test_control_device_success(self, app_client, _mock_ha_client):
        async with app_client as ac:
            resp = await ac.post(
                "/api/home-assistant/devices/light.sala/control",
                json={"action": "turn_on", "brightness_pct": 80},
            )
        assert resp.status_code == 200
        _mock_ha_client.call_service.assert_awaited_once_with(
            "light", "turn_on", entity_id="light.sala", brightness_pct=80
        )

    async def test_control_device_missing_action_400s(self, app_client, _mock_ha_client):
        async with app_client as ac:
            resp = await ac.post("/api/home-assistant/devices/light.sala/control", json={})
        assert resp.status_code == 400

    async def test_control_device_service_failure_502s(self, app_client, _mock_ha_client):
        _mock_ha_client.call_service = AsyncMock(return_value={"success": False, "error": "offline"})
        async with app_client as ac:
            resp = await ac.post(
                "/api/home-assistant/devices/light.sala/control", json={"action": "turn_off"}
            )
        assert resp.status_code == 502


class TestScenesEndpoints:
    async def test_list_scenes(self, app_client, _mock_ha_client):
        _mock_ha_client.list_states.side_effect = lambda domain="": (
            [{"entity_id": "scene.modo_noche", "state": "scening", "attributes": {}}] if domain == "scene" else []
        )
        async with app_client as ac:
            resp = await ac.get("/api/home-assistant/scenes")
        assert resp.status_code == 200
        assert resp.json()["scenes"][0]["entity_id"] == "scene.modo_noche"

    async def test_activate_scene(self, app_client, _mock_ha_client):
        async with app_client as ac:
            resp = await ac.post("/api/home-assistant/scenes/scene.modo_noche/activate")
        assert resp.status_code == 200
        _mock_ha_client.call_service.assert_awaited_once_with("scene", "turn_on", entity_id="scene.modo_noche")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_home_assistant_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'openacm.plugins.home_assistant.router'`

- [ ] **Step 3: Create `router.py`**

Create `src/openacm/plugins/home_assistant/router.py`:

```python
"""Home Assistant — FastAPI router for the /home-assistant dashboard page."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/home-assistant", tags=["home-assistant"])

# Set by HomeAssistantPlugin.on_start()
_client: Any = None


def _require_client():
    if _client is None:
        raise HTTPException(status_code=503, detail="Home Assistant no está configurado")
    return _client


@router.get("/devices")
async def list_devices(domain: str = ""):
    client = _require_client()
    return {"devices": client.list_states(domain=domain)}


@router.post("/devices/{entity_id}/control")
async def control_device(entity_id: str, body: dict):
    client = _require_client()
    action = body.get("action", "")
    if not action:
        raise HTTPException(status_code=400, detail="Falta 'action'")

    domain = entity_id.split(".")[0]
    service = body.get("service", action)
    data = {k: v for k, v in body.items() if k not in ("action", "service")}

    result = await client.call_service(domain, service, entity_id=entity_id, **data)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result["error"])
    return {"status": "ok"}


@router.get("/scenes")
async def list_scenes():
    client = _require_client()
    return {"scenes": client.list_states(domain="scene")}


@router.post("/scenes/{entity_id}/activate")
async def activate_scene(entity_id: str):
    client = _require_client()
    result = await client.call_service("scene", "turn_on", entity_id=entity_id)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result["error"])
    return {"status": "ok"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_home_assistant_router.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/home_assistant/router.py tests/unit/test_home_assistant_router.py
git commit -m "feat(home-assistant): dashboard REST endpoints (devices, control, scenes)"
```

---

### Task 7: `__init__.py` — `HomeAssistantPlugin`

**Files:**
- Modify: `src/openacm/plugins/home_assistant/__init__.py` (replace the Task 1 placeholder)
- Test: `tests/unit/test_home_assistant_plugin.py`

**Interfaces:**
- Consumes: `HomeAssistantClient` (Tasks 1-2), `tools`/`router` modules' `_client` globals (Tasks 3-6), `Plugin.get_setting()`/`on_start()` from `src/openacm/plugins/__init__.py`.
- Produces: `HomeAssistantPlugin(Plugin)`, module-level `PLUGIN = HomeAssistantPlugin()` (auto-discovered by `PluginManager.load_builtin_plugins()`, which scans `openacm.plugins.*` subpackages for a `PLUGIN` attribute).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_home_assistant_plugin.py`:

```python
"""Unit tests for HomeAssistantPlugin lifecycle."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_plugin():
    from openacm.plugins.home_assistant import HomeAssistantPlugin
    return HomeAssistantPlugin()


class TestConfigAndMetadata:
    def test_config_schema_has_url_and_token(self):
        plugin = _make_plugin()
        schema = plugin.get_config_schema()
        keys = {f["key"] for f in schema}
        assert keys == {"ha_url", "ha_token"}
        token_field = next(f for f in schema if f["key"] == "ha_token")
        assert token_field["type"] == "password"

    def test_nav_item_points_at_home_assistant_page(self):
        plugin = _make_plugin()
        [item] = plugin.get_nav_items()
        assert item["path"] == "/home-assistant"

    def test_intent_keywords_under_iot_category(self):
        plugin = _make_plugin()
        kws = plugin.get_intent_keywords()
        assert "iot" in kws
        assert "domótica" in kws["iot"]

    def test_get_tool_modules_returns_tools_module(self):
        plugin = _make_plugin()
        from openacm.plugins.home_assistant import tools as expected_module
        assert plugin.get_tool_modules() == [expected_module]

    def test_get_api_router_returns_router(self):
        plugin = _make_plugin()
        from openacm.plugins.home_assistant import router as expected_module
        assert plugin.get_api_router() is expected_module.router


class TestOnStart:
    async def test_not_configured_stays_inactive(self):
        plugin = _make_plugin()
        mock_db = AsyncMock()
        mock_db.get_plugin_config.return_value = {}

        await plugin.on_start(database=mock_db, event_bus=MagicMock())

        assert plugin._client is None

    async def test_configured_starts_client(self):
        plugin = _make_plugin()
        mock_db = AsyncMock()
        mock_db.get_plugin_config.return_value = {"ha_url": "http://ha.local:8123", "ha_token": "tok"}
        event_bus = MagicMock()

        fake_client = MagicMock()
        fake_client.fetch_states = AsyncMock()
        fake_client.start = MagicMock()

        with patch("openacm.plugins.home_assistant.client.HomeAssistantClient", return_value=fake_client):
            await plugin.on_start(database=mock_db, event_bus=event_bus)

        assert plugin._client is fake_client
        fake_client.fetch_states.assert_awaited_once()
        fake_client.start.assert_called_once()

        from openacm.plugins.home_assistant import tools as _tools_mod
        from openacm.plugins.home_assistant import router as _router_mod
        assert _tools_mod._client is fake_client
        assert _router_mod._client is fake_client


class TestOnStop:
    async def test_on_stop_stops_the_client_if_running(self):
        plugin = _make_plugin()
        fake_client = MagicMock()
        fake_client.stop = AsyncMock()
        plugin._client = fake_client

        await plugin.on_stop()

        fake_client.stop.assert_awaited_once()

    async def test_on_stop_is_a_noop_when_never_started(self):
        plugin = _make_plugin()
        await plugin.on_stop()  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_home_assistant_plugin.py -v`
Expected: FAIL — `ImportError: cannot import name 'HomeAssistantPlugin' from 'openacm.plugins.home_assistant'`

- [ ] **Step 3: Replace `__init__.py`'s placeholder with the real plugin**

Replace the full contents of `src/openacm/plugins/home_assistant/__init__.py`:

```python
"""Home Assistant Plugin — smart-home control via a running Home Assistant instance."""
from __future__ import annotations

from typing import Any

import structlog

from openacm.plugins import Plugin

log = structlog.get_logger()


class HomeAssistantPlugin(Plugin):
    name = "home_assistant"
    version = "1.0.0"
    description = "Control smart-home devices through Home Assistant"
    author = "JsonProductions / OpenACM"

    def __init__(self):
        self._client = None

    # ── Config schema (Phase 1 dashboard config form) ───────────

    def get_config_schema(self) -> list[dict]:
        return [
            {
                "key": "ha_url",
                "label": "URL de Home Assistant",
                "type": "text",
                "required": True,
                "help": "ej. http://homeassistant.local:8123",
            },
            {
                "key": "ha_token",
                "label": "Long-Lived Access Token",
                "type": "password",
                "required": True,
                "help": "Genéralo desde tu perfil de usuario en Home Assistant.",
            },
        ]

    # ── Tools / API router / nav ─────────────────────────────────

    def get_tool_modules(self) -> list[Any]:
        from openacm.plugins.home_assistant import tools as _tools
        return [_tools]

    def get_api_router(self):
        from openacm.plugins.home_assistant import router as _r
        return _r.router

    def get_nav_items(self) -> list[dict]:
        return [
            {"path": "/home-assistant", "label": "Home Assistant", "icon": "Home", "section": "main"}
        ]

    def get_intent_keywords(self) -> dict[str, list[str]]:
        return {
            "iot": [
                "light", "lights", "luz", "luces", "lamp", "lampara", "bulb",
                "curtain", "curtains", "blind", "blinds", "persiana", "persianas",
                "cortina", "cortinas", "cover", "shutter",
                "switch", "enchufe", "plug", "outlet",
                "climate", "clima", "termostato", "thermostat", "temperatura",
                "home assistant", "domótica", "domotica", "casa inteligente",
                "smart home", "escena", "scene", "modo noche", "modo día",
                "turn on", "turn off", "enciende", "apaga", "encender", "apagar",
                "dim", "brightness", "brillo", "color", "temperatura de color",
                "open", "close", "abre", "cierra", "abrir", "cerrar",
                "volume", "volumen",
            ]
        }

    # ── Lifecycle ──────────────────────────────────────────────

    async def on_start(self, **app_context: Any) -> None:
        await super().on_start(**app_context)
        event_bus = app_context.get("event_bus")

        from openacm.plugins.home_assistant import tools as _tools_mod
        from openacm.plugins.home_assistant import router as _router_mod

        ha_url = await self.get_setting("ha_url", default="")
        ha_token = await self.get_setting("ha_token", default="")

        if not ha_url or not ha_token:
            log.info(
                "Home Assistant plugin loaded without configuration — "
                "inactive until /plugins is filled in"
            )
            return

        from openacm.plugins.home_assistant.client import HomeAssistantClient
        self._client = HomeAssistantClient(base_url=ha_url, token=ha_token, event_bus=event_bus)
        await self._client.fetch_states()
        self._client.start()

        _tools_mod._client = self._client
        _router_mod._client = self._client

        log.info("HomeAssistantPlugin started", url=ha_url)

    async def on_stop(self) -> None:
        if self._client:
            await self._client.stop()


PLUGIN = HomeAssistantPlugin()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_home_assistant_plugin.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Run all Home Assistant tests together**

Run: `uv run pytest tests/unit/test_home_assistant_client.py tests/unit/test_home_assistant_tools.py tests/unit/test_home_assistant_router.py tests/unit/test_home_assistant_plugin.py -v`
Expected: PASS (64 tests total)

- [ ] **Step 6: Commit**

```bash
git add src/openacm/plugins/home_assistant/__init__.py tests/unit/test_home_assistant_plugin.py
git commit -m "feat(home-assistant): HomeAssistantPlugin — config schema, lifecycle, nav"
```

---

### Task 8: Wire `ha:state_changed` into the real-time browser broadcast

**Files:**
- Modify: `src/openacm/web/server.py`
- Test: `tests/unit/test_home_assistant_broadcast.py`

**Interfaces:**
- Consumes: the existing generic event-forwarding list in `create_web_server()` (`src/openacm/web/server.py`, the `for evt in [...]: event_bus.on(evt, on_event)` block) — every event type in that list is broadcast to connected dashboard WebSocket clients via the existing `on_event`/`broadcast_event` pair. No new handler function needed, just one more entry in the list.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_home_assistant_broadcast.py`:

```python
"""Confirm ha:state_changed is wired into the real-time WebSocket broadcast pipeline."""
import pytest

TEST_TOKEN = "test-dashboard-token"


@pytest.fixture
def dashboard_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", TEST_TOKEN)
    return TEST_TOKEN


class TestHaStateChangedBroadcast:
    async def test_ha_state_changed_is_registered_on_event_bus(self, dashboard_token, client, event_bus):
        assert "ha:state_changed" in event_bus._handlers
        assert len(event_bus._handlers["ha:state_changed"]) >= 1
```

Note: `dashboard_token` must be listed before `client` in the signature (env var must be set before `create_web_server()` builds the app) — same ordering constraint Phase 1 established.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_home_assistant_broadcast.py -v`
Expected: FAIL — `assert "ha:state_changed" in event_bus._handlers` fails (empty/missing key)

- [ ] **Step 3: Add `ha:state_changed` to the broadcast list**

In `src/openacm/web/server.py`, find the `for evt in [...]:` list inside `create_web_server()` (it currently ends with `"message.reasoning_stream",` right before the closing `]:`). Add one new entry with a comment, right after `"message.reasoning_stream",`:

```python
        "message.reasoning_stream",
        # Home Assistant real-time device state (see plugins/home_assistant/client.py)
        "ha:state_changed",
    ]:
        event_bus.on(evt, on_event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_home_assistant_broadcast.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Run the full plugins test module set for regressions**

Run: `uv run pytest tests/unit/test_home_assistant_client.py tests/unit/test_home_assistant_tools.py tests/unit/test_home_assistant_router.py tests/unit/test_home_assistant_plugin.py tests/unit/test_home_assistant_broadcast.py tests/unit/test_plugins_api.py -v`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/openacm/web/server.py tests/unit/test_home_assistant_broadcast.py
git commit -m "feat(home-assistant): broadcast ha:state_changed to dashboard WebSocket clients"
```

---

### Task 9: Retire `tools/iot/`

**Files:**
- Delete: `src/openacm/tools/iot/` (entire directory — `__init__.py`, `base.py`, `discovery.py`, `iot_tool.py`, `registry.py`, `drivers/__init__.py`, `drivers/lgtv_driver.py`, `drivers/miio_driver.py`, `drivers/tuya_driver.py`)
- Modify: `src/openacm/tools/__init__.py`
- Modify: `src/openacm/app.py`
- Modify: `src/openacm/tools/intent_keywords.py`
- Modify: `pyproject.toml`
- Modify: `tests/unit/test_tool_registry.py`

This task has no new tests of its own — it's confirmed safe by the existing test suite (Home Assistant's tools already provide the `"iot"` category via `HomeAssistantPlugin.get_intent_keywords()`, proven in Task 7) plus a manual import-cleanliness check.

- [ ] **Step 1: Delete `tools/iot/`**

```bash
rm -rf src/openacm/tools/iot
```

- [ ] **Step 2: Remove the import in `tools/__init__.py`**

In `src/openacm/tools/__init__.py`, remove this block entirely (currently the whole file's only other content besides the first import line):

```python
try:
    from openacm.tools.iot import iot_tool
except Exception as _iot_err:
    import structlog as _log
    _log.get_logger().warning("IoT tools not loaded", error=str(_iot_err),
                              hint="Run: uv pip install tinytuya aiowebostv python-miio")
```

The file should end up as just:

```python
"""Tools module — system tools the AI can use."""

from openacm.tools import system_cmd, file_ops, system_info, web_search, google_services, set_workspace, list_tools

__all__ = ["system_cmd", "file_ops", "system_info", "web_search", "google_services", "set_workspace", "list_tools"]
```

- [ ] **Step 3: Remove the registration block in `app.py`**

In `src/openacm/app.py`, remove this block (currently right after the Stitch tool registration, before "Give brain access to tools"):

```python
        # IoT tools (optional — skipped gracefully if dependencies missing)
        try:
            from openacm.tools.iot import iot_tool
            self.tool_registry.register_module(iot_tool)
        except Exception as _iot_err:
            console.print(f"  [yellow]~[/yellow] IoT tools skipped: {_iot_err}")

```

(Home Assistant's tools are registered automatically via the plugin system's `get_tool_modules()` hook — no manual registration call needed here, same as `gmail_classifier`.)

- [ ] **Step 4: Remove the static `"iot"` keyword block**

In `src/openacm/tools/intent_keywords.py`, remove the entire `"iot": [...]` entry (currently the last key in the `INTENT_KEYWORDS` dict, right before the closing `}`):

```python
    "iot": [
        # Lighting
        "light", "lights", "luz", "luces", "lamp", "lampara", "bulb",
        # Covers
        "curtain", "curtains", "blind", "blinds", "persiana", "persianas",
        "cortina", "cortinas", "cover", "shutter",
        # Entertainment
        "tv", "television", "tele", "lg", "webos",
        "netflix", "youtube", "hdmi",
        # Appliances
        "vacuum", "aspiradora", "robot", "xiaomi", "roborock",
        "switch", "enchufe", "plug", "outlet",
        # Platforms
        "iot", "smart home", "domótica", "domotica",
        "tuya", "smartlife", "miio",
        # Controls
        "turn on", "turn off", "enciende", "apaga", "encender", "apagar",
        "dim", "brightness", "brillo", "color", "temperatura de color",
        "open", "close", "abre", "cierra", "abrir", "cerrar",
        "volume", "volumen", "channel", "canal", "mute", "silencio",
        "scan devices", "escanear dispositivos",
    ],
```

Make sure the entry before it (`"ui": [...]`) now ends with a trailing comma and the dict's closing `}` follows directly.

- [ ] **Step 5: Remove the IoT-specific dependencies from `pyproject.toml`**

In `pyproject.toml`, remove this block from the main `dependencies` list (currently right after the PTY support section, before "MCP"):

```python
    # IoT
    "tinytuya>=1.15",
    "aiowebostv>=0.7",
    # python-miio is intentionally NOT here: it pulls in netifaces==0.11.0
    # which has no Windows wheels and requires MSVC Build Tools to compile.
    # The IoT discovery code (src/openacm/tools/iot/discovery.py) already
    # try/except's the import, so Xiaomi devices simply stay undiscovered
    # unless the user opts in via: uv pip install ".[xiaomi]"

```

And remove the entire `xiaomi` extras group from `[project.optional-dependencies]`:

```python
xiaomi = [
    # Optional: Xiaomi / Roborock device discovery & control.
    # Requires MSVC Build Tools on Windows because of native netifaces.
    "python-miio>=0.5",
]
```

- [ ] **Step 6: Update `test_tool_registry.py`'s category expectations**

In `tests/unit/test_tool_registry.py`, change:

```python
    EXPECTED_CATEGORIES = {"system", "file", "web", "ai", "media", "google", "meta", "mcp", "ui", "iot"}
```

to:

```python
    EXPECTED_CATEGORIES = {"system", "file", "web", "ai", "media", "google", "meta", "mcp", "ui"}
```

("iot" is no longer a *static* category — it's supplied at runtime by `HomeAssistantPlugin.get_intent_keywords()`, already covered by `tests/unit/test_home_assistant_plugin.py::TestConfigAndMetadata::test_intent_keywords_under_iot_category` from Task 7.)

- [ ] **Step 7: Confirm nothing else references the deleted module**

Run: `grep -rn "tools\.iot\|tools/iot\|iot_tool\|iot_scan\|iot_devices\|iot_control\|iot_status\|iot_rename\|DeviceRegistry\|get_registry" --include="*.py" src/ tests/`
Expected: no matches (confirmed clean before this task started — this just re-verifies after the edits)

- [ ] **Step 8: Confirm the app still imports cleanly**

Run: `uv run python -c "from openacm.app import OpenACM; from openacm.tools import registry; print('OK')"`
Expected: `OK`

- [ ] **Step 9: Run the full test suite for regressions**

Run: `uv run pytest tests/unit/ -q`
Expected: PASS (the 5 failures + 7 errors in `test_gmail_summary.py`/`test_thread_endpoints.py` are pre-existing and unrelated — confirmed in an earlier session by reproducing them on `main` before any plugin work existed; do not treat them as caused by this task)

- [ ] **Step 10: Commit**

```bash
git add -A -- src/openacm/tools/iot src/openacm/tools/__init__.py src/openacm/app.py src/openacm/tools/intent_keywords.py pyproject.toml tests/unit/test_tool_registry.py
git commit -m "refactor: retire tools/iot/ — replaced by the home_assistant plugin"
```

---

### Task 10: Frontend — real-time store, WebSocket branch, `/home-assistant` page

**Files:**
- Create: `frontend/stores/ha-store.ts`
- Create: `frontend/hooks/use-home-assistant.ts`
- Modify: `frontend/hooks/use-websocket.ts`
- Create: `frontend/app/home-assistant/page.tsx`

No new automated tests for this task (pure frontend, no test runner configured for it in this repo) — verification is `npx tsc --noEmit` + `npm run build`, matching every other frontend task in this project's plan history.

- [ ] **Step 1: Create the Zustand store**

Create `frontend/stores/ha-store.ts`:

```typescript
import { create } from 'zustand';

export interface HAEntityState {
  entity_id: string;
  state: string;
  attributes: Record<string, any>;
}

interface HAState {
  entities: Record<string, HAEntityState>;
  setEntityState: (entityId: string, state: HAEntityState) => void;
}

export const useHAStore = create<HAState>()((set) => ({
  entities: {},
  setEntityState: (entityId, state) =>
    set((s) => ({ entities: { ...s.entities, [entityId]: state } })),
}));
```

- [ ] **Step 2: Add the `ha:state_changed` branch to `use-websocket.ts`**

In `frontend/hooks/use-websocket.ts`:

1. Add the import, next to the other store imports at the top of the file:

```typescript
import { useHAStore } from '@/stores/ha-store';
```

2. Add a ref next to `storeRef`/`tamaRef` (find `const storeRef = useRef(useChatStore.getState());` and add right after it):

```typescript
  const haRef = useRef(useHAStore.getState());
```

3. Extend the `WebSocketMessage` interface (add near the end, after the `chunk?: string;` field for `message.reasoning_stream`):

```typescript
  // ha:state_changed fields
  entity_id?: string;
  state?: Record<string, any>;
```

4. Add the dispatch branch. Find the `else if (data.type === 'skill.active')` branch and add a new `else if` right after its closing `}`:

```typescript
      } else if (data.type === 'ha:state_changed') {
        if (data.entity_id && data.state) {
          haRef.current.setEntityState(data.entity_id, data.state as any);
        }
```

- [ ] **Step 3: Create the Home Assistant API hooks**

Create `frontend/hooks/use-home-assistant.ts`:

```typescript
'use client';

import { useQuery, useMutation } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';
import { toast } from 'sonner';

export interface HAEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, any>;
}

export function useHADevices() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<{ devices: HAEntity[] }>({
    queryKey: ['ha-devices'],
    queryFn: () => fetchAPI('/api/home-assistant/devices'),
    enabled: isAuthenticated,
    staleTime: 30_000,
  });
}

export function useHAScenes() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<{ scenes: HAEntity[] }>({
    queryKey: ['ha-scenes'],
    queryFn: () => fetchAPI('/api/home-assistant/scenes'),
    enabled: isAuthenticated,
    staleTime: 30_000,
  });
}

export function useHAControl() {
  const { fetchAPI } = useAPI();

  return useMutation({
    mutationFn: ({ entityId, action, ...params }: { entityId: string; action: string; [k: string]: any }) =>
      fetchAPI(`/api/home-assistant/devices/${entityId}/control`, {
        method: 'POST',
        body: JSON.stringify({ action, ...params }),
      }),
    onError: (err: Error) => toast.error(err.message || 'No se pudo controlar el dispositivo'),
  });
}

export function useHAActivateScene() {
  const { fetchAPI } = useAPI();

  return useMutation({
    mutationFn: (entityId: string) =>
      fetchAPI(`/api/home-assistant/scenes/${entityId}/activate`, { method: 'POST' }),
    onSuccess: () => toast.success('Escena activada'),
    onError: (err: Error) => toast.error(err.message || 'No se pudo activar la escena'),
  });
}
```

- [ ] **Step 4: Create the `/home-assistant` page**

Create `frontend/app/home-assistant/page.tsx`:

```tsx
'use client';

import { useMemo } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useHADevices, useHAScenes, useHAControl, useHAActivateScene, type HAEntity } from '@/hooks/use-home-assistant';
import { useHAStore } from '@/stores/ha-store';
import { Loader2, Home, Power } from 'lucide-react';

const DOMAIN_LABELS: Record<string, string> = {
  light: 'Luces',
  switch: 'Enchufes',
  climate: 'Clima',
  cover: 'Cortinas',
  media_player: 'Reproductores',
  vacuum: 'Aspiradoras',
};

const TOGGLEABLE_DOMAINS = new Set(['light', 'switch', 'climate', 'media_player']);

export default function HomeAssistantPage() {
  const { data, isLoading, error } = useHADevices();
  const { data: scenesData } = useHAScenes();
  const liveEntities = useHAStore((s) => s.entities);
  const control = useHAControl();
  const activateScene = useHAActivateScene();

  const entities = useMemo<HAEntity[]>(() => {
    const base = data?.devices ?? [];
    return base.map((e) => liveEntities[e.entity_id] ?? e);
  }, [data, liveEntities]);

  const byDomain = useMemo(() => {
    const groups: Record<string, HAEntity[]> = {};
    for (const e of entities) {
      const domain = e.entity_id.split('.')[0];
      if (!DOMAIN_LABELS[domain]) continue;
      (groups[domain] ??= []).push(e);
    }
    return groups;
  }, [entities]);

  if (error) {
    return (
      <AppLayout>
        <div style={{ padding: 32, maxWidth: 1100, margin: '0 auto' }}>
          <div className="acm-card flex flex-col items-center justify-center" style={{ padding: '64px 32px', textAlign: 'center' }}>
            <Home size={40} style={{ color: 'var(--acm-fg-4)', marginBottom: 16 }} />
            <h3 className="text-base font-semibold mb-2" style={{ color: 'var(--acm-fg-2)' }}>
              Home Assistant no está configurado
            </h3>
            <p className="text-sm" style={{ color: 'var(--acm-fg-4)' }}>
              Configura la URL y el token desde <span className="mono">/plugins</span>.
            </p>
          </div>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div style={{ padding: 32, maxWidth: 1100, margin: '0 auto' }}>
        <h1 className="font-bold" style={{ fontSize: 24, color: 'var(--acm-fg)', marginBottom: 28 }}>
          Home Assistant
        </h1>

        {isLoading ? (
          <Loader2 size={24} className="animate-spin" />
        ) : (
          <>
            {Object.entries(byDomain).map(([domain, devs]) => (
              <div key={domain} style={{ marginBottom: 28 }}>
                <h2 className="label" style={{ marginBottom: 12, color: 'var(--acm-fg-3)' }}>
                  {DOMAIN_LABELS[domain]}
                </h2>
                <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
                  {devs.map((e) => {
                    const name = e.attributes?.friendly_name || e.entity_id;
                    const isOn = e.state === 'on';
                    return (
                      <div
                        key={e.entity_id}
                        className="acm-card"
                        style={{ padding: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}
                      >
                        <div style={{ minWidth: 0 }}>
                          <div
                            style={{
                              fontWeight: 600, color: 'var(--acm-fg)',
                              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                            }}
                          >
                            {name}
                          </div>
                          <div style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>{e.state}</div>
                        </div>
                        {TOGGLEABLE_DOMAINS.has(domain) && (
                          <button
                            className="btn-secondary"
                            style={{ padding: '4px 10px', fontSize: 12, flexShrink: 0 }}
                            onClick={() => control.mutate({ entityId: e.entity_id, action: isOn ? 'turn_off' : 'turn_on' })}
                          >
                            <Power size={13} style={{ color: isOn ? 'var(--acm-accent)' : 'var(--acm-fg-4)' }} />
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}

            {(scenesData?.scenes ?? []).length > 0 && (
              <div>
                <h2 className="label" style={{ marginBottom: 12, color: 'var(--acm-fg-3)' }}>Escenas</h2>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  {scenesData!.scenes.map((s) => (
                    <button key={s.entity_id} className="btn-secondary" onClick={() => activateScene.mutate(s.entity_id)}>
                      {s.attributes?.friendly_name || s.entity_id}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </AppLayout>
  );
}
```

Note: this page is **not** added to `frontend/components/layout/sidebar.tsx` — unlike the core `/plugins` page, this is a plugin-provided page, discovered dynamically via `HomeAssistantPlugin.get_nav_items()` → `GET /api/plugins/nav` → `sidebar.tsx`'s existing `pluginItems` fetch (the same mechanism `gmail_classifier`'s `/gmail-classifier` nav entry already uses — confirmed no core sidebar edit was needed for that page either).

- [ ] **Step 5: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 errors

- [ ] **Step 6: Full build**

Run: `cd frontend && npm run build`
Expected: build succeeds, `/home-assistant` appears in the route list

- [ ] **Step 7: Commit**

```bash
git add frontend/stores/ha-store.ts frontend/hooks/use-home-assistant.ts frontend/hooks/use-websocket.ts frontend/app/home-assistant/page.tsx
git commit -m "feat(home-assistant): /home-assistant dashboard page with real-time state"
```

---

### Task 11: Docs update + full regression pass + manual verification

**Files:**
- Modify: `docs/05-tools-reference.md`

- [ ] **Step 1: Replace the IoT tools reference section**

In `docs/05-tools-reference.md`, change the category table row (currently `| \`iot\` | 9 | Smart home device control |`) to:

```markdown
| `iot` | 7 | Smart home device control via Home Assistant |
```

Then replace the entire `## IoT / Smart Home Tools` section (from that heading through the `---` right before `## MCP Tools`) with:

```markdown
## IoT / Smart Home Tools

Control smart home devices through a [Home Assistant](https://www.home-assistant.io/) instance — configure the URL and a Long-Lived Access Token from `/plugins`. No per-vendor setup in OpenACM: Home Assistant's own integrations (Tuya, Xiaomi, LG WebOS, and hundreds more) already normalize every device behind one API.

### `ha_devices`
List entities, optionally filtered by domain.

```python
ha_devices(
    domain: str = ""     # e.g. "light", "switch", "climate", "cover", "media_player", "vacuum"
)
```

### `ha_status`
Get the current state and attributes of one entity — by exact `entity_id` or friendly name.

```python
ha_status(
    entity_id: str       # e.g. "light.sala" or "Luz Sala"
)
```

### `ha_control`
Control one or more entities, or a whole Home Assistant area, in one call.

```python
ha_control(
    entity_id: str | list = None,  # single id, list of ids, or omit if using `area`
    action: str,                    # turn_on, turn_off, toggle, set_brightness, set_color_temp,
                                     # set_temperature, open, close, stop, set_volume
    area: str = "",                  # area name — only with turn_on/turn_off/toggle
    brightness: int = None,          # 0-100, for set_brightness
    kelvin: int = None,              # 2000-6500, for set_color_temp
    temperature: float = None,       # for set_temperature
    volume: float = None,            # 0.0-1.0, for set_volume
)
```

### `ha_scenes`
List scenes available to activate.

```python
ha_scenes()
```

### `ha_activate_scene`
Activate a scene by name.

```python
ha_activate_scene(
    name: str             # e.g. "Modo Noche"
)
```

**Example:**
```
"Apaga todas las luces de la sala"
→ ha_control(area="sala", action="turn_off")   # one call, whole area

"Apaga las luces, cierra las cortinas, y activa modo noche"
→ ha_control(entity_id=["light.sala", "light.cocina"], action="turn_off")
→ ha_control(entity_id="cover.sala", action="close")
→ ha_activate_scene("Modo Noche")
```

---
```

- [ ] **Step 2: Commit the docs update**

```bash
git add docs/05-tools-reference.md
git commit -m "docs: replace IoT tools reference with Home Assistant tools"
```

- [ ] **Step 3: Run the full backend test suite**

Run: `uv run pytest tests/unit/ -q`
Expected: PASS (same pre-existing, unrelated 5 failures + 7 errors as Task 9's check — no new failures)

- [ ] **Step 4: Run the full frontend build**

Run: `cd frontend && npm run build`
Expected: builds clean

- [ ] **Step 5: Manual verification against a real Home Assistant instance**

This step needs your actual Home Assistant instance and can't be automated:

1. Rebuild and restart OpenACM (`run.bat`, which rebuilds the frontend automatically).
2. Go to `/plugins`, find `home_assistant`, click "Configurar", fill in your HA URL and a Long-Lived Access Token (generate one from your HA user profile page).
3. Restart (the banner will prompt you) so `on_start()` picks up the new config and connects.
4. Visit `/home-assistant` — confirm your real devices show up, grouped by domain.
5. Toggle a light or switch from the page — confirm it actually changes in Home Assistant (and that flipping it back from the HA app or a physical switch updates the OpenACM page within about a second, proving the real-time path end-to-end).
6. From chat, try: "apaga todas las luces de la sala" (if you have an area named that in HA), "enciende la luz de X al 50%", and — if you have a scene configured — "activa modo noche".
7. Confirm `ha_devices`/`ha_status` in chat return sensible results for your real entities.

- [ ] **Step 6: Final commit if any fixups were needed**

```bash
git add -A
git commit -m "fix: address issues found in Home Assistant manual verification"
```
