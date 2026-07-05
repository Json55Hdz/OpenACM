"""Tests for migration 33 — skills.agent_id + agent_skills table."""
import pytest
from openacm.storage.database import Database


async def _make_db():
    db = Database(":memory:")
    await db.initialize()
    return db


async def _make_agent(db, name="a1"):
    return await db.create_agent(
        name=name, description="", system_prompt="test prompt",
    )


class TestMigration33Schema:
    async def test_skills_table_has_agent_id_column(self):
        db = await _make_db()
        cursor = await db._db.execute("PRAGMA table_info(skills)")
        columns = {row["name"] for row in await cursor.fetchall()}
        assert "agent_id" in columns
        await db.close()

    async def test_agent_skills_table_exists(self):
        db = await _make_db()
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_skills'"
        )
        assert await cursor.fetchone() is not None
        await db.close()

    async def test_two_global_skills_still_cannot_share_a_name(self):
        db = await _make_db()
        await db.create_skill(name="dup", description="d1", content="c1")
        with pytest.raises(Exception):
            await db.create_skill(name="dup", description="d2", content="c2")
        await db.close()

    async def test_a_global_skill_and_an_agent_skill_can_share_a_name(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        await db.create_skill(name="shared", description="d1", content="c1")
        skill_id = await db.create_skill(name="shared", description="d2", content="c2", agent_id=agent_id)
        assert skill_id
        await db.close()

    async def test_two_different_agents_can_each_have_a_skill_with_the_same_name(self):
        db = await _make_db()
        a1 = await _make_agent(db, "a1")
        a2 = await _make_agent(db, "a2")
        await db._db.execute(
            "INSERT INTO skills (name, description, content, agent_id) VALUES (?, ?, ?, ?)",
            ("shared-name", "d1", "c1", a1),
        )
        await db._db.execute(
            "INSERT INTO skills (name, description, content, agent_id) VALUES (?, ?, ?, ?)",
            ("shared-name", "d2", "c2", a2),
        )
        await db._db.commit()
        cursor = await db._db.execute("SELECT COUNT(*) as n FROM skills WHERE name = 'shared-name'")
        assert (await cursor.fetchone())["n"] == 2
        await db.close()

    async def test_one_agent_cannot_have_two_skills_with_the_same_name(self):
        db = await _make_db()
        a1 = await _make_agent(db)
        await db._db.execute(
            "INSERT INTO skills (name, description, content, agent_id) VALUES (?, ?, ?, ?)",
            ("mine", "d1", "c1", a1),
        )
        await db._db.commit()
        with pytest.raises(Exception):
            await db._db.execute(
                "INSERT INTO skills (name, description, content, agent_id) VALUES (?, ?, ?, ?)",
                ("mine", "d2", "c2", a1),
            )
            await db._db.commit()
        await db.close()

    async def test_deleting_agent_cascades_to_its_private_skills_and_agent_skills_rows(self):
        db = await _make_db()
        a1 = await _make_agent(db)
        global_skill_id = await db.create_skill(name="g1", description="d", content="c")
        await db._db.execute(
            "INSERT INTO skills (name, description, content, agent_id) VALUES (?, ?, ?, ?)",
            ("private1", "d", "c", a1),
        )
        await db._db.execute(
            "INSERT INTO agent_skills (agent_id, skill_id) VALUES (?, ?)", (a1, global_skill_id)
        )
        await db._db.commit()

        await db._db.execute("DELETE FROM agents WHERE id = ?", (a1,))
        await db._db.commit()

        cursor = await db._db.execute("SELECT COUNT(*) as n FROM skills WHERE agent_id = ?", (a1,))
        assert (await cursor.fetchone())["n"] == 0
        cursor = await db._db.execute("SELECT COUNT(*) as n FROM agent_skills WHERE agent_id = ?", (a1,))
        assert (await cursor.fetchone())["n"] == 0
        cursor = await db._db.execute("SELECT COUNT(*) as n FROM skills WHERE id = ?", (global_skill_id,))
        assert (await cursor.fetchone())["n"] == 1
        await db.close()
