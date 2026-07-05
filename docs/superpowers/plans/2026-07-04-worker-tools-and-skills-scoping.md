# Worker Tools & Skills Scoping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a swarm worker's tools and skills (system + private/custom) be configured after the worker exists, from a "Configurar" panel on its card in `/swarms`.

**Architecture:** Tool selection needs zero backend changes (`swarm_workers.allowed_tools` + `PUT /api/swarms/{swarm_id}/workers/{worker_id}` already support it) — only a checkbox-by-category UI. Skills need a schema change: a nullable `worker_id` column on the existing `skills` table (NULL = global, unchanged; set = private to one worker, DB-only — never written to the `./skills/*.md` file-sync path a global skill goes through) plus a `worker_skills` join table recording which *global* skills a given worker has opted into.

**Tech Stack:** Python 3.13, aiosqlite, FastAPI, pytest + pytest-asyncio (auto mode), Next.js/React/TypeScript, TanStack Query.

## Global Constraints

- `_SCHEMA_VERSION` goes from 31 to 32 (`src/openacm/storage/database.py:171`). Migration block follows the exact pattern of the existing Migration 31 (`src/openacm/storage/database.py:924-934`): `if current < 32:` → `executescript` → `await self._db.commit()` → `log.info(...)`.
- Private (worker-scoped) skills MUST NOT go through `SkillManager._save_skill_to_file()` / `_sync_files_to_database()` — those two methods are unaware of `worker_id` and treat every `.md` file under `./skills/` as a global skill to (re)import on next startup. Private skills are DB-only, full stop.
- `SkillManager._refresh_cache()` (`src/openacm/core/skill_manager.py:82-85`) feeds the *global* active-skills prompt used by the main assistant for every conversation. It must never include a private skill — this is enforced by making `Database.get_all_skills()` always filter to `worker_id IS NULL`, so no caller of the existing method needs to change.
- Every new/changed async DB method and API endpoint follows this repo's existing patterns exactly — no new patterns invented. Compare each new method/endpoint against the existing sibling named in its task before writing it.
- A plain composite `UNIQUE(name, worker_id)` constraint is WRONG here — SQL treats `NULL != NULL`, so it would let multiple global skills (`worker_id IS NULL`) share a name. Use two partial unique indexes instead (exact SQL in Task 1).

---

### Task 1: Migration 32 — `skills.worker_id` + `worker_skills` table

**Files:**
- Modify: `src/openacm/storage/database.py:171` (bump `_SCHEMA_VERSION`), `src/openacm/storage/database.py:924-934` area (add migration block after Migration 31, before the "Save new version" block at line 936)
- Test: `tests/unit/test_database_worker_skills.py` (new)

**Interfaces:**
- Produces: `skills.worker_id INTEGER` column (nullable, `REFERENCES swarm_workers(id) ON DELETE CASCADE`); `worker_skills(worker_id INTEGER, skill_id INTEGER, PRIMARY KEY(worker_id, skill_id))` table with both FKs `ON DELETE CASCADE`; two partial unique indexes replacing the old bare `UNIQUE` on `skills.name`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for migration 32 — skills.worker_id + worker_skills table."""
import pytest
from openacm.storage.database import Database


async def _make_db():
    db = Database(":memory:")
    await db.initialize()
    return db


async def _make_swarm_and_worker(db, name="w1"):
    swarm_id = await db.create_swarm(name="Test Swarm", goal="test")
    worker_id = await db.add_swarm_worker(
        swarm_id=swarm_id, name=name, role="worker",
        description="", system_prompt="test prompt",
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
```

Check `Database.create_swarm` and `Database.add_swarm_worker`'s exact signatures before running this — read `src/openacm/storage/database.py` for both (search `async def create_swarm` and `async def add_swarm_worker`) and adjust the test helper's kwargs to match exactly if they differ from above. Do not guess; read the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_database_worker_skills.py -v`
Expected: FAIL — `worker_id` column / `worker_skills` table don't exist yet, and the uniqueness tests fail because the old bare `UNIQUE` constraint doesn't distinguish worker scopes.

- [ ] **Step 3: Write the migration**

In `src/openacm/storage/database.py`, change line 171:

```python
    _SCHEMA_VERSION = 32
```

Then add this block right after the Migration 31 block (after line 934, before the "Save new version" comment at line 936):

```python
        # ── Migration 32: per-worker skill scoping ────────────────────────
        # Adds skills.worker_id (NULL = global system skill, unchanged;
        # set = private to that one swarm worker) and worker_skills (which
        # GLOBAL skills a given worker has enabled). SQLite can't ALTER a
        # UNIQUE constraint in place, so we rebuild skills with the same
        # columns plus worker_id, then replace the bare UNIQUE(name) with
        # two partial unique indexes — a plain composite UNIQUE(name,
        # worker_id) would NOT work here since SQL treats NULL != NULL,
        # which would let multiple global skills share a name.
        if current < 32:
            await self._db.executescript("""
                CREATE TABLE skills_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    is_active INTEGER DEFAULT 1,
                    is_builtin INTEGER DEFAULT 0,
                    worker_id INTEGER REFERENCES swarm_workers(id) ON DELETE CASCADE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO skills_new (id, name, description, content, category, is_active, is_builtin, created_at, updated_at)
                    SELECT id, name, description, content, category, is_active, is_builtin, created_at, updated_at FROM skills;
                DROP TABLE skills;
                ALTER TABLE skills_new RENAME TO skills;

                CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category);
                CREATE INDEX IF NOT EXISTS idx_skills_active ON skills(is_active);
                CREATE INDEX IF NOT EXISTS idx_skills_worker ON skills(worker_id);
                CREATE UNIQUE INDEX idx_skills_name_global ON skills(name) WHERE worker_id IS NULL;
                CREATE UNIQUE INDEX idx_skills_name_per_worker ON skills(name, worker_id) WHERE worker_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS worker_skills (
                    worker_id INTEGER NOT NULL REFERENCES swarm_workers(id) ON DELETE CASCADE,
                    skill_id  INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                    PRIMARY KEY (worker_id, skill_id)
                );
            """)
            await self._db.commit()
            log.info("Migration 32: per-worker skill scoping (skills.worker_id, worker_skills)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_database_worker_skills.py -v`
Expected: PASS (6/6)

- [ ] **Step 5: Run the full existing skills + database test suite to confirm no regression**

Run: `pytest tests/unit/test_database.py tests/unit/plugins/gmail_classifier/ -v -k skill or Skill`

(There is no dedicated `test_skill_manager.py` yet — Task 3 adds one. This step is just a sanity check that rebuilding the `skills` table didn't silently break an existing caller; skim for any failure whose message references a `skills` column.)

- [ ] **Step 6: Commit**

```bash
git add src/openacm/storage/database.py tests/unit/test_database_worker_skills.py
git commit -m "feat(db): add migration 32 — skills.worker_id + worker_skills for per-worker skill scoping"
```

---

### Task 2: Database methods for worker-scoped skills

**Files:**
- Modify: `src/openacm/storage/database.py` — `create_skill` (~line 1296), `get_all_skills` (~line 1337)
- Test: `tests/unit/test_database_worker_skills.py` (extend from Task 1)

**Interfaces:**
- Consumes: schema from Task 1 (`skills.worker_id`, `worker_skills` table).
- Produces: `Database.create_skill(name, description, content, category="general", is_builtin=False, worker_id=None) -> int` (extended signature — `worker_id` is new, defaults preserve every existing caller's behavior); `Database.get_all_skills(active_only=False) -> list[dict]` (now ALWAYS excludes private skills — no signature change, existing callers unaffected since no private skills existed before this feature); `Database.get_worker_private_skills(worker_id) -> list[dict]` (new); `Database.get_worker_enabled_global_skill_ids(worker_id) -> set[int]` (new); `Database.enable_worker_skill(worker_id, skill_id) -> None` (new); `Database.disable_worker_skill(worker_id, skill_id) -> None` (new).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database_worker_skills.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_database_worker_skills.py::TestWorkerScopedSkillMethods -v`
Expected: FAIL — `create_skill()` doesn't accept `worker_id`, `get_worker_private_skills`/`enable_worker_skill`/etc. don't exist, and `get_all_skills()` doesn't filter yet.

- [ ] **Step 3: Implement**

In `src/openacm/storage/database.py`, replace the existing `create_skill` (around line 1296):

```python
    async def create_skill(
        self,
        name: str,
        description: str,
        content: str,
        category: str = "general",
        is_builtin: bool = False,
        worker_id: int | None = None,
    ) -> int:
        """Create a new skill. worker_id=None makes it a global system skill;
        set makes it private to that one swarm worker."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO skills (name, description, content, category, is_builtin, worker_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, description, content, category, int(is_builtin), worker_id),
        )
        await self._db.commit()
        return cursor.lastrowid
