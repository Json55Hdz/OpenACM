# Flow JSON Import/Export + AI-Generated Flows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a flow be exported/imported as a portable JSON file, and let any agent create or update its own flows by generating `graph_json` directly through a tool call — both gated by a new, real server-side graph validator that today barely exists.

**Architecture:** A new `validate_graph()` in `flow_executor.py` (structural checks: known node types, exactly one Start, at least one End, unique ids, valid edge references, valid handle ids per node type — plus the existing `detect_cycle`) becomes the single gate used by the existing PUT/test endpoints, a newly-extended POST-create endpoint, and a brand-new tool. Frontend gets an Export button (client-side download, no backend change) and an Import panel (paste JSON → POST with `graph_json`).

**Tech Stack:** FastAPI + `httpx.AsyncClient`/`ASGITransport` tests (backend), Next.js/React + `@tanstack/react-query` (frontend), pytest with `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed).

**Spec:** `docs/superpowers/specs/2026-08-21-flow-json-import-export-and-ai-generation-design.md`

## Global Constraints

- `validate_graph(graph: dict) -> list[str]` — empty list means valid. Collects every problem found, never stops at the first (an AI fixing a bad graph needs to see everything wrong in one round-trip).
- The "at least one `end` node" check is existence-only, not reachability — do not add reachability analysis.
- A node with no `config` key is treated as `config: {}` — no per-type required-config-key validation (every handler already degrades gracefully via `.get(..., default)`).
- Import always creates a NEW flow. Never overwrites the currently-open flow.
- Export embeds `graph_json` as a real nested object, not a double-encoded string: `{"kind": "openacm-flow", "version": 1, "name": ..., "description": ..., "graph_json": {...}}`.
- Auto-layout in the tool (Task 5) only fills in `position` for nodes that don't already have one — never overwrites a node's existing position.
- `agent_id` resolution order in the tool: explicit `agent_id` param wins; otherwise parse `_channel_id` for the `^agent_(\d+)$` pattern; otherwise return an error string (never guess).
- Every backend test that needs `flow_executor` imports (`detect_cycle`, `validate_graph`) locally inside the test function, matching this repo's existing convention in `tests/unit/test_flow_executor.py` — not at module top.
- This repo has no frontend unit-test runner (confirmed: no jest/vitest config or test files exist under `frontend/`) — frontend tasks are verified with `npx tsc --noEmit` plus the plan's final manual browser verification, not unit tests.

---

### Task 1: `validate_graph()` and node/handle constants in `flow_executor.py`

**Files:**
- Modify: `src/openacm/core/flow_executor.py` (insert after `detect_cycle`, which ends at line 67 — insert starting at line 69, before the current blank-line gap leading into the templating section)
- Test: `tests/unit/test_flow_executor.py` (existing file — add a new `TestValidateGraph` class)

**Interfaces:**
- Produces: `validate_graph(graph: dict) -> list[str]`, `KNOWN_NODE_TYPES: set[str]`, `NODE_TARGET_HANDLES: dict[str, set[str]]`, `NODE_SOURCE_HANDLES: dict[str, set[str]]` — all importable from `openacm.core.flow_executor`. Task 2 and Task 5 both call `validate_graph` directly.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_flow_executor.py`:

```python
class TestValidateGraph:
    def _valid_graph(self):
        return {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://x", "method": "GET"}},
                {"id": "end", "type": "end", "config": {"template": "{{http1}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "end", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
            ],
        }

    def test_valid_graph_has_no_errors(self):
        from openacm.core.flow_executor import validate_graph
        assert validate_graph(self._valid_graph()) == []

    def test_unknown_node_type_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["nodes"][1]["type"] = "not_a_real_type"
        errors = validate_graph(graph)
        assert any("not_a_real_type" in e for e in errors)

    def test_zero_start_nodes_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["nodes"] = [n for n in graph["nodes"] if n["type"] != "start"]
        graph["edges"] = []
        errors = validate_graph(graph)
        assert any("start" in e.lower() for e in errors)

    def test_two_start_nodes_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["nodes"].append({"id": "start2", "type": "start", "config": {"parameters": []}})
        errors = validate_graph(graph)
        assert any("start" in e.lower() for e in errors)

    def test_zero_end_nodes_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["nodes"] = [n for n in graph["nodes"] if n["type"] != "end"]
        graph["edges"] = [e for e in graph["edges"] if e["to"] != "end"]
        errors = validate_graph(graph)
        assert any("end" in e.lower() for e in errors)

    def test_duplicate_node_ids_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["nodes"][1]["id"] = "start"
        errors = validate_graph(graph)
        assert any("duplicate" in e.lower() or "unique" in e.lower() for e in errors)

    def test_edge_to_missing_node_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        graph["edges"].append({"from": "http1", "to": "nonexistent", "fromHandle": "default", "toHandle": "default", "kind": "flow"})
        errors = validate_graph(graph)
        assert any("nonexistent" in e for e in errors)

    def test_invalid_handle_for_node_type_is_rejected(self):
        from openacm.core.flow_executor import validate_graph
        graph = self._valid_graph()
        # "count" is a valid SOURCE handle on woocommerce, not on http.
        graph["edges"][1]["fromHandle"] = "count"
        errors = validate_graph(graph)
        assert any("count" in e for e in errors)

    def test_cycle_is_still_reported(self):
        from openacm.core.flow_executor import validate_graph
        # A minimal cyclic graph: conditional's "false" branch loops back to
        # itself instead of reaching an exit — a real cycle, unrelated to
        # any other validation rule.
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "cond", "type": "conditional", "config": {"field": "x", "operator": "equals", "value": "y"}},
                {"id": "end", "type": "end", "config": {"template": "done"}},
            ],
            "edges": [
                {"from": "start", "to": "cond", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
                {"from": "cond", "to": "end", "fromHandle": "true", "toHandle": "default", "kind": "flow"},
                {"from": "cond", "to": "cond", "fromHandle": "false", "toHandle": "default", "kind": "flow"},
            ],
        }
        errors = validate_graph(graph)
        assert any("cycle" in e.lower() for e in errors)

    def test_multiple_problems_are_all_reported_together(self):
        from openacm.core.flow_executor import validate_graph
        graph = {"nodes": [{"id": "a", "type": "bogus", "config": {}}], "edges": []}
        errors = validate_graph(graph)
        assert len(errors) >= 2  # unknown type AND missing start AND missing end
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_flow_executor.py::TestValidateGraph -v`
Expected: FAIL with `ImportError: cannot import name 'validate_graph'`

- [ ] **Step 3: Implement `validate_graph` and the handle-table constants**

Insert into `src/openacm/core/flow_executor.py` immediately after `detect_cycle` (after its closing `return None` at line 67, i.e. starting at line 69):

```python
# Mirrors classifyPin() in frontend/components/flow-editor/node-types.tsx —
# keep both in sync when either changes. Target = a node's flow-in/data-in
# handle ids; source = its flow-out/data-out handle ids.
KNOWN_NODE_TYPES = {"start", "http", "conditional", "woocommerce", "set", "get", "end"}

NODE_TARGET_HANDLES: dict[str, set[str]] = {
    "start": set(),
    "http": {"default", "url", "body"},
    "conditional": {"default", "field", "value"},
    "woocommerce": {"default", "search_term"},
    "set": {"default", "value"},
    "get": set(),
    "end": {"default"},
}

NODE_SOURCE_HANDLES: dict[str, set[str]] = {
    "start": {"default"},
    "http": {"default"},
    "conditional": {"true", "false"},
    "woocommerce": {"default", "result", "count"},
    "set": {"default"},
    "get": {"default"},
    "end": set(),
}


def validate_graph(graph: dict) -> list[str]:
    """Structural validation of a flow's graph_json, beyond just "is this
    valid JSON" and "does it have a cycle" (detect_cycle, above). Collects
    every problem found rather than stopping at the first, so an AI (or a
    human) fixing a bad graph sees everything wrong in one round-trip.
    Returns an empty list when the graph is valid.
    """
    errors: list[str] = []
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    if not isinstance(nodes, list):
        return ["graph_json.nodes must be a list"]
    if not isinstance(edges, list):
        return ["graph_json.edges must be a list"]

    node_ids_seen: set[str] = set()
    node_types: dict[str, str] = {}
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            errors.append("A node is missing its 'id'")
            continue
        if node_id in node_ids_seen:
            errors.append(f"Duplicate node id: '{node_id}' — node ids must be unique")
        node_ids_seen.add(node_id)

        node_type = node.get("type")
        if node_type not in KNOWN_NODE_TYPES:
            errors.append(f"Node '{node_id}' has unknown type '{node_type}' — must be one of {sorted(KNOWN_NODE_TYPES)}")
        else:
            node_types[node_id] = node_type

    start_count = sum(1 for n in nodes if n.get("type") == "start")
    if start_count != 1:
        errors.append(f"A flow must have exactly one 'start' node (found {start_count})")

    end_count = sum(1 for n in nodes if n.get("type") == "end")
    if end_count == 0:
        errors.append("A flow must have at least one 'end' node")

    for edge in edges:
        from_id, to_id = edge.get("from"), edge.get("to")
        from_ok = from_id in node_types
        to_ok = to_id in node_types
        if not from_ok:
            errors.append(f"Edge references unknown source node '{from_id}'")
        if not to_ok:
            errors.append(f"Edge references unknown target node '{to_id}'")
        if not (from_ok and to_ok):
            continue  # handle-id checks below would just cascade confusingly

        from_handle = edge.get("fromHandle", "default")
        if from_handle not in NODE_SOURCE_HANDLES.get(node_types[from_id], set()):
            errors.append(f"'{from_handle}' is not a valid output pin on node '{from_id}' (type '{node_types[from_id]}')")

        to_handle = edge.get("toHandle", "default")
        if to_handle not in NODE_TARGET_HANDLES.get(node_types[to_id], set()):
            errors.append(f"'{to_handle}' is not a valid input pin on node '{to_id}' (type '{node_types[to_id]}')")

    cycle = detect_cycle(graph)
    if cycle:
        errors.append(f"Flow has a cycle: {' -> '.join(cycle)}")

    return errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_flow_executor.py::TestValidateGraph -v`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Run the full existing file to confirm no regressions**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS, same count as before plus the 10 new ones

