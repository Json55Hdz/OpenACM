"""Tests for migration 32 — skills.worker_id + worker_skills table."""
import pytest
from openacm.storage.database import Database


async def _make_db():
    db = Database(":memory:")
    await db.initialize()
    return db


async def _make_swarm_and_worker(db, name="w1"):
    swarm_id = await db.create_swarm(name="Test Swarm", goal="test")
    worker_id = await db.create_swarm_worker(
        swarm_id=swarm_id, name=name, role="worker",
        description="", system_prompt="test prompt",
        model=None, allowed_tools="", workspace_path="/tmp",
    )
    return swarm_id, worker_id


class TestMigration32Schema:
    async def test_skills_table_has_worker_id_column(self):
        db = await _make_db()
        cursor = await db._db.execute("PRAGMA table_info(skills)")
        columns = {row["name"] for row in await cursor.fetchall()}
        assert "worker_id" in columns
        await db.close()

    async def test_worker_skills_table_exists(self):
        db = await _make_db()
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='worker_skills'"
        )
        assert await cursor.fetchone() is not None
        await db.close()

    async def test_two_global_skills_cannot_share_a_name(self):
        db = await _make_db()
        await db.create_skill(name="dup", description="d1", content="c1")
        with pytest.raises(Exception):
            await db.create_skill(name="dup", description="d2", content="c2")
        await db.close()

    async def test_two_different_workers_can_each_have_a_skill_with_the_same_name(self):
        db = await _make_db()
        _, w1 = await _make_swarm_and_worker(db, "w1")
        _, w2 = await _make_swarm_and_worker(db, "w2")
        await db._db.execute(
            "INSERT INTO skills (name, description, content, worker_id) VALUES (?, ?, ?, ?)",
            ("shared-name", "d1", "c1", w1),
        )
        await db._db.execute(
            "INSERT INTO skills (name, description, content, worker_id) VALUES (?, ?, ?, ?)",
            ("shared-name", "d2", "c2", w2),
        )
        await db._db.commit()
        cursor = await db._db.execute("SELECT COUNT(*) as n FROM skills WHERE name = 'shared-name'")
        assert (await cursor.fetchone())["n"] == 2
        await db.close()

    async def test_one_worker_cannot_have_two_skills_with_the_same_name(self):
        db = await _make_db()
        _, w1 = await _make_swarm_and_worker(db)
        await db._db.execute(
            "INSERT INTO skills (name, description, content, worker_id) VALUES (?, ?, ?, ?)",
            ("mine", "d1", "c1", w1),
        )
        await db._db.commit()
        with pytest.raises(Exception):
            await db._db.execute(
                "INSERT INTO skills (name, description, content, worker_id) VALUES (?, ?, ?, ?)",
                ("mine", "d2", "c2", w1),
            )
            await db._db.commit()
        await db.close()

    async def test_deleting_worker_cascades_to_its_private_skills_and_worker_skills_rows(self):
        db = await _make_db()
        _, w1 = await _make_swarm_and_worker(db)
        global_skill_id = await db.create_skill(name="g1", description="d", content="c")
        await db._db.execute(
            "INSERT INTO skills (name, description, content, worker_id) VALUES (?, ?, ?, ?)",
            ("private1", "d", "c", w1),
        )
        await db._db.execute(
            "INSERT INTO worker_skills (worker_id, skill_id) VALUES (?, ?)", (w1, global_skill_id)
        )
        await db._db.commit()

        await db._db.execute("DELETE FROM swarm_workers WHERE id = ?", (w1,))
        await db._db.commit()

        cursor = await db._db.execute("SELECT COUNT(*) as n FROM skills WHERE worker_id = ?", (w1,))
        assert (await cursor.fetchone())["n"] == 0
        cursor = await db._db.execute("SELECT COUNT(*) as n FROM worker_skills WHERE worker_id = ?", (w1,))
        assert (await cursor.fetchone())["n"] == 0
        # The global skill itself must survive — only the link row is gone
        cursor = await db._db.execute("SELECT COUNT(*) as n FROM skills WHERE id = ?", (global_skill_id,))
        assert (await cursor.fetchone())["n"] == 1
        await db.close()


class TestWorkerScopedSkillMethods:
    async def test_create_skill_with_worker_id_is_excluded_from_get_all_skills(self):
        db = await _make_db()
        _, w1 = await _make_swarm_and_worker(db)
        await db.create_skill(name="global1", description="d", content="c")
        await db.create_skill(name="private1", description="d", content="c", worker_id=w1)

        all_skills = await db.get_all_skills()

        names = {s["name"] for s in all_skills}
        assert names == {"global1"}
        await db.close()

    async def test_get_worker_private_skills_returns_only_that_workers_skills(self):
        db = await _make_db()
        _, w1 = await _make_swarm_and_worker(db, "w1")
        _, w2 = await _make_swarm_and_worker(db, "w2")
        await db.create_skill(name="p1", description="d", content="c", worker_id=w1)
        await db.create_skill(name="p2", description="d", content="c", worker_id=w2)

        w1_skills = await db.get_worker_private_skills(w1)

        assert [s["name"] for s in w1_skills] == ["p1"]
        await db.close()

    async def test_enable_and_disable_worker_skill(self):
        db = await _make_db()
        _, w1 = await _make_swarm_and_worker(db)
        skill_id = await db.create_skill(name="g1", description="d", content="c")

        await db.enable_worker_skill(w1, skill_id)
        assert await db.get_worker_enabled_global_skill_ids(w1) == {skill_id}

        await db.disable_worker_skill(w1, skill_id)
        assert await db.get_worker_enabled_global_skill_ids(w1) == set()
        await db.close()

    async def test_enable_worker_skill_is_idempotent(self):
        db = await _make_db()
        _, w1 = await _make_swarm_and_worker(db)
        skill_id = await db.create_skill(name="g1", description="d", content="c")

        await db.enable_worker_skill(w1, skill_id)
        await db.enable_worker_skill(w1, skill_id)  # must not raise (duplicate PK)

        assert await db.get_worker_enabled_global_skill_ids(w1) == {skill_id}
        await db.close()