```

Replace `get_all_skills` (around line 1337):

```python
    async def get_all_skills(self, active_only: bool = False) -> list[dict[str, Any]]:
        """Get all GLOBAL skills (never includes a worker-private skill)."""
        if not self._db:
            return []
        query = "SELECT * FROM skills WHERE worker_id IS NULL"
        if active_only:
            query += " AND is_active = 1"
        query += " ORDER BY category, name"
        cursor = await self._db.execute(query)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

Add these new methods right after `toggle_skill` (around line 1407, before the `# ─── Settings ─────` comment):

```python
    async def get_worker_private_skills(self, worker_id: int) -> list[dict[str, Any]]:
        """Get a worker's own private skills (worker_id set to it)."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM skills WHERE worker_id = ? ORDER BY category, name",
            (worker_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_worker_enabled_global_skill_ids(self, worker_id: int) -> set[int]:
        """IDs of global skills this worker has opted into."""
        if not self._db:
            return set()
        cursor = await self._db.execute(
            "SELECT skill_id FROM worker_skills WHERE worker_id = ?", (worker_id,)
        )
        rows = await cursor.fetchall()
        return {row["skill_id"] for row in rows}

    async def enable_worker_skill(self, worker_id: int, skill_id: int) -> None:
        """Enable a global skill for a worker. Idempotent."""
        if not self._db:
            return
        await self._db.execute(
            "INSERT OR IGNORE INTO worker_skills (worker_id, skill_id) VALUES (?, ?)",
            (worker_id, skill_id),
        )
        await self._db.commit()

    async def disable_worker_skill(self, worker_id: int, skill_id: int) -> None:
        """Disable a global skill for a worker. Idempotent."""
        if not self._db:
            return
        await self._db.execute(
            "DELETE FROM worker_skills WHERE worker_id = ? AND skill_id = ?",
            (worker_id, skill_id),
        )
        await self._db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_database_worker_skills.py -v`