- [ ] **Step 6: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(agents): add validate_graph() structural checks for flow graph_json"
```

---

### Task 2: Wire `validate_graph` into `_parse_and_validate_graph`; accept `graph_json` on flow create

**Files:**
- Modify: `src/openacm/web/routers/agents.py:31-42` (`_parse_and_validate_graph`) and `:190-200` (`create_agent_flow`)
- Test: `tests/unit/test_agents_flows_api.py` (existing file — extends `TestCreateUpdateDeleteFlow`, adds a new class for validation)

**Interfaces:**
- Consumes: `validate_graph` from `openacm.core.flow_executor` (Task 1).
- Produces: `POST /api/agents/{agent_id}/flows` now accepts an optional `graph_json` field in its JSON body, validated the same way the PUT endpoint already validates it. No change to the response shape (still the full created flow row via `get_flow`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_agents_flows_api.py`, inside `class TestCreateUpdateDeleteFlow` (reusing its existing `app_client`/`_mock_state` fixtures):

```python
    async def test_create_flow_with_graph_json_passes_it_through(self, app_client, _mock_state):
        valid_graph = (
            '{"nodes":[{"id":"start","type":"start","config":{"parameters":[]}},'
            '{"id":"end","type":"end","config":{"template":"done"}}],'
            '"edges":[{"from":"start","to":"end","fromHandle":"default","toHandle":"default","kind":"flow"}]}'
        )
        async with app_client as ac:
            resp = await ac.post(
                "/api/agents/42/flows",
                json={"name": "imported", "description": "d", "graph_json": valid_graph},
            )
        assert resp.status_code == 200
        _mock_state.create_flow.assert_awaited_once()
        assert _mock_state.create_flow.await_args.kwargs["graph_json"] == valid_graph

    async def test_create_flow_with_invalid_graph_json_is_rejected(self, app_client, _mock_state):
        bad_graph = '{"nodes":[{"id":"a","type":"bogus","config":{}}],"edges":[]}'
        async with app_client as ac:
            resp = await ac.post(
                "/api/agents/42/flows",
                json={"name": "imported", "graph_json": bad_graph},
            )
        assert resp.status_code == 400
        _mock_state.create_flow.assert_not_awaited()

    async def test_create_flow_without_graph_json_is_unchanged(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows", json={"name": "new-flow"})
        assert resp.status_code == 200
        assert "graph_json" not in _mock_state.create_flow.await_args.kwargs


class TestParseAndValidateGraphNowUsesFullValidation:
    async def test_update_with_unknown_node_type_is_rejected_with_specific_message(self, app_client, _mock_state):
        bad_graph = '{"nodes":[{"id":"a","type":"bogus","config":{}}],"edges":[]}'
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/flows/7", json={"graph_json": bad_graph})
        assert resp.status_code == 400
        assert "bogus" in resp.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_agents_flows_api.py -v`
