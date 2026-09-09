"""Tests for the webhook_connectors / webhook_connector_events migration."""
import pytest
from openacm.storage.database import Database


async def _make_db():
    db = Database(":memory:")
    await db.initialize()
    # Create a default agent for the flow to reference
    await db._db.execute(
        "INSERT INTO agents (name, system_prompt, webhook_secret) VALUES (?, ?, ?)",
        ("Test Agent", "test prompt", "secret"),
    )
    # Create a default flow for foreign key constraint
    await db._db.execute(
        "INSERT INTO flows (name, agent_id, graph_json) VALUES (?, ?, ?)",
        ("Test Flow", 1, "{}"),
    )
    await db._db.commit()
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