Expected: PASS (all tests from Task 1 and Task 2)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/storage/database.py tests/unit/test_database_worker_skills.py
git commit -m "feat(db): worker-scoped skill CRUD — create_skill(worker_id=), get_worker_private_skills, enable/disable_worker_skill"
```

---

### Task 3: SkillManager — worker-scoped creation and prompt building

**Files:**
- Modify: `src/openacm/core/skill_manager.py`
- Test: `tests/unit/test_skill_manager_worker_scoping.py` (new)

**Interfaces:**
- Consumes: `Database` methods from Task 2.
- Produces: `SkillManager.create_worker_skill(worker_id, name, description, content, category="custom") -> dict | None` (DB-only, no file write); `SkillManager.generate_worker_skill(worker_id, name, description, use_cases, llm_router) -> dict | None`; `SkillManager.get_active_skills_prompt_for_worker(worker_id, user_message="") -> str`.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for SkillManager's per-worker skill scoping — private skills must
never leak into the global active-skills cache used by every conversation."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from openacm.core.skill_manager import SkillManager
from openacm.storage.database import Database


async def _make_manager():
    db = Database(":memory:")
    await db.initialize()
    manager = SkillManager(db)
    return manager, db


async def _make_worker(db, name="w1"):
    swarm_id = await db.create_swarm(name="Test Swarm", goal="test")
    worker_id = await db.add_swarm_worker(
        swarm_id=swarm_id, name=name, role="worker", description="", system_prompt="test",
    )
    return worker_id


class TestCreateWorkerSkill:
    async def test_creates_a_private_skill_without_writing_a_file(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)  # SKILLS_BASE_DIR is relative ("./skills")
        worker_id = await _make_worker(db)

        skill = await manager.create_worker_skill(
            worker_id=worker_id, name="obj-handling", description="d", content="c",
        )

        assert skill["name"] == "obj-handling"
        assert skill["worker_id"] == worker_id
        assert not (tmp_path / "skills" / "custom" / "obj-handling.md").exists()
        await db.close()

    async def test_private_skill_is_excluded_from_global_get_all_skills(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        worker_id = await _make_worker(db)

        await manager.create_worker_skill(worker_id=worker_id, name="obj-handling", description="d", content="c")

        assert await db.get_all_skills() == []
        await db.close()


class TestGenerateWorkerSkill:
    async def test_generates_content_via_llm_and_saves_it_privately(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        worker_id = await _make_worker(db)
        fake_router = MagicMock()
        fake_router.chat = AsyncMock(return_value={"content": "# Generated content"})

        skill = await manager.generate_worker_skill(
            worker_id=worker_id, name="closing-deals", description="d", use_cases="u",
            llm_router=fake_router,
        )

        assert skill["content"] == "# Generated content"
        assert skill["worker_id"] == worker_id
        fake_router.chat.assert_awaited_once()
        await db.close()


class TestActiveSkillsPromptForWorker:
    async def test_includes_workers_own_active_private_skill(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        worker_id = await _make_worker(db)
        await manager.create_worker_skill(worker_id=worker_id, name="s1", description="d", content="worker-only content")

        prompt = await manager.get_active_skills_prompt_for_worker(worker_id)

        assert "worker-only content" in prompt
        await db.close()

    async def test_includes_enabled_global_skill(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        worker_id = await _make_worker(db)
        global_id = await db.create_skill(name="g1", description="d", content="global content")
        await db.enable_worker_skill(worker_id, global_id)

        prompt = await manager.get_active_skills_prompt_for_worker(worker_id)

        assert "global content" in prompt
        await db.close()

    async def test_excludes_global_skill_not_enabled_for_this_worker(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        worker_id = await _make_worker(db)
        await db.create_skill(name="g1", description="d", content="not enabled content")

        prompt = await manager.get_active_skills_prompt_for_worker(worker_id)

        assert "not enabled content" not in prompt
        await db.close()

    async def test_excludes_inactive_private_skill(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        worker_id = await _make_worker(db)
        skill = await manager.create_worker_skill(worker_id=worker_id, name="s1", description="d", content="inactive content")
        await db.toggle_skill(skill["id"])  # is_active 1 -> 0

        prompt = await manager.get_active_skills_prompt_for_worker(worker_id)

        assert "inactive content" not in prompt
        await db.close()

    async def test_empty_when_worker_has_no_skills(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        worker_id = await _make_worker(db)

        prompt = await manager.get_active_skills_prompt_for_worker(worker_id)

        assert prompt == ""
        await db.close()
```

Read `Database.create_swarm` / `add_swarm_worker`'s actual signatures before running (same note as Task 1) and adjust the `_make_worker` helper if they differ.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_skill_manager_worker_scoping.py -v`
Expected: FAIL — none of `create_worker_skill`/`generate_worker_skill`/`get_active_skills_prompt_for_worker` exist yet.

- [ ] **Step 3: Implement**

In `src/openacm/core/skill_manager.py`, add these three methods after the existing `generate_skill` method (after line 354, its closing `return await self.create_skill(...)`):

```python
    async def create_worker_skill(
        self,
        worker_id: int,
        name: str,
        description: str,
        content: str,
        category: str = "custom",
    ) -> dict[str, Any] | None:
        """Create a skill private to one swarm worker. Unlike create_skill(),
        this never touches the ./skills/ file-sync path — that path treats
        every .md file as a global skill to (re)import on next startup, which
        would silently make a "private" skill global again."""
        skill_id = await self.database.create_skill(
            name=name,
            description=description,
            content=content,
            category=category,
            is_builtin=False,
            worker_id=worker_id,
        )
        return await self.database.get_skill(skill_id)

    async def generate_worker_skill(
        self,
        worker_id: int,
        name: str,
        description: str,
        use_cases: str,
        llm_router=None,
    ) -> dict[str, Any] | None:
        """Generate a private, worker-scoped skill using the LLM — same
        prompt shape as generate_skill(), but saved via create_worker_skill()
        instead of create_skill()."""
        if not llm_router:
            raise ValueError("LLM router required for skill generation")

        prompt = f"""Create a comprehensive skill guide for an AI assistant.

Skill Name: {name}
Description: {description}
Use Cases: {use_cases}

Write the skill content in Markdown format following this structure:

# {name}

## Overview
Brief description of what this skill does.

## Guidelines
Detailed instructions, best practices, and specific patterns to follow.

## Examples
Concrete examples of how to apply this skill.

## Common Pitfalls
What to avoid and why.

Make it practical and actionable. The AI should be able to immediately apply this knowledge.
"""
        response = await llm_router.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        content = response.get("content", "")

        return await self.create_worker_skill(
            worker_id=worker_id,
            name=name,
            description=description,
            content=content,
            category="generated",
        )

    async def get_active_skills_prompt_for_worker(self, worker_id: int, user_message: str = "") -> str:
        """Build a skills prompt for one swarm worker: its own active private
        skills, plus whichever global skills it has enabled. Does not touch
        self._active_skills / self._skills_cache — those are the main
        assistant's global-only cache."""
        private_skills = [s for s in await self.database.get_worker_private_skills(worker_id) if s["is_active"]]

        enabled_ids = await self.database.get_worker_enabled_global_skill_ids(worker_id)
        global_skills = await self.database.get_all_skills(active_only=True)
        enabled_global_skills = [s for s in global_skills if s["id"] in enabled_ids]

        combined = private_skills + enabled_global_skills
        if not combined:
            return ""

        sections = [f"## {s['name']}\n\n{s['content']}" for s in combined]
        return MSG_SKILL_CONTEXT_HEADER + "\n\n".join(sections) + MSG_SKILL_CONTEXT_FOOTER
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_skill_manager_worker_scoping.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/skill_manager.py tests/unit/test_skill_manager_worker_scoping.py
git commit -m "feat(skills): SkillManager.create_worker_skill/generate_worker_skill/get_active_skills_prompt_for_worker"
```

---

### Task 4: API endpoints — worker skills

**Files:**
- Modify: `src/openacm/web/routers/swarms.py`
- Test: `tests/unit/test_swarms_worker_skills_api.py` (new)

