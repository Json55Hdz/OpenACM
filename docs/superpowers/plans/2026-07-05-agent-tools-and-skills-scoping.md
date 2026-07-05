# Agent Tools & Skills Scoping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an Agent's tools and skills (system + private/custom) be configured after the agent exists, from an in-place "detail view" that replaces the `/agents` grid when an agent is selected.

**Architecture:** Tool selection needs zero backend changes (`agents.allowed_tools` + `PUT /api/agents/{id}` already support "all"/"none"/a JSON array, exactly like the already-shipped Swarms feature — only a checkbox-by-category UI is new). Skills need a schema change: a nullable `agent_id` column on the existing `skills` table, added as a **new column parallel to** the already-shipped `worker_id` column (not a modification of it), plus an `agent_skills` join table mirroring `worker_skills` exactly. The frontend converts the existing agent-editing experience from a small overlay modal to an in-place "detail view" that takes over the page's content area (with an ✕ to return to the grid), adding two new tabs (Herramientas, Skills) alongside the three that already exist (Config, Knowledge, Channels).

**Tech Stack:** Python 3.13, aiosqlite, FastAPI, pytest + pytest-asyncio (auto mode), Next.js/React/TypeScript, TanStack Query.

## Global Constraints

- `_SCHEMA_VERSION` goes from 32 to 33 (`src/openacm/storage/database.py:171`). Migration block follows the exact existing pattern (`if current < 33:` → statements → `await self._db.commit()` → `log.info(...)`), placed after the Migration 32 block (ends at `database.py:977`, right before the "Save new version" comment at line 979).
- The `skills.agent_id` column is a **new column added via plain `ALTER TABLE ... ADD COLUMN`** — unlike Migration 32 (which needed a full table rebuild to change the `UNIQUE` constraint shape), this migration only needs a rebuild-free `ALTER TABLE ADD COLUMN` for the column itself, plus dropping/recreating exactly one existing index. Do NOT rebuild the `skills` table again.
- A skill row is never both worker-scoped and agent-scoped — `worker_id` and `agent_id` are mutually exclusive by construction (every call site that creates a skill passes at most one of them). This is an application-layer invariant, not a DB constraint — no task should add a `CHECK` constraint for this; just don't write code that would ever set both.
- Every new DB method/pattern mirrors its already-shipped worker equivalent exactly (same guard style, same idempotency, same return shapes) — the worker versions were already reviewed and approved; do not deviate without a reason.
- Private (agent-scoped) skills MUST NOT go through `SkillManager._save_skill_to_file()` / `_sync_files_to_database()`, for the same reason as worker-scoped skills: those methods have no concept of ownership and would treat a private skill's `.md` file as globally importable on next startup.
- `SkillManager._refresh_cache()` (feeds the *global* active-skills prompt used by the main assistant for every conversation) must never include an agent-scoped skill — enforced by extending `Database.get_all_skills()`'s existing `WHERE worker_id IS NULL` filter to also require `agent_id IS NULL`.
- Frontend: the existing `AgentFormModal` component (`frontend/app/agents/page.tsx:628-987`) is used **only for creating a new agent** going forward — it currently branches on `isEditing` to also handle edits with a full tab bar; that branching is removed. A **new** component, `AgentDetailView`, owns the full experience for an *existing* agent (Config/Knowledge/Channels — moved over unchanged — plus new Herramientas/Skills tabs), and renders **in place of** the agent grid (not as a `fixed inset-0` overlay) when an agent is selected, with its own ✕ control that returns to the grid.

---

### Task 1: Migration 33 — `skills.agent_id` + `agent_skills` table

**Files:**
- Modify: `src/openacm/storage/database.py:171` (bump `_SCHEMA_VERSION`), add a new migration block after line 977 (end of the Migration 32 block), before the "Save new version" comment at line 979
- Test: `tests/unit/test_database_agent_skills.py` (new)

**Interfaces:**
- Produces: `skills.agent_id INTEGER` column (nullable, `REFERENCES agents(id) ON DELETE CASCADE`); `agent_skills(agent_id INTEGER, skill_id INTEGER, PRIMARY KEY(agent_id, skill_id))` table with both FKs `ON DELETE CASCADE`; `idx_skills_name_global` dropped and recreated to require `agent_id IS NULL` in addition to `worker_id IS NULL`; new `idx_skills_name_per_agent` partial unique index.

- [ ] **Step 1: Write the failing test**

```python
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
```

Read `Database.create_agent`'s exact current signature in `src/openacm/storage/database.py` (search `async def create_agent`) before running this — adjust the `_make_agent` helper's kwargs to match exactly if they differ from above. Do not guess; read the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_database_agent_skills.py -v`
Expected: FAIL — `agent_id` column / `agent_skills` table don't exist yet, and the cross-scope uniqueness tests fail because the current index only accounts for `worker_id`.

- [ ] **Step 3: Write the migration**

In `src/openacm/storage/database.py`, change line 171:

```python
    _SCHEMA_VERSION = 33
