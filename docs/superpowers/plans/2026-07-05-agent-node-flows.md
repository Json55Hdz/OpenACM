# Agent Node Flows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user build a visual node-based flow (HTTP call → conditional → WooCommerce query → …) for an Agent, which is automatically exposed as a callable tool the agent's own LLM can invoke — no separate automation/pipeline system, just another way to build a tool besides Python code.

**Architecture:** A `Flow` is stored as JSON (nodes + edges) in a new `flows` table, 100% private to one agent. A small purpose-built Python interpreter (`FlowExecutor`) walks the graph (linear chain, with exactly one branch point at a Conditional node) and dispatches each node type to its own handler. When an agent runs, `AgentRunner` converts each of the agent's active flows into a dynamically-built `ToolDefinition` and merges it into the tool registry the LLM sees for that run — reusing the existing `ToolDefinition`/`ToolRegistry.execute()` machinery unchanged. A new `connections` table stores reusable credentials (e.g. a WooCommerce store's API keys) so multiple flows can reference the same connection without re-entering it.

**Tech Stack:** Python 3.13, aiosqlite, FastAPI, httpx (already a dependency), pytest + pytest-asyncio (auto mode), Next.js/React/TypeScript, TanStack Query, `@xyflow/react` (React Flow — new frontend dependency).

## Global Constraints

- `_SCHEMA_VERSION` goes from 33 to 34 (`src/openacm/storage/database.py:171`). New migration block follows the exact existing pattern (`if current < 34:` → `executescript()` with `IF NOT EXISTS` guards → commit → `log.info(...)`).
- A Flow is **never shared between agents** — `flows.agent_id` is `NOT NULL`, `ON DELETE CASCADE`. Same for `connections.agent_id`.
- **A flow becomes a tool, not an automation.** The agent's LLM decides when to call it, exactly like any other tool — there is no "runs on every message" trigger mechanism anywhere in this plan.
- **Node topology for v1: linear chain + exactly one branch point.** Every node has exactly one outgoing edge (`fromHandle: "default"`), except a Conditional node, which has exactly two (`fromHandle: "true"` and `fromHandle: "false"`). No loops, no multiple inputs into one node, no rejoining branches. Do not build general DAG/cycle-detection machinery — it is out of scope.
- **Template substitution semantics (exact, from the approved spec) — get this right, it is easy to implement subtly wrong:**
  - `{{name}}` with no dot: first checks the flow's *parameters* (from the Start node) for an exact key match; if not found there, checks *node outputs* (keyed by node id) for an exact match; if found in either, the WHOLE value is stringified and substituted. If found in neither, substitutes the literal marker `[missing: name]`.
  - `{{node_id.field}}` (with a dot): ONLY looks up `node_id` in node outputs (never in parameters — parameters are flat scalars, they have no `.field` form). If `node_id`'s output is a JSON object (Python `dict`) and `field` is one of its keys, substitutes that key's value (stringified). In every other case (node_id not found, or its output is not a `dict`, or `field` is not a key in it), substitutes the literal marker `[missing: node_id.field]` — **never** a silent empty string.
- **Node output shapes, precisely:**
  - HTTP Request node's output: the parsed JSON body (a `dict` or `list`) if the response parses as JSON, else the raw response text (a `str`).
  - Conditional node's *stored output* (available to later nodes via `{{node_id}}`) is the value it evaluated (pass-through) — **not** the boolean branch result. The branch decision is used only for routing, it is never stored as this node's "output" value.
  - WooCommerce Query node's output: always a formatted multi-line `str` (never a `dict`) — so only whole-value `{{node_id}}` substitution ever applies to it, `{{node_id.field}}` always resolves to the missing-marker for it.
- **No arbitrary code execution anywhere.** The Conditional node's condition is evaluated with a closed set of 4 operators (`contains` / `equals` / `is_empty` / `is_error`) applied to a single substituted string — never `eval()`/`exec()` on user input.
- **Connection credentials are stored as plain text** (`connections.config` is a plain JSON string, no field-level encryption) — consistent with this codebase's existing secret-handling norm (`webhook_secret`, `telegram_token`, `DASHBOARD_TOKEN` are all plain text, protected by the dashboard's own auth boundary). Do not introduce a new encryption mechanism. Connection credentials are **never** included in any API response after creation — list/get endpoints return only `id`, `name`, `type`, `created_at`.
- **No SSRF allowlist/denylist for the HTTP node.** This matches every other HTTP-calling tool already in this codebase (none of them restrict target URLs) and the single-trusted-administrator dashboard model. Do not add URL validation beyond what's needed for basic correctness (e.g. a well-formed URL).
- Every backend endpoint added under `agents.py` follows that file's existing conventions exactly: `if not _state.database: raise HTTPException(503, ...)`, `HTTPException(404, ...)` for a missing agent/flow/connection id.
- **Frontend node-canvas work (Tasks 11 and 13) requires an actual manual browser verification before being marked complete — `tsc --noEmit` alone is not sufficient for these two tasks.** This is called out explicitly because sub-project 1's equivalent frontend restructuring task skipped manual verification once, and it was flagged as that plan's single biggest unverified risk in its final review.

---

### Task 1: Migration 34 — `flows` + `connections` tables

**Files:**
- Modify: `src/openacm/storage/database.py:171` (bump `_SCHEMA_VERSION`), add a new migration block after the Migration 33 block (search `Migration 33: per-agent skill scoping`, add immediately after that block, before the "Save new version" comment)
- Test: `tests/unit/test_database_flows.py` (new)

**Interfaces:**
- Produces: `flows(id, agent_id, name, description, graph_json, is_active, created_at, updated_at)` table; `connections(id, agent_id, name, type, config, created_at)` table; both with `agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE` and an index on `agent_id`.

- [ ] **Step 1: Write the failing test**

```python
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
```

Read `Database.create_agent`'s actual current signature (`src/openacm/storage/database.py`, search `async def create_agent`) before running this — adjust `_make_agent` if it differs.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_database_flows.py -v`
Expected: FAIL — `flows`/`connections` tables don't exist yet.

- [ ] **Step 3: Write the migration**

In `src/openacm/storage/database.py`, change line 171:

```python
    _SCHEMA_VERSION = 34
```

Add this block right after the Migration 33 block (search for `log.info("Migration 33: per-agent skill scoping`, add immediately after that line, before the "Save new version" comment):

```python
        # ── Migration 34: agent node flows + reusable connections ────────
        # A Flow is a node graph (JSON) that becomes a dynamically-registered
        # tool for its owning agent. A Connection is a reusable set of
        # credentials (e.g. a WooCommerce store's API keys) a flow's nodes
        # can reference, so the same store doesn't need re-entering per flow.
        # Both are 100% private to one agent (ON DELETE CASCADE, no sharing).
        if current < 34:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS flows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    graph_json TEXT NOT NULL DEFAULT '{"nodes":[],"edges":[]}',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_flows_agent ON flows(agent_id);

                CREATE TABLE IF NOT EXISTS connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    config TEXT NOT NULL DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_connections_agent ON connections(agent_id);
            """)
            await self._db.commit()
            log.info("Migration 34: agent node flows (flows, connections)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_database_flows.py -v`
Expected: PASS (5/5)

- [ ] **Step 5: Run the existing database tests to confirm no regression**

Run: `pytest tests/unit/test_database.py tests/unit/test_database_agent_skills.py -q`
Expected: all still pass.

- [ ] **Step 6: Commit**

```bash
git add src/openacm/storage/database.py tests/unit/test_database_flows.py
git commit -m "feat(db): add migration 34 — flows + connections tables for agent node flows"
```

---

### Task 2: Database CRUD — flows and connections

**Files:**
- Modify: `src/openacm/storage/database.py`
- Test: `tests/unit/test_database_flows.py` (extend from Task 1)

**Interfaces:**
- Consumes: schema from Task 1.
- Produces:
  - `Database.create_flow(agent_id: int, name: str, description: str = "", graph_json: str = '{"nodes":[],"edges":[]}') -> int`
  - `Database.get_flow(flow_id: int) -> dict[str, Any] | None`
  - `Database.get_agent_flows(agent_id: int, active_only: bool = False) -> list[dict[str, Any]]`
  - `Database.update_flow(flow_id: int, **kwargs) -> bool` (allowed keys: `name`, `description`, `graph_json`, `is_active`)
  - `Database.delete_flow(flow_id: int) -> bool`
  - `Database.create_connection(agent_id: int, name: str, type: str, config: str) -> int`
  - `Database.get_connection(connection_id: int) -> dict[str, Any] | None` (includes `config` — used internally by `FlowExecutor`, never returned by an API list endpoint)
  - `Database.get_agent_connections(agent_id: int) -> list[dict[str, Any]]` (excludes `config` — safe for API responses)
  - `Database.update_connection(connection_id: int, **kwargs) -> bool` (allowed keys: `name`, `config`)
  - `Database.delete_connection(connection_id: int) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database_flows.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_database_flows.py::TestFlowCRUD tests/unit/test_database_flows.py::TestConnectionCRUD -v`
Expected: FAIL — none of these methods exist on `Database` yet.

- [ ] **Step 3: Implement**

Add these methods to `src/openacm/storage/database.py`, in a new section after the Skills section (search for the end of `disable_agent_skill`, or any convenient point before `# ─── Settings ─────`):

```python
    # ─── Agent Node Flows ───────────────────────────────────

    async def create_flow(
        self,
        agent_id: int,
        name: str,
        description: str = "",
        graph_json: str = '{"nodes":[],"edges":[]}',
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO flows (agent_id, name, description, graph_json) VALUES (?, ?, ?, ?)",
            (agent_id, name, description, graph_json),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_flow(self, flow_id: int) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM flows WHERE id = ?", (flow_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_agent_flows(self, agent_id: int, active_only: bool = False) -> list[dict[str, Any]]:
        if not self._db:
            return []
        query = "SELECT * FROM flows WHERE agent_id = ?"
        if active_only:
            query += " AND is_active = 1"
        query += " ORDER BY name"
        cursor = await self._db.execute(query, (agent_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_flow(self, flow_id: int, **kwargs: Any) -> bool:
        if not self._db:
            return False
        allowed = {"name", "description", "graph_json", "is_active"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(val)
        if not updates:
            return False
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(flow_id)
        cursor = await self._db.execute(
            f"UPDATE flows SET {', '.join(updates)} WHERE id = ?", params
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_flow(self, flow_id: int) -> bool:
        if not self._db:
            return False
        cursor = await self._db.execute("DELETE FROM flows WHERE id = ?", (flow_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    # ─── Agent Connections ────────────────────────────────────

    async def create_connection(self, agent_id: int, name: str, type: str, config: str) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO connections (agent_id, name, type, config) VALUES (?, ?, ?, ?)",
            (agent_id, name, type, config),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_connection(self, connection_id: int) -> dict[str, Any] | None:
        """Includes config — for internal use by FlowExecutor only, never
        return this directly from an API list/get endpoint."""
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM connections WHERE id = ?", (connection_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_agent_connections(self, agent_id: int) -> list[dict[str, Any]]:
        """Excludes config — safe to return from an API response."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT id, agent_id, name, type, created_at FROM connections WHERE agent_id = ? ORDER BY name",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_connection(self, connection_id: int, **kwargs: Any) -> bool:
        if not self._db:
            return False
        allowed = {"name", "config"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(val)
        if not updates:
            return False
        params.append(connection_id)
        cursor = await self._db.execute(
            f"UPDATE connections SET {', '.join(updates)} WHERE id = ?", params
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_connection(self, connection_id: int) -> bool:
        if not self._db:
            return False
        cursor = await self._db.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
        await self._db.commit()
        return cursor.rowcount > 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_database_flows.py -v`