**Interfaces:**
- Consumes: `SkillManager` methods from Task 3, `Database.get_worker_private_skills`/`get_worker_enabled_global_skill_ids`/`enable_worker_skill`/`disable_worker_skill` from Task 2.
- Produces: `GET /api/swarms/{swarm_id}/workers/{worker_id}/skills`, `POST /api/swarms/{swarm_id}/workers/{worker_id}/skills/{skill_id}`, `DELETE /api/swarms/{swarm_id}/workers/{worker_id}/skills/{skill_id}`, `POST /api/swarms/{swarm_id}/workers/{worker_id}/skills/generate`.

Read `src/openacm/web/routers/swarms.py:358-369` (`update_swarm_worker`) first for the exact `_state.database` / `HTTPException` conventions this file uses, and `src/openacm/web/routers/skills.py:98-114` (`generate_skill`) for the generate-endpoint error-handling convention — match both exactly.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for per-worker skill API endpoints under the swarms router."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from openacm.web.routers import swarms as swarms_router
from openacm.web.state import _state


@pytest.fixture
def app_client():
    app = FastAPI()
    swarms_router.register_routes(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _mock_brain(monkeypatch):
    db = MagicMock()
    db.get_all_skills = AsyncMock(return_value=[
        {"id": 1, "name": "g1", "description": "d", "content": "c", "category": "general", "is_active": 1, "is_builtin": 0, "worker_id": None},
    ])
    db.get_worker_private_skills = AsyncMock(return_value=[
        {"id": 2, "name": "p1", "description": "d", "content": "c", "category": "custom", "is_active": 1, "is_builtin": 0, "worker_id": 42},
    ])
    db.get_worker_enabled_global_skill_ids = AsyncMock(return_value={1})
    db.enable_worker_skill = AsyncMock()
    db.disable_worker_skill = AsyncMock()
    monkeypatch.setattr(_state, "database", db)

    skill_manager = MagicMock()
    skill_manager.generate_worker_skill = AsyncMock(return_value={"id": 3, "name": "gen1", "worker_id": 42})
    brain = MagicMock()
    brain.skill_manager = skill_manager
    brain.llm_router = MagicMock()
    monkeypatch.setattr(_state, "brain", brain)
    yield db, skill_manager
    monkeypatch.setattr(_state, "database", None)
    monkeypatch.setattr(_state, "brain", None)


class TestGetWorkerSkills:
    async def test_returns_global_skills_annotated_and_private_skills(self, app_client, _mock_brain):
        async with app_client as ac:
            resp = await ac.get("/api/swarms/1/workers/42/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["global_skills"] == [
            {"id": 1, "name": "g1", "description": "d", "content": "c", "category": "general", "is_active": 1, "is_builtin": 0, "worker_id": None, "enabled": True}
        ]
        assert body["private_skills"][0]["name"] == "p1"


class TestEnableDisableWorkerSkill:
    async def test_enable_calls_database(self, app_client, _mock_brain):
        db, _ = _mock_brain
        async with app_client as ac:
            resp = await ac.post("/api/swarms/1/workers/42/skills/1")
        assert resp.status_code == 200
        db.enable_worker_skill.assert_awaited_once_with(42, 1)

    async def test_disable_calls_database(self, app_client, _mock_brain):
        db, _ = _mock_brain
        async with app_client as ac:
            resp = await ac.delete("/api/swarms/1/workers/42/skills/1")
        assert resp.status_code == 200
        db.disable_worker_skill.assert_awaited_once_with(42, 1)


class TestGenerateWorkerSkill:
    async def test_generates_and_returns_the_skill(self, app_client, _mock_brain):
        _, skill_manager = _mock_brain
        async with app_client as ac:
            resp = await ac.post(
                "/api/swarms/1/workers/42/skills/generate",
                json={"name": "gen1", "description": "d", "use_cases": "u"},
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "gen1"
        skill_manager.generate_worker_skill.assert_awaited_once_with(
            worker_id=42, name="gen1", description="d", use_cases="u", llm_router=skill_manager.generate_worker_skill.await_args.kwargs["llm_router"],
        )

    async def test_no_brain_503s(self, app_client, monkeypatch):
        monkeypatch.setattr(_state, "brain", None)
        async with app_client as ac:
            resp = await ac.post(
                "/api/swarms/1/workers/42/skills/generate",
                json={"name": "gen1", "description": "d"},
            )
        assert resp.status_code == 503
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_swarms_worker_skills_api.py -v`
Expected: FAIL — 404s, the endpoints don't exist yet.

- [ ] **Step 3: Implement**

In `src/openacm/web/routers/swarms.py`, add these four endpoints right after the existing `update_swarm_worker` endpoint (after line 369):

```python
    @app.get("/api/swarms/{swarm_id}/workers/{worker_id}/skills")
    async def get_worker_skills(swarm_id: int, worker_id: int):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        global_skills = await _state.database.get_all_skills()
        enabled_ids = await _state.database.get_worker_enabled_global_skill_ids(worker_id)
        annotated = [{**s, "enabled": s["id"] in enabled_ids} for s in global_skills]
        private_skills = await _state.database.get_worker_private_skills(worker_id)
        return {"global_skills": annotated, "private_skills": private_skills}

    @app.post("/api/swarms/{swarm_id}/workers/{worker_id}/skills/{skill_id}")
    async def enable_worker_skill(swarm_id: int, worker_id: int, skill_id: int):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        await _state.database.enable_worker_skill(worker_id, skill_id)
        return {"status": "ok", "enabled": True}

    @app.delete("/api/swarms/{swarm_id}/workers/{worker_id}/skills/{skill_id}")
    async def disable_worker_skill(swarm_id: int, worker_id: int, skill_id: int):
        if not _state.database:
            raise HTTPException(503, "Database not available")
        await _state.database.disable_worker_skill(worker_id, skill_id)
        return {"status": "ok", "enabled": False}

    @app.post("/api/swarms/{swarm_id}/workers/{worker_id}/skills/generate")
    async def generate_worker_skill_endpoint(swarm_id: int, worker_id: int, request: Request):
        if not _state.brain or not _state.brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        data = await request.json()
        try:
            skill = await _state.brain.skill_manager.generate_worker_skill(
                worker_id=worker_id,
                name=data["name"],
                description=data["description"],
                use_cases=data.get("use_cases", ""),
                llm_router=_state.brain.llm_router,
            )
            return skill
        except Exception as e:
            log.error("Failed to generate worker skill", error=str(e))
            raise HTTPException(status_code=500, detail="Failed to generate skill")
```

Confirm `Request` and `HTTPException` are already imported at the top of `swarms.py` (they should be, since the file already uses `Request` in `update_swarm_worker`) — if `Request` isn't imported, add it to the existing `fastapi` import line.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_swarms_worker_skills_api.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/web/routers/swarms.py tests/unit/test_swarms_worker_skills_api.py
git commit -m "feat(api): worker skill endpoints — get/enable/disable global, generate private"
```

---

### Task 5: Expose tool category in `GET /api/tools`

**Files:**
- Modify: `src/openacm/web/routers/system.py:360-373`
- Test: `tests/unit/test_system_tools_api.py` (new, or extend an existing one if `tests/unit/test_system_api.py` already covers `/api/tools` — check first with `grep -rl "api/tools" tests/`)

**Interfaces:**
- Produces: `GET /api/tools` response items now include `"category": str` (additive — no existing field removed or renamed).

- [ ] **Step 1: Write the failing test**

Run `grep -rl "api/tools" tests/` first. If a file already tests this endpoint, add the test there instead of creating a new file; otherwise create `tests/unit/test_system_tools_api.py`:

```python
"""Test GET /api/tools includes each tool's category."""
from unittest.mock import MagicMock
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from openacm.web.routers import system as system_router
from openacm.web.state import _state


@pytest.fixture
def app_client():
    app = FastAPI()
    system_router.register_routes(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_get_tools_includes_category(app_client, monkeypatch):
    tool = MagicMock()
    tool.name = "ha_control"
    tool.description = "control devices"
    tool.risk_level = "low"
    tool.parameters = {}
    tool.category = "iot"

    registry = MagicMock()
    registry.tools = {"ha_control": tool}
    monkeypatch.setattr(_state, "tool_registry", registry)

    async with app_client as ac:
        resp = await ac.get("/api/tools")

    assert resp.status_code == 200
    assert resp.json()[0]["category"] == "iot"
    monkeypatch.setattr(_state, "tool_registry", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_system_tools_api.py -v`
Expected: FAIL — `category` key missing from the response.

- [ ] **Step 3: Implement**

In `src/openacm/web/routers/system.py`, update the `get_tools` endpoint (line 360-373):

```python
    @app.get("/api/tools")
    async def get_tools():
        """List available tools."""
        if not _state.tool_registry:
            return []
        return [
            {
                "name": t.name,
                "description": t.description,
                "risk_level": t.risk_level,
                "parameters": t.parameters,
                "category": t.category,
            }
            for t in _state.tool_registry.tools.values()
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_system_tools_api.py -v`
Expected: PASS

- [ ] **Step 5: Run the full existing test suite to confirm no regression**

Run: `pytest -q`
Expected: same pass/fail counts as before this task (any pre-existing failures unrelated to this change — e.g. in `gmail_classifier` tests — are not this task's concern; do not fix them here).

- [ ] **Step 6: Commit**

```bash
git add src/openacm/web/routers/system.py tests/unit/test_system_tools_api.py
git commit -m "feat(api): include tool category in GET /api/tools response"
```

---

### Task 6: Frontend — "Configurar" panel, Tools tab

**Files:**
- Create: `frontend/hooks/use-worker-config.ts`
- Modify: `frontend/app/swarms/page.tsx` (the `WorkerCard` component, lines 321-415, and its `Worker` interface at lines 33-44 stays as-is — no new fields needed there)

**Interfaces:**
- Consumes: `GET /api/tools` (Task 5, now includes `category`), existing `PUT /api/swarms/{swarm_id}/workers/{worker_id}` (unchanged, already accepts `allowed_tools`).
- Produces: `useTools()` hook returning `{name, description, risk_level, category}[]`; `useUpdateWorkerTools(swarmId, workerId)` mutation; a `<ToolsTab>` component used inside `WorkerCard`'s new "Configurar" panel.

- [ ] **Step 1: Add the tools-listing hook**

Create `frontend/hooks/use-worker-config.ts`:

```typescript
'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

export interface ToolInfo {
  name: string;
  description: string;
  risk_level: string;
  category: string;
}

export function useTools() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<ToolInfo[]>({
    queryKey: ['tools'],
    queryFn: () => fetchAPI('/api/tools'),
    enabled: isAuthenticated,
    staleTime: 5 * 60_000, // tool list rarely changes within a session
  });
}

export function useUpdateWorkerTools(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (allowedTools: string) =>
      fetchAPI(`/api/swarms/${swarmId}/workers/${workerId}`, {
        method: 'PUT',
        body: JSON.stringify({ allowed_tools: allowedTools }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['swarm', swarmId] }),
  });
}

/** allowed_tools is stored as "all" | "none" | a JSON array string of tool names. */
export function parseAllowedTools(allowedTools: string, allToolNames: string[]): Set<string> {
  if (allowedTools === 'all') return new Set(allToolNames);
  if (allowedTools === 'none') return new Set();
  try {
    const parsed = JSON.parse(allowedTools);
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

/** Inverse of parseAllowedTools — collapses back to "all"/"none" when applicable. */
export function serializeAllowedTools(selected: Set<string>, allToolNames: string[]): string {
  if (selected.size === 0) return 'none';
  if (selected.size === allToolNames.length) return 'all';
  return JSON.stringify(Array.from(selected));
}
```

- [ ] **Step 2: Add the Tools tab component and wire "Configurar" into WorkerCard**

In `frontend/app/swarms/page.tsx`, add these imports near the top (after the existing `MessageBubble` import at line 18):

```typescript
import { useTools, useUpdateWorkerTools, parseAllowedTools, serializeAllowedTools } from '@/hooks/use-worker-config';
import { Settings, Search } from 'lucide-react';
```

Add a new component right before `// ─── Worker Card ───` (before line 321):

```typescript
function ToolsTab({ worker, swarmId }: { worker: Worker; swarmId: number }) {
  const { data: tools, isLoading } = useTools();
  const updateTools = useUpdateWorkerTools(swarmId, worker.id);
  const [search, setSearch] = useState('');
  const allNames = (tools ?? []).map(t => t.name);
  const [selected, setSelected] = useState<Set<string>>(() => parseAllowedTools(worker.allowed_tools, allNames));

  if (isLoading || !tools) return <Loader2 size={16} className="animate-spin" />;

  const filtered = tools.filter(t =>
    !search || t.name.toLowerCase().includes(search.toLowerCase()) || t.category.toLowerCase().includes(search.toLowerCase())
  );
  const byCategory: Record<string, ToolInfoLike[]> = {};
  for (const t of filtered) (byCategory[t.category] ??= []).push(t);

  const toggle = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const save = () => updateTools.mutate(serializeAllowedTools(selected, allNames));

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded px-2 py-1">
        <Search size={12} className="text-[var(--acm-fg-4)]" />
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Buscar herramienta o categoría..."
          className="flex-1 bg-transparent text-[11px] text-[var(--acm-fg)] focus:outline-none mono"
        />
      </div>
      <div className="max-h-60 overflow-auto flex flex-col gap-2">
        {Object.entries(byCategory).map(([category, catTools]) => (
          <div key={category}>
            <div className="label text-[var(--acm-fg-4)] mb-1">{category}</div>
            {catTools.map(t => (
              <label key={t.name} className="flex items-center gap-2 py-0.5 text-[11px] text-[var(--acm-fg-2)] cursor-pointer">
                <input type="checkbox" checked={selected.has(t.name)} onChange={() => toggle(t.name)} />
                <span className="mono">{t.name}</span>
              </label>
            ))}
          </div>
        ))}
      </div>
      <button onClick={save} disabled={updateTools.isPending} className="btn-secondary self-end text-[11px] px-2 py-1">
        {updateTools.isPending ? 'Guardando...' : 'Guardar herramientas'}
      </button>
    </div>
  );
}
```

Add `type ToolInfoLike = { name: string; category: string };` near the top of the file with the other interfaces (after the `Task` interface, line 55), or just import `ToolInfo` from the hook and use it directly in place of `ToolInfoLike` — prefer that; remove the `ToolInfoLike` alias and use `import type { ToolInfo } from '@/hooks/use-worker-config'` instead, typing `byCategory: Record<string, ToolInfo[]>`.

In `WorkerCard`, add a `configOpen` state and the "Configurar" toggle button, right after the existing "System prompt" toggle button (after line 407, before the closing `{expanded && (...)}` block ends at line 412 — insert after that whole block):

```typescript
      <button
        onClick={() => setConfigOpen(v => !v)}
        className="flex items-center gap-1 text-[10px] text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-3)] transition-colors"
      >
        <Settings size={11} />
        <span className="label">Configurar</span>
      </button>
      {configOpen && <ToolsTab worker={worker} swarmId={swarmId} />}
```

And declare the new state alongside the existing `expanded` state (line 327):

```typescript
  const [configOpen, setConfigOpen] = useState(false);
```

- [ ] **Step 3: Manual verification**

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors.

Start the dev server (`npm run dev` in `frontend/`), open `/swarms`, open a swarm with at least one worker, click "Configurar" on a worker card, confirm the tool checkboxes render grouped by category, confirm the search filter narrows the list, check/uncheck a couple, click "Guardar herramientas", refresh the page, re-open "Configurar" and confirm the same tools are still checked (persisted via the existing `PUT` endpoint).

- [ ] **Step 4: Commit**

```bash
git add frontend/hooks/use-worker-config.ts frontend/app/swarms/page.tsx
git commit -m "feat(swarms): Configurar panel with per-worker tool selection (checkbox by category + search)"
```

---

### Task 7: Frontend — Skills tab

**Files:**
- Modify: `frontend/hooks/use-worker-config.ts` (add skill hooks)
- Modify: `frontend/app/swarms/page.tsx` (add `<SkillsTab>`, a tab switcher in the Configurar panel)

**Interfaces:**
- Consumes: the four endpoints from Task 4.
- Produces: `useWorkerSkills(swarmId, workerId)`, `useEnableWorkerSkill`/`useDisableWorkerSkill`, `useGenerateWorkerSkill` hooks; a `<SkillsTab>` component; a tab switcher ("Herramientas" | "Skills") inside the Configurar panel added in Task 6.

- [ ] **Step 1: Add skill hooks**

Append to `frontend/hooks/use-worker-config.ts`:

```typescript
export interface WorkerSkill {
  id: number;
  name: string;
  description: string;
  content: string;
  category: string;
  is_active: number;
  is_builtin: number;
  worker_id: number | null;
  enabled?: boolean; // present only on global_skills entries
}

export function useWorkerSkills(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<{ global_skills: WorkerSkill[]; private_skills: WorkerSkill[] }>({
    queryKey: ['worker-skills', swarmId, workerId],
    queryFn: () => fetchAPI(`/api/swarms/${swarmId}/workers/${workerId}/skills`),
    enabled: isAuthenticated,
  });
}

export function useToggleWorkerGlobalSkill(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ skillId, enable }: { skillId: number; enable: boolean }) =>
      fetchAPI(`/api/swarms/${swarmId}/workers/${workerId}/skills/${skillId}`, {
        method: enable ? 'POST' : 'DELETE',
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['worker-skills', swarmId, workerId] }),
  });
}

export function useGenerateWorkerSkill(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; description: string; use_cases: string }) =>
      fetchAPI(`/api/swarms/${swarmId}/workers/${workerId}/skills/generate`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['worker-skills', swarmId, workerId] }),
  });
}

export function useToggleWorkerPrivateSkill(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (skillId: number) => fetchAPI(`/api/skills/${skillId}/toggle`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['worker-skills', swarmId, workerId] }),
  });
}

export function useDeleteWorkerPrivateSkill(swarmId: number, workerId: number) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (skillId: number) => fetchAPI(`/api/skills/${skillId}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['worker-skills', swarmId, workerId] }),
  });
}
```

- [ ] **Step 2: Add the Skills tab component**

In `frontend/app/swarms/page.tsx`, add near `ToolsTab`:

```typescript
function SkillsTab({ worker, swarmId }: { worker: Worker; swarmId: number }) {
  const { data, isLoading } = useWorkerSkills(swarmId, worker.id);
  const toggleGlobal = useToggleWorkerGlobalSkill(swarmId, worker.id);
  const togglePrivate = useToggleWorkerPrivateSkill(swarmId, worker.id);
  const deletePrivate = useDeleteWorkerPrivateSkill(swarmId, worker.id);
  const generate = useGenerateWorkerSkill(swarmId, worker.id);
  const [showGenerateForm, setShowGenerateForm] = useState(false);
  const [genName, setGenName] = useState('');
  const [genDescription, setGenDescription] = useState('');
  const [genUseCases, setGenUseCases] = useState('');

  if (isLoading || !data) return <Loader2 size={16} className="animate-spin" />;

  const submitGenerate = () => {
    generate.mutate(
      { name: genName, description: genDescription, use_cases: genUseCases },
      { onSuccess: () => { setShowGenerateForm(false); setGenName(''); setGenDescription(''); setGenUseCases(''); } },
    );
  };

  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="label text-[var(--acm-fg-4)] mb-1">Skills del sistema</div>
        {data.global_skills.map(s => (
          <label key={s.id} className="flex items-center gap-2 py-0.5 text-[11px] text-[var(--acm-fg-2)] cursor-pointer">
            <input
              type="checkbox"
              checked={!!s.enabled}
              onChange={() => toggleGlobal.mutate({ skillId: s.id, enable: !s.enabled })}
            />
            <span>{s.name}</span>
          </label>
        ))}
      </div>

      <div className="border-t border-[var(--acm-border)] pt-2">
        <div className="label text-[var(--acm-fg-4)] mb-1">Skills de este worker</div>
        {data.private_skills.map(s => (
          <div key={s.id} className="flex items-center gap-2 py-0.5 text-[11px] text-[var(--acm-fg-2)]">
            <input type="checkbox" checked={!!s.is_active} onChange={() => togglePrivate.mutate(s.id)} />
            <span className="flex-1">{s.name}</span>
            <button onClick={() => deletePrivate.mutate(s.id)} className="text-[var(--acm-fg-4)] hover:text-[var(--acm-err)]">
              <Trash2 size={11} />
            </button>
          </div>
        ))}

        {showGenerateForm ? (
          <div className="flex flex-col gap-1 mt-2">
            <input value={genName} onChange={e => setGenName(e.target.value)} placeholder="Nombre"
              className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded px-2 py-1 text-[11px]" />
            <input value={genDescription} onChange={e => setGenDescription(e.target.value)} placeholder="Descripción"
              className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded px-2 py-1 text-[11px]" />
            <input value={genUseCases} onChange={e => setGenUseCases(e.target.value)} placeholder="Casos de uso"
              className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded px-2 py-1 text-[11px]" />
            <div className="flex gap-1 justify-end">
              <button onClick={() => setShowGenerateForm(false)} className="btn-secondary text-[11px] px-2 py-1">Cancelar</button>
              <button onClick={submitGenerate} disabled={generate.isPending || !genName} className="btn-secondary text-[11px] px-2 py-1">
                {generate.isPending ? 'Generando...' : 'Generar'}
              </button>
            </div>
          </div>
        ) : (
          <button onClick={() => setShowGenerateForm(true)} className="btn-secondary text-[11px] px-2 py-1 mt-2">
            + Nueva skill personalizada
          </button>
        )}
      </div>
    </div>
  );
}
```

Add the corresponding hook imports to the existing import line from Task 6:

```typescript
import { useTools, useUpdateWorkerTools, parseAllowedTools, serializeAllowedTools, useWorkerSkills, useToggleWorkerGlobalSkill, useToggleWorkerPrivateSkill, useDeleteWorkerPrivateSkill, useGenerateWorkerSkill } from '@/hooks/use-worker-config';
```

- [ ] **Step 3: Add the tab switcher in WorkerCard**

Replace the single `{configOpen && <ToolsTab worker={worker} swarmId={swarmId} />}` line added in Task 6 with a tab switcher:

```typescript
      {configOpen && (
        <div className="flex flex-col gap-2 border-t border-[var(--acm-border)] pt-2">
          <div className="flex gap-2">
            <button
              onClick={() => setConfigTab('tools')}
              className={`label px-2 py-1 rounded ${configTab === 'tools' ? 'bg-[var(--acm-elev)] text-[var(--acm-fg)]' : 'text-[var(--acm-fg-4)]'}`}
            >
              Herramientas
            </button>
            <button
              onClick={() => setConfigTab('skills')}
              className={`label px-2 py-1 rounded ${configTab === 'skills' ? 'bg-[var(--acm-elev)] text-[var(--acm-fg)]' : 'text-[var(--acm-fg-4)]'}`}
            >
              Skills
            </button>
          </div>
          {configTab === 'tools' ? <ToolsTab worker={worker} swarmId={swarmId} /> : <SkillsTab worker={worker} swarmId={swarmId} />}
        </div>
      )}
