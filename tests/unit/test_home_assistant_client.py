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