Expected: PASS (all tests from Task 1 and Task 2)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/storage/database.py tests/unit/test_database_flows.py
git commit -m "feat(db): flow + connection CRUD methods"
```

---

### Task 3: FlowExecutor core — template substitution, Start/End nodes, linear walk

**Files:**
- Create: `src/openacm/core/flow_executor.py`
- Test: `tests/unit/test_flow_executor.py` (new)

**Interfaces:**
- Produces:
  - `substitute_templates(template: str, params: dict[str, Any], outputs: dict[str, Any]) -> str`
  - `class FlowExecutor:` with `async def run(self, graph: dict, params: dict) -> str`
  - `FlowExecutor._HANDLERS: dict[str, Callable]` — a dispatch table, populated with only `{}` in this task (Start/End are handled directly by the main loop, not via `_HANDLERS`, since they're structural, not "processing" nodes). Later tasks (4, 5, 6) each add one entry: `"http"`, `"conditional"`, `"woocommerce"`.
- This task's `run()` must correctly execute a flow with ONLY a Start and an End node (no processing nodes in between) — this is the minimal, fully-working slice; later tasks add real node types on top without changing this task's code paths.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for FlowExecutor's core mechanics: template substitution and the
minimal Start-to-End graph walk. Node-type-specific handlers (HTTP,
Conditional, WooCommerce) are tested in their own dedicated test files."""
from openacm.core.flow_executor import FlowExecutor, substitute_templates


class TestSubstituteTemplates:
    def test_bare_param_name_substitutes_whole_value(self):
        result = substitute_templates("Hello {{name}}", params={"name": "Ana"}, outputs={})
        assert result == "Hello Ana"

    def test_bare_node_id_substitutes_whole_output(self):
        result = substitute_templates("Result: {{http1}}", params={}, outputs={"http1": "some text"})
        assert result == "Result: some text"

    def test_node_id_dot_field_looks_up_json_key(self):
        result = substitute_templates(
            "Price: {{http1.price}}", params={}, outputs={"http1": {"price": "19.99", "name": "Widget"}}
        )
        assert result == "Price: 19.99"

    def test_dot_field_on_non_dict_output_is_missing_marker(self):
        result = substitute_templates(
            "{{woo1.price}}", params={}, outputs={"woo1": "Search results for 'x':\n- Product: Widget"}
        )
        assert result == "[missing: woo1.price]"

    def test_dot_field_not_a_key_in_dict_is_missing_marker(self):
        result = substitute_templates(
            "{{http1.nonexistent}}", params={}, outputs={"http1": {"price": "19.99"}}
        )
        assert result == "[missing: http1.nonexistent]"

    def test_unknown_bare_name_is_missing_marker(self):
        result = substitute_templates("{{unknown}}", params={}, outputs={})
        assert result == "[missing: unknown]"

    def test_param_takes_priority_over_a_same_named_node_output(self):
        # params and outputs are separate namespaces for bare (no-dot) lookups;
        # params checked first per the spec's documented precedence.
        result = substitute_templates("{{x}}", params={"x": "from-param"}, outputs={"x": "from-node"})
        assert result == "from-param"

    def test_multiple_substitutions_in_one_template(self):
        result = substitute_templates(
            "{{name}} bought {{http1.item}}", params={"name": "Ana"}, outputs={"http1": {"item": "Widget"}}
        )
        assert result == "Ana bought Widget"


class TestFlowExecutorStartToEnd:
    async def test_minimal_start_to_end_flow_returns_end_template(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": [{"name": "producto", "type": "string", "required": True}]}},
                {"id": "end", "type": "end", "config": {"template": "You asked about {{producto}}"}},
            ],
            "edges": [{"from": "start", "to": "end", "fromHandle": "default"}],
        }
        executor = FlowExecutor()

        result = await executor.run(graph, params={"producto": "zapatos"})

        assert result == "You asked about zapatos"

    async def test_missing_required_param_returns_error_without_running(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": [{"name": "producto", "type": "string", "required": True}]}},
                {"id": "end", "type": "end", "config": {"template": "{{producto}}"}},
            ],
            "edges": [{"from": "start", "to": "end", "fromHandle": "default"}],
        }
        executor = FlowExecutor()

        result = await executor.run(graph, params={})

        assert "producto" in result
        assert result.startswith("Error")

    async def test_flow_with_no_start_node_returns_error(self):
        graph = {"nodes": [{"id": "end", "type": "end", "config": {"template": "x"}}], "edges": []}
        executor = FlowExecutor()

        result = await executor.run(graph, params={})

        assert result.startswith("Error")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: FAIL — `openacm.core.flow_executor` doesn't exist yet.

- [ ] **Step 3: Implement**

Create `src/openacm/core/flow_executor.py`:

```python
"""
FlowExecutor — interprets a node-graph flow (built visually by the user)
and runs it as a tool call for an Agent.

A flow is a linear chain of nodes with exactly one possible branch point
(a Conditional node, which has two outgoing edges: "true" and "false").
There are no loops, no multi-input nodes, and no rejoined branches — see
docs/superpowers/specs/2026-07-05-agent-node-flows-design.md for the full
design rationale.
"""
import re
from typing import Any, Callable, Coroutine

_TEMPLATE_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)(?:\.([a-zA-Z0-9_]+))?\}\}")


def substitute_templates(template: str, params: dict[str, Any], outputs: dict[str, Any]) -> str:
    """Replace {{name}} / {{node_id.field}} references in template.

    {{name}} (no dot): checks params first, then node outputs, for an exact
    key match — substitutes the whole value (stringified) if found in
    either, else the literal marker "[missing: name]".

    {{node_id.field}} (with a dot): only looks in node outputs. If that
    node's output is a dict and field is one of its keys, substitutes that
    key's value (stringified); in every other case (unknown node_id,
    non-dict output, or field not a key), substitutes
    "[missing: node_id.field]" — never a silent empty string.
    """
    def _replace(match: re.Match) -> str:
        name, field = match.group(1), match.group(2)
        if field is None:
            if name in params:
                return str(params[name])
            if name in outputs:
                return str(outputs[name])
            return f"[missing: {name}]"
        value = outputs.get(name)
        if isinstance(value, dict) and field in value:
            return str(value[field])
        return f"[missing: {name}.{field}]"

    return _TEMPLATE_RE.sub(_replace, template)


class FlowExecutor:
    """Interprets and runs one flow's graph_json against a set of params."""

    def __init__(self, get_connection: Callable[[int], Coroutine[Any, Any, dict | None]] | None = None):
        self.get_connection = get_connection
        self._HANDLERS: dict[str, Callable] = {}

    async def run(self, graph: dict, params: dict) -> str:
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        edges_by_source: dict[str, dict[str, str]] = {}
        for edge in graph.get("edges", []):
            edges_by_source.setdefault(edge["from"], {})[edge.get("fromHandle", "default")] = edge["to"]

        start_node = next((n for n in nodes.values() if n["type"] == "start"), None)
        if not start_node:
            return "Error: flow has no Start node"

        for param_def in start_node["config"].get("parameters", []):
            if param_def.get("required") and param_def["name"] not in params:
                return f"Error: missing required parameter '{param_def['name']}'"

        outputs: dict[str, Any] = {}
        current_id = edges_by_source.get(start_node["id"], {}).get("default")

        while current_id:
            node = nodes.get(current_id)
            if node is None:
                return f"Error: flow references unknown node '{current_id}'"

            if node["type"] == "end":
                template = node["config"].get("template", "")
                return substitute_templates(template, params, outputs)

            handler = self._HANDLERS.get(node["type"])
            if handler is None:
                return f"Error: unknown node type '{node['type']}'"

            try:
                result = await handler(self, node, params, outputs)
            except Exception as exc:
                return f"Error in node '{node['id']}' ({node['type']}): {exc}"

            if node["type"] == "conditional":
                outputs[node["id"]] = result["passthrough"]
                current_id = edges_by_source.get(node["id"], {}).get("true" if result["branch"] else "false")
            else:
                outputs[node["id"]] = result
                current_id = edges_by_source.get(node["id"], {}).get("default")

        return "Error: flow ended without reaching an End node"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (11/11)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): FlowExecutor core — template substitution + Start/End graph walk"
```

---

### Task 4: FlowExecutor — HTTP Request node

**Files:**
- Modify: `src/openacm/core/flow_executor.py`
- Test: `tests/unit/test_flow_executor.py` (extend)

**Interfaces:**
- Consumes: `FlowExecutor` core from Task 3.
- Produces: `FlowExecutor._run_http_node(self, node: dict, params: dict, outputs: dict) -> Any` registered in `_HANDLERS["http"]`. Output: parsed JSON (`dict`/`list`) if the response is JSON, else raw text (`str`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flow_executor.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch


def _http_graph(url="https://example.com/api", method="GET", headers=None, body=None):
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": []}},
            {"id": "http1", "type": "http", "config": {"url": url, "method": method, "headers": headers or {}, "body": body}},
            {"id": "end", "type": "end", "config": {"template": "{{http1.status}}"}},
        ],
        "edges": [
            {"from": "start", "to": "http1", "fromHandle": "default"},
            {"from": "http1", "to": "end", "fromHandle": "default"},
        ],
    }


class TestHttpNode:
    async def test_json_response_is_parsed_and_fields_are_addressable(self):
        graph = _http_graph()
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(graph, params={})

        assert result == "ok"

    async def test_non_json_response_is_raw_text_and_has_no_dot_fields(self):
        graph = _http_graph()
        graph["nodes"][2]["config"]["template"] = "{{http1}}"
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "plain body"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(graph, params={})

        assert result == "plain body"

    async def test_http_error_stops_the_flow_and_returns_an_error_string(self):
        graph = _http_graph()
        mock_client = AsyncMock()
        mock_client.request.side_effect = Exception("connection refused")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(graph, params={})

        assert result.startswith("Error in node 'http1'")
        assert "connection refused" in result

    async def test_url_and_body_support_template_substitution(self):
        graph = _http_graph(url="https://example.com/{{producto}}", body='{"q": "{{producto}}"}')
        graph["nodes"][0]["config"]["parameters"] = [{"name": "producto", "type": "string", "required": True}]
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client) as mock_cls:
            executor = FlowExecutor()
            await executor.run(graph, params={"producto": "zapatos"})

        call_kwargs = mock_client.request.call_args
        assert "zapatos" in call_kwargs.args[1] or "zapatos" in str(call_kwargs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestHttpNode -v`