```

And add the new state next to `configOpen`:

```typescript
  const [configTab, setConfigTab] = useState<'tools' | 'skills'>('tools');
```

- [ ] **Step 4: Manual verification**

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors.

With the dev server running: open "Configurar" on a worker, switch to the "Skills" tab, confirm global skills list with checkboxes, toggle one on/off and confirm it persists across a page refresh. Click "+ Nueva skill personalizada", fill in name/description/use cases, submit, confirm it appears under "Skills de este worker" once generation completes (this calls the real LLM router — expect it to take a few seconds). Toggle its active checkbox off/on and delete it, confirming each persists.

- [ ] **Step 5: Commit**

```bash
git add frontend/hooks/use-worker-config.ts frontend/app/swarms/page.tsx
git commit -m "feat(swarms): Skills tab in Configurar panel — enable global skills, create/manage private ones"
```

---

### Task 8: Wire per-worker skills into swarm execution

**Files:**
- Modify: `src/openacm/core/swarm_manager.py` — `__init__` (line 48), `_build_worker_system_prompt` (line 1910), and its two call sites (lines 1073, 1325)
- Modify: `src/openacm/app.py` — the `SwarmManager(...)` construction call (line 472)
- Test: `tests/unit/test_swarm_manager_worker_skills.py` (new)

**Interfaces:**
- Consumes: `SkillManager.get_active_skills_prompt_for_worker` from Task 3.
- Produces: `SwarmManager.__init__` gains a `skill_manager` param; `_build_worker_system_prompt(self, worker, swarm, all_workers, skills_prompt: str = "")` — new trailing param, appended to the returned prompt the same way `brain_prompt.py:70-72` appends the main assistant's skills prompt (`system_prompt = f"{system_prompt}\n\n{skills_prompt}"`, only when non-empty).

This mirrors the existing pattern exactly: `core/brain_prompt.py:69-72` already does
```python
if self.skill_manager:
    skills_prompt = await self.skill_manager.get_active_skills_prompt(content)
    if skills_prompt:
        system_prompt = f"{system_prompt}\n\n{skills_prompt}"
