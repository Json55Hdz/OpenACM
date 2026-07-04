"""Unit tests for HomeAssistantClient — REST layer."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
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

    async def test_call_service_non_json_2xx_response_returns_friendly_error(self):
        client = _make_client()
        resp = MagicMock(status_code=200)
        resp.json.side_effect = ValueError("bad json")
        client._http.post = AsyncMock(return_value=resp)

        result = await client.call_service("light", "turn_on", entity_id="light.sala")

        assert result["success"] is False
        assert "non-JSON" in result["error"]


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
