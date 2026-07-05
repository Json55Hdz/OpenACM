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


class TestFlowCRUD:
    async def test_create_and_get_flow(self):
        db = await _make_db()
        agent_id = await _make_agent(db)

        flow_id = await db.create_flow(agent_id=agent_id, name="check-website", description="Checks a URL")
        flow = await db.get_flow(flow_id)

        assert flow["name"] == "check-website"
        assert flow["description"] == "Checks a URL"
        assert flow["agent_id"] == agent_id
        assert flow["is_active"] == 1
        await db.close()

    async def test_get_agent_flows_returns_only_that_agents_flows(self):
        db = await _make_db()
        a1 = await _make_agent(db, "a1")
        a2 = await _make_agent(db, "a2")
        await db.create_flow(agent_id=a1, name="f1")
        await db.create_flow(agent_id=a2, name="f2")

        flows = await db.get_agent_flows(a1)

        assert [f["name"] for f in flows] == ["f1"]
        await db.close()

    async def test_get_agent_flows_active_only_filters_inactive(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        active_id = await db.create_flow(agent_id=agent_id, name="active-flow")
        inactive_id = await db.create_flow(agent_id=agent_id, name="inactive-flow")
        await db.update_flow(inactive_id, is_active=0)

        flows = await db.get_agent_flows(agent_id, active_only=True)

        assert [f["id"] for f in flows] == [active_id]
        await db.close()

    async def test_update_flow_graph_json(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        flow_id = await db.create_flow(agent_id=agent_id, name="f1")

        ok = await db.update_flow(flow_id, graph_json='{"nodes":[{"id":"n1"}],"edges":[]}')

        assert ok
        flow = await db.get_flow(flow_id)
        assert flow["graph_json"] == '{"nodes":[{"id":"n1"}],"edges":[]}'
        await db.close()

    async def test_delete_flow(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        flow_id = await db.create_flow(agent_id=agent_id, name="f1")

        ok = await db.delete_flow(flow_id)

        assert ok
        assert await db.get_flow(flow_id) is None
        await db.close()

    async def test_update_flow_scoped_to_wrong_agent_id_fails(self):
        db = await _make_db()
        owner = await _make_agent(db, "owner")
        other = await _make_agent(db, "other")
        flow_id = await db.create_flow(agent_id=owner, name="f1")

        ok = await db.update_flow(flow_id, agent_id=other, name="hijacked")

        assert not ok
        flow = await db.get_flow(flow_id)
        assert flow["name"] == "f1"
        await db.close()

    async def test_delete_flow_scoped_to_wrong_agent_id_fails(self):
        db = await _make_db()
        owner = await _make_agent(db, "owner")
        other = await _make_agent(db, "other")
        flow_id = await db.create_flow(agent_id=owner, name="f1")

        ok = await db.delete_flow(flow_id, agent_id=other)

        assert not ok
        assert await db.get_flow(flow_id) is not None
        await db.close()

    async def test_update_flow_scoped_to_correct_agent_id_succeeds(self):
        db = await _make_db()
        owner = await _make_agent(db, "owner")
        flow_id = await db.create_flow(agent_id=owner, name="f1")

        ok = await db.update_flow(flow_id, agent_id=owner, name="renamed")

        assert ok
        flow = await db.get_flow(flow_id)
        assert flow["name"] == "renamed"
        await db.close()


class TestConnectionCRUD:
    async def test_create_and_get_connection_includes_config(self):
        db = await _make_db()
        agent_id = await _make_agent(db)

        conn_id = await db.create_connection(
            agent_id=agent_id, name="Mi Tienda", type="woocommerce",
            config='{"url": "https://example.com", "consumer_key": "ck_1", "consumer_secret": "cs_1"}',
        )
        conn = await db.get_connection(conn_id)

        assert conn["name"] == "Mi Tienda"
        assert conn["type"] == "woocommerce"
        assert "ck_1" in conn["config"]
        await db.close()

    async def test_get_agent_connections_excludes_config(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        await db.create_connection(agent_id=agent_id, name="Mi Tienda", type="woocommerce", config='{"consumer_secret": "topsecret"}')

        connections = await db.get_agent_connections(agent_id)

        assert connections[0]["name"] == "Mi Tienda"
        assert "config" not in connections[0]

    async def test_update_connection_config(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        conn_id = await db.create_connection(agent_id=agent_id, name="Mi Tienda", type="woocommerce", config='{"consumer_key":"old"}')

        ok = await db.update_connection(conn_id, config='{"consumer_key":"new"}')

        assert ok
        conn = await db.get_connection(conn_id)
        assert "new" in conn["config"]
        await db.close()

    async def test_delete_connection(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        conn_id = await db.create_connection(agent_id=agent_id, name="Mi Tienda", type="woocommerce", config="{}")

        ok = await db.delete_connection(conn_id)

        assert ok
        assert await db.get_connection(conn_id) is None
        await db.close()

    async def test_update_connection_scoped_to_wrong_agent_id_fails(self):
        db = await _make_db()
        owner = await _make_agent(db, "owner")
        other = await _make_agent(db, "other")
        conn_id = await db.create_connection(agent_id=owner, name="Mi Tienda", type="woocommerce", config='{"consumer_key":"old"}')

        ok = await db.update_connection(conn_id, agent_id=other, config='{"consumer_key":"hijacked"}')

        assert not ok
        conn = await db.get_connection(conn_id)
        assert "old" in conn["config"]
        await db.close()

    async def test_delete_connection_scoped_to_wrong_agent_id_fails(self):
        db = await _make_db()
        owner = await _make_agent(db, "owner")
        other = await _make_agent(db, "other")
        conn_id = await db.create_connection(agent_id=owner, name="Mi Tienda", type="woocommerce", config="{}")

        ok = await db.delete_connection(conn_id, agent_id=other)

        assert not ok
        assert await db.get_connection(conn_id) is not None
        await db.close()

    async def test_update_connection_scoped_to_correct_agent_id_succeeds(self):
        db = await _make_db()
        owner = await _make_agent(db, "owner")
        conn_id = await db.create_connection(agent_id=owner, name="Mi Tienda", type="woocommerce", config='{"consumer_key":"old"}')

        ok = await db.update_connection(conn_id, agent_id=owner, config='{"consumer_key":"new"}')

        assert ok
        conn = await db.get_connection(conn_id)
        assert "new" in conn["config"]
        await db.close()
