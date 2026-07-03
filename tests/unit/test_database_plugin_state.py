import pytest
from openacm.storage.database import Database


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


class TestPluginState:
    async def test_unknown_plugin_is_enabled_by_default(self, db):
        assert await db.is_plugin_enabled("never_seen") is True

    async def test_set_and_read_enabled_flag(self, db):
        await db.set_plugin_enabled("gmail_classifier", False)
        assert await db.is_plugin_enabled("gmail_classifier") is False
        await db.set_plugin_enabled("gmail_classifier", True)
        assert await db.is_plugin_enabled("gmail_classifier") is True

    async def test_config_defaults_to_empty_dict(self, db):
        assert await db.get_plugin_config("never_seen") == {}

    async def test_set_and_read_config(self, db):
        await db.set_plugin_config("home_assistant", {"url": "http://ha.local:8123", "token": "abc"})
        assert await db.get_plugin_config("home_assistant") == {
            "url": "http://ha.local:8123",
            "token": "abc",
        }

    async def test_set_plugin_config_overwrites_fully(self, db):
        await db.set_plugin_config("home_assistant", {"url": "http://old", "token": "x"})
        await db.set_plugin_config("home_assistant", {"url": "http://new"})
        assert await db.get_plugin_config("home_assistant") == {"url": "http://new"}

    async def test_get_all_plugin_states_only_lists_rows_that_exist(self, db):
        await db.set_plugin_enabled("gmail_classifier", False)
        await db.set_plugin_config("home_assistant", {"url": "http://ha.local"})
        states = await db.get_all_plugin_states()
        assert states["gmail_classifier"]["enabled"] is False
        assert states["gmail_classifier"]["config"] == {}
        assert states["home_assistant"]["enabled"] is True
        assert states["home_assistant"]["config"] == {"url": "http://ha.local"}
        assert "never_seen" not in states
