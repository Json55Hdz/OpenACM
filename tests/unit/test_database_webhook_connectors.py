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
        # flow_id=1 (the flow the fixture actually creates) on purpose: with a
        # non-existent flow_id this would fail on the FK constraint and never
        # exercise the UNIQUE slug index it's meant to prove.
        with pytest.raises(Exception):
            await db.create_webhook_connector(
                slug="pagos", name="Pagos 2", auth_scheme="bearer_token",
                auth_config={"token": "t2", "header_name": "Authorization"}, flow_id=1,
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

    async def test_failed_event_is_not_deduped(self):
        # A failed attempt must never be cached and replayed as a success —
        # the retry has to actually re-run the flow.
        db = await _make_db()
        cid = await db.create_webhook_connector(
            slug="pagos", name="Pagos", auth_scheme="bearer_token",
            auth_config={"token": "t", "header_name": "Authorization"}, flow_id=1,
        )
        await db.record_webhook_connector_event(
            cid, "evt-fail", "{}", "flow_error", "Error in node http1: boom", 5,
        )
        assert await db.find_webhook_connector_event_by_dedupe_key(cid, "evt-fail") is None

        # ...while a successful one with the same key IS found.
        await db.record_webhook_connector_event(cid, "evt-ok", "{}", "ok", "done", 5)
        found = await db.find_webhook_connector_event_by_dedupe_key(cid, "evt-ok")
        assert found is not None
        assert found["status"] == "ok"

    async def test_ok_event_is_found_even_after_an_earlier_failure(self):
        # Same key, failed first then succeeded: the `ok` row is the one that
        # counts (the status filter must not just take the oldest row).
        db = await _make_db()
        cid = await db.create_webhook_connector(
            slug="pagos", name="Pagos", auth_scheme="bearer_token",
            auth_config={"token": "t", "header_name": "Authorization"}, flow_id=1,
        )
        await db.record_webhook_connector_event(cid, "evt-1", "{}", "flow_error", "boom", 5)
        await db.record_webhook_connector_event(cid, "evt-1", "{}", "ok", "done", 7)
        found = await db.find_webhook_connector_event_by_dedupe_key(cid, "evt-1")
        assert found is not None
        assert found["status"] == "ok"
        assert found["result"] == "done"

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
