import pytest
from unittest.mock import AsyncMock
from openacm.plugins import Plugin, PluginManager


class _NavPlugin(Plugin):
    name = "nav_plugin"

    def get_nav_items(self):
        return [{"path": "/nav-plugin", "label": "Nav Plugin", "icon": "Puzzle"}]

    def get_context_extension(self):
        return "Nav plugin context."

    def get_api_router(self):
        from fastapi import APIRouter
        router = APIRouter(prefix="/nav-plugin")
        return router


class TestPluginManagerEnabledState:
    async def test_plugins_property_lists_disabled_plugins_too(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = False
        await pm.load_enabled_state(mock_db)
        assert [p.name for p in pm.plugins] == ["nav_plugin"]

    async def test_disabled_plugin_excluded_from_nav_items(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = False
        await pm.load_enabled_state(mock_db)
        assert pm.get_nav_items() == []

    async def test_disabled_plugin_excluded_from_context_extensions(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = False
        await pm.load_enabled_state(mock_db)
        assert pm.get_context_extensions() == []

    async def test_disabled_plugin_excluded_from_api_routers(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = False
        await pm.load_enabled_state(mock_db)
        assert pm.get_api_routers() == []

    async def test_enabled_plugin_included_everywhere(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = True
        await pm.load_enabled_state(mock_db)
        assert len(pm.get_nav_items()) == 1
        assert len(pm.get_context_extensions()) == 1
        assert len(pm.get_api_routers()) == 1

    async def test_start_all_skips_on_start_for_disabled_plugin(self):
        pm = PluginManager()
        plugin = _NavPlugin()
        plugin.on_start = AsyncMock()
        pm.register(plugin)
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = False
        await pm.load_enabled_state(mock_db)
        await pm.start_all(database=mock_db)
        plugin.on_start.assert_not_awaited()

    def test_is_enabled_defaults_true_before_load_enabled_state(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        assert pm.is_enabled("nav_plugin") is True

    async def test_nav_items_are_tagged_with_owning_plugin_name(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = True
        await pm.load_enabled_state(mock_db)
        [item] = pm.get_nav_items()
        assert item["plugin"] == "nav_plugin"
        assert item["path"] == "/nav-plugin"
