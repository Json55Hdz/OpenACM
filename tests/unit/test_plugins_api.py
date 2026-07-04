import pytest
from openacm.plugins import Plugin, plugin_manager

TEST_TOKEN = "test-dashboard-token"


@pytest.fixture
def dashboard_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", TEST_TOKEN)
    return TEST_TOKEN


@pytest.fixture
def auth_headers(dashboard_token):
    return {"Authorization": f"Bearer {dashboard_token}"}


class _ConfigPlugin(Plugin):
    name = "config_plugin"
    version = "1.0.0"
    description = "Test plugin"
    author = "test"

    def get_config_schema(self):
        return [
            {"key": "url", "label": "URL", "type": "text", "required": True, "help": ""},
            {"key": "token", "label": "Token", "type": "password", "required": True, "help": ""},
        ]


@pytest.fixture(autouse=True)
def _register_test_plugin():
    plugin_manager._plugins = [p for p in plugin_manager._plugins if p.name != "config_plugin"]
    plugin_manager.register(_ConfigPlugin())
    plugin_manager._enabled["config_plugin"] = True
    yield
    plugin_manager._plugins = [p for p in plugin_manager._plugins if p.name != "config_plugin"]
    plugin_manager._enabled.pop("config_plugin", None)


class TestPluginsListEndpoint:
    async def test_list_includes_enabled_and_schema_flags(self, dashboard_token, client, auth_headers):
        resp = await client.get("/api/plugins", headers=auth_headers)
        assert resp.status_code == 200
        entry = next(p for p in resp.json() if p["name"] == "config_plugin")
        assert entry["enabled"] is True
        assert entry["has_config_schema"] is True
        assert entry["has_custom_ui"] is False


class TestPluginToggleEndpoint:
    async def test_toggle_disables_plugin(self, dashboard_token, client, auth_headers):
        resp = await client.post("/api/plugins/config_plugin/toggle", json={"enabled": False}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    async def test_toggle_unknown_plugin_404s(self, dashboard_token, client, auth_headers):
        resp = await client.post("/api/plugins/does_not_exist/toggle", json={"enabled": False}, headers=auth_headers)
        assert resp.status_code == 404


class TestPluginConfigEndpoints:
    async def test_get_config_returns_schema_and_masks_password(self, dashboard_token, client, auth_headers):
        await client.post(
            "/api/plugins/config_plugin/config",
            json={"url": "http://ha.local:8123", "token": "secret123"},
            headers=auth_headers,
        )
        resp = await client.get("/api/plugins/config_plugin/config", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["values"]["url"] == "http://ha.local:8123"
        assert body["values"]["token"] == "***"

    async def test_post_config_missing_required_field_400s(self, dashboard_token, client, auth_headers):
        resp = await client.post(
            "/api/plugins/config_plugin/config",
            json={"url": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_post_config_unchanged_password_marker_preserves_existing(self, dashboard_token, client, auth_headers):
        await client.post(
            "/api/plugins/config_plugin/config",
            json={"url": "http://ha.local:8123", "token": "secret123"},
            headers=auth_headers,
        )
        await client.post(
            "/api/plugins/config_plugin/config",
            json={"url": "http://ha.local:9999", "token": "***"},
            headers=auth_headers,
        )
        resp = await client.get("/api/plugins/config_plugin/config", headers=auth_headers)
        assert resp.json()["values"]["url"] == "http://ha.local:9999"
        assert resp.json()["values"]["token"] == "***"  # still set, still masked


class TestPluginDocsEndpoint:
    async def test_docs_returns_markdown_text(self, dashboard_token, client, auth_headers):
        resp = await client.get("/api/plugins/docs", headers=auth_headers)
        assert resp.status_code == 200
        assert "plugin" in resp.text.lower()