Expected: FAIL — `"http"` isn't a registered handler, and `httpx` isn't imported in `flow_executor.py` yet.

- [ ] **Step 3: Implement**

In `src/openacm/core/flow_executor.py`, add `import httpx` at the top (alongside the existing `import re`), and add this method to `FlowExecutor`, then register it in `__init__`:

```python
    async def _run_http_node(self, node: dict, params: dict, outputs: dict) -> Any:
        cfg = node["config"]
        url = substitute_templates(cfg["url"], params, outputs)
        method = cfg.get("method", "GET").upper()
        headers = {k: substitute_templates(v, params, outputs) for k, v in (cfg.get("headers") or {}).items()}
        body = cfg.get("body")
        if body:
            body = substitute_templates(body, params, outputs)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(method, url, headers=headers, content=body)
            response.raise_for_status()
            try:
                return response.json()
            except Exception:
                return response.text
```

Update `__init__` to register it:

```python
    def __init__(self, get_connection: Callable[[int], Coroutine[Any, Any, dict | None]] | None = None):
        self.get_connection = get_connection
        self._HANDLERS: dict[str, Callable] = {"http": FlowExecutor._run_http_node}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests, Task 3 + Task 4)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): FlowExecutor HTTP Request node"
```

---

### Task 5: FlowExecutor — Conditional node + branching

**Files:**
- Modify: `src/openacm/core/flow_executor.py`
- Test: `tests/unit/test_flow_executor.py` (extend)

**Interfaces:**
- Consumes: `FlowExecutor` core + branching logic already in Task 3's `run()` (the `if node["type"] == "conditional":` branch-routing code already exists — this task only needs to add the handler that PRODUCES the `{"branch": bool, "passthrough": Any}` shape that code expects).
- Produces: `FlowExecutor._run_conditional_node(self, node, params, outputs) -> dict` returning `{"branch": bool, "passthrough": Any}`, registered in `_HANDLERS["conditional"]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flow_executor.py`:

```python
def _conditional_graph(operator, value, field="{{start_value}}"):
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": [{"name": "start_value", "type": "string", "required": True}]}},
            {"id": "cond1", "type": "conditional", "config": {"field": field, "operator": operator, "value": value}},
            {"id": "end_true", "type": "end", "config": {"template": "YES: {{cond1}}"}},
            {"id": "end_false", "type": "end", "config": {"template": "NO: {{cond1}}"}},
        ],
        "edges": [
            {"from": "start", "to": "cond1", "fromHandle": "default"},
            {"from": "cond1", "to": "end_true", "fromHandle": "true"},
            {"from": "cond1", "to": "end_false", "fromHandle": "false"},
        ],
    }


class TestConditionalNode:
    async def test_contains_operator_true_branch(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("contains", "zap"), params={"start_value": "zapatos"})
        assert result == "YES: zapatos"

    async def test_contains_operator_false_branch(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("contains", "camisa"), params={"start_value": "zapatos"})
        assert result == "NO: zapatos"

    async def test_equals_operator(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("equals", "zapatos"), params={"start_value": "zapatos"})
        assert result == "YES: zapatos"

    async def test_is_empty_operator_true(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("is_empty", ""), params={"start_value": ""})
        assert result == "YES: "

    async def test_is_empty_operator_false(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("is_empty", ""), params={"start_value": "zapatos"})
        assert result == "NO: zapatos"

    async def test_is_error_operator(self):
        graph = _conditional_graph("is_error", "", field="{{prev}}")
        graph["nodes"][0]["config"]["parameters"] = []
        graph["nodes"][1]["config"]["field"] = "{{missing_node}}"
        executor = FlowExecutor()
        result = await executor.run(graph, params={})
        # "{{missing_node}}" resolves to "[missing: missing_node]" which starts with neither
        # "error" — this exercises is_error's false path using the missing-marker text itself.
        assert result == "NO: [missing: missing_node]"

    async def test_unknown_operator_is_an_error(self):
        graph = _conditional_graph("bogus_operator", "x")
        executor = FlowExecutor()
        result = await executor.run(graph, params={"start_value": "zapatos"})
        assert result.startswith("Error in node 'cond1'")

    async def test_passthrough_output_is_the_evaluated_value_not_the_boolean(self):
        executor = FlowExecutor()
        result = await executor.run(_conditional_graph("contains", "zap"), params={"start_value": "zapatos"})
        # end_true's template is "YES: {{cond1}}" — if the stored output were the
        # boolean True/False instead of the passthrough string, this would read "YES: True".
        assert result == "YES: zapatos"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestConditionalNode -v`
Expected: FAIL — `"conditional"` isn't a registered handler yet.

- [ ] **Step 3: Implement**

Add this method to `FlowExecutor` in `src/openacm/core/flow_executor.py`:

```python
    _CONDITIONAL_OPERATORS = {"contains", "equals", "is_empty", "is_error"}

    async def _run_conditional_node(self, node: dict, params: dict, outputs: dict) -> dict:
        cfg = node["config"]
        operator = cfg["operator"]
        if operator not in self._CONDITIONAL_OPERATORS:
            raise ValueError(f"Unknown conditional operator: {operator}")

        resolved = substitute_templates(cfg["field"], params, outputs)
        compare_value = cfg.get("value", "")

        if operator == "contains":
            branch = compare_value in resolved
        elif operator == "equals":
            branch = resolved == compare_value
        elif operator == "is_empty":
            branch = resolved == ""
        else:  # is_error
            branch = resolved.lower().startswith("error")

        return {"branch": branch, "passthrough": resolved}
```

Update `__init__`'s `_HANDLERS` dict:

```python
        self._HANDLERS: dict[str, Callable] = {
            "http": FlowExecutor._run_http_node,
            "conditional": FlowExecutor._run_conditional_node,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests, Tasks 3-5)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): FlowExecutor Conditional node + branching"
```

---

### Task 6: FlowExecutor — WooCommerce Query node

**Files:**
- Modify: `src/openacm/core/flow_executor.py`
- Test: `tests/unit/test_flow_executor.py` (extend)

**Interfaces:**
- Consumes: `FlowExecutor` core from Task 3, `get_connection: Callable[[int], Awaitable[dict | None]]` constructor param (already present, unused until now).
- Produces: `FlowExecutor._run_woocommerce_node(self, node, params, outputs) -> str`, registered in `_HANDLERS["woocommerce"]`. Response-formatting logic is a direct port of the reference implementation (`git show 0dffcbf -- src/openacm/tools/woocommerce.py` on this repo's already-fetched `Cristian/woocommerce` ref) — same top-5-results, name/price/stock/truncated-300-char-description/permalink format.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flow_executor.py`:

```python
import json as _json


def _woo_graph(connection_id=1, search_term="{{producto}}"):
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": [{"name": "producto", "type": "string", "required": True}]}},
            {"id": "woo1", "type": "woocommerce", "config": {"connection_id": connection_id, "search_term": search_term}},
            {"id": "end", "type": "end", "config": {"template": "{{woo1}}"}},
        ],
        "edges": [
            {"from": "start", "to": "woo1", "fromHandle": "default"},
            {"from": "woo1", "to": "end", "fromHandle": "default"},
        ],
    }


def _connection_row(url="https://tienda.example.com", ck="ck_123", cs="cs_456"):
    return {"id": 1, "config": _json.dumps({"url": url, "consumer_key": ck, "consumer_secret": cs})}


class TestWooCommerceNode:
    async def test_formats_top_5_products(self):
        products = [
            {"name": "Zapatos rojos", "price": "49.99", "stock_quantity": 3, "manage_stock": True,
             "short_description": "<p>Comodos y <b>bonitos</b></p>", "permalink": "https://tienda.example.com/zapatos-rojos"},
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = products
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        async def get_connection(conn_id):
            return _connection_row()

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            result = await executor.run(_woo_graph(), params={"producto": "zapatos"})

        assert "Zapatos rojos" in result
        assert "$49.99" in result
        assert "Comodos y bonitos" in result  # HTML stripped
        assert "https://tienda.example.com/zapatos-rojos" in result

    async def test_no_products_found_message(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        async def get_connection(conn_id):
            return _connection_row()

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            result = await executor.run(_woo_graph(), params={"producto": "inexistente"})

        assert "No products found" in result

    async def test_missing_connection_is_an_error(self):
        async def get_connection(conn_id):
            return None

        executor = FlowExecutor(get_connection=get_connection)
        result = await executor.run(_woo_graph(), params={"producto": "zapatos"})

        assert result.startswith("Error in node 'woo1'")

    async def test_no_get_connection_configured_is_an_error(self):
        executor = FlowExecutor()  # get_connection defaults to None
        result = await executor.run(_woo_graph(), params={"producto": "zapatos"})

        assert result.startswith("Error in node 'woo1'")

    async def test_search_uses_basic_auth_with_connection_credentials(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        async def get_connection(conn_id):
            return _connection_row(ck="my_key", cs="my_secret")

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            await executor.run(_woo_graph(), params={"producto": "x"})

        _, call_kwargs = mock_client.get.call_args
        assert call_kwargs["auth"] == ("my_key", "my_secret")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestWooCommerceNode -v`
Expected: FAIL — `"woocommerce"` isn't a registered handler yet.

- [ ] **Step 3: Implement**

Add `import re` is already present; add this method to `FlowExecutor` in `src/openacm/core/flow_executor.py` — response-formatting logic ported directly from the reference `woocommerce_search` implementation:

```python
    async def _run_woocommerce_node(self, node: dict, params: dict, outputs: dict) -> str:
        cfg = node["config"]
        search_term = substitute_templates(cfg["search_term"], params, outputs)

        if not self.get_connection:
            raise RuntimeError("No connection lookup configured for this flow executor")

        connection = await self.get_connection(cfg["connection_id"])
        if not connection:
            raise RuntimeError(f"Connection {cfg['connection_id']} not found")

        import json as _json
        conn_config = _json.loads(connection["config"])
        woo_url = conn_config["url"].rstrip("/")
        if not woo_url.endswith("/wp-json/wc/v3/products"):
            woo_url += "/wp-json/wc/v3/products"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                woo_url,
                params={"search": search_term},
                auth=(conn_config["consumer_key"], conn_config["consumer_secret"]),
            )
            response.raise_for_status()
            products = response.json()

        if not products:
            return f"No products found for query: '{search_term}'."

        output = [f"Search results for '{search_term}':"]
        for p in products[:5]:
            stock = p.get("stock_quantity")
            stock_text = str(stock) if stock is not None else ("In stock" if p.get("manage_stock") is False else "Out of stock")

            raw_desc = p.get("short_description") or p.get("description", "")
            clean_desc = re.sub(r"<[^>]+>", " ", raw_desc).strip()
            clean_desc = re.sub(r"\s+", " ", clean_desc)

            output.append(f"- Product: {p.get('name')}")
            output.append(f"  Price: ${p.get('price')}")
            output.append(f"  Stock: {stock_text}")
            if clean_desc:
                shortened = clean_desc[:300] + "..." if len(clean_desc) > 300 else clean_desc
                output.append(f"  Description: {shortened}")
            output.append(f"  Link: {p.get('permalink')}")

        return "\n".join(output)
```

Update `__init__`'s `_HANDLERS` dict:

```python
        self._HANDLERS: dict[str, Callable] = {
            "http": FlowExecutor._run_http_node,
            "conditional": FlowExecutor._run_conditional_node,
            "woocommerce": FlowExecutor._run_woocommerce_node,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests, Tasks 3-6)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): FlowExecutor WooCommerce Query node"
```

---

### Task 7: API endpoints — flows

**Files:**
- Modify: `src/openacm/web/routers/agents.py`
- Test: `tests/unit/test_agents_flows_api.py` (new)

**Interfaces:**
- Consumes: `Database` methods from Task 2, `FlowExecutor` from Tasks 3-6.
- Produces: `GET /api/agents/{agent_id}/flows`, `GET /api/agents/{agent_id}/flows/{flow_id}`, `POST /api/agents/{agent_id}/flows`, `PUT /api/agents/{agent_id}/flows/{flow_id}`, `DELETE /api/agents/{agent_id}/flows/{flow_id}`, `POST /api/agents/{agent_id}/flows/{flow_id}/test`.

Read `src/openacm/web/routers/agents.py`'s existing skill endpoints (`get_agent_skills`, `enable_agent_skill`, etc. — added in the prior sub-project's Task 4) first, for this file's exact conventions. Route ordering matters: register `/flows/{flow_id}/test` (or ensure FastAPI's routing correctly resolves it) — since `test` isn't purely static text but part of a nested path under an already-`int`-typed `{flow_id}`, there's no static-vs-dynamic collision risk here the way `/skills/generate` vs `/skills/{skill_id}` had, but register routes in the order shown below regardless, for consistency with this file's established layout.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for per-agent flow API endpoints under the agents router."""
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