Expected: FAIL — the three new `TestCreateUpdateDeleteFlow` tests fail because `create_agent_flow` doesn't read `graph_json` yet; `TestParseAndValidateGraphNowUsesFullValidation` fails because today's message is only about cycles, not unknown types (it currently returns 200, not 400, since an acyclic-but-bogus-type graph passes today's weaker check).

- [ ] **Step 3: Implement**

In `src/openacm/web/routers/agents.py`, replace `_parse_and_validate_graph` (lines 31-42):

```python
def _parse_and_validate_graph(graph_json: str) -> dict:
    """Parse graph_json and reject it if malformed or structurally invalid. Raises HTTPException."""
    from openacm.core.flow_executor import validate_graph

    try:
        graph = json.loads(graph_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid graph_json: not valid JSON")
    errors = validate_graph(graph)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return graph
```

Replace `create_agent_flow` (lines 191-200):

```python
    async def create_agent_flow(agent_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        create_kwargs: dict[str, Any] = {
            "agent_id": agent_id,
            "name": data.get("name", "Untitled flow"),
            "description": data.get("description", ""),
        }
        if "graph_json" in data:
            _parse_and_validate_graph(data["graph_json"])  # raises on invalid, discards the parsed dict — DB stores the string
            create_kwargs["graph_json"] = data["graph_json"]
        flow_id = await _state.database.create_flow(**create_kwargs)
        return await _state.database.get_flow(flow_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_agents_flows_api.py -v`
Expected: PASS, all tests including the new ones

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `pytest -q`
Expected: same pass count as the pre-existing baseline (643 passed) plus this task's new tests, no new failures beyond the already-known pre-existing `gmail_classifier` sqlite-column-mismatch errors (unrelated, documented, not this branch's concern)

- [ ] **Step 6: Commit**

```bash
git add src/openacm/web/routers/agents.py tests/unit/test_agents_flows_api.py
git commit -m "feat(agents): accept graph_json on flow create; use validate_graph everywhere"
```

---