```
for the main assistant. `app.py:230` already constructs `self.skill_manager = SkillManager(self.database)` well before `app.py:472`'s `SwarmManager(...)` call, so it's available to pass in.

- [ ] **Step 1: Write the failing test**

`_build_worker_system_prompt` is a plain synchronous, side-effect-free method — test it directly without constructing a full `SwarmManager` with live dependencies:

```python
"""Test that _build_worker_system_prompt includes a worker's skills prompt
when one is provided, and is unaffected when it isn't (existing behavior)."""
from unittest.mock import MagicMock
from openacm.core.swarm_manager import SwarmManager


def _make_manager():
    return SwarmManager(
        database=MagicMock(), llm_router=MagicMock(), tool_registry=MagicMock(),
        memory=MagicMock(), event_bus=MagicMock(), skill_manager=MagicMock(),
    )


WORKER = {"id": 1, "name": "w1", "role": "worker", "description": "d",
          "system_prompt": "Base prompt.", "workspace_path": "/tmp/ws"}
SWARM = {"goal": "test goal", "working_path": None}


class TestBuildWorkerSystemPromptWithSkills:
    def test_appends_skills_prompt_when_provided(self):
        manager = _make_manager()

        result = manager._build_worker_system_prompt(WORKER, SWARM, [WORKER], skills_prompt="## my-skill\n\ndo the thing")

        assert "## my-skill" in result
        assert "do the thing" in result

    def test_no_skills_prompt_leaves_output_unchanged_from_before(self):
        manager = _make_manager()

        with_empty = manager._build_worker_system_prompt(WORKER, SWARM, [WORKER], skills_prompt="")
        with_default = manager._build_worker_system_prompt(WORKER, SWARM, [WORKER])

        assert with_empty == with_default
        assert "Base prompt." in with_empty
