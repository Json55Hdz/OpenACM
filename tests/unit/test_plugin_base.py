import pytest
from unittest.mock import AsyncMock
from openacm.plugins import Plugin


class _BarePlugin(Plugin):
    name = "bare"


class _ConfigurablePlugin(Plugin):
    name = "configurable"

    def get_config_schema(self):
        return [{"key": "url", "label": "URL", "type": "text", "required": True, "help": ""}]

    def has_custom_ui(self):
        return True


class TestPluginDefaults:
    def test_bare_plugin_has_no_config_schema(self):
        assert _BarePlugin().get_config_schema() == []

    def test_bare_plugin_has_no_custom_ui(self):
        assert _BarePlugin().has_custom_ui() is False

    def test_configurable_plugin_overrides(self):
        p = _ConfigurablePlugin()
        assert p.get_config_schema()[0]["key"] == "url"
        assert p.has_custom_ui() is True


class TestGetSetting:
    async def test_get_setting_returns_default_before_on_start(self):
        p = _BarePlugin()
        assert await p.get_setting("missing", default="fallback") == "fallback"

    async def test_get_setting_reads_from_database_after_on_start(self):
        mock_db = AsyncMock()
        mock_db.get_plugin_config.return_value = {"url": "http://ha.local"}
        p = _BarePlugin()
        await p.on_start(database=mock_db)
        assert await p.get_setting("url") == "http://ha.local"
        mock_db.get_plugin_config.assert_awaited_once_with("bare")

    async def test_get_setting_returns_default_for_missing_key(self):
        mock_db = AsyncMock()
        mock_db.get_plugin_config.return_value = {}
        p = _BarePlugin()
        await p.on_start(database=mock_db)
        assert await p.get_setting("missing", default=42) == 42