### Task 3: Export button (frontend)

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx` (toolbar around line 564, `handleSave` at line 558)

**Interfaces:**
- Consumes: `toGraphJson(nodes, edges)` (existing, same file), `flow.name`/`flow.description` (existing props, `AgentFlow` from `@/hooks/use-agent-flows`).
- Produces: no new exports — purely an added button + handler in `FlowCanvasInner`.

- [ ] **Step 1: Implement the export handler and button**

In `frontend/components/flow-editor/FlowCanvas.tsx`, add right after `handleSave` (line 558):

```tsx
  const handleExport = () => {
    const payload = {
      kind: 'openacm-flow',
      version: 1,
      name: flow.name,
      description: flow.description,
      graph_json: toGraphJson(nodes, edges),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const slug = flow.name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'flujo';
    a.href = url;
    a.download = `${slug}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
```

Add the button right after the "Guardar flujo" button (line 564):

```tsx
        <button onClick={handleSave} className="btn-primary text-[11px] px-2 py-1 mt-2">Guardar flujo</button>
        <button onClick={handleExport} className="btn-secondary text-[11px] px-2 py-1 mt-1">Exportar</button>
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: clean, no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): export a flow as a downloadable JSON file"
```

---

### Task 4: Import panel (frontend)

**Files:**
- Modify: `frontend/hooks/use-agent-flows.ts:39-48` (`useCreateFlow`)
- Modify: `frontend/app/agents/page.tsx` (`FlowsTab`, around lines 1775-1816)

**Interfaces:**
- Consumes: the extended `POST /api/agents/{agent_id}/flows` from Task 2 (accepts optional `graph_json`).
- Produces: `useCreateFlow`'s mutate payload type gains an optional `graph_json` field — no other signature change, existing callers (`handleCreate`, unchanged) keep working exactly as today since the field is optional.

- [ ] **Step 1: Extend `useCreateFlow`'s type**

In `frontend/hooks/use-agent-flows.ts`, change (line 44):

```ts
    mutationFn: (data: { name: string; description?: string }) =>
```

to:

```ts
    mutationFn: (data: { name: string; description?: string; graph_json?: string }) =>
```

- [ ] **Step 2: Implement the import panel in `FlowsTab`**

In `frontend/app/agents/page.tsx`, add state and a handler right after the existing `handleCreate` (after line 1788):

```tsx
  const [showImport, setShowImport] = useState(false);
  const [importText, setImportText] = useState('');
  const [importError, setImportError] = useState<string | null>(null);

  const handleImport = () => {
    setImportError(null);
    let parsed: any;
    try {
      parsed = JSON.parse(importText);
    } catch {
      setImportError('Eso no es JSON válido.');
      return;
    }
    if (parsed.kind !== 'openacm-flow' || !parsed.graph_json) {
      setImportError('Esto no parece un flujo de OpenACM exportado.');
      return;
    }
    create.mutate(
      {
        name: parsed.name || 'Flujo importado',
        description: parsed.description || '',
        graph_json: JSON.stringify(parsed.graph_json),
      },
      {
        onSuccess: (created: any) => {
          setShowImport(false);
          setImportText('');
          setEditingFlowId(created.id);
        },
        onError: (err: Error) => setImportError(err.message || 'Error al importar el flujo.'),
      }
    );
  };
```

Add `useState` to the existing React import at the top of the file if not already imported (check first — `FlowsTab` already uses `useState` for `editingFlowId` at line 1780, so the import already exists; no change needed there).

Replace the list-view return block (lines 1812-1816) to add the Import button and (conditionally) the paste panel:

```tsx
  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2 self-end">
        <button onClick={() => setShowImport(v => !v)} className="btn-secondary text-[11px] px-2 py-1">
          Importar flujo
        </button>
        <button onClick={handleCreate} disabled={create.isPending} className="btn-secondary text-[11px] px-2 py-1">
          + Nuevo flujo
        </button>
      </div>
      {showImport && (
        <div className="flex flex-col gap-1 p-2 rounded" style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}>
          <textarea
            value={importText}
            onChange={e => setImportText(e.target.value)}
            placeholder="Pega el JSON exportado aquí"
            rows={6}
            className="text-[11px] p-2 rounded"
            style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-border)', color: 'var(--acm-fg-2)', fontFamily: 'monospace' }}
          />
          {importError && <div className="text-[11px]" style={{ color: 'var(--acm-danger, #e55)' }}>{importError}</div>}
          <button onClick={handleImport} disabled={create.isPending || !importText.trim()} className="btn-primary text-[11px] px-2 py-1 self-start">
            Importar
          </button>
        </div>
      )}
```

(the rest of the existing list-rendering JSX below — `{flows.length === 0 ? ... : ...}` — is unchanged, just now nested inside this same returned fragment as before).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: clean, no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/hooks/use-agent-flows.ts frontend/app/agents/page.tsx
git commit -m "feat(agents): import a flow from a pasted JSON export"
```

---

### Task 5: `create_or_update_agent_flow` tool (AI-generated flows)

**Files:**
- Create: `src/openacm/tools/flow_tool.py`
- Modify: `src/openacm/app.py` (`_init_tools`, insert after the `cron_tool` registration block, matching the existing `agent_tool`/`cron_tool`/`swarm_tool` two-line-per-module pattern)
- Test: `tests/unit/test_flow_tool.py` (new file — no existing precedent for a `openacm.tools.*` handler test in this repo; follow `cron_tool.py`'s `_brain.skill_manager.database` access pattern for the fake)

**Interfaces:**
- Consumes: `validate_graph` from `openacm.core.flow_executor` (Task 1); `@tool` decorator from `openacm.tools.base`; `db.create_flow`/`db.update_flow`/`db.get_flow` (existing, `src/openacm/storage/database.py:1654,1670,1688`).
- Produces: `create_or_update_agent_flow` (the tool's handler function), `_resolve_agent_id(agent_id, channel_id) -> int | None`, `_auto_layout(nodes, edges) -> None` — all in `flow_tool.py`, importable for direct unit testing.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_flow_tool.py`:

```python
"""Unit tests for the create_or_update_agent_flow tool."""
from unittest.mock import AsyncMock, MagicMock

from openacm.tools.flow_tool import create_or_update_agent_flow, _resolve_agent_id, _auto_layout


def _valid_graph():
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": []}},
            {"id": "end", "type": "end", "config": {"template": "done"}},
        ],
        "edges": [{"from": "start", "to": "end", "fromHandle": "default", "toHandle": "default", "kind": "flow"}],
    }


def _fake_brain(db):
    brain = MagicMock()
    brain.skill_manager.database = db
    return brain


class TestResolveAgentId:
    def test_explicit_agent_id_wins(self):
        assert _resolve_agent_id(5, "agent_9") == 5

    def test_falls_back_to_channel_id(self):
        assert _resolve_agent_id(None, "agent_9") == 9

    def test_non_agent_channel_id_returns_none(self):
        assert _resolve_agent_id(None, "swarm_abc") is None

    def test_no_agent_id_no_channel_id_returns_none(self):
        assert _resolve_agent_id(None, None) is None


class TestAutoLayout:
    def test_fills_in_missing_positions(self):
        nodes = [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}]
        edges = [{"from": "start", "to": "end", "fromHandle": "default", "toHandle": "default", "kind": "flow"}]
        _auto_layout(nodes, edges)
        assert "position" in nodes[0] and "position" in nodes[1]
        assert nodes[0]["position"]["x"] < nodes[1]["position"]["x"]  # start before end

    def test_never_overwrites_existing_position(self):
        nodes = [{"id": "start", "type": "start", "position": {"x": 999, "y": 999}}]
        _auto_layout(nodes, [])
        assert nodes[0]["position"] == {"x": 999, "y": 999}


class TestCreateOrUpdateAgentFlow:
    async def test_no_agent_resolvable_returns_error_without_db_call(self):
        db = AsyncMock()
        result = await create_or_update_agent_flow(
            name="x", graph_json=_valid_graph(), _brain=_fake_brain(db), _channel_id=None,
        )
        assert "agent_id" in result
        db.create_flow.assert_not_awaited()

    async def test_invalid_graph_returns_errors_without_db_call(self):
        db = AsyncMock()
        bad_graph = {"nodes": [{"id": "a", "type": "bogus", "config": {}}], "edges": []}
        result = await create_or_update_agent_flow(
            name="x", graph_json=bad_graph, agent_id=1, _brain=_fake_brain(db),
        )
        assert "bogus" in result
        db.create_flow.assert_not_awaited()

    async def test_valid_graph_creates_flow_via_explicit_agent_id(self):
        db = AsyncMock()
        db.create_flow = AsyncMock(return_value=42)
        result = await create_or_update_agent_flow(
            name="Buscar productos", graph_json=_valid_graph(), agent_id=7, _brain=_fake_brain(db),
        )
        db.create_flow.assert_awaited_once()
        assert db.create_flow.await_args.kwargs["agent_id"] == 7
        assert "42" in result

    async def test_valid_graph_creates_flow_via_channel_id(self):
        db = AsyncMock()
        db.create_flow = AsyncMock(return_value=8)
        result = await create_or_update_agent_flow(
            name="x", graph_json=_valid_graph(), _brain=_fake_brain(db), _channel_id="agent_7",
        )
        assert db.create_flow.await_args.kwargs["agent_id"] == 7

    async def test_flow_id_given_updates_instead_of_creating(self):
        db = AsyncMock()
        db.get_flow = AsyncMock(return_value={"id": 5, "agent_id": 7})
        db.update_flow = AsyncMock(return_value=True)
        result = await create_or_update_agent_flow(
            name="x", graph_json=_valid_graph(), agent_id=7, flow_id=5, _brain=_fake_brain(db),
        )
        db.update_flow.assert_awaited_once()
        db.create_flow.assert_not_awaited()
        assert "5" in result

    async def test_flow_id_belonging_to_other_agent_is_rejected(self):
        db = AsyncMock()
        db.get_flow = AsyncMock(return_value={"id": 5, "agent_id": 999})
        result = await create_or_update_agent_flow(
            name="x", graph_json=_valid_graph(), agent_id=7, flow_id=5, _brain=_fake_brain(db),
        )
        assert "5" in result
        db.update_flow.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_flow_tool.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'openacm.tools.flow_tool'`

- [ ] **Step 3: Implement `src/openacm/tools/flow_tool.py`**

```python
"""Tool letting an agent create or update one of its own flows by
generating graph_json directly, without the visual editor."""
from __future__ import annotations

import json
import re

from openacm.core.flow_executor import validate_graph
from openacm.tools.base import tool

_CHANNEL_AGENT_RE = re.compile(r"^agent_(\d+)$")

_FLOW_TOOL_DESCRIPTION = """Crea o actualiza un flujo visual de un agente generando su grafo (graph_json) directamente, sin usar el editor visual. Usa esto cuando el usuario te pida construir, armar o modificar un flujo/automatización.

Un flujo es un grafo con dos tipos de conexión: 'flow' (define el orden de ejecución) y 'data' (pasa un valor de la salida de un nodo al campo de otro, sin afectar el orden).

TIPOS DE NODO Y SU CONFIG (campo 'config' de cada nodo):
- start: {"parameters": [{"name": str, "type": "string"|"number"|"boolean", "description": str, "required": bool}]} — el punto de entrada. Sin pin de flujo de entrada. Pin de flujo de salida: "default".
- http: {"url": str, "method": "GET"|"POST"|"PUT"|"DELETE", "headers": dict, "body": str} — llamada HTTP. Pines de flujo: entrada "default", salida "default". Pines de dato de entrada (wire-or-literal): "url", "body". Pin de dato de salida: "response" (JSON parseado o texto crudo).
- conditional: {"field": str, "operator": "contains"|"equals"|"is_empty"|"is_error", "value": str} — evalúa una condición. Pin de flujo de entrada: "default". NO tiene pin de flujo de salida "default" — en su lugar tiene DOS: "true" y "false". Pines de dato de entrada: "field", "value".
- woocommerce: {"connection_id": int, "search_term": str} — busca productos en una tienda WooCommerce conectada. Pines de flujo: entrada "default", salida "default". Pin de dato de entrada: "search_term". Pines de dato de salida: "result" (texto formateado con la lista de productos), "count" (número de productos encontrados).
- set: {"name": str} — guarda un valor en una variable con nombre, referenciable luego como {{name}}. Pines de flujo: entrada "default", salida "default". Pin de dato de entrada (opcional): "value" — si no se conecta, usa la salida del nodo anterior en el flujo.
- get: {"name": str} — nodo puro (SIN pines de flujo, ni entrada ni salida) que expone el valor de una variable ya guardada. Pin de dato de salida: "default".
- end: {"template": str} — termina el flujo y devuelve el resultado de sustituir plantillas en 'template'. Pin de flujo de entrada: "default". Sin salidas.

EDGES: cada edge es {"from": node_id, "to": node_id, "fromHandle": pin_id, "toHandle": pin_id, "kind": "flow"|"data"}. Un edge "flow" define qué nodo se ejecuta después. Un edge "data" conecta la salida nombrada de un nodo directamente al campo de entrada nombrado de otro (alternativa a escribir {{node_id.field}} a mano).

PLANTILLAS: cualquier campo de texto no conectado por un edge "data" puede usar {{nombre}} (variable de un Set, o parámetro de Start) o {{node_id.campo}} (un campo específico de la salida de otro nodo) para insertar valores dinámicamente.

POSICIÓN: el campo "position" de cada nodo es opcional — si lo omites, se calcula automáticamente. No inventes coordenadas de píxeles.

REGLAS: debe haber exactamente un nodo "start" y al menos un nodo "end". Todo id de nodo debe ser único. Todo "from"/"to" de un edge debe apuntar a un id de nodo que exista en el grafo."""

_FLOW_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Nombre del flujo."},
        "graph_json": {
            "type": "object",
            "description": 'El grafo del flujo: {"nodes": [...], "edges": [...]}. Ver la descripción de la herramienta para el formato exacto de cada tipo de nodo y edge.',
        },
        "description": {"type": "string", "description": "Descripción opcional del flujo."},
        "flow_id": {"type": "integer", "description": "Si se pasa, actualiza este flujo existente en lugar de crear uno nuevo."},
        "agent_id": {
            "type": "integer",
            "description": "El agente dueño del flujo. Opcional si esta herramienta se llama desde dentro de la ejecución de un agente (se detecta solo); requerido si se llama desde el asistente principal para crear un flujo en otro agente.",
        },
    },
    "required": ["name", "graph_json"],
}


def _resolve_agent_id(agent_id: int | None, channel_id: str | None) -> int | None:
    if agent_id is not None:
        return agent_id
    if channel_id:
        match = _CHANNEL_AGENT_RE.match(channel_id)
        if match:
            return int(match.group(1))
    return None


def _get_db(brain):
    if brain and brain.skill_manager and brain.skill_manager.database:
        return brain.skill_manager.database
    return None


def _auto_layout(nodes: list[dict], edges: list[dict]) -> None:
    """Fills in `position` for any node missing one, via BFS depth over
    flow-kind edges from the start node. Mutates `nodes` in place. Never
    touches a node that already has a position."""
    start_id = next((n["id"] for n in nodes if n.get("type") == "start"), None)

    flow_adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if edge.get("kind", "flow") == "flow":
            flow_adjacency.setdefault(edge["from"], []).append(edge["to"])

    depth: dict[str, int] = {}
    if start_id is not None:
        depth[start_id] = 0
        queue = [start_id]
        while queue:
            current = queue.pop(0)
            for neighbor in flow_adjacency.get(current, []):
                if neighbor not in depth:
                    depth[neighbor] = depth[current] + 1
                    queue.append(neighbor)

    column_counts: dict[int, int] = {}
    for node in nodes:
        if node.get("position"):
            continue
        node_depth = depth.get(node["id"], 0)
        index_in_column = column_counts.get(node_depth, 0)
        column_counts[node_depth] = index_in_column + 1
        node["position"] = {"x": node_depth * 260, "y": index_in_column * 140}


@tool(
    name="create_or_update_agent_flow",
    description=_FLOW_TOOL_DESCRIPTION,
    parameters=_FLOW_TOOL_PARAMETERS,
    category="agents",
)
async def create_or_update_agent_flow(
    name: str,
    graph_json: dict,
    description: str = "",
    flow_id: int | None = None,
    agent_id: int | None = None,
    _brain=None,
    _channel_id: str | None = None,
    **kwargs,
) -> str:
    resolved_agent_id = _resolve_agent_id(agent_id, _channel_id)
    if resolved_agent_id is None:
        return "No se pudo determinar a qué agente pertenece este flujo — pasa agent_id explícitamente."

    db = _get_db(_brain)
    if db is None:
        return "Error: base de datos no disponible."

    nodes = graph_json.get("nodes", [])
    edges = graph_json.get("edges", [])
    _auto_layout(nodes, edges)

    errors = validate_graph(graph_json)
    if errors:
        return "El grafo del flujo tiene errores:\n- " + "\n- ".join(errors)

    graph_str = json.dumps(graph_json)

    if flow_id is not None:
        existing = await db.get_flow(flow_id)
        if not existing or existing["agent_id"] != resolved_agent_id:
            return f"No se encontró el flujo {flow_id} para este agente."
        await db.update_flow(flow_id, agent_id=resolved_agent_id, name=name, description=description, graph_json=graph_str)
        return f"Flujo '{name}' (id {flow_id}) actualizado. Ábrelo en Agentes → Flujos para verlo, o pídeme que lo pruebe."

    new_id = await db.create_flow(agent_id=resolved_agent_id, name=name, description=description, graph_json=graph_str)
    return f"Flujo '{name}' creado (id {new_id}). Ábrelo en Agentes → Flujos para verlo, o pídeme que lo pruebe."
```

- [ ] **Step 4: Register the tool in `app.py`**

In `src/openacm/app.py`'s `_init_tools`, right after the `cron_tool` registration block (`from openacm.tools import cron_tool` / `self.tool_registry.register_module(cron_tool)`) and before `swarm_tool`, insert:

```python
        from openacm.tools import flow_tool
        self.tool_registry.register_module(flow_tool)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_flow_tool.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Run the full backend suite to confirm no regressions**

Run: `pytest -q`
Expected: same pass count as Task 2's baseline plus this task's new tests, no new failures beyond the pre-existing unrelated `gmail_classifier` errors

- [ ] **Step 7: Commit**

```bash
git add src/openacm/tools/flow_tool.py src/openacm/app.py tests/unit/test_flow_tool.py
git commit -m "feat(agents): create_or_update_agent_flow tool lets an AI generate flows"
```

---

## Final manual verification (after all 5 tasks)

Per the spec's Testing section — build+deploy the frontend, start the backend (app-level Telegram/Discord tokens disabled, per this session's established consent), and using the real UI:

1. Open an existing flow, click "Exportar", confirm the downloaded `.json` has the `{kind, version, name, description, graph_json}` shape with `graph_json` as a real nested object.
2. Click "Importar flujo" on the flow list, paste that same JSON back in, confirm it creates a NEW flow (not overwriting the original) that opens and runs identically (use "Probar flujo").
3. Paste deliberately-broken JSON (e.g. an unknown node type) into Import, confirm the error is shown inline and legible.
4. Ask an agent, in a normal chat message, to build a small flow (e.g. "hazme un flujo que reciba un producto y busque en WooCommerce"), confirm the agent calls `create_or_update_agent_flow`, the flow appears in that agent's Flujos tab with auto-placed nodes, and it's valid/runnable.
5. Clean up any test flows created during verification; stop the backend afterward.