```

Then add this block right after the Migration 32 block (after line 977, before the "Save new version" comment at line 979):

```python
        # ── Migration 33: per-agent skill scoping ─────────────────────────
        # Adds skills.agent_id (NULL = not agent-scoped, unchanged; set =
        # private to that one Agent) and agent_skills (which GLOBAL skills a
        # given agent has enabled) — the exact same shape as Migration 32's
        # worker_id/worker_skills, but for the separate Agents feature.
        # Unlike Migration 32, adding this column needs no table rebuild —
        # SQLite supports ALTER TABLE ADD COLUMN for a plain nullable column
        # fine; only the existing idx_skills_name_global index needs to be
        # dropped and recreated, since its WHERE clause (worker_id IS NULL)
        # doesn't yet know agent_id exists, and a global skill + an
        # agent-scoped skill could otherwise collide on name.
        if current < 33:
            await self._db.execute(
                "ALTER TABLE skills ADD COLUMN agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE"
            )
            await self._db.executescript("""
                DROP INDEX IF EXISTS idx_skills_name_global;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name_global
                    ON skills(name) WHERE worker_id IS NULL AND agent_id IS NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name_per_agent
                    ON skills(name, agent_id) WHERE agent_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_skills_agent ON skills(agent_id);

                CREATE TABLE IF NOT EXISTS agent_skills (
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                    PRIMARY KEY (agent_id, skill_id)
                );
            """)
            await self._db.commit()
            log.info("Migration 33: per-agent skill scoping (skills.agent_id, agent_skills)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_database_agent_skills.py -v`
Expected: PASS (7/7)

- [ ] **Step 5: Run the existing worker-skills tests to confirm no regression**

Run: `pytest tests/unit/test_database_worker_skills.py tests/unit/test_database.py -q`
Expected: all still pass — the `idx_skills_name_global` drop/recreate must not have broken the worker-scoped uniqueness guarantees from Migration 32 (a global skill still can't share a name with another global skill; a worker-scoped skill's own uniqueness rule, `idx_skills_name_per_worker`, is untouched by this migration).

- [ ] **Step 6: Commit**

```bash
git add src/openacm/storage/database.py tests/unit/test_database_agent_skills.py
git commit -m "feat(db): add migration 33 — skills.agent_id + agent_skills for per-agent skill scoping"
```

---

### Task 2: Database methods for agent-scoped skills

**Files:**
- Modify: `src/openacm/storage/database.py` — `create_skill` (~line 1339), `get_all_skills` (~line 1382)
- Test: `tests/unit/test_database_agent_skills.py` (extend from Task 1)

**Interfaces:**
- Consumes: schema from Task 1 (`skills.agent_id`, `agent_skills` table).
- Produces: `Database.create_skill(name, description, content, category="general", is_builtin=False, worker_id=None, agent_id=None) -> int` (extended signature — `agent_id` is new, both `worker_id` and `agent_id` default `None`, existing callers unaffected); `Database.get_all_skills(active_only=False) -> list[dict]` (now excludes both worker- and agent-scoped skills); `Database.get_agent_private_skills(agent_id) -> list[dict]` (new); `Database.get_agent_enabled_global_skill_ids(agent_id) -> set[int]` (new); `Database.enable_agent_skill(agent_id, skill_id) -> None` (new); `Database.disable_agent_skill(agent_id, skill_id) -> None` (new).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database_agent_skills.py`:

```python
class TestAgentScopedSkillMethods:
    async def test_create_skill_with_agent_id_is_excluded_from_get_all_skills(self):
        db = await _make_db()
        a1 = await _make_agent(db)
        await db.create_skill(name="global1", description="d", content="c")
        await db.create_skill(name="private1", description="d", content="c", agent_id=a1)

        all_skills = await db.get_all_skills()

        names = {s["name"] for s in all_skills}
        assert names == {"global1"}
        await db.close()

    async def test_get_agent_private_skills_returns_only_that_agents_skills(self):
        db = await _make_db()
        a1 = await _make_agent(db, "a1")
        a2 = await _make_agent(db, "a2")
        await db.create_skill(name="p1", description="d", content="c", agent_id=a1)
        await db.create_skill(name="p2", description="d", content="c", agent_id=a2)

        a1_skills = await db.get_agent_private_skills(a1)

        assert [s["name"] for s in a1_skills] == ["p1"]
        await db.close()

    async def test_enable_and_disable_agent_skill(self):
        db = await _make_db()
        a1 = await _make_agent(db)
        skill_id = await db.create_skill(name="g1", description="d", content="c")

        await db.enable_agent_skill(a1, skill_id)
        assert await db.get_agent_enabled_global_skill_ids(a1) == {skill_id}

        await db.disable_agent_skill(a1, skill_id)
        assert await db.get_agent_enabled_global_skill_ids(a1) == set()
        await db.close()

    async def test_enable_agent_skill_is_idempotent(self):
        db = await _make_db()
        a1 = await _make_agent(db)
        skill_id = await db.create_skill(name="g1", description="d", content="c")

        await db.enable_agent_skill(a1, skill_id)
        await db.enable_agent_skill(a1, skill_id)  # must not raise (duplicate PK)

        assert await db.get_agent_enabled_global_skill_ids(a1) == {skill_id}
        await db.close()

    async def test_worker_scoped_and_agent_scoped_skills_are_mutually_exclusive_in_listings(self):
        """A worker's private skills and an agent's private skills never leak into each other."""
        db = await _make_db()
        swarm_id = await db.create_swarm(name="s", goal="g")
        worker_id = await db.create_swarm_worker(
            swarm_id=swarm_id, name="w1", role="worker", description="", system_prompt="p",
        )
        agent_id = await _make_agent(db)
        await db.create_skill(name="worker-only", description="d", content="c", worker_id=worker_id)
        await db.create_skill(name="agent-only", description="d", content="c", agent_id=agent_id)

        worker_skills = await db.get_worker_private_skills(worker_id)
        agent_skills = await db.get_agent_private_skills(agent_id)

        assert [s["name"] for s in worker_skills] == ["worker-only"]
        assert [s["name"] for s in agent_skills] == ["agent-only"]
        await db.close()
```

Read `Database.create_swarm`/`create_swarm_worker`'s exact signatures (already used correctly in the shipped `tests/unit/test_database_worker_skills.py` — copy the pattern from there) before running this.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_database_agent_skills.py::TestAgentScopedSkillMethods -v`
Expected: FAIL — `create_skill()` doesn't accept `agent_id`, `get_agent_private_skills`/`enable_agent_skill`/etc. don't exist, and `get_all_skills()` doesn't filter `agent_id` yet.

- [ ] **Step 3: Implement**

In `src/openacm/storage/database.py`, replace the existing `create_skill` (around line 1339):

```python
    async def create_skill(
        self,
        name: str,
        description: str,
        content: str,
        category: str = "general",
        is_builtin: bool = False,
        worker_id: int | None = None,
        agent_id: int | None = None,
    ) -> int:
        """Create a new skill. worker_id/agent_id=None (the default for both)
        makes it a global system skill; setting one makes it private to that
        one swarm worker or Agent — never set both on the same skill."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO skills (name, description, content, category, is_builtin, worker_id, agent_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, description, content, category, int(is_builtin), worker_id, agent_id),
        )
        await self._db.commit()
        return cursor.lastrowid
```

Replace `get_all_skills` (around line 1382):

```python
    async def get_all_skills(self, active_only: bool = False) -> list[dict[str, Any]]:
        """Get all GLOBAL skills (never includes a worker- or agent-private skill)."""
        if not self._db:
            return []
        query = "SELECT * FROM skills WHERE worker_id IS NULL AND agent_id IS NULL"
        if active_only:
            query += " AND is_active = 1"
        query += " ORDER BY category, name"
        cursor = await self._db.execute(query)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

Add these new methods right after `disable_worker_skill` (search for that method, add immediately below it, before the `# ─── Settings ─────` comment):

```python
    async def get_agent_private_skills(self, agent_id: int) -> list[dict[str, Any]]:
        """Get an Agent's own private skills (agent_id set to it)."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM skills WHERE agent_id = ? ORDER BY category, name",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_agent_enabled_global_skill_ids(self, agent_id: int) -> set[int]:
        """IDs of global skills this Agent has opted into."""
        if not self._db:
            return set()
        cursor = await self._db.execute(
            "SELECT skill_id FROM agent_skills WHERE agent_id = ?", (agent_id,)
        )
        rows = await cursor.fetchall()
        return {row["skill_id"] for row in rows}

    async def enable_agent_skill(self, agent_id: int, skill_id: int) -> None:
        """Enable a global skill for an Agent. Idempotent."""
        if not self._db:
            return
        await self._db.execute(
            "INSERT OR IGNORE INTO agent_skills (agent_id, skill_id) VALUES (?, ?)",
            (agent_id, skill_id),
        )
        await self._db.commit()

    async def disable_agent_skill(self, agent_id: int, skill_id: int) -> None:
        """Disable a global skill for an Agent. Idempotent."""
        if not self._db:
            return
        await self._db.execute(
            "DELETE FROM agent_skills WHERE agent_id = ? AND skill_id = ?",
            (agent_id, skill_id),
        )
        await self._db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_database_agent_skills.py -v`
Expected: PASS (all tests from Task 1 and Task 2)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/storage/database.py tests/unit/test_database_agent_skills.py
git commit -m "feat(db): agent-scoped skill CRUD — create_skill(agent_id=), get_agent_private_skills, enable/disable_agent_skill"
```

---

### Task 3: SkillManager — agent-scoped creation and prompt building

**Files:**
- Modify: `src/openacm/core/skill_manager.py`
- Test: `tests/unit/test_skill_manager_agent_scoping.py` (new)

**Interfaces:**
- Consumes: `Database` methods from Task 2.
- Produces: `SkillManager.create_agent_skill(agent_id, name, description, content, category="custom") -> dict | None` (DB-only, no file write); `SkillManager.generate_agent_skill(agent_id, name, description, use_cases, llm_router) -> dict | None`; `SkillManager.get_active_skills_prompt_for_agent(agent_id, user_message="") -> str`.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for SkillManager's per-agent skill scoping — private skills must
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


async def _make_agent(db, name="a1"):
    return await db.create_agent(name=name, description="", system_prompt="test")


class TestCreateAgentSkill:
    async def test_creates_a_private_skill_without_writing_a_file(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)  # SKILLS_BASE_DIR is relative ("./skills")
        agent_id = await _make_agent(db)

        skill = await manager.create_agent_skill(
            agent_id=agent_id, name="faq-answers", description="d", content="c",
        )

        assert skill["name"] == "faq-answers"
        assert skill["agent_id"] == agent_id
        assert not (tmp_path / "skills" / "custom" / "faq-answers.md").exists()
        await db.close()

    async def test_private_skill_is_excluded_from_global_get_all_skills(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)

        await manager.create_agent_skill(agent_id=agent_id, name="faq-answers", description="d", content="c")

        assert await db.get_all_skills() == []
        await db.close()


class TestGenerateAgentSkill:
    async def test_generates_content_via_llm_and_saves_it_privately(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        fake_router = MagicMock()
        fake_router.chat = AsyncMock(return_value={"content": "# Generated content"})

        skill = await manager.generate_agent_skill(
            agent_id=agent_id, name="closing-deals", description="d", use_cases="u",
            llm_router=fake_router,
        )

        assert skill["content"] == "# Generated content"
        assert skill["agent_id"] == agent_id
        fake_router.chat.assert_awaited_once()
        await db.close()


class TestActiveSkillsPromptForAgent:
    async def test_includes_agents_own_active_private_skill(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        await manager.create_agent_skill(agent_id=agent_id, name="s1", description="d", content="agent-only content")

        prompt = await manager.get_active_skills_prompt_for_agent(agent_id)

        assert "agent-only content" in prompt
        await db.close()

    async def test_includes_enabled_global_skill(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        global_id = await db.create_skill(name="g1", description="d", content="global content")
        await db.enable_agent_skill(agent_id, global_id)

        prompt = await manager.get_active_skills_prompt_for_agent(agent_id)

        assert "global content" in prompt
        await db.close()

    async def test_excludes_global_skill_not_enabled_for_this_agent(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        await db.create_skill(name="g1", description="d", content="not enabled content")

        prompt = await manager.get_active_skills_prompt_for_agent(agent_id)

        assert "not enabled content" not in prompt
        await db.close()

    async def test_excludes_inactive_private_skill(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        skill = await manager.create_agent_skill(agent_id=agent_id, name="s1", description="d", content="inactive content")
        await db.toggle_skill(skill["id"])  # is_active 1 -> 0

        prompt = await manager.get_active_skills_prompt_for_agent(agent_id)

        assert "inactive content" not in prompt
        await db.close()

    async def test_empty_when_agent_has_no_skills(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)

        prompt = await manager.get_active_skills_prompt_for_agent(agent_id)

        assert prompt == ""
        await db.close()
```

Read `Database.create_agent`'s actual signature before running (same note as Task 1) and adjust `_make_agent` if it differs.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_skill_manager_agent_scoping.py -v`
Expected: FAIL — none of `create_agent_skill`/`generate_agent_skill`/`get_active_skills_prompt_for_agent` exist yet.

- [ ] **Step 3: Implement**

In `src/openacm/core/skill_manager.py`, add these three methods after the existing `get_active_skills_prompt_for_worker` method (after its closing `return` statement):

```python
    async def create_agent_skill(
        self,
        agent_id: int,
        name: str,
        description: str,
        content: str,
        category: str = "custom",
    ) -> dict[str, Any] | None:
        """Create a skill private to one Agent. Unlike create_skill(),
        this never touches the ./skills/ file-sync path — see
        create_worker_skill() for why that matters."""
        skill_id = await self.database.create_skill(
            name=name,
            description=description,
            content=content,
            category=category,
            is_builtin=False,
            agent_id=agent_id,
        )
        return await self.database.get_skill(skill_id)

    async def generate_agent_skill(
        self,
        agent_id: int,
        name: str,
        description: str,
        use_cases: str,
        llm_router=None,
    ) -> dict[str, Any] | None:
        """Generate a private, agent-scoped skill using the LLM — same
        prompt shape as generate_skill()/generate_worker_skill(), but saved
        via create_agent_skill()."""
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

        return await self.create_agent_skill(
            agent_id=agent_id,
            name=name,
            description=description,
            content=content,
            category="generated",
        )

    async def get_active_skills_prompt_for_agent(self, agent_id: int, user_message: str = "") -> str:
        """Build a skills prompt for one Agent: its own active private
        skills, plus whichever global skills it has enabled. Does not touch
        self._active_skills / self._skills_cache — those are the main
        assistant's global-only cache."""
        private_skills = [s for s in await self.database.get_agent_private_skills(agent_id) if s["is_active"]]

        enabled_ids = await self.database.get_agent_enabled_global_skill_ids(agent_id)
        global_skills = await self.database.get_all_skills(active_only=True)
        enabled_global_skills = [s for s in global_skills if s["id"] in enabled_ids]

        combined = private_skills + enabled_global_skills
        if not combined:
            return ""

        sections = [f"## {s['name']}\n\n{s['content']}" for s in combined]
        return MSG_SKILL_CONTEXT_HEADER + "\n\n".join(sections) + MSG_SKILL_CONTEXT_FOOTER
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_skill_manager_agent_scoping.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/skill_manager.py tests/unit/test_skill_manager_agent_scoping.py
git commit -m "feat(skills): SkillManager.create_agent_skill/generate_agent_skill/get_active_skills_prompt_for_agent"
```

---

### Task 4: API endpoints — agent skills

**Files:**
- Modify: `src/openacm/web/routers/agents.py`
- Test: `tests/unit/test_agents_skills_api.py` (new)

**Interfaces:**
- Consumes: `SkillManager` methods from Task 3, `Database.get_agent_private_skills`/`get_agent_enabled_global_skill_ids`/`enable_agent_skill`/`disable_agent_skill` from Task 2.
- Produces: `GET /api/agents/{agent_id}/skills`, `POST /api/agents/{agent_id}/skills/{skill_id}`, `DELETE /api/agents/{agent_id}/skills/{skill_id}`, `POST /api/agents/{agent_id}/skills/generate`.

Read `src/openacm/web/routers/agents.py:68-96` (`get_agent`/`update_agent`) first for this file's exact `_state.database` / `HTTPException` conventions, and `src/openacm/web/routers/skills.py:98-114` (`generate_skill`) for the generate-endpoint error-handling convention — match both exactly. This is a flatter shape than the Swarms version (an Agent is the top-level unit, no nested swarm/worker path).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for per-agent skill API endpoints under the agents router."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from openacm.web.routers import agents as agents_router
from openacm.web.state import _state


@pytest.fixture
def app_client():
    app = FastAPI()
    agents_router.register_routes(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _mock_brain(monkeypatch):
    db = MagicMock()
    db.get_all_skills = AsyncMock(return_value=[
        {"id": 1, "name": "g1", "description": "d", "content": "c", "category": "general", "is_active": 1, "is_builtin": 0, "worker_id": None, "agent_id": None},
    ])
    db.get_agent_private_skills = AsyncMock(return_value=[
        {"id": 2, "name": "p1", "description": "d", "content": "c", "category": "custom", "is_active": 1, "is_builtin": 0, "worker_id": None, "agent_id": 42},
    ])
    db.get_agent_enabled_global_skill_ids = AsyncMock(return_value={1})
    db.enable_agent_skill = AsyncMock()
    db.disable_agent_skill = AsyncMock()
    db.get_skill = AsyncMock(return_value=None)
    monkeypatch.setattr(_state, "database", db)

    skill_manager = MagicMock()
    skill_manager.generate_agent_skill = AsyncMock(return_value={"id": 3, "name": "gen1", "agent_id": 42})
    brain = MagicMock()
    brain.skill_manager = skill_manager
    brain.llm_router = MagicMock()
    monkeypatch.setattr(_state, "brain", brain)
    yield db, skill_manager
    monkeypatch.setattr(_state, "database", None)
    monkeypatch.setattr(_state, "brain", None)


class TestGetAgentSkills:
    async def test_returns_global_skills_annotated_and_private_skills(self, app_client, _mock_brain):
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["global_skills"] == [
            {"id": 1, "name": "g1", "description": "d", "content": "c", "category": "general", "is_active": 1, "is_builtin": 0, "worker_id": None, "agent_id": None, "enabled": True}
        ]
        assert body["private_skills"][0]["name"] == "p1"


class TestEnableDisableAgentSkill:
    async def test_enable_calls_database(self, app_client, _mock_brain):
        db, _ = _mock_brain
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/skills/1")
        assert resp.status_code == 200
        db.enable_agent_skill.assert_awaited_once_with(42, 1)

    async def test_enable_rejects_a_private_skill_id_with_400(self, app_client, _mock_brain):
        db, _ = _mock_brain
        db.get_skill = AsyncMock(return_value={"id": 2, "name": "p1", "agent_id": 42})
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/skills/2")
        assert resp.status_code == 400
        db.enable_agent_skill.assert_not_awaited()

    async def test_disable_calls_database(self, app_client, _mock_brain):
        db, _ = _mock_brain
        async with app_client as ac:
            resp = await ac.delete("/api/agents/42/skills/1")
        assert resp.status_code == 200
        db.disable_agent_skill.assert_awaited_once_with(42, 1)


class TestGenerateAgentSkill:
    async def test_generates_and_returns_the_skill(self, app_client, _mock_brain):
        _, skill_manager = _mock_brain
        async with app_client as ac:
            resp = await ac.post(
                "/api/agents/42/skills/generate",
                json={"name": "gen1", "description": "d", "use_cases": "u"},
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "gen1"

    async def test_no_brain_503s(self, app_client, monkeypatch):
        monkeypatch.setattr(_state, "brain", None)
        async with app_client as ac:
            resp = await ac.post(
                "/api/agents/42/skills/generate",
                json={"name": "gen1", "description": "d"},
            )
        assert resp.status_code == 503
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agents_skills_api.py -v`
Expected: FAIL — 404s, the endpoints don't exist yet.

- [ ] **Step 3: Implement**

In `src/openacm/web/routers/agents.py`, add these four endpoints right after the existing `delete_agent` endpoint (after line 110, before the `# ─── Knowledge Base ───` comment at line 112) — placing the skills endpoints as their own section right after the core agent CRUD, before Knowledge:

```python
    # ─── Skills ─────────────────────────────────────────────

    @app.get("/api/agents/{agent_id}/skills")
    async def get_agent_skills(agent_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        global_skills = await _state.database.get_all_skills()
        enabled_ids = await _state.database.get_agent_enabled_global_skill_ids(agent_id)
        annotated = [{**s, "enabled": s["id"] in enabled_ids} for s in global_skills]
        private_skills = await _state.database.get_agent_private_skills(agent_id)
        return {"global_skills": annotated, "private_skills": private_skills}

    @app.post("/api/agents/{agent_id}/skills/{skill_id}")
    async def enable_agent_skill(agent_id: int, skill_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        skill = await _state.database.get_skill(skill_id)
        if skill and skill.get("agent_id") is not None:
            raise HTTPException(400, "Cannot enable a private skill as a global one")
        await _state.database.enable_agent_skill(agent_id, skill_id)
        return {"status": "ok", "enabled": True}

    @app.delete("/api/agents/{agent_id}/skills/{skill_id}")
    async def disable_agent_skill(agent_id: int, skill_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        await _state.database.disable_agent_skill(agent_id, skill_id)
        return {"status": "ok", "enabled": False}

    @app.post("/api/agents/{agent_id}/skills/generate")
    async def generate_agent_skill_endpoint(agent_id: int, request: Request):
        if not _state.brain or not _state.brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        data = await request.json()
        try:
            skill = await _state.brain.skill_manager.generate_agent_skill(
                agent_id=agent_id,
                name=data["name"],
                description=data["description"],
                use_cases=data.get("use_cases", ""),
                llm_router=_state.brain.llm_router,
            )
            return skill
        except Exception as e:
            log.error("Failed to generate agent skill", error=str(e))
            raise HTTPException(status_code=500, detail="Failed to generate skill")
```

Note the 400-check for enabling a private skill is included from the start this time (unlike the Swarms plan, where it was dropped and had to be added back after review — same reasoning applies: don't let a caller enable an agent-private or worker-private skill ID as if it were global).

Confirm `Request`, `HTTPException`, and `log` (a `structlog` logger) are already available in this file's scope — `agents.py` already uses `Request` (in `update_agent`) and `HTTPException` extensively; check the top of the file for a `log = structlog.get_logger()` line matching the convention used in `swarms.py`/`skills.py` — add it if missing.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agents_skills_api.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/web/routers/agents.py tests/unit/test_agents_skills_api.py
git commit -m "feat(api): agent skill endpoints — get/enable/disable global, generate private"
```

---

### Task 5: Wire per-agent skills into agent execution

**Files:**
- Modify: `src/openacm/core/agent_runner.py` — `__init__` (line 31), `run()` (line 96)
- Modify: `src/openacm/app.py` — `AgentRunner(...)` construction (line 415)
- Modify: `src/openacm/web/routers/agents.py` — two more `AgentRunner(...)` construction sites (lines 416, 535)
- Test: `tests/unit/test_agent_runner_skills.py` (new)

**Interfaces:**
- Consumes: `SkillManager.get_active_skills_prompt_for_agent` from Task 3.
- Produces: `AgentRunner.__init__` gains a `skill_manager=None` param; `run()` appends the agent's active skills prompt to its system prompt, mirroring the exact pattern already used in `core/brain_prompt.py:69-72` and in the already-shipped Swarms wiring (`system_prompt = f"{system_prompt}\n\n{skills_prompt}"`, only when non-empty).

- [ ] **Step 1: Write the failing test**

`AgentRunner`'s `_build_system_prompt` is a plain, synchronous, side-effect-free method — but the skills-prompt fetch itself is async and happens in `run()`, not in `_build_system_prompt`. Test the composed behavior through `run()` with mocked dependencies:

```python
"""Test that AgentRunner.run() includes the agent's active skills prompt
in the system prompt handed to Brain, and is unaffected when the agent has
no skill_manager or no active skills (existing behavior preserved)."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from openacm.core.agent_runner import AgentRunner

AGENT = {
    "id": 42, "name": "TestAgent", "description": "d",
    "system_prompt": "Base agent prompt.", "allowed_tools": "all",
}


def _make_runner(skill_manager=None):
    return AgentRunner(
        llm_router=MagicMock(), tool_registry=MagicMock(), memory=MagicMock(),
        event_bus=MagicMock(), database=None, skill_manager=skill_manager,
    )


class TestRunIncludesAgentSkillsPrompt:
    async def test_appends_skills_prompt_when_skill_manager_returns_one(self):
        skill_manager = MagicMock()
        skill_manager.get_active_skills_prompt_for_agent = AsyncMock(return_value="## my-skill\n\ndo the thing")
        runner = _make_runner(skill_manager=skill_manager)

        captured = {}

        class _FakeBrain:
            def __init__(self, config, **kwargs):
                captured["system_prompt"] = config.system_prompt

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        assert "## my-skill" in captured["system_prompt"]
        assert "do the thing" in captured["system_prompt"]
        skill_manager.get_active_skills_prompt_for_agent.assert_awaited_once_with(42)

    async def test_no_skill_manager_leaves_prompt_unchanged(self):
        runner = _make_runner(skill_manager=None)

        captured = {}

        class _FakeBrain:
            def __init__(self, config, **kwargs):
                captured["system_prompt"] = config.system_prompt

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        assert captured["system_prompt"] == "Base agent prompt."
```

Read `AgentRunner.run()`'s exact current body (`src/openacm/core/agent_runner.py:68-127`) before writing this test — confirm how it actually invokes `Brain` (constructor kwargs, whether it calls `.process_message(...)` or something else) and adjust `_FakeBrain`'s interface to match reality exactly; the snippet above is a best-effort based on the plan's earlier research and may need small adjustments once you read the live file.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agent_runner_skills.py -v`
Expected: FAIL — `AgentRunner.__init__()` doesn't accept `skill_manager` yet, and the skills prompt isn't fetched/appended.

- [ ] **Step 3: Implement**

In `src/openacm/core/agent_runner.py`, update `__init__` (line 31):

```python
    def __init__(self, llm_router, tool_registry, memory, event_bus, database=None, skill_manager=None):
        self.llm_router = llm_router
        self.tool_registry = tool_registry
        self.memory = memory
        self.event_bus = event_bus
        self.database = database
        self.skill_manager = skill_manager
```

In `run()`, right where the system prompt is currently built (line 96: `system_prompt = self._build_system_prompt(agent["system_prompt"], knowledge_items)`), add the skills-prompt fetch and append immediately after:

```python
        system_prompt = self._build_system_prompt(agent["system_prompt"], knowledge_items)

        if self.skill_manager:
            skills_prompt = await self.skill_manager.get_active_skills_prompt_for_agent(agent["id"])
            if skills_prompt:
                system_prompt = f"{system_prompt}\n\n{skills_prompt}"
```

In `src/openacm/app.py`, update the `AgentRunner(...)` call inside `_init_agent_channels` (line 415-421):

```python
            agent_runner = AgentRunner(
                llm_router=self.llm_router,
                tool_registry=self.tool_registry,
                memory=self.memory,
                event_bus=self.event_bus,
                database=self.database,
                skill_manager=self.skill_manager,
            )
```

In `src/openacm/web/routers/agents.py`, update BOTH `AgentRunner(...)` construction sites (the webhook `/chat` endpoint around line 416, and the dashboard `/test` endpoint around line 535) to add `skill_manager=_state.brain.skill_manager,` as a new line inside each constructor call, alongside the existing `database=_state.database,` line.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agent_runner_skills.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: no new failures beyond the known pre-existing `gmail_classifier` errors (7 errors — do not fix them as part of this task; ignore any transient date-dependent test behavior in `test_gmail_summary.py` unrelated to this change).

- [ ] **Step 6: Commit**

```bash
git add src/openacm/core/agent_runner.py src/openacm/app.py src/openacm/web/routers/agents.py tests/unit/test_agent_runner_skills.py
git commit -m "feat(agents): inject each agent's active skills (private + enabled-global) into its run"
```

---

### Task 6: Frontend — convert agent editing from a modal to an in-place detail view

**Files:**
- Modify: `frontend/app/agents/page.tsx`

**Interfaces:**
- Consumes: existing `Agent`, `AgentFormData` types and `useAgentMutations()` hook (`frontend/hooks/use-agents.ts`) — unchanged.
- Produces: a new `AgentDetailView({ agent, onClose }: { agent: Agent; onClose: () => void }) => JSX.Element` component, rendered by the main page in place of the header+grid when an agent is selected (not as an overlay). `AgentFormModal` continues to exist but is simplified to handle **only** the "create new agent" flow (no tabs, no Knowledge/Channels rendering — those never applied to a not-yet-created agent anyway).

This is the largest task in this plan — a genuine UI restructuring, not just an addition. Read `frontend/app/agents/page.tsx` in full before starting (it's 1500+ lines); the line numbers below reflect its state as of this plan's writing and may have shifted slightly — if so, find the same logical blocks by their content (the `AgentFormModal` function, the tab bar, the main `AgentsPage` component's `modal`/`editing` state) rather than trusting line numbers blindly.

- [ ] **Step 1: Extract `AgentDetailView` from `AgentFormModal`'s editing-mode content**

`AgentFormModal` (currently spanning roughly lines 628-987) already contains everything needed for the detail view — a header with a working ✕ close button (lines 706-722), a tab bar shown only when editing (lines 725-767), and tab content branching on `activeTab` (lines 769-956) that already renders `<ChannelsTab agentId={initial.id} />` and `<KnowledgeTab agentId={initial.id} />` for those two tabs. Create a new component, placed right after `AgentFormModal`'s closing brace and before the `// ── Test Panel ──` comment:

```typescript
// ── Agent Detail View (in-place, replaces the grid — not an overlay) ──────────

function AgentDetailView({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const { update, generate } = useAgentMutations();
  const [form, setForm] = useState<AgentFormData>({
    name: agent.name,
    description: agent.description,
    system_prompt: agent.system_prompt,
    allowed_tools: agent.allowed_tools,
    telegram_token: agent.telegram_token ?? '',
  });
  const [genDescription, setGenDescription] = useState('');
  const [droppedFiles, setDroppedFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [activeTab, setActiveTab] = useState<'config' | 'knowledge' | 'channels' | 'tools' | 'skills'>('config');

  const set = (field: keyof AgentFormData, val: string) =>
    setForm((f) => ({ ...f, [field]: val }));

  const handleGenerate = async () => {
    if (!genDescription.trim()) return;
    try {
      const res = await generate.mutateAsync({ description: genDescription, files: droppedFiles.length ? droppedFiles : undefined });
      setForm((f) => ({
        ...f,
        name: res.name || f.name,
        description: res.description || f.description,
        system_prompt: res.system_prompt || f.system_prompt,
      }));
      toast.success('Agent config generated!');
    } catch {
      toast.error('Generation failed — try again');
    }
  };

  const addFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    const allowed = ['pdf', 'txt', 'md', 'csv', 'json', 'yaml', 'yml'];
    const next = Array.from(incoming).filter((f) => {
      const ext = f.name.split('.').pop()?.toLowerCase() ?? '';
      return allowed.includes(ext);
    });
    setDroppedFiles((prev) => {
      const names = new Set(prev.map((f) => f.name));
      return [...prev, ...next.filter((f) => !names.has(f.name))];
    });
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    addFiles(e.dataTransfer.files);
  };

  const removeFile = (name: string) =>
    setDroppedFiles((prev) => prev.filter((f) => f.name !== name));

  const handleSave = async () => {
    try {
      await update.mutateAsync({ id: agent.id, data: form });
      toast.success('Agent updated');
    } catch {
      toast.error('Failed to save agent');
    }
  };

  return (
    <div className="w-full flex flex-col" style={{ minHeight: '70vh' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-2 py-4 shrink-0" style={{ borderBottom: '1px solid var(--acm-border)' }}>
        <h2 className="text-[18px] font-semibold" style={{ color: 'var(--acm-fg)' }}>{agent.name}</h2>
        <button
          onClick={onClose}
          className="p-1.5 rounded transition-colors"
          style={{ color: 'var(--acm-fg-4)' }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--acm-fg)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--acm-fg-4)')}
        >
          <X size={18} />
        </button>
      </div>

      {/* Tab bar — 5 tabs now */}
      <div className="flex border-b border-zinc-800 px-2 flex-wrap">
        <button onClick={() => setActiveTab('config')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'config' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>⚙ Config</button>
        <button onClick={() => setActiveTab('knowledge')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'knowledge' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>
          <span className="flex items-center gap-1.5"><BookOpen className="w-3.5 h-3.5" />Knowledge</span>
        </button>
        <button onClick={() => setActiveTab('channels')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'channels' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>
          <span className="flex items-center gap-1.5"><Radio className="w-3.5 h-3.5" />Channels</span>
        </button>
        <button onClick={() => setActiveTab('tools')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'tools' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>Herramientas</button>
        <button onClick={() => setActiveTab('skills')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'skills' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>Skills</button>
      </div>

      <div className="p-2 pt-5 space-y-5 overflow-y-auto acm-scroll flex-1">
        {activeTab === 'channels' ? (
          <ChannelsTab agentId={agent.id} />
        ) : activeTab === 'knowledge' ? (
          <KnowledgeTab agentId={agent.id} />
        ) : activeTab === 'tools' ? (
          <AgentToolsTab agent={agent} />
        ) : activeTab === 'skills' ? (
          <AgentSkillsTab agentId={agent.id} />
        ) : (
          <>
            {/* ── AI Generator ─────────────────────────────── */}
            <div className="rounded-xl p-4 space-y-3" style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}>
              <p className="text-[11px] font-semibold flex items-center gap-1.5 uppercase tracking-[0.1em]" style={{ color: 'var(--acm-accent)' }}>
                <Sparkles size={12} /> Generate with AI
              </p>
              <textarea
                value={genDescription}
                onChange={(e) => setGenDescription(e.target.value)}
                placeholder="Describe what your agent should do..."
                rows={3}
                className="acm-input w-full resize-none text-[13px]"
              />
              <div
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={onDrop}
                className="relative rounded-lg px-4 py-3 transition-colors cursor-pointer"
                style={{
                  border: `2px dashed ${isDragging ? 'var(--acm-accent)' : 'var(--acm-border-strong)'}`,
                  background: isDragging ? 'var(--acm-accent-tint)' : 'transparent',
                }}
              >
                <input
                  id="agent-detail-file-input"
                  type="file"
                  accept=".pdf,.txt,.md,.csv,.json,.yaml,.yml"
                  multiple
                  className="hidden"
                  onChange={(e) => addFiles(e.target.files)}
                />
                <label htmlFor="agent-detail-file-input" className="flex items-center gap-2 text-[12px] cursor-pointer" style={{ color: 'var(--acm-fg-3)' }}>
                  <Upload size={14} />
                  Drop files here or click to attach (optional context for generation)
                </label>
                {droppedFiles.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {droppedFiles.map((f) => (
                      <span key={f.name} className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded" style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)', color: 'var(--acm-fg-3)' }}>
                        {f.name}
                        <button onClick={(e) => { e.stopPropagation(); removeFile(f.name); }}><X size={10} /></button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <button onClick={handleGenerate} disabled={generate.isPending || !genDescription.trim()} className="btn-secondary w-full justify-center">
                {generate.isPending ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                Generate
              </button>
            </div>

            {/* ── Fields ───────────────────────────────────── */}
            <div className="space-y-1">
              <label className="text-[11px] font-medium" style={{ color: 'var(--acm-fg-3)' }}>Name</label>
              <input value={form.name} onChange={(e) => set('name', e.target.value)} className="acm-input w-full text-[13px]" />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] font-medium" style={{ color: 'var(--acm-fg-3)' }}>Description</label>
              <input value={form.description} onChange={(e) => set('description', e.target.value)} className="acm-input w-full text-[13px]" />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] font-medium" style={{ color: 'var(--acm-fg-3)' }}>System Prompt</label>
              <textarea value={form.system_prompt} onChange={(e) => set('system_prompt', e.target.value)} rows={8} className="acm-input w-full text-[13px] resize-y" />
            </div>

            <button onClick={handleSave} disabled={update.isPending || !form.name.trim() || !form.system_prompt.trim()} className="btn-primary">
              {update.isPending && <Loader2 size={13} className="animate-spin" />}
              Save changes
            </button>
          </>
        )}
      </div>
    </div>
  );
}
```

Note: this drops the `TOOLS_OPTIONS`/`allowed_tools` dropdown and the `telegram_token`/"Advanced options" field that existed on the Config tab (they're superseded — tools now live on the new Herramientas tab built in Task 7, and per this plan's spec, `telegram_token` is already legacy/labeled "coming soon" per the earlier research and Telegram is now configured via the Channels tab instead). If the live file's Config tab has since changed and still actively uses `TOOLS_OPTIONS` or `telegram_token` in a way that looks load-bearing (not just legacy/unused), stop and flag this — don't silently drop something still in active use.

- [ ] **Step 2: Simplify `AgentFormModal` to create-only**

In the existing `AgentFormModal` component, remove the tab bar block (the `{isEditing && (...)}` block) and simplify the body to always render the Config-tab content (the AI generator + fields), since `isEditing` will now always be `false` — this component is called only from the "create" path. Remove the `isEditing`/`initial` props and the `activeTab` state entirely (they're no longer needed since there's only ever one "tab" — Config). Keep the ✕ header, the footer's Cancel/Create buttons, and the `onSave`/`onClose`/`isSaving` prop contract exactly as they are today, since `openCreate`/`handleSave` in the main page component still use them for the create flow. Rename nothing else in this component — only remove the dead editing-mode branches.

- [ ] **Step 3: Wire the new view into the main page component**

In `AgentsPage` (the main page component, currently using `modal`/`editing` state), add:

```typescript
  const [viewingAgent, setViewingAgent] = useState<Agent | null>(null);
```

Change `openEdit` from setting `editing`/`modal` to instead:

```typescript
  const openEdit = (a: Agent) => setViewingAgent(a);
```

`openCreate`/`closeModal`/`handleSave`'s `modal === 'edit'` branch, and the `<AgentFormModal>` render block should keep working for `create` only — `modal` will now only ever be `'create' | null` in practice (nothing sets it to `'edit'` anymore), so no changes needed to that logic itself, just note `editing` is no longer read anywhere except possibly a stale reference — grep the file for `editing` after this change and remove any now-dead code that referenced it for the edit path specifically.

Replace the page's return block's content area — currently:
```typescript
        {/* ── Content ──────────────────────────────────────── */}
        {isLoading ? (
          ...
        ) : agents.length === 0 ? (
          ...
        ) : (
          /* Agent grid */
          ...
        )}
```
Wrap this so it only renders when `!viewingAgent`, and render `<AgentDetailView>` instead when an agent is selected. Also hide the page header (title + "New Agent" button) while viewing a detail, matching the "content area is fully replaced" behavior requested:

```typescript
        {viewingAgent ? (
          <AgentDetailView agent={viewingAgent} onClose={() => setViewingAgent(null)} />
        ) : (
          <>
            {/* ── Page Header ──────────────────────────────────── */}
            <header className="mb-8 flex items-start justify-between gap-4 flex-wrap">
              {/* ...unchanged header content exactly as it is today... */}
            </header>

            {/* ── Content ──────────────────────────────────────── */}
            {isLoading ? (
              ...
            ) : agents.length === 0 ? (
              ...
            ) : (
              /* Agent grid */
              ...
            )}
          </>
        )}
```

Copy the header/loading/empty-state/grid JSX exactly as it exists today into this new wrapping structure — do not change any of their internals, only their conditional placement.

- [ ] **Step 4: Run `tsc` and fix any type errors**

Run: `cd frontend && npx tsc --noEmit`
Expected: errors initially, because `AgentToolsTab`/`AgentSkillsTab` (referenced in Step 1) don't exist yet — that's expected, they're built in Tasks 7 and 8. For THIS task, temporarily stub them at the bottom of the file so `tsc` passes cleanly before those tasks run:

```typescript
function AgentToolsTab({ agent }: { agent: Agent }) {
  return <div className="text-[12px]" style={{ color: 'var(--acm-fg-4)' }}>Coming in Task 7.</div>;
}

function AgentSkillsTab({ agentId }: { agentId: number }) {
  return <div className="text-[12px]" style={{ color: 'var(--acm-fg-4)' }}>Coming in Task 8.</div>;
}
```

Run `tsc --noEmit` again — must show zero errors before proceeding.

- [ ] **Step 5: Manual verification**

Start the dev server, open `/agents`, click an existing agent card, confirm the grid disappears and the agent's detail view fills the content area with all 5 tabs, confirm Config/Knowledge/Channels behave exactly as before (unchanged), confirm the ✕ returns to the grid, confirm "New Agent" still opens the small create modal as before.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/agents/page.tsx
git commit -m "refactor(agents): convert agent editing from an overlay modal to an in-place detail view with Tools/Skills tab placeholders"
```

---

### Task 7: Frontend — Herramientas tab for Agents

**Files:**
- Modify: `frontend/hooks/use-worker-config.ts` — generalize `parseAllowedTools`/`serializeAllowedTools` (they already operate on a plain string + tool-name list, nothing worker-specific about their logic — confirm this by reading them, then just reuse as-is; do NOT duplicate them into a new file)
- Modify: `frontend/app/agents/page.tsx` — replace the `AgentToolsTab` stub from Task 6 with a real implementation

**Interfaces:**
- Consumes: `useTools()`/`ToolInfo` from `frontend/hooks/use-api.ts` (already shipped), `parseAllowedTools`/`serializeAllowedTools` from `frontend/hooks/use-worker-config.ts` (already shipped, reused as-is), `useAgentMutations()`'s `update` mutation (already shipped in `frontend/hooks/use-agents.ts`) — no new hook needed for saving.
- Produces: `AgentToolsTab({ agent }: { agent: Agent })` replacing the Task 6 stub.

- [ ] **Step 1: Read the shipped `parseAllowedTools`/`serializeAllowedTools`**

Read `frontend/hooks/use-worker-config.ts` in full. Confirm both functions take a plain `allowedTools: string` and `allToolNames: string[]` — genuinely worker-agnostic already (this plan's spec called this out explicitly). Import them directly into `frontend/app/agents/page.tsx`:

```typescript
import { useTools, parseAllowedTools, serializeAllowedTools } from '@/hooks/use-worker-config';
```

(if `useTools`/`ToolInfo` now live in `use-api.ts` per the Swarms plan's Task 6 fix rather than `use-worker-config.ts`, import `useTools` from `@/hooks/use-api` instead — check which file currently exports it before writing the import line.)

- [ ] **Step 2: Implement `AgentToolsTab`**

Replace the Task 6 stub in `frontend/app/agents/page.tsx` with:

```typescript
function AgentToolsTab({ agent }: { agent: Agent }) {
  const { data: tools, isLoading } = useTools();
  const { update } = useAgentMutations();
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const initializedRef = useRef(false);

  useEffect(() => {
    if (tools && !initializedRef.current) {
      const allNames = tools.map(t => t.name);
      setSelected(parseAllowedTools(agent.allowed_tools, allNames));
      initializedRef.current = true;
    }
  }, [tools, agent.allowed_tools]);

  if (isLoading || !tools) return <Loader2 size={16} className="animate-spin" />;

  const allNames = tools.map(t => t.name);
  const filtered = tools.filter(t =>
    !search || t.name.toLowerCase().includes(search.toLowerCase()) || t.category.toLowerCase().includes(search.toLowerCase())
  );
  const byCategory: Record<string, typeof tools> = {};
  for (const t of filtered) (byCategory[t.category] ??= []).push(t);

  const toggle = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const save = () => update.mutate({ id: agent.id, data: { allowed_tools: serializeAllowedTools(selected, allNames) } });

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
      <div className="max-h-96 overflow-auto flex flex-col gap-2">
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
      <button onClick={save} disabled={update.isPending} className="btn-secondary self-end text-[11px] px-2 py-1">
        {update.isPending ? 'Guardando...' : 'Guardar herramientas'}
      </button>
    </div>
  );
}
```

Add `Search` to the existing `lucide-react` import line at the top of the file if not already imported (check first — `frontend/app/agents/page.tsx`'s import list is large; it may already include icons this component doesn't need, but `Search` specifically may be new).

- [ ] **Step 3: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

Manual verification: open an agent's detail view, go to "Herramientas", confirm checkboxes render grouped by category with search filtering, toggle a few, save, refresh the page, re-open the same agent's Herramientas tab and confirm the same tools are still checked (persisted via the existing `PUT /api/agents/{id}` endpoint, no data-loss race — this reuses the exact fixed pattern from the Swarms `ToolsTab`, not the buggy lazy-`useState` version that was caught in review there).

- [ ] **Step 4: Commit**

```bash
git add frontend/app/agents/page.tsx
git commit -m "feat(agents): Herramientas tab — per-tool selection reusing the shipped checkbox-by-category pattern"
```

---

### Task 8: Frontend — Skills tab for Agents

**Files:**
- Modify: `frontend/hooks/use-agents.ts` — add agent-skill hooks
- Modify: `frontend/app/agents/page.tsx` — replace the `AgentSkillsTab` stub from Task 6 with a real implementation

**Interfaces:**
- Consumes: the four endpoints from Task 4.
- Produces: `useAgentSkills(agentId)`, `useToggleAgentGlobalSkill(agentId)`, `useGenerateAgentSkill(agentId)`, `useToggleAgentPrivateSkill(agentId)`, `useDeleteAgentPrivateSkill(agentId)` hooks (mirroring `use-worker-config.ts`'s worker-skill hooks exactly, added to `use-agents.ts` alongside the existing agent hooks since Skills are now a core part of the Agent's own data, not a separate concern file); `AgentSkillsTab` component.

- [ ] **Step 1: Add skill hooks to `use-agents.ts`**

Append to `frontend/hooks/use-agents.ts` (reuse the `WorkerSkill`-shaped interface, renamed for agents — do not import the Swarms one, since it's specific to that file's module and this keeps Agents' hooks self-contained in their own file, matching this file's existing pattern of owning all Agent-related types):

```typescript
export interface AgentSkill {
  id: number;
  name: string;
  description: string;
  content: string;
  category: string;
  is_active: number;
  is_builtin: number;
  agent_id: number | null;
  enabled?: boolean; // present only on global_skills entries
}

export function useAgentSkills(agentId: number) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<{ global_skills: AgentSkill[]; private_skills: AgentSkill[] }>({
    queryKey: ['agent-skills', agentId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/skills`),
    enabled: isAuthenticated,
  });
}

export function useToggleAgentGlobalSkill(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ skillId, enable }: { skillId: number; enable: boolean }) =>
      fetchAPI(`/api/agents/${agentId}/skills/${skillId}`, { method: enable ? 'POST' : 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-skills', agentId] }),
  });
}

export function useGenerateAgentSkill(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; description: string; use_cases: string }) =>
      fetchAPI(`/api/agents/${agentId}/skills/generate`, { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-skills', agentId] }),
  });
}

export function useToggleAgentPrivateSkill(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (skillId: number) => fetchAPI(`/api/skills/${skillId}/toggle`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-skills', agentId] }),
  });
}

export function useDeleteAgentPrivateSkill(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (skillId: number) => fetchAPI(`/api/skills/${skillId}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-skills', agentId] }),
  });
}
```

Confirm `useQuery`, `useMutation`, `useQueryClient` are already imported at the top of `use-agents.ts` (they are, per the file's existing header) — no new imports needed for these.

- [ ] **Step 2: Implement `AgentSkillsTab`**

Replace the Task 6 stub in `frontend/app/agents/page.tsx` with:

```typescript
function AgentSkillsTab({ agentId }: { agentId: number }) {
  const { data, isLoading } = useAgentSkills(agentId);
  const toggleGlobal = useToggleAgentGlobalSkill(agentId);
  const togglePrivate = useToggleAgentPrivateSkill(agentId);
  const deletePrivate = useDeleteAgentPrivateSkill(agentId);
  const generate = useGenerateAgentSkill(agentId);
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
        <div className="label text-[var(--acm-fg-4)] mb-1">Skills de este agente</div>
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

Update the imports at the top of `frontend/app/agents/page.tsx` to include the new hooks from `use-agents.ts` (this file already imports several things from `@/hooks/use-agents` per its existing header — add `useAgentSkills, useToggleAgentGlobalSkill, useGenerateAgentSkill, useToggleAgentPrivateSkill, useDeleteAgentPrivateSkill` to that same import line) and `Trash2` to the `lucide-react` import line if not already present (check first — this file already imports many icons).

- [ ] **Step 3: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

Manual verification: open an agent's detail view, go to "Skills", confirm global skills list with checkboxes, toggle one on/off and confirm it persists across a page refresh. Click "+ Nueva skill personalizada", fill in name/description/use cases, submit, confirm it appears under "Skills de este agente" once generation completes. Toggle its active checkbox off/on and delete it, confirming each persists.

- [ ] **Step 4: Commit**

```bash
git add frontend/hooks/use-agents.ts frontend/app/agents/page.tsx
git commit -m "feat(agents): Skills tab — enable global skills, create/manage private ones via AI generation"
```

---

## Post-plan manual smoke test (end to end)

After all 8 tasks are merged, manually verify the whole feature end to end:

1. Open `/agents`, click an existing agent (or create one first via "New Agent").
2. Confirm the grid disappears and the agent's detail view takes over the content, with all 5 tabs (Config, Knowledge, Channels, Herramientas, Skills) and a working ✕ that returns to the grid.
3. In Herramientas, uncheck everything except 2-3 tools, save.
4. In Skills, enable one global skill, create a new private skill with a distinctive instruction (e.g. "always end every response with the exact string ZXQ456").
5. Trigger the agent via the dashboard "Test this agent" panel (already existing feature, unaffected by this plan) with a simple message.
6. Confirm its response contains "ZXQ456" (proves the private skill reached its prompt) and that it only ever calls the 2-3 tools left checked (proves `allowed_tools` — already working end-to-end before this plan — wasn't desynced by the new UI).
