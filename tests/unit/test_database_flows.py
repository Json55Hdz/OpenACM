"""Tests for migration 34 — flows + connections tables."""
import pytest
from openacm.storage.database import Database


async def _make_db():
    db = Database(":memory:")
    await db.initialize()
    return db


async def _make_agent(db, name="a1"):
    return await db.create_agent(name=name, description="", system_prompt="test prompt")


class TestMigration34Schema:
    async def test_flows_table_exists(self):
        db = await _make_db()
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='flows'"
        )
        assert await cursor.fetchone() is not None
        await db.close()

    async def test_connections_table_exists(self):
        db = await _make_db()
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='connections'"
        )
        assert await cursor.fetchone() is not None
        await db.close()

    async def test_flow_requires_an_agent_id(self):
        db = await _make_db()
        with pytest.raises(Exception):
            await db._db.execute(
                "INSERT INTO flows (agent_id, name, description, graph_json) VALUES (NULL, 'f1', '', '{}')"
            )
            await db._db.commit()
        await db.close()

    async def test_deleting_agent_cascades_to_its_flows_and_connections(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        await db._db.execute(
            "INSERT INTO flows (agent_id, name, description, graph_json) VALUES (?, 'f1', '', '{}')",
            (agent_id,),
        )
        await db._db.execute(
            "INSERT INTO connections (agent_id, name, type, config) VALUES (?, 'c1', 'woocommerce', '{}')",
            (agent_id,),
        )
        await db._db.commit()

        await db._db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        await db._db.commit()

        cursor = await db._db.execute("SELECT COUNT(*) as n FROM flows WHERE agent_id = ?", (agent_id,))
        assert (await cursor.fetchone())["n"] == 0
        cursor = await db._db.execute("SELECT COUNT(*) as n FROM connections WHERE agent_id = ?", (agent_id,))
        assert (await cursor.fetchone())["n"] == 0
        await db.close()

    async def test_flow_defaults(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        await db._db.execute(
            "INSERT INTO flows (agent_id, name) VALUES (?, 'f1')", (agent_id,)
        )
        await db._db.commit()
        cursor = await db._db.execute("SELECT * FROM flows WHERE agent_id = ?", (agent_id,))
        row = await cursor.fetchone()
        assert row["is_active"] == 1
        assert row["graph_json"] == '{"nodes":[],"edges":[]}'
        assert row["description"] == ""
        await db.close()
