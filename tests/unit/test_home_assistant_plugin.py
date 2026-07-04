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