```

Read `SwarmManager.__init__`'s exact current parameter list at `src/openacm/core/swarm_manager.py:48` before running this — if any of `database`/`llm_router`/`tool_registry`/`memory`/`event_bus` differ from what's shown here, adjust `_make_manager()` to match exactly (this test must add `skill_manager` as a NEW kwarg to whatever the existing signature already is, not replace it).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_swarm_manager_worker_skills.py -v`
Expected: FAIL — `SwarmManager.__init__()` doesn't accept `skill_manager` yet, and `_build_worker_system_prompt` doesn't accept `skills_prompt` yet.

- [ ] **Step 3: Implement**

In `src/openacm/core/swarm_manager.py`, update `__init__` (line 48):

```python
    def __init__(self, database, llm_router, tool_registry, memory, event_bus, skill_manager=None):
        self.db = database
```

(keep every other line inside `__init__` exactly as-is — only the signature and one new line change)

Add right after the existing `self.tool_registry = tool_registry` assignment (line 51):

```python
        self.skill_manager = skill_manager
```

Update `_build_worker_system_prompt`'s signature (line 1910-1912):

```python
    def _build_worker_system_prompt(
        self, worker: dict, swarm: dict, all_workers: list[dict], skills_prompt: str = ""
    ) -> str:
```

And change its `return` statement (line 1932) from `return (\n f"{worker['system_prompt']}\n\n"` to build the base prompt first, then append:

```python
        base_prompt = worker["system_prompt"]
        if skills_prompt:
            base_prompt = f"{base_prompt}\n\n{skills_prompt}"

        return (
            f"{base_prompt}\n\n"
            f"---\n"
```

(everything else in the f-string after `f"---\n"` stays exactly as it already is — only the first line changes from `f"{worker['system_prompt']}\n\n"` to `f"{base_prompt}\n\n"`, fed by the two new lines above it)

Now update both call sites. At line 1073, change:

```python
            system_prompt = self._build_worker_system_prompt(worker, swarm, all_workers)
```

to:

```python
            skills_prompt = ""
            if self.skill_manager:
                skills_prompt = await self.skill_manager.get_active_skills_prompt_for_worker(worker["id"])
            system_prompt = self._build_worker_system_prompt(worker, swarm, all_workers, skills_prompt)
```

At line 1325, change:

```python
                system_prompt=self._build_worker_system_prompt(worker, swarm, all_workers),
```

to (this one is inside a dict-literal argument list, so compute the value on its own line just above the `config = AssistantConfig(` block that starts at line 1323):

```python
            worker_skills_prompt = ""
            if self.skill_manager:
                worker_skills_prompt = await self.skill_manager.get_active_skills_prompt_for_worker(worker["id"])

            config = AssistantConfig(
                name=worker["name"],
                system_prompt=self._build_worker_system_prompt(worker, swarm, all_workers, worker_skills_prompt),
```

In `src/openacm/app.py`, update the `SwarmManager(...)` call (line 472-478):

```python
            self._swarm_manager = SwarmManager(
                database=self.database,
                llm_router=self.llm_router,
                tool_registry=self.tool_registry,
                memory=self.memory,
                event_bus=self.event_bus,
                skill_manager=self.skill_manager,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_swarm_manager_worker_skills.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: no new failures beyond whatever pre-existing ones were already there before this plan (5 failed + 7 errors in `gmail_classifier` tests are pre-existing and unrelated — do not fix them as part of this task).

- [ ] **Step 6: Commit**

```bash
git add src/openacm/core/swarm_manager.py src/openacm/app.py tests/unit/test_swarm_manager_worker_skills.py
git commit -m "feat(swarms): inject each worker's active skills (private + enabled-global) into its turn"
```

---

## Post-plan manual smoke test (end to end)

After all 8 tasks are merged, manually verify the whole feature end to end (not covered by any single task's automated test, since it spans backend + frontend + a real swarm run):

1. Create or open an existing swarm with at least one worker.
2. Open "Configurar" → "Herramientas", uncheck everything except 2-3 tools, save.
3. Switch to "Skills", enable one global skill, create a new private skill via "+ Nueva skill personalizada" with a distinctive instruction (e.g. "always end every response with the exact string ZXQ123").
4. Trigger that worker to run (send it a task/message through whatever the swarm's normal trigger path is).
5. Confirm its response contains "ZXQ123" (proves the private skill reached its prompt) and that its trace/tool-call log only ever calls the 2-3 tools you left checked (proves `allowed_tools` is actually enforced — this part already worked before this plan, but confirm the new UI didn't desync it).