FLOW_ROW = {
    "id": 7, "agent_id": 42, "name": "check-website", "description": "Checks a URL",
    "graph_json": '{"nodes":[{"id":"start","type":"start","config":{"parameters":[]}},'
                  '{"id":"end","type":"end","config":{"template":"done"}}],'
                  '"edges":[{"from":"start","to":"end","fromHandle":"default"}]}',
    "is_active": 1, "created_at": "2026-01-01", "updated_at": "2026-01-01",
}


@pytest.fixture(autouse=True)
def _mock_state(monkeypatch):
    db = MagicMock()
    db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
    db.get_flow = AsyncMock(return_value=FLOW_ROW)
    db.create_flow = AsyncMock(return_value=8)
    db.update_flow = AsyncMock(return_value=True)
    db.delete_flow = AsyncMock(return_value=True)
    db.get_connection = AsyncMock(return_value=None)
    monkeypatch.setattr(_state, "database", db)
    yield db
    monkeypatch.setattr(_state, "database", None)


class TestListAndGetFlows:
    async def test_list_flows(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/flows")
        assert resp.status_code == 200
        assert resp.json()[0]["name"] == "check-website"

    async def test_get_flow_detail_includes_graph_json(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/flows/7")
        assert resp.status_code == 200
        assert "graph_json" in resp.json()

    async def test_get_missing_flow_404s(self, app_client, _mock_state):
        _mock_state.get_flow.return_value = None
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/flows/999")
        assert resp.status_code == 404


class TestCreateUpdateDeleteFlow:
    async def test_create_flow(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows", json={"name": "new-flow", "description": "d"})
        assert resp.status_code == 200
        _mock_state.create_flow.assert_awaited_once()

    async def test_update_flow(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/flows/7", json={"graph_json": '{"nodes":[],"edges":[]}'})
        assert resp.status_code == 200
        _mock_state.update_flow.assert_awaited_once()

    async def test_update_missing_flow_404s(self, app_client, _mock_state):
        _mock_state.update_flow.return_value = False
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/flows/999", json={"name": "x"})
        assert resp.status_code == 404

    async def test_delete_flow(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.delete("/api/agents/42/flows/7")
        assert resp.status_code == 200
        _mock_state.delete_flow.assert_awaited_once_with(7)


class TestTestFlowEndpoint:
    async def test_runs_the_flow_with_given_params(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/test", json={"params": {}})
        assert resp.status_code == 200
        assert resp.json()["result"] == "done"

    async def test_missing_flow_404s(self, app_client, _mock_state):
        _mock_state.get_flow.return_value = None
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/999/test", json={"params": {}})
        assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agents_flows_api.py -v`
Expected: FAIL — 404s, the endpoints don't exist yet.

- [ ] **Step 3: Implement**

In `src/openacm/web/routers/agents.py`, add a new section after the existing Skills endpoints (search for `disable_agent_skill`/`generate_agent_skill_endpoint`, add immediately after that section):

```python
    # ─── Flows ──────────────────────────────────────────────

    @app.get("/api/agents/{agent_id}/flows")
    async def list_agent_flows(agent_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        return await _state.database.get_agent_flows(agent_id)

    @app.get("/api/agents/{agent_id}/flows/{flow_id}")
    async def get_agent_flow(agent_id: int, flow_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        flow = await _state.database.get_flow(flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        return flow

    @app.post("/api/agents/{agent_id}/flows")
    async def create_agent_flow(agent_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        flow_id = await _state.database.create_flow(
            agent_id=agent_id,
            name=data.get("name", "Untitled flow"),
            description=data.get("description", ""),
        )
        return await _state.database.get_flow(flow_id)

    @app.put("/api/agents/{agent_id}/flows/{flow_id}")
    async def update_agent_flow(agent_id: int, flow_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        allowed_fields = {"name", "description", "graph_json", "is_active"}
        kwargs = {k: v for k, v in data.items() if k in allowed_fields}
        ok = await _state.database.update_flow(flow_id, **kwargs)
        if not ok:
            raise HTTPException(status_code=404, detail="Flow not found")
        return await _state.database.get_flow(flow_id)

    @app.delete("/api/agents/{agent_id}/flows/{flow_id}")
    async def delete_agent_flow(agent_id: int, flow_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        ok = await _state.database.delete_flow(flow_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Flow not found")
        return {"status": "ok", "deleted": True}

    @app.post("/api/agents/{agent_id}/flows/{flow_id}/test")
    async def test_agent_flow(agent_id: int, flow_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        flow = await _state.database.get_flow(flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")

        from openacm.core.flow_executor import FlowExecutor
        import json as _json

        data = await request.json()
        test_params = data.get("params", {})

        async def get_connection(connection_id: int):
            return await _state.database.get_connection(connection_id)

        executor = FlowExecutor(get_connection=get_connection)
        graph = _json.loads(flow["graph_json"])
        result = await executor.run(graph, test_params)
        return {"result": result}
```

Confirm `Request`/`HTTPException` are already imported at the top of `agents.py` (they are, used extensively already).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agents_flows_api.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/web/routers/agents.py tests/unit/test_agents_flows_api.py
git commit -m "feat(api): agent flow endpoints — CRUD + test execution"
```

---

### Task 8: API endpoints — connections

**Files:**
- Modify: `src/openacm/web/routers/agents.py`
- Test: `tests/unit/test_agents_connections_api.py` (new)

**Interfaces:**
- Consumes: `Database` connection methods from Task 2.
- Produces: `GET /api/agents/{agent_id}/connections`, `POST /api/agents/{agent_id}/connections`, `PUT /api/agents/{agent_id}/connections/{id}`, `DELETE /api/agents/{agent_id}/connections/{id}`.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for per-agent connection API endpoints — credentials must never
appear in a response after creation."""
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
def _mock_state(monkeypatch):
    db = MagicMock()
    db.get_agent_connections = AsyncMock(return_value=[{"id": 1, "agent_id": 42, "name": "Mi Tienda", "type": "woocommerce", "created_at": "2026-01-01"}])
    db.create_connection = AsyncMock(return_value=2)
    db.update_connection = AsyncMock(return_value=True)
    db.delete_connection = AsyncMock(return_value=True)
    monkeypatch.setattr(_state, "database", db)
    yield db
    monkeypatch.setattr(_state, "database", None)


class TestListConnections:
    async def test_list_never_includes_config(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/connections")
        assert resp.status_code == 200
        body = resp.json()
        assert "config" not in body[0]
        assert body[0]["name"] == "Mi Tienda"


class TestCreateUpdateDeleteConnection:
    async def test_create_connection(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post(
                "/api/agents/42/connections",
                json={"name": "Mi Tienda", "type": "woocommerce", "url": "https://x.com", "consumer_key": "ck", "consumer_secret": "cs"},
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == 2
        # The created response must not echo the credentials back either.
        assert "consumer_secret" not in resp.json()
        _mock_state.create_connection.assert_awaited_once()

    async def test_update_connection(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/connections/1", json={"name": "Nueva Tienda"})
        assert resp.status_code == 200
        _mock_state.update_connection.assert_awaited_once()

    async def test_update_missing_connection_404s(self, app_client, _mock_state):
        _mock_state.update_connection.return_value = False
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/connections/999", json={"name": "x"})
        assert resp.status_code == 404

    async def test_delete_connection(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.delete("/api/agents/42/connections/1")
        assert resp.status_code == 200
        _mock_state.delete_connection.assert_awaited_once_with(1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agents_connections_api.py -v`
Expected: FAIL — endpoints don't exist yet.

- [ ] **Step 3: Implement**

In `src/openacm/web/routers/agents.py`, add right after the Flows section from Task 7:

```python
    # ─── Connections ────────────────────────────────────────

    @app.get("/api/agents/{agent_id}/connections")
    async def list_agent_connections(agent_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        return await _state.database.get_agent_connections(agent_id)

    @app.post("/api/agents/{agent_id}/connections")
    async def create_agent_connection(agent_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        import json as _json
        config = _json.dumps({
            "url": data.get("url", ""),
            "consumer_key": data.get("consumer_key", ""),
            "consumer_secret": data.get("consumer_secret", ""),
        })
        connection_id = await _state.database.create_connection(
            agent_id=agent_id, name=data.get("name", "Untitled connection"),
            type=data.get("type", "woocommerce"), config=config,
        )
        return {"id": connection_id, "name": data.get("name"), "type": data.get("type")}

    @app.put("/api/agents/{agent_id}/connections/{connection_id}")
    async def update_agent_connection(agent_id: int, connection_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        kwargs: dict = {}
        if "name" in data:
            kwargs["name"] = data["name"]
        if any(k in data for k in ("url", "consumer_key", "consumer_secret")):
            import json as _json
            kwargs["config"] = _json.dumps({
                "url": data.get("url", ""),
                "consumer_key": data.get("consumer_key", ""),
                "consumer_secret": data.get("consumer_secret", ""),
            })
        ok = await _state.database.update_connection(connection_id, **kwargs)
        if not ok:
            raise HTTPException(status_code=404, detail="Connection not found")
        return {"status": "ok"}

    @app.delete("/api/agents/{agent_id}/connections/{connection_id}")
    async def delete_agent_connection(agent_id: int, connection_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        ok = await _state.database.delete_connection(connection_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Connection not found")
        return {"status": "ok", "deleted": True}
```

Note `update_agent_connection`'s partial-config-overwrite behavior: if the caller sends ANY of `url`/`consumer_key`/`consumer_secret`, all three are re-written together (defaulting missing ones to `""`) rather than merged with the existing stored config — this matches the spec's "update = overwrite credentials" wording. The frontend task (Task 12) must always send the full credential set when editing, not a partial one, to avoid silently blanking fields.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agents_connections_api.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/web/routers/agents.py tests/unit/test_agents_connections_api.py
git commit -m "feat(api): agent connection endpoints — CRUD, credentials never returned"
```

---

### Task 9: Wire flow tools into agent execution

**Files:**
- Modify: `src/openacm/core/agent_runner.py`
- Test: `tests/unit/test_agent_runner_flows.py` (new)

**Interfaces:**
- Consumes: `Database.get_agent_flows(agent_id, active_only=True)` (Task 2), `Database.get_connection` (Task 2), `FlowExecutor` (Tasks 3-6), `ToolDefinition` (`src/openacm/tools/base.py` — already exists, unchanged).
- Produces: `AgentRunner.run()` now merges the agent's active flows into the tool set the LLM sees for that run, dispatched through a new wrapper class `_AgentToolRegistry` (defined in `agent_runner.py`) that **replaces** the existing conditional `_FilteredRegistry` block (same file, same method) — the new wrapper always applies (even when `allowed_tools == "all"`), since flow tools are additive regardless of the system-tool allowlist.

This is the most architecturally delicate task in this plan — read the "Important background" below fully before touching any code.

**Important background:** `ToolRegistry.execute()` (`src/openacm/tools/registry.py:340`) is only reached from `Brain`'s agentic loop (`src/openacm/core/brain_loop.py:231`) if `tool_name in self.tool_registry.tools` passes FIRST — this is a plain dict-membership check on the `.tools` attribute, done BEFORE `execute()` is ever called. The existing `_FilteredRegistry` class (being replaced by this task) does NOT define its own `.tools` — it relies on `__getattr__` to delegate to the real registry, meaning `.tools` today always resolves to the REAL, unfiltered global registry's tool dict. This task's new wrapper MUST expose an explicit `.tools` dict that includes the flow tools by name, or `brain_loop.py`'s gate check will reject any flow-tool call before it ever reaches this wrapper's `execute()` override.

- [ ] **Step 1: Write the failing tests**

```python
"""Test that AgentRunner.run() exposes the agent's active flows as callable
tools, dispatches flow-tool calls through FlowExecutor, and leaves an
agent with no flows completely unaffected (byte-identical to before this
change)."""
from unittest.mock import AsyncMock, MagicMock, patch
import json
import pytest
from openacm.core.agent_runner import AgentRunner

AGENT = {
    "id": 42, "name": "TestAgent", "description": "d",
    "system_prompt": "Base agent prompt.", "allowed_tools": "all",
}

FLOW_ROW = {
    "id": 7, "name": "check-availability", "description": "Checks product availability",
    "graph_json": json.dumps({
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": [{"name": "producto", "type": "string", "description": "product name", "required": True}]}},
            {"id": "end", "type": "end", "config": {"template": "Checked: {{producto}}"}},
        ],
        "edges": [{"from": "start", "to": "end", "fromHandle": "default"}],
    }),
}


def _make_runner(database=None):
    return AgentRunner(
        llm_router=MagicMock(), tool_registry=MagicMock(), memory=MagicMock(),
        event_bus=MagicMock(), database=database, skill_manager=None,
    )


class _FakeToolRegistry:
    def __init__(self):
        self.tools = {"some_static_tool": MagicMock()}

    def get_tools_schema(self):
        return [{"type": "function", "function": {"name": "some_static_tool"}}]

    def get_tools_by_intent(self, msg):
        return self.get_tools_schema()


class TestFlowToolsExposedToAgent:
    async def test_agents_active_flow_appears_in_the_tool_schema(self):
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        schema_names = {t["function"]["name"] for t in captured["tool_registry"].get_tools_schema()}
        assert "flow_7" in schema_names
        assert "some_static_tool" in schema_names  # existing static tools still present

    async def test_flow_tool_is_in_the_tools_membership_dict(self):
        """brain_loop.py gates on `tool_name in tool_registry.tools` before
        calling execute() — flow_7 must be a real key there, not just in
        the schema list."""
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        assert "flow_7" in captured["tool_registry"].tools
        assert "some_static_tool" in captured["tool_registry"].tools

    async def test_calling_the_flow_tool_runs_it_via_flow_executor(self):
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
        db.get_connection = AsyncMock(return_value=None)
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        result = await captured["tool_registry"].execute("flow_7", {"producto": "zapatos"})
        assert result == "Checked: zapatos"

    async def test_agent_with_no_flows_is_unaffected(self):
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[])
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        schema_names = {t["function"]["name"] for t in captured["tool_registry"].get_tools_schema()}
        assert schema_names == {"some_static_tool"}

    async def test_no_database_means_no_flow_tools_but_static_tools_still_work(self):
        runner = _make_runner(database=None)
        runner.tool_registry = _FakeToolRegistry()

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        schema_names = {t["function"]["name"] for t in captured["tool_registry"].get_tools_schema()}
        assert schema_names == {"some_static_tool"}

    async def test_allowed_tools_none_still_gets_no_tool_registry_at_all(self):
        """Existing behavior (from before this task) must be preserved:
        allowed_tools == 'none' passes tool_registry=None to Brain entirely."""
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()
        agent_none = {**AGENT, "allowed_tools": "none"}

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=agent_none, message="hi")

        assert captured["tool_registry"] is None
```

Read `AgentRunner.run()`'s exact current body (`src/openacm/core/agent_runner.py:69-149`, already reproduced in this brief's background section above) before writing this test — confirm exactly how `Brain(...)` is constructed and adjust `_FakeBrain`'s signature to match precisely if it's drifted since this plan was written.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agent_runner_flows.py -v`
Expected: FAIL — flow tools aren't wired in yet, `flow_7` isn't in any schema or `.tools` dict.

- [ ] **Step 3: Implement**

In `src/openacm/core/agent_runner.py`, add imports at the top:

```python
import json
```

(already imported — confirm, don't duplicate).

Add this new class in `agent_runner.py`, before the `AgentRunner` class:

```python
def _build_flow_tool(flow: dict, executor) -> ToolDefinition:
    """Convert one flow DB row into a dynamically-callable ToolDefinition."""
    graph = json.loads(flow["graph_json"])
    start_node = next((n for n in graph["nodes"] if n["type"] == "start"), None)
    properties: dict = {}
    required: list[str] = []
    for p in (start_node["config"].get("parameters", []) if start_node else []):
        properties[p["name"]] = {"type": p.get("type", "string"), "description": p.get("description", "")}
        if p.get("required"):
            required.append(p["name"])

    async def handler(_brain=None, **kwargs) -> str:
        call_params = {k: v for k, v in kwargs.items() if not k.startswith("_")}
        return await executor.run(graph, call_params)

    return ToolDefinition(
        name=f"flow_{flow['id']}",
        description=flow["description"] or flow["name"],
        parameters={"type": "object", "properties": properties, "required": required},
        handler=handler,
        risk_level="medium",
        category="custom_flow",
    )


class _AgentToolRegistry:
    """Wraps the shared, global tool registry for one AgentRunner.run() call:
    applies this agent's allowed_tools system-tool filter (unchanged from
    before this class existed) AND always adds this agent's active flow
    tools on top, regardless of that filter. Flow tools are agent-private
    and additive — they are never subject to the allowed_tools allowlist,
    which only ever applied to the shared static/system tool set.

    Exposes `.tools` explicitly (not via __getattr__) because Brain's
    agentic loop gates every tool call on `tool_name in tool_registry.tools`
    before calling execute() — see brain_loop.py."""

    def __init__(self, base_registry, filtered_schema: list[dict] | None, flow_tools: dict[str, "ToolDefinition"]):
        self._base = base_registry
        self._filtered_schema = filtered_schema
        self._flow_tools = flow_tools
        self.tools = {**getattr(base_registry, "tools", {}), **flow_tools}

    def get_tools_schema(self) -> list[dict]:
        base_schema = self._filtered_schema if self._filtered_schema is not None else self._base.get_tools_schema()
        return base_schema + [t.to_openai_schema() for t in self._flow_tools.values()]

    def get_tools_by_intent(self, message: str) -> list[dict]:
        base_schema = self._base.get_tools_by_intent(message)
        if self._filtered_schema is not None:
            allowed_names = {t["function"]["name"] for t in self._filtered_schema}
            base_schema = [t for t in base_schema if t["function"]["name"] in allowed_names]
        return base_schema + [t.to_openai_schema() for t in self._flow_tools.values()]

    async def execute(self, tool_name: str, arguments: dict, user_id: str = "", channel_id: str = "", channel_type: str = "web", _brain=None) -> str:
        if tool_name in self._flow_tools:
            return await self._flow_tools[tool_name].handler(_brain=_brain, **arguments)
        return await self._base.execute(tool_name, arguments, user_id, channel_id, channel_type, _brain=_brain)

    def __getattr__(self, name):
        return getattr(self._base, name)
```

Now replace the existing tool-registry-building block inside `AgentRunner.run()`. The current code (lines 120-137, reproduced from this task's background) is:

```python
        brain = Brain(
            config=config,
            llm_router=self.llm_router,
            memory=self.memory,
            event_bus=self.event_bus,
            tool_registry=self.tool_registry if agent.get("allowed_tools", "all") != "none" else None,
        )

        allowed = agent.get("allowed_tools", "all")
        if allowed not in ("all", "none"):
            _tools = self._get_tools(allowed)

            class _FilteredRegistry:
                def get_tools_schema(self_inner):
                    return _tools or []

                def get_tools_by_intent(self_inner, msg):
                    return _tools or []

                def __getattr__(self_inner, name):
                    return getattr(self.tool_registry, name)

            brain.tool_registry = _FilteredRegistry()
```

Replace it with:

```python
        allowed = agent.get("allowed_tools", "all")

        flow_tools: dict[str, ToolDefinition] = {}
        if self.database and allowed != "none":
            try:
                active_flows = await self.database.get_agent_flows(agent["id"], active_only=True)
            except Exception as exc:
                log.warning("AgentRunner: failed to fetch flows", agent_id=agent["id"], error=str(exc))
                active_flows = []
            if active_flows:
                from openacm.core.flow_executor import FlowExecutor

                async def get_connection(connection_id: int):
                    return await self.database.get_connection(connection_id)

                executor = FlowExecutor(get_connection=get_connection)
                flow_tools = {f"flow_{f['id']}": _build_flow_tool(f, executor) for f in active_flows}

        brain = Brain(
            config=config,
            llm_router=self.llm_router,
            memory=self.memory,
            event_bus=self.event_bus,
            tool_registry=self.tool_registry if allowed != "none" else None,
        )

        if allowed != "none" and (allowed not in ("all",) or flow_tools):
            filtered_schema = self._get_tools(allowed) if allowed not in ("all", "none") else None
            brain.tool_registry = _AgentToolRegistry(self.tool_registry, filtered_schema, flow_tools)
```

Add `from openacm.tools.base import ToolDefinition` to the imports at the top of `agent_runner.py`, alongside `import json`. This is safe: `tools/base.py` imports only `dataclasses`/`typing`, nothing from `core/`, so there is no import cycle. Use this top-level import for the `flow_tools: dict[str, ToolDefinition]` type annotation — the `import` inside `_build_flow_tool`'s body shown in the snippet above is then redundant and can be removed from that function (keep `ToolDefinition` imported once, at module level, not duplicated inside the function).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agent_runner_flows.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest -q`
Expected: no new failures beyond the known pre-existing 7 `gmail_classifier` errors. Pay special attention to `tests/unit/test_agent_runner_skills.py` (from the prior sub-project) — those tests must still pass unchanged, since this task rewrites the same method they cover.

- [ ] **Step 6: Commit**

```bash
git add src/openacm/core/agent_runner.py tests/unit/test_agent_runner_flows.py
git commit -m "feat(agents): expose each agent's active flows as dynamically-registered tools"
```

---

### Task 10: Frontend — add React Flow dependency, "Flujos" tab scaffold, flow list CRUD

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/app/agents/page.tsx`
- Create: `frontend/hooks/use-agent-flows.ts`

**Interfaces:**
- Produces: `@xyflow/react` added as a frontend dependency. `AgentFlow` interface, `useAgentFlows(agentId)`, `useCreateFlow(agentId)`, `useUpdateFlow(agentId)`, `useDeleteFlow(agentId)` hooks in `use-agent-flows.ts`. A 6th "Flujos" tab in `AgentDetailView`'s tab bar, rendering a `FlowsTab({ agentId }: { agentId: number })` component that lists flows (name, description, active toggle, Edit/Delete) — **no node canvas yet**, "Edit"/"+ New Flow" just create a blank flow row and show a placeholder ("Editor de nodos — Task 11") for now, replaced by the real canvas in Task 11.

- [ ] **Step 1: Add the dependency**

```bash
cd frontend && npm install @xyflow/react
```

- [ ] **Step 2: Create the flows hooks file**

Create `frontend/hooks/use-agent-flows.ts`:

```typescript
'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

export interface AgentFlow {
  id: number;
  agent_id: number;
  name: string;
  description: string;
  graph_json: string;
  is_active: number;
  created_at: string;
  updated_at: string;
}

export function useAgentFlows(agentId: number) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<AgentFlow[]>({
    queryKey: ['agent-flows', agentId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/flows`),
    enabled: isAuthenticated,
  });
}

export function useAgentFlow(agentId: number, flowId: number | null) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<AgentFlow>({
    queryKey: ['agent-flow', flowId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/flows/${flowId}`),
    enabled: isAuthenticated && flowId !== null,
  });
}

export function useCreateFlow(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      fetchAPI(`/api/agents/${agentId}/flows`, { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-flows', agentId] }),
  });
}

export function useUpdateFlow(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<Pick<AgentFlow, 'name' | 'description' | 'graph_json' | 'is_active'>> }) =>
      fetchAPI(`/api/agents/${agentId}/flows/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['agent-flows', agentId] });
      qc.invalidateQueries({ queryKey: ['agent-flow', vars.id] });
    },
  });
}

export function useDeleteFlow(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => fetchAPI(`/api/agents/${agentId}/flows/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-flows', agentId] }),
  });
}
```

Confirm `useAPI`/`useIsAuthenticated` are exported from `@/hooks/use-api` (they already are, used by every other hooks file this session touched) before finalizing this import line.

- [ ] **Step 3: Add the "Flujos" tab to `AgentDetailView`**

In `frontend/app/agents/page.tsx`, update the `activeTab` union type (search for `useState<'config' | 'knowledge' | 'channels' | 'tools' | 'skills'>`):

```typescript
  const [activeTab, setActiveTab] = useState<'config' | 'knowledge' | 'channels' | 'tools' | 'skills' | 'flows'>('config');
```

Add a 6th tab button right after the "Skills" button (search for `setActiveTab('skills')`, add immediately after that `<button>` element):

```typescript
        <button onClick={() => setActiveTab('flows')} className={cn('px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors', activeTab === 'flows' ? 'border-blue-500 text-blue-400' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>Flujos</button>
```

Add a rendering branch (search for `activeTab === 'skills' ? (`, note its structure, add a parallel branch for `'flows'` before the final `else` fallback):

```typescript
        ) : activeTab === 'flows' ? (
          <FlowsTab agentId={agent.id} />
        ) : (
```

- [ ] **Step 4: Implement `FlowsTab` (list + CRUD, no canvas yet)**

Add this component to `frontend/app/agents/page.tsx`, near the other Tab components (`AgentToolsTab`/`AgentSkillsTab`):

```typescript
function FlowsTab({ agentId }: { agentId: number }) {
  const { data: flows, isLoading } = useAgentFlows(agentId);
  const create = useCreateFlow(agentId);
  const update = useUpdateFlow(agentId);
  const del = useDeleteFlow(agentId);
  const [editingFlowId, setEditingFlowId] = useState<number | null>(null);

  if (isLoading || !flows) return <Loader2 size={16} className="animate-spin" />;

  const handleCreate = () => {
    create.mutate({ name: 'Nuevo flujo', description: '' }, {
      onSuccess: (created: any) => setEditingFlowId(created.id),
    });
  };

  if (editingFlowId !== null) {
    return (
      <div className="flex flex-col gap-2">
        <button onClick={() => setEditingFlowId(null)} className="btn-secondary self-start text-[11px] px-2 py-1">
          ← Volver a la lista
        </button>
        <div className="text-[12px]" style={{ color: 'var(--acm-fg-4)' }}>
          Editor de nodos — llega en la Tarea 11. (flow id: {editingFlowId})
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <button onClick={handleCreate} disabled={create.isPending} className="btn-secondary self-end text-[11px] px-2 py-1">
        + Nuevo flujo
      </button>
      {flows.length === 0 ? (
        <div className="text-[12px]" style={{ color: 'var(--acm-fg-4)' }}>Este agente no tiene flujos todavía.</div>
      ) : (
        flows.map(f => (
          <div key={f.id} className="flex items-center gap-2 py-1.5 px-2 rounded text-[12px]" style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}>
            <input
              type="checkbox"
              checked={!!f.is_active}
              onChange={() => update.mutate({ id: f.id, data: { is_active: f.is_active ? 0 : 1 } })}
              title="Activo"
            />
            <div className="flex-1">
              <div style={{ color: 'var(--acm-fg-2)' }}>{f.name}</div>
              {f.description && <div style={{ color: 'var(--acm-fg-4)' }}>{f.description}</div>}
            </div>
            <button onClick={() => setEditingFlowId(f.id)} className="btn-secondary text-[11px] px-2 py-1">Editar</button>
            <button onClick={() => del.mutate(f.id)} className="text-[var(--acm-fg-4)] hover:text-[var(--acm-err)]">
              <Trash2 size={12} />
            </button>
          </div>
        ))
      )}
    </div>
  );
}
```

Add the new import line for the flows hooks near the existing `use-agents`/`use-worker-config` imports at the top of the file:

```typescript
import { useAgentFlows, useCreateFlow, useUpdateFlow, useDeleteFlow } from '@/hooks/use-agent-flows';
```

- [ ] **Step 5: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/hooks/use-agent-flows.ts frontend/app/agents/page.tsx
git commit -m "feat(agents): Flujos tab scaffold — flow list CRUD, React Flow dependency added"
```

---

### Task 11: Frontend — visual node canvas (the node editor itself)

**Files:**
- Create: `frontend/components/flow-editor/FlowCanvas.tsx`
- Create: `frontend/components/flow-editor/node-types.tsx`
- Modify: `frontend/app/agents/page.tsx`

**Interfaces:**
- Consumes: `@xyflow/react` (Task 10), `AgentFlow` (Task 10), `useUpdateFlow` (Task 10).
- Produces: `FlowCanvas({ flow, onSave }: { flow: AgentFlow; onSave: (graphJson: string) => void })` — a full node-graph editor: canvas with drag-and-drop node placement, a palette to add new nodes (Start/HTTP/Conditional/WooCommerce/End), connection-drawing between node handles, and a side panel to configure whichever node is currently selected. `FlowsTab`'s placeholder from Task 10 is replaced with a real `<FlowCanvas>` render.

This task requires an actual manual browser verification before being marked complete — per this plan's Global Constraints, `tsc --noEmit` passing is not sufficient evidence for this specific task.

- [ ] **Step 1: Define the node type components**

Create `frontend/components/flow-editor/node-types.tsx` — one visual node component per node type, using `@xyflow/react`'s `Handle`/`Position` for connection points:

```typescript
'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';

const baseStyle: React.CSSProperties = {
  padding: '8px 12px', borderRadius: 8, fontSize: 11,
  background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', color: 'var(--acm-fg-2)',
  minWidth: 140,
};

export function StartNode({ data }: NodeProps) {
  return (
    <div style={{ ...baseStyle, borderColor: 'var(--acm-accent)' }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>▶ Inicio</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{(data.parameters as any[] || []).length} parámetro(s)</div>
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function HttpNode({ data }: NodeProps) {
  return (
    <div style={baseStyle}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>🌐 HTTP Request</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.method || 'GET')} {String(data.url || '')}</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function ConditionalNode({ data }: NodeProps) {
  return (
    <div style={baseStyle}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>◆ Condicional</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.field || '')} {String(data.operator || '')} {String(data.value || '')}</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="true" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="false" style={{ left: '70%' }} />
    </div>
  );
}

export function WooCommerceNode({ data }: NodeProps) {
  return (
    <div style={baseStyle}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>🛒 WooCommerce</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.search_term || '')}</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function EndNode({ data }: NodeProps) {
  return (
    <div style={{ ...baseStyle, borderColor: 'var(--acm-accent)' }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>■ Final</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.template || '')}</div>
      <Handle type="target" position={Position.Top} id="default" />
    </div>
  );
}

export const NODE_TYPES = {
  start: StartNode,
  http: HttpNode,
  conditional: ConditionalNode,
  woocommerce: WooCommerceNode,
  end: EndNode,
};
```

- [ ] **Step 2: Build the canvas + config side panel**

Create `frontend/components/flow-editor/FlowCanvas.tsx`:

```typescript
'use client';

import { useCallback, useMemo, useState } from 'react';
import {
  ReactFlow, Background, Controls, MiniMap, addEdge, applyNodeChanges, applyEdgeChanges,
  type Node, type Edge, type Connection, type NodeChange, type EdgeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { NODE_TYPES } from './node-types';
import type { AgentFlow } from '@/hooks/use-agent-flows';

interface GraphJson {
  nodes: Array<{ id: string; type: string; config: Record<string, unknown>; position: { x: number; y: number } }>;
  edges: Array<{ from: string; to: string; fromHandle: string }>;
}

function toReactFlow(graph: GraphJson): { nodes: Node[]; edges: Edge[] } {
  return {
    nodes: graph.nodes.map(n => ({ id: n.id, type: n.type, position: n.position, data: n.config })),
    edges: graph.edges.map(e => ({
      id: `${e.from}-${e.to}-${e.fromHandle}`, source: e.from, target: e.to, sourceHandle: e.fromHandle,
    })),
  };
}

function toGraphJson(nodes: Node[], edges: Edge[]): GraphJson {
  return {
    nodes: nodes.map(n => ({ id: n.id, type: n.type || 'http', config: n.data as Record<string, unknown>, position: n.position })),
    edges: edges.map(e => ({ from: e.source, to: e.target, fromHandle: e.sourceHandle || 'default' })),
  };
}

let _nodeIdCounter = 0;
function nextNodeId(prefix: string) {
  _nodeIdCounter += 1;
  return `${prefix}_${_nodeIdCounter}`;
}

export function FlowCanvas({ flow, onSave }: { flow: AgentFlow; onSave: (graphJson: string) => void }) {
  const initial = useMemo(() => toReactFlow(JSON.parse(flow.graph_json || '{"nodes":[],"edges":[]}')), [flow.id]);
  const [nodes, setNodes] = useState<Node[]>(initial.nodes);
  const [edges, setEdges] = useState<Edge[]>(initial.edges);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes(nds => applyNodeChanges(changes, nds)), []);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => setEdges(eds => applyEdgeChanges(changes, eds)), []);
  const onConnect = useCallback((connection: Connection) => setEdges(eds => addEdge(connection, eds)), []);

  const addNode = (type: keyof typeof NODE_TYPES) => {
    const defaults: Record<string, Record<string, unknown>> = {
      start: { parameters: [] },
      http: { url: '', method: 'GET', headers: {}, body: '' },
      conditional: { field: '', operator: 'contains', value: '' },
      woocommerce: { connection_id: null, search_term: '' },
      end: { template: '' },
    };
    setNodes(nds => [...nds, { id: nextNodeId(type), type, position: { x: 100, y: 100 + nds.length * 90 }, data: defaults[type] }]);
  };

  const selectedNode = nodes.find(n => n.id === selectedId) || null;

  const updateSelectedNodeData = (patch: Record<string, unknown>) => {
    if (!selectedNode) return;
    setNodes(nds => nds.map(n => n.id === selectedNode.id ? { ...n, data: { ...n.data, ...patch } } : n));
  };

  const handleSave = () => onSave(JSON.stringify(toGraphJson(nodes, edges)));

  return (
    <div className="flex gap-2" style={{ height: 500 }}>
      <div className="flex flex-col gap-1 shrink-0" style={{ width: 120 }}>
        {(Object.keys(NODE_TYPES) as (keyof typeof NODE_TYPES)[]).map(t => (
          <button key={t} onClick={() => addNode(t)} className="btn-secondary text-[11px] px-2 py-1">+ {t}</button>
        ))}
        <button onClick={handleSave} className="btn-primary text-[11px] px-2 py-1 mt-2">Guardar flujo</button>
      </div>
      <div className="flex-1" style={{ border: '1px solid var(--acm-border)', borderRadius: 8 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_e, node) => setSelectedId(node.id)}
          nodeTypes={NODE_TYPES}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
      {selectedNode && (
        <div className="shrink-0 p-2 text-[11px]" style={{ width: 220, border: '1px solid var(--acm-border)', borderRadius: 8, color: 'var(--acm-fg-2)' }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>{selectedNode.type}</div>
          {selectedNode.type === 'http' && (
            <>
              <label>URL</label>
              <input className="acm-input w-full mb-2" value={String(selectedNode.data.url || '')} onChange={e => updateSelectedNodeData({ url: e.target.value })} />
              <label>Método</label>
              <select className="acm-input w-full mb-2" value={String(selectedNode.data.method || 'GET')} onChange={e => updateSelectedNodeData({ method: e.target.value })}>
                <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option>
              </select>
            </>
          )}
          {selectedNode.type === 'conditional' && (
            <>
              <label>Campo (ej: {'{{http1.status}}'})</label>
              <input className="acm-input w-full mb-2" value={String(selectedNode.data.field || '')} onChange={e => updateSelectedNodeData({ field: e.target.value })} />
              <label>Operador</label>
              <select className="acm-input w-full mb-2" value={String(selectedNode.data.operator || 'contains')} onChange={e => updateSelectedNodeData({ operator: e.target.value })}>
                <option value="contains">contiene</option>
                <option value="equals">es igual a</option>
                <option value="is_empty">está vacío</option>
                <option value="is_error">es un error</option>
              </select>
              <label>Valor</label>
              <input className="acm-input w-full" value={String(selectedNode.data.value || '')} onChange={e => updateSelectedNodeData({ value: e.target.value })} />
            </>
          )}
          {selectedNode.type === 'woocommerce' && (
            <>
              <label>Término de búsqueda</label>
              <input className="acm-input w-full" value={String(selectedNode.data.search_term || '')} onChange={e => updateSelectedNodeData({ search_term: e.target.value })} />
            </>
          )}
          {selectedNode.type === 'end' && (
            <>
              <label>Plantilla de respuesta</label>
              <textarea className="acm-input w-full" rows={4} value={String(selectedNode.data.template || '')} onChange={e => updateSelectedNodeData({ template: e.target.value })} />
            </>
          )}
        </div>
      )}
    </div>
  );
}
```

Note: the WooCommerce node's Connection dropdown (selecting a saved `connection_id`) and the Start node's parameter-list editor are intentionally minimal placeholders in this task (a plain text/number field is acceptable here) — Task 12 wires the real Connection dropdown once the Connections management UI exists. If a reviewer flags the Start node having no parameter-editing UI at all, note it as a gap for a follow-up — this task's primary deliverable is the canvas/connection-drawing/node-placement mechanics working correctly, not every field being polished.

- [ ] **Step 3: Wire `FlowCanvas` into `FlowsTab`**

In `frontend/app/agents/page.tsx`, replace `FlowsTab`'s placeholder editing branch (from Task 10):

```typescript
  if (editingFlowId !== null) {
    const editingFlow = flows.find(f => f.id === editingFlowId);
    if (!editingFlow) return null;
    return (
      <div className="flex flex-col gap-2">
        <button onClick={() => setEditingFlowId(null)} className="btn-secondary self-start text-[11px] px-2 py-1">
          ← Volver a la lista
        </button>
        <FlowCanvas
          flow={editingFlow}
          onSave={(graphJson) => {
            update.mutate({ id: editingFlow.id, data: { graph_json: graphJson } });
          }}
        />
      </div>
    );
  }
```

Add the import at the top of `page.tsx`:

```typescript
import { FlowCanvas } from '@/components/flow-editor/FlowCanvas';
```

- [ ] **Step 4: Verify with `tsc`**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5: Manual browser verification (required for this task)**

Start the dev server, open an agent's Flujos tab, click "+ Nuevo flujo", click "Editar", confirm the canvas renders. Add a Start node, an HTTP node, and an End node from the palette. Drag a connection from Start's bottom handle to the HTTP node's top handle, then from the HTTP node to the End node. Click the HTTP node and confirm the side panel shows URL/Method fields and editing them updates the node. Click "Guardar flujo" and confirm no console errors. Reload the page, re-open the same flow, and confirm the nodes/edges you placed are still there (proves `graph_json` round-trips correctly through save/load). If a live process is already running on a port you didn't start, do not reuse someone else's session without checking first — start a fresh dev server instance for this verification instead.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/flow-editor/ frontend/app/agents/page.tsx
git commit -m "feat(agents): visual node canvas for flow editing (React Flow)"
```

---

### Task 12: Frontend — Connections management UI

**Files:**
- Create: `frontend/hooks/use-agent-connections.ts`
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`
- Modify: `frontend/app/agents/page.tsx`

**Interfaces:**
- Consumes: Connections API from Task 8.
- Produces: `AgentConnection` interface, `useAgentConnections(agentId)`, `useCreateConnection(agentId)`, `useDeleteConnection(agentId)` hooks. The WooCommerce node's side panel (in `FlowCanvas`) gains a real Connection dropdown + "+ Nueva conexión" inline form, replacing Task 11's placeholder text field.

- [ ] **Step 1: Create the connections hooks file**

Create `frontend/hooks/use-agent-connections.ts`:

```typescript
'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

export interface AgentConnection {
  id: number;
  agent_id: number;
  name: string;
  type: string;
  created_at: string;
}

export function useAgentConnections(agentId: number) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<AgentConnection[]>({
    queryKey: ['agent-connections', agentId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/connections`),
    enabled: isAuthenticated,
  });
}

export function useCreateConnection(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; type: string; url: string; consumer_key: string; consumer_secret: string }) =>
      fetchAPI(`/api/agents/${agentId}/connections`, { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-connections', agentId] }),
  });
}

export function useDeleteConnection(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => fetchAPI(`/api/agents/${agentId}/connections/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-connections', agentId] }),
  });
}
```

- [ ] **Step 2: Wire the Connection dropdown into `FlowCanvas`'s WooCommerce panel**

In `frontend/components/flow-editor/FlowCanvas.tsx`, add `agentId` as a required prop and use it to fetch connections:

```typescript
import { useAgentConnections, useCreateConnection } from '@/hooks/use-agent-connections';

export function FlowCanvas({ agentId, flow, onSave }: { agentId: number; flow: AgentFlow; onSave: (graphJson: string) => void }) {
```

Inside the component body, add:

```typescript
  const { data: connections } = useAgentConnections(agentId);
  const createConnection = useCreateConnection(agentId);
  const [showNewConnectionForm, setShowNewConnectionForm] = useState(false);
  const [newConnName, setNewConnName] = useState('');
  const [newConnUrl, setNewConnUrl] = useState('');
  const [newConnKey, setNewConnKey] = useState('');
  const [newConnSecret, setNewConnSecret] = useState('');

  const submitNewConnection = () => {
    createConnection.mutate(
      { name: newConnName, type: 'woocommerce', url: newConnUrl, consumer_key: newConnKey, consumer_secret: newConnSecret },
      { onSuccess: () => { setShowNewConnectionForm(false); setNewConnName(''); setNewConnUrl(''); setNewConnKey(''); setNewConnSecret(''); } },
    );
  };
```

Replace the WooCommerce panel's placeholder (from Task 11 — the block starting `{selectedNode.type === 'woocommerce' && (`) with:

```typescript
          {selectedNode.type === 'woocommerce' && (
            <>
              <label>Conexión</label>
              <select
                className="acm-input w-full mb-2"
                value={String(selectedNode.data.connection_id ?? '')}
                onChange={e => updateSelectedNodeData({ connection_id: Number(e.target.value) })}
              >
                <option value="">Seleccionar...</option>
                {(connections || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              {showNewConnectionForm ? (
                <div className="flex flex-col gap-1 mb-2">
                  <input className="acm-input w-full" placeholder="Nombre" value={newConnName} onChange={e => setNewConnName(e.target.value)} />
                  <input className="acm-input w-full" placeholder="URL de la tienda" value={newConnUrl} onChange={e => setNewConnUrl(e.target.value)} />
                  <input className="acm-input w-full" placeholder="Consumer Key" value={newConnKey} onChange={e => setNewConnKey(e.target.value)} />
                  <input className="acm-input w-full" placeholder="Consumer Secret" type="password" value={newConnSecret} onChange={e => setNewConnSecret(e.target.value)} />
                  <div className="flex gap-1 justify-end">
                    <button onClick={() => setShowNewConnectionForm(false)} className="btn-secondary text-[11px] px-2 py-1">Cancelar</button>
                    <button onClick={submitNewConnection} disabled={createConnection.isPending || !newConnName} className="btn-secondary text-[11px] px-2 py-1">Guardar</button>
                  </div>
                </div>
              ) : (
                <button onClick={() => setShowNewConnectionForm(true)} className="btn-secondary text-[11px] px-2 py-1 mb-2">+ Nueva conexión</button>
              )}
              <label>Término de búsqueda</label>
              <input className="acm-input w-full" value={String(selectedNode.data.search_term || '')} onChange={e => updateSelectedNodeData({ search_term: e.target.value })} />
            </>
          )}
```

- [ ] **Step 3: Pass `agentId` through from `FlowsTab`**

In `frontend/app/agents/page.tsx`, update the `<FlowCanvas>` call site (from Task 11):

```typescript
        <FlowCanvas
          agentId={agentId}
          flow={editingFlow}
          onSave={(graphJson) => {
            update.mutate({ id: editingFlow.id, data: { graph_json: graphJson } });
          }}
        />
```

- [ ] **Step 4: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/hooks/use-agent-connections.ts frontend/components/flow-editor/FlowCanvas.tsx frontend/app/agents/page.tsx
git commit -m "feat(agents): Connections management — dropdown + inline creation in the WooCommerce node panel"
```

---

### Task 13: Frontend — "Probar flujo" (test) button + final manual verification

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: `POST /api/agents/{agent_id}/flows/{flow_id}/test` (Task 7).
- Produces: a "Probar flujo" button in `FlowCanvas` that prompts for test parameter values (derived from the Start node's declared parameters), calls the test endpoint, and displays the result inline.

This task requires an actual manual browser verification before being marked complete, exercising a REAL end-to-end flow (not just the canvas mechanics from Task 11) — per this plan's Global Constraints.

- [ ] **Step 1: Add the test-run UI to `FlowCanvas`**

In `frontend/components/flow-editor/FlowCanvas.tsx`, add state and a handler:

```typescript
  const [testParams, setTestParams] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const { fetchAPI } = useAPI();

  const startNode = nodes.find(n => n.type === 'start');
  const startParams = (startNode?.data.parameters as Array<{ name: string }> | undefined) || [];

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const savedGraph = toGraphJson(nodes, edges);
      const res = await fetchAPI<{ result: string }>(`/api/agents/${agentId}/flows/${flow.id}/test`, {
        method: 'POST',
        body: JSON.stringify({ params: testParams }),
      });
      setTestResult(res.result);
    } catch {
      setTestResult('Error al ejecutar la prueba.');
    } finally {
      setTesting(false);
    }
  };
```

Add `useAPI` to the existing import line from `@/hooks/use-api` at the top of the file (add it alongside whatever else this file already imports from there, if anything — otherwise add a new import line: `import { useAPI } from '@/hooks/use-api';`).

Add the UI, right below the "Guardar flujo" button in the left palette column:

```typescript
        <div className="mt-2 pt-2" style={{ borderTop: '1px solid var(--acm-border)' }}>
          <div className="text-[11px] mb-1" style={{ color: 'var(--acm-fg-4)' }}>Probar flujo</div>
          {startParams.map(p => (
            <input
              key={p.name}
              className="acm-input w-full mb-1 text-[11px]"
              placeholder={p.name}
              value={testParams[p.name] || ''}
              onChange={e => setTestParams(prev => ({ ...prev, [p.name]: e.target.value }))}
            />
          ))}
          <button onClick={runTest} disabled={testing} className="btn-secondary text-[11px] px-2 py-1 w-full">
            {testing ? 'Ejecutando...' : 'Probar flujo'}
          </button>
          {testResult && (
            <div className="mt-1 p-1 text-[10px] whitespace-pre-wrap" style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)', borderRadius: 4, color: 'var(--acm-fg-3)' }}>
              {testResult}
            </div>
          )}
        </div>
```

Note: "Probar flujo" runs the endpoint against the flow's **currently saved** `graph_json`, not unsaved canvas edits — if a reviewer flags that clicking "Probar flujo" without first clicking "Guardar flujo" tests stale content, that's expected v1 behavior (the spec's `/test` endpoint reads the flow row from the database, it doesn't accept an inline graph override) — not a bug to fix in this task; note it as a possible future UX improvement instead.

- [ ] **Step 2: Verify with `tsc`**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 3: Manual browser verification (required, end-to-end)**

Using a fresh dev server (do not reuse a process you didn't start, per Task 11's same caution): build a real flow — Start (one required parameter, e.g. `producto`) → HTTP Request node pointed at any public test API (e.g. `https://httpbin.org/get?q={{producto}}`) → End node with template `{{http1.args.q}}` — wait, `httpbin.org/get`'s response shape nests the query string under `args`, so this specific template requires two-level access which this plan's `.field` lookup does NOT support (only one level) — instead use an End template of `{{http1}}` (whole-output passthrough) and just confirm the raw JSON appears in the test result, since exercising true two-level JSON access is out of scope for v1. Click "Guardar flujo", enter a test value for `producto`, click "Probar flujo", and confirm a real HTTP response appears in the result panel — this proves the full path (canvas → save → `graph_json` → `/test` endpoint → `FlowExecutor` → real network call → formatted result) works end to end, not just each piece in isolation.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): 'Probar flujo' test button — end-to-end flow execution from the canvas"
```

---

## Post-plan manual smoke test (end to end)

After all 13 tasks are merged:

1. Open an agent's Flujos tab, create a flow with a Start (parameter `producto`), a Conditional node checking whether `{{producto}}` `contains` some keyword, two separate End nodes for the true/false branches, save it, and confirm both branches produce visibly different results via "Probar flujo".
2. Create a WooCommerce Connection with real (or a disposable test store's) credentials, build a flow using the WooCommerce node against it, and confirm a real product search returns formatted results.
3. Activate the flow, then use the agent's existing "Test this agent" dashboard panel (unrelated pre-existing feature) to send a message that should trigger the LLM to call the flow — confirm the LLM actually invokes `flow_<id>` and the conversation reflects the flow's result, proving the Task 9 wiring works with the real `Brain` (not just the `_FakeBrain` used in Task 9's unit tests).
4. Deactivate the flow and confirm it no longer appears in the agent's available tools (re-run step 3's message and confirm the LLM no longer has that option).
