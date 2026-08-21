# Flow Editor Power Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add branch-rejoin (merge) topology, canvas copy/paste, a per-flow LLM-facing skill, and an Inspector v2 (collapsible sections + live template preview) to the already-shipped Agent Node Flows feature.

**Architecture:** The backend changes are small and precise — `FlowExecutor`'s `set` node gets a `previous_id`-based source fix instead of a static reverse-edge map (so it survives merges), a cycle-detection function gates both save and test execution, and a runtime iteration cap backstops it. A fourth `skills.flow_id` scope is added to the existing three-times-proven Skills pattern, injected from inside `AgentRunner.run()` only when the flow's tool is actually selected for a given message — no changes to the shared `Brain` agentic loop. Everything else is frontend: `FlowCanvas.tsx` gets copy/paste and a multi-predecessor-aware variable walk, `node-types.tsx` gets a merge badge, and a new `InspectorSection` component plus live preview round out the Inspector.

**Tech Stack:** Python 3.13, pytest + pytest-asyncio (auto mode), Next.js/React/TypeScript, `@xyflow/react` v12.

**Spec:** `docs/superpowers/specs/2026-08-20-flow-editor-power-upgrades-design.md`

## Global Constraints

- **A Conditional never takes both branches in one execution** — "merge" is two edges sharing a target, never a join that waits for two inputs. No general DAG engine, no loop/iteration feature.
- **Real cycles remain rejected, not supported** — a save or test with a cycle in the graph must fail with a clear error naming the nodes involved, both in the editor (save/test time) and, as defense in depth, at runtime (iteration cap).
- **Flows remain 100% private per agent** — copy/paste never crosses flow or agent boundaries.
- **A flow-skill is singular** — zero or one skill per flow, never many, never toggled/shared like global/worker/agent skills are.
- **No custom-code node type** — nothing in this plan adds arbitrary code execution.
- **No changes to Set/Get variables or to node delete/multi-select in this plan** — both are open questions pending the user's own manual re-verification (see the Post-plan manual smoke test).
- **No test framework exists for the frontend** — `npx tsc --noEmit` clean is this plan's frontend verification bar, consistent with every prior flow-editor plan. Manual browser verification is still required before the plan is considered done (see the final section).

---

### Task 1: Backend — `set` node merge fix (`previous_id` instead of `edges_by_target`)

**Files:**
- Modify: `src/openacm/core/flow_executor.py`
- Test: `tests/unit/test_flow_executor.py`

**Interfaces:**
- Consumes: nothing from other tasks — this is the first task.
- Produces: `FlowExecutor.run()`'s internal walk no longer builds or reads `edges_by_target`; the `set` node case resolves its source from a `previous_id` local variable the loop already tracks. Nothing outside `run()` calls `edges_by_target`, so no other file changes.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_flow_executor.py`, add this test to the existing `TestSetNode` class (after `test_two_variables_with_the_same_name_last_one_wins`):

```python
    async def test_set_node_downstream_of_a_merge_uses_the_branch_actually_taken(self):
        """Two edges point at the same Set node — one from each of a
        Conditional's branches. Only one branch executes per run, so the
        Set node must alias whichever branch's output actually reached it,
        not whichever edge happens to be last in the graph's edge list."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": [{"name": "x", "type": "string", "required": True}]}},
                {"id": "cond1", "type": "conditional", "config": {"field": "{{x}}", "operator": "equals", "value": "yes"}},
                {"id": "merge1", "type": "set", "config": {"name": "picked"}},
                {"id": "end", "type": "end", "config": {"template": "{{picked}}"}},
            ],
            "edges": [
                {"from": "start", "to": "cond1", "fromHandle": "default"},
                {"from": "cond1", "to": "merge1", "fromHandle": "true"},
                {"from": "cond1", "to": "merge1", "fromHandle": "false"},
                {"from": "merge1", "to": "end", "fromHandle": "default"},
            ],
        }
        executor = FlowExecutor()

        result_true = await executor.run(graph, params={"x": "yes"})
        result_false = await executor.run(graph, params={"x": "no"})

        # cond1's passthrough output is the resolved field value itself
        # (per TestConditionalNode.test_passthrough_output_is_the_evaluated_value_not_the_boolean)
        assert result_true == "yes"
        assert result_false == "no"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestSetNode::test_set_node_downstream_of_a_merge_uses_the_branch_actually_taken -v`
Expected: FAIL. With today's `edges_by_target` dict, the second edge inserted for `merge1` (whichever of `true`/`false` is processed last while building the map) silently overwrites the first — so one of `result_true`/`result_false` will assert against the wrong branch's value instead of correctly reflecting whichever branch actually ran.

- [ ] **Step 3: Implement**

In `src/openacm/core/flow_executor.py`, find `run()` (currently lines 146-206). Replace:

```python
    async def run(self, graph: dict, params: dict) -> str:
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        edges_by_source: dict[str, dict[str, str]] = {}
        edges_by_target: dict[str, str] = {}
        for edge in graph.get("edges", []):
            edges_by_source.setdefault(edge["from"], {})[edge.get("fromHandle", "default")] = edge["to"]
            edges_by_target[edge["to"]] = edge["from"]

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

            if node["type"] == "set":
                source_id = edges_by_target.get(node["id"])
                if source_id and source_id in outputs:
                    value = outputs[source_id]
                    outputs[node["id"]] = value
                    outputs[node["config"]["name"]] = value
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue

            if node["type"] == "get":
                name = node["config"]["name"]
                if name in outputs:
                    outputs[node["id"]] = outputs[name]
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue

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

with:

```python
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
        previous_id: str | None = None

        while current_id:
            node = nodes.get(current_id)
            if node is None:
                return f"Error: flow references unknown node '{current_id}'"

            if node["type"] == "end":
                template = node["config"].get("template", "")
                return substitute_templates(template, params, outputs)

            if node["type"] == "set":
                # previous_id is the node actually visited just before this
                # one IN THIS RUN — correct even when this node has multiple
                # incoming edges in the graph (a merge point after a
                # Conditional's two branches), since only one of those
                # edges is ever the real predecessor on any given run.
                if previous_id and previous_id in outputs:
                    value = outputs[previous_id]
                    outputs[node["id"]] = value
                    outputs[node["config"]["name"]] = value
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue

            if node["type"] == "get":
                name = node["config"]["name"]
                if name in outputs:
                    outputs[node["id"]] = outputs[name]
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue

            handler = self._HANDLERS.get(node["type"])
            if handler is None:
                return f"Error: unknown node type '{node['type']}'"

            try:
                result = await handler(self, node, params, outputs)
            except Exception as exc:
                return f"Error in node '{node['id']}' ({node['type']}): {exc}"

            if node["type"] == "conditional":
                outputs[node["id"]] = result["passthrough"]
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("true" if result["branch"] else "false")
            else:
                outputs[node["id"]] = result
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("default")

        return "Error: flow ended without reaching an End node"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests, including the new merge test — `edges_by_target` is gone and nothing else in the file referenced it, confirmed by re-reading the full file after this edit).

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "fix(flows): Set node resolves source via previous_id, not a static reverse-edge map, so it survives merges"
```

---

### Task 2: Backend — cycle detection at save/test time

**Files:**
- Modify: `src/openacm/core/flow_executor.py`
- Modify: `src/openacm/web/routers/agents.py:188-233` (`update_agent_flow`, `test_agent_flow`)
- Test: `tests/unit/test_flow_executor.py`, `tests/unit/test_agents_flows_api.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent function).
- Produces: `detect_cycle(graph: dict) -> list[str] | None` in `flow_executor.py`, importable as `from openacm.core.flow_executor import detect_cycle`. `PUT /flows/{flow_id}` and `POST /flows/{flow_id}/test` both return HTTP 400 with a message naming the cycle's node ids when the graph they're about to persist/execute contains one.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_flow_executor.py`, add near the top (after the imports, before `class TestSubstituteTemplates`):

```python
class TestDetectCycle:
    def test_linear_flow_has_no_cycle(self):
        from openacm.core.flow_executor import detect_cycle
        graph = {
            "nodes": [{"id": "start"}, {"id": "http1"}, {"id": "end"}],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default"},
                {"from": "http1", "to": "end", "fromHandle": "default"},
            ],
        }
        assert detect_cycle(graph) is None

    def test_a_valid_merge_is_not_a_cycle(self):
        from openacm.core.flow_executor import detect_cycle
        graph = {
            "nodes": [{"id": "start"}, {"id": "cond1"}, {"id": "merge1"}, {"id": "end"}],
            "edges": [
                {"from": "start", "to": "cond1", "fromHandle": "default"},
                {"from": "cond1", "to": "merge1", "fromHandle": "true"},
                {"from": "cond1", "to": "merge1", "fromHandle": "false"},
                {"from": "merge1", "to": "end", "fromHandle": "default"},
            ],
        }
        assert detect_cycle(graph) is None

    def test_a_real_cycle_is_detected_and_names_its_nodes(self):
        from openacm.core.flow_executor import detect_cycle
        graph = {
            "nodes": [{"id": "start"}, {"id": "a"}, {"id": "b"}, {"id": "c"}],
            "edges": [
                {"from": "start", "to": "a", "fromHandle": "default"},
                {"from": "a", "to": "b", "fromHandle": "default"},
                {"from": "b", "to": "c", "fromHandle": "default"},
                {"from": "c", "to": "a", "fromHandle": "default"},
            ],
        }
        cycle = detect_cycle(graph)
        assert cycle is not None
        assert set(cycle) == {"a", "b", "c"}
```

Then, in `tests/unit/test_agents_flows_api.py`, add a new test class after `class TestCreateUpdateDeleteFlow`:

```python
CYCLIC_GRAPH = _json.dumps({
    "nodes": [{"id": "start", "type": "start", "config": {"parameters": []}},
              {"id": "a", "type": "http", "config": {"url": "https://example.com", "method": "GET"}},
              {"id": "b", "type": "http", "config": {"url": "https://example.com", "method": "GET"}}],
    "edges": [{"from": "start", "to": "a", "fromHandle": "default"},
              {"from": "a", "to": "b", "fromHandle": "default"},
              {"from": "b", "to": "a", "fromHandle": "default"}],
})

VALID_MERGE_GRAPH = _json.dumps({
    "nodes": [{"id": "start", "type": "start", "config": {"parameters": []}},
              {"id": "cond1", "type": "conditional", "config": {"field": "x", "operator": "contains", "value": "x"}},
              {"id": "merge1", "type": "end", "config": {"template": "done"}}],
    "edges": [{"from": "start", "to": "cond1", "fromHandle": "default"},
              {"from": "cond1", "to": "merge1", "fromHandle": "true"},
              {"from": "cond1", "to": "merge1", "fromHandle": "false"}],
})


class TestCycleValidation:
    async def test_saving_a_valid_merge_graph_succeeds(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/flows/7", json={"graph_json": VALID_MERGE_GRAPH})
        assert resp.status_code == 200

    async def test_saving_a_cyclic_graph_is_rejected(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/flows/7", json={"graph_json": CYCLIC_GRAPH})
        assert resp.status_code == 400
        assert "a" in resp.json()["detail"]
        assert "b" in resp.json()["detail"]
        _mock_state.update_flow.assert_not_awaited()

    async def test_testing_a_cyclic_graph_override_is_rejected(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post(
                "/api/agents/42/flows/7/test",
                json={"params": {}, "graph_json": CYCLIC_GRAPH},
            )
        assert resp.status_code == 400

    async def test_testing_the_saved_graph_with_no_override_still_validates_it(self, app_client, _mock_state):
        _mock_state.get_flow.return_value = {**FLOW_ROW, "graph_json": CYCLIC_GRAPH}
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/test", json={"params": {}})
        assert resp.status_code == 400
```

Add `import json as _json` at the top of `tests/unit/test_agents_flows_api.py` if it isn't already imported (check the file first — it isn't, per the current file read).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestDetectCycle -v`
Expected: FAIL with `ImportError: cannot import name 'detect_cycle'`.

Run: `pytest tests/unit/test_agents_flows_api.py::TestCycleValidation -v`
Expected: FAIL — both endpoints currently return 200 for a cyclic graph (no validation exists yet).

- [ ] **Step 3: Implement**

In `src/openacm/core/flow_executor.py`, add this function after the module-level `_TEMPLATE_RE` definition and before `substitute_templates`:

```python
def detect_cycle(graph: dict) -> list[str] | None:
    """DFS cycle detection over the flow's directed edges (ignoring
    fromHandle — both a Conditional's true and false edges are just
    directed edges for this purpose). Returns the node ids forming a
    cycle if one exists, else None.

    A merge (two edges into the same target) is NOT a cycle: the first
    path to reach a node finishes exploring it (turns it BLACK) before a
    second path can reach it, so the second arrival sees BLACK, not GRAY,
    and is correctly not treated as a cycle.
    """
    adjacency: dict[str, list[str]] = {}
    for edge in graph.get("edges", []):
        adjacency.setdefault(edge["from"], []).append(edge["to"])

    node_ids = [n["id"] for n in graph.get("nodes", [])]
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node_id: WHITE for node_id in node_ids}
    stack: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        color[node_id] = GRAY
        stack.append(node_id)
        for neighbor in adjacency.get(node_id, []):
            neighbor_color = color.get(neighbor, WHITE)
            if neighbor_color == GRAY:
                cycle_start = stack.index(neighbor)
                return stack[cycle_start:]
            if neighbor_color == WHITE:
                found = visit(neighbor)
                if found:
                    return found
        stack.pop()
        color[node_id] = BLACK
        return None

    for node_id in node_ids:
        if color[node_id] == WHITE:
            found = visit(node_id)
            if found:
                return found
    return None
```

In `src/openacm/web/routers/agents.py`, modify `update_agent_flow` (currently lines 188-198):

```python
    @app.put("/api/agents/{agent_id}/flows/{flow_id}")
    async def update_agent_flow(agent_id: int, flow_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        data = await request.json()
        allowed_fields = {"name", "description", "graph_json", "is_active"}
        kwargs = {k: v for k, v in data.items() if k in allowed_fields}

        if "graph_json" in kwargs:
            from openacm.core.flow_executor import detect_cycle
            import json as _json
            cycle = detect_cycle(_json.loads(kwargs["graph_json"]))
            if cycle:
                raise HTTPException(status_code=400, detail=f"Flow has a cycle: {' -> '.join(cycle)}")

        ok = await _state.database.update_flow(flow_id, agent_id=agent_id, **kwargs)
        if not ok:
            raise HTTPException(status_code=404, detail="Flow not found")
        return await _state.database.get_flow(flow_id)
```

And `test_agent_flow` (currently lines 209-233):

```python
    @app.post("/api/agents/{agent_id}/flows/{flow_id}/test")
    async def test_agent_flow(agent_id: int, flow_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        flow = await _state.database.get_flow(flow_id)
        if not flow or flow["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Flow not found")

        from openacm.core.flow_executor import FlowExecutor, detect_cycle
        import json as _json

        data = await request.json()
        test_params = data.get("params", {})
        graph_json_override = data.get("graph_json")

        graph = _json.loads(graph_json_override) if graph_json_override else _json.loads(flow["graph_json"])

        cycle = detect_cycle(graph)
        if cycle:
            raise HTTPException(status_code=400, detail=f"Flow has a cycle: {' -> '.join(cycle)}")

        async def get_connection(connection_id: int):
            return await _state.database.get_connection(connection_id)

        executor = FlowExecutor(get_connection=get_connection)
        result = await executor.run(graph, test_params)
        return {"result": result}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py tests/unit/test_agents_flows_api.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/flow_executor.py src/openacm/web/routers/agents.py tests/unit/test_flow_executor.py tests/unit/test_agents_flows_api.py
git commit -m "feat(flows): reject cyclic graphs at save and test time with a named-cycle error"
```

---

### Task 3: Backend — runtime iteration cap (defense in depth)

**Files:**
- Modify: `src/openacm/core/flow_executor.py`
- Test: `tests/unit/test_flow_executor.py`

**Interfaces:**
- Consumes: Task 1's `run()` shape (the `previous_id`-based loop).
- Produces: `run()` returns the exact string `"Error: flow exceeded maximum node visits (possible cycle)"` instead of looping forever when a cycle somehow reaches it despite Task 2's save-time guard.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_flow_executor.py`, add to `class TestFlowExecutorStartToEnd` (after `test_flow_with_no_start_node_returns_error`):

```python
    async def test_a_cycle_that_reaches_run_directly_is_capped_not_infinite(self):
        """detect_cycle() (Task 2) guards the API layer, but run() itself
        must not hang if a cyclic graph reaches it some other way (e.g. a
        row edited directly in the database, bypassing the API)."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "a", "type": "http", "config": {"url": "https://example.com", "method": "GET"}},
                {"id": "b", "type": "http", "config": {"url": "https://example.com", "method": "GET"}},
            ],
            "edges": [
                {"from": "start", "to": "a", "fromHandle": "default"},
                {"from": "a", "to": "b", "fromHandle": "default"},
                {"from": "b", "to": "a", "fromHandle": "default"},
            ],
        }
        executor = FlowExecutor()

        result = await executor.run(graph, params={})

        assert result == "Error: flow exceeded maximum node visits (possible cycle)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest "tests/unit/test_flow_executor.py::TestFlowExecutorStartToEnd::test_a_cycle_that_reaches_run_directly_is_capped_not_infinite" -v --timeout=10`

Note: this repo may not have `pytest-timeout` installed — if the command hangs past ~10 seconds with no output, that itself confirms the failure (an infinite loop); press Ctrl-C and proceed to Step 3. Expected either way: no cap exists yet, so the test cannot currently pass.

- [ ] **Step 3: Implement**

In `src/openacm/core/flow_executor.py`, inside `run()` (the version from Task 1), add a class constant and a counter. Add the constant next to `_CONDITIONAL_OPERATORS`:

```python
    _CONDITIONAL_OPERATORS = {"contains", "equals", "is_empty", "is_error"}
    _MAX_NODE_VISITS = 50
```

Then change the `while current_id:` loop's opening lines from:

```python
        outputs: dict[str, Any] = {}
        current_id = edges_by_source.get(start_node["id"], {}).get("default")
        previous_id: str | None = None

        while current_id:
            node = nodes.get(current_id)
            if node is None:
                return f"Error: flow references unknown node '{current_id}'"
```

to:

```python
        outputs: dict[str, Any] = {}
        current_id = edges_by_source.get(start_node["id"], {}).get("default")
        previous_id: str | None = None
        visits = 0

        while current_id:
            visits += 1
            if visits > self._MAX_NODE_VISITS:
                return "Error: flow exceeded maximum node visits (possible cycle)"

            node = nodes.get(current_id)
            if node is None:
                return f"Error: flow references unknown node '{current_id}'"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): cap FlowExecutor.run() at 50 node visits as a runtime cycle backstop"
```

---

### Task 4: Frontend — Inspector variable-picker union walk + merge badge

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx:59-78`
- Modify: `frontend/components/flow-editor/node-types.tsx`

**Interfaces:**
- Consumes: nothing from backend tasks (pure frontend, independent).
- Produces: `availableVariableNames()` keeps its exact signature (`(nodes, edges, selectedNodeId) => string[]`) — callers in the Inspector (5 call sites) are unaffected. `node-types.tsx` exports a new `MergeBadge` component used internally by each target-handle node.

- [ ] **Step 1: Implement the union walk**

In `frontend/components/flow-editor/FlowCanvas.tsx`, replace `availableVariableNames` (currently lines 59-78):

```typescript
function availableVariableNames(nodes: Node[], edges: Edge[], selectedNodeId: string): string[] {
  // Every node has exactly one incoming edge (the graph is linear + one
  // branch point at Conditional) — walking backward from a specific node
  // through "target -> source" is a single, unambiguous path. It never
  // needs to know which of a Conditional's branches is "taken" at
  // runtime, because tracing backward from one node only ever follows
  // the one path that actually leads to it.
  const incomingBySource: Record<string, string> = {};
  for (const e of edges) incomingBySource[e.target] = e.source;

  const names: string[] = [];
  let currentId: string | undefined = incomingBySource[selectedNodeId];
  while (currentId) {
    const node = nodes.find(n => n.id === currentId);
    const name = node?.type === 'set' ? (node.data.name as string | undefined) : undefined;
    if (name) names.push(name);
    currentId = incomingBySource[currentId];
  }
  return names;
}
```

with:

```typescript
function availableVariableNames(nodes: Node[], edges: Edge[], selectedNodeId: string): string[] {
  // A node can have multiple incoming edges since merge points were added
  // (a Conditional's true/false branches sharing a downstream node) — this
  // collects every ancestor reachable via ANY incoming path, not just a
  // single linear chain. A Set node reachable via only one branch still
  // shows up as an insertable reference here; if the flow actually took
  // the other branch at runtime, referencing it resolves to the existing
  // "[missing: ...]" marker rather than being silently hidden from the
  // picker.
  const incomingBySource: Record<string, string[]> = {};
  for (const e of edges) {
    (incomingBySource[e.target] ||= []).push(e.source);
  }

  const names = new Set<string>();
  const visited = new Set<string>();
  const queue: string[] = [...(incomingBySource[selectedNodeId] || [])];
  while (queue.length > 0) {
    const currentId = queue.shift()!;
    if (visited.has(currentId)) continue;
    visited.add(currentId);
    const node = nodes.find(n => n.id === currentId);
    const name = node?.type === 'set' ? (node.data.name as string | undefined) : undefined;
    if (name) names.add(name);
    queue.push(...(incomingBySource[currentId] || []));
  }
  return Array.from(names);
}
```

- [ ] **Step 2: Add the merge badge**

In `frontend/components/flow-editor/node-types.tsx`, add the import and a small shared component after the existing imports:

```typescript
'use client';

import { Handle, Position, useNodeConnections, type NodeProps } from '@xyflow/react';
```

Then, after `pinLabelStyle` and before `StartNode`:

```typescript
const mergeBadgeStyle: React.CSSProperties = {
  position: 'absolute', top: -6, right: -6, width: 14, height: 14, borderRadius: '50%',
  background: 'var(--acm-accent)', color: 'var(--acm-base)', fontSize: 9, fontWeight: 700,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

function MergeBadge({ id }: { id: string }) {
  const incoming = useNodeConnections({ id, handleType: 'target' });
  if (incoming.length < 2) return null;
  return <div style={mergeBadgeStyle} title="Punto de unión (varias ramas llegan aquí)">{incoming.length}</div>;
}
```

Then add `<MergeBadge id={id} />` as the first child inside the outer `<div>` of every node component that has a target handle — `HttpNode`, `ConditionalNode`, `WooCommerceNode`, `SetNode`, `EndNode` (NOT `StartNode` or `GetNode`, neither of which has a target handle). For example, `HttpNode` becomes:

```typescript
export function HttpNode({ id, data }: NodeProps) {
  return (
    <div style={{ ...baseStyleFor('http'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.integration }}>🌐 HTTP Request</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.method || 'GET')} {String(data.url || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: response</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}
```

Apply the same two changes (`position: 'relative'` added to the outer `style`, `<MergeBadge id={id} />` as first child) to `ConditionalNode`, `WooCommerceNode`, `SetNode`, and `EndNode`.

- [ ] **Step 3: Verify types**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors. If `useNodeConnections`'s exported type signature doesn't match (e.g. the `handleType` option name), check the installed package's type definitions (`node_modules/@xyflow/react/dist/esm/hooks/useNodeConnections.d.ts` or similar) and adjust the call to match rather than casting past the error.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx frontend/components/flow-editor/node-types.tsx
git commit -m "feat(agents): variable-picker sees both branches of a merge, nodes show a merge badge"
```

---

### Task 5: Frontend — copy/paste

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: `nextNodeId` (existing, `FlowCanvas.tsx:179-182`), `nodes`/`edges`/`setNodes`/`setEdges` state (existing).
- Produces: nothing consumed by later tasks — this is a self-contained addition.

- [ ] **Step 1: Implement**

In `frontend/components/flow-editor/FlowCanvas.tsx`, add a clipboard ref and keyboard handler inside `FlowCanvasInner`, right after the `nextNodeId` function (currently lines 179-182):

```typescript
  const nextNodeId = (prefix: string) => {
    nodeIdCounterRef.current += 1;
    return `${prefix}_${nodeIdCounterRef.current}`;
  };

  const clipboardRef = useRef<{ nodes: Node[]; edges: Edge[] } | null>(null);

  const onCanvasCopy = useCallback(() => {
    const selectedNodes = nodes.filter(n => n.selected && n.type !== 'start' && n.type !== 'end');
    if (selectedNodes.length === 0) return;
    const selectedIds = new Set(selectedNodes.map(n => n.id));
    const internalEdges = edges.filter(e => selectedIds.has(e.source) && selectedIds.has(e.target));
    clipboardRef.current = { nodes: selectedNodes, edges: internalEdges };
  }, [nodes, edges]);

  const onCanvasPaste = useCallback(() => {
    const clip = clipboardRef.current;
    if (!clip || clip.nodes.length === 0) return;

    const idMap: Record<string, string> = {};
    const pastedNodes: Node[] = clip.nodes.map(n => {
      const newId = nextNodeId((n.type || 'http') as string);
      idMap[n.id] = newId;
      return { ...n, id: newId, selected: false, position: { x: n.position.x + 40, y: n.position.y + 40 } };
    });
    const pastedEdges: Edge[] = clip.edges.map(e => ({
      id: `${idMap[e.source]}-${idMap[e.target]}-${e.sourceHandle || 'default'}`,
      source: idMap[e.source],
      target: idMap[e.target],
      sourceHandle: e.sourceHandle,
    }));

    setNodes(nds => [...nds, ...pastedNodes]);
    setEdges(eds => [...eds, ...pastedEdges]);
  }, [nodeIdCounterRef]);

  const onCanvasKeyDown = useCallback((event: React.KeyboardEvent) => {
    const isMeta = event.ctrlKey || event.metaKey;
    if (!isMeta) return;
    if (event.key === 'c' || event.key === 'C') {
      onCanvasCopy();
    } else if (event.key === 'v' || event.key === 'V') {
      onCanvasPaste();
    }
  }, [onCanvasCopy, onCanvasPaste]);
```

Then wire `onCanvasKeyDown` onto the canvas wrapper div (currently lines 355-361):

```typescript
      <div
        ref={canvasWrapperRef}
        className="flex-1 relative"
        style={{ border: '1px solid var(--acm-border)', borderRadius: 8 }}
        onDragOver={onCanvasDragOver}
        onDrop={onCanvasDrop}
        onKeyDown={onCanvasKeyDown}
        tabIndex={0}
      >
```

(`tabIndex={0}` is required — a plain `div` doesn't receive keyboard focus/events without it, and the canvas needs focus for `Ctrl+C`/`Ctrl+V` to reach this handler when the user has clicked a node rather than a text field.)

`onCanvasCopy` reads `n.selected` — this relies on React Flow's built-in node selection state (set by clicking/Shift-clicking/box-selecting a node), which `applyNodeChanges` (already wired via `onNodesChange`) already keeps in sync on the `nodes` array. No new state needed for "what's selected."

- [ ] **Step 2: Verify types**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): Ctrl+C/Ctrl+V copies selected nodes within the same flow, internal edges only"
```

---

### Task 6: Backend — `skills.flow_id` migration + DB-layer flow-skill access

**Files:**
- Modify: `src/openacm/storage/database.py`
- Test: `tests/unit/test_database_flows.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `Database.create_skill(..., flow_id: int | None = None)` (extended signature, backward compatible — existing callers pass no `flow_id` and are unaffected). `Database.get_flow_skill(flow_id: int) -> dict | None`. `_SCHEMA_VERSION` becomes `35`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_database_flows.py`, add a new class after the existing `TestFlowCRUD`/`TestConnectionCRUD` classes (read the file's current tail first to append after the last class, matching its existing style):

```python
class TestFlowSkill:
    async def test_create_and_get_flow_skill(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        flow_id = await db.create_flow(agent_id=agent_id, name="f1")

        skill_id = await db.create_skill(
            name="cuando-usar-f1", description="d", content="c", flow_id=flow_id,
        )
        skill = await db.get_flow_skill(flow_id)

        assert skill is not None
        assert skill["id"] == skill_id
        assert skill["flow_id"] == flow_id
        await db.close()

    async def test_flow_with_no_skill_returns_none(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        flow_id = await db.create_flow(agent_id=agent_id, name="f1")

        assert await db.get_flow_skill(flow_id) is None
        await db.close()

    async def test_skill_name_unique_per_flow(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        flow_id = await db.create_flow(agent_id=agent_id, name="f1")
        await db.create_skill(name="dup", description="d", content="c", flow_id=flow_id)

        with pytest.raises(Exception):
            await db.create_skill(name="dup", description="d2", content="c2", flow_id=flow_id)
        await db.close()

    async def test_deleting_flow_cascades_to_its_skill(self):
        db = await _make_db()
        agent_id = await _make_agent(db)
        flow_id = await db.create_flow(agent_id=agent_id, name="f1")
        await db.create_skill(name="s1", description="d", content="c", flow_id=flow_id)

        await db.delete_flow(flow_id)

        assert await db.get_flow_skill(flow_id) is None
        await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_database_flows.py::TestFlowSkill -v`
Expected: FAIL — `create_skill()` doesn't accept `flow_id` yet, and `get_flow_skill` doesn't exist.

- [ ] **Step 3: Implement**

In `src/openacm/storage/database.py`, change `_SCHEMA_VERSION` (currently line 171):

```python
    _SCHEMA_VERSION = 35
```

Find Migration 33's block (search `# ── Migration 33`) and add a new block immediately after it, before whatever migration/code currently follows:

```python
        # ── Migration 35: per-flow skill scoping ──────────────────────────
        # Adds skills.flow_id (NULL = not flow-scoped, unchanged; set =
        # private to that one flow). Unlike worker_id/agent_id, a flow-skill
        # is singular by design (zero or one skill per flow, enforced at the
        # API layer in Task 7) — no flow_skills join table, since there is
        # no "flow opts into a global skill" concept to track.
        if current < 35:
            await self._db.execute(
                "ALTER TABLE skills ADD COLUMN flow_id INTEGER REFERENCES flows(id) ON DELETE CASCADE"
            )
            await self._db.executescript("""
                DROP INDEX IF EXISTS idx_skills_name_global;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name_global
                    ON skills(name) WHERE worker_id IS NULL AND agent_id IS NULL AND flow_id IS NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name_per_flow
                    ON skills(name, flow_id) WHERE flow_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_skills_flow ON skills(flow_id);
            """)
            await self._db.commit()
            log.info("Migration 35: per-flow skill scoping (skills.flow_id)")
```

Modify `create_skill` (currently lines 1404-1425):

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
        flow_id: int | None = None,
    ) -> int:
        """Create a new skill. worker_id=None + agent_id=None + flow_id=None
        makes it a global system skill; setting exactly one of the three
        scopes it privately to that worker/agent/flow."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO skills (name, description, content, category, is_builtin, worker_id, agent_id, flow_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, description, content, category, int(is_builtin), worker_id, agent_id, flow_id),
        )
        await self._db.commit()
        return cursor.lastrowid
```

Add `get_flow_skill` right after `get_agent_private_skills`/`get_agent_enabled_global_skill_ids`/`enable_agent_skill`/`disable_agent_skill` (currently ending around line 1600, right before the `# ─── Agent Node Flows ───` comment at line 1602):

```python
    async def get_flow_skill(self, flow_id: int) -> dict[str, Any] | None:
        """A flow has zero or one skill (singular by design, unlike the
        many-global-skills-per-agent/worker pattern)."""
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM skills WHERE flow_id = ?", (flow_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_database_flows.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest -q`
Expected: no new failures beyond the known pre-existing baseline (gmail_classifier + date-dependent gmail_summary tests, per every prior flow-editor plan's final review).

- [ ] **Step 6: Commit**

```bash
git add src/openacm/storage/database.py tests/unit/test_database_flows.py
git commit -m "feat(flows): Migration 35 — skills.flow_id, a flow's own singular skill"
```

---

### Task 7: Backend — flow-skill API + LLM-assisted generation

**Files:**
- Modify: `src/openacm/core/skill_manager.py`
- Modify: `src/openacm/web/routers/agents.py`
- Test: `tests/unit/test_agents_flow_skill_api.py` (new)

**Interfaces:**
- Consumes: `Database.create_skill(..., flow_id=)`, `Database.get_flow_skill(flow_id)` (Task 6). `Database.get_flow(flow_id)`, `Database.update_skill(skill_id, ...)`, `Database.delete_skill(skill_id)` (pre-existing).
- Produces: `SkillManager.create_flow_skill(flow_id, name, description, content) -> dict | None`, `SkillManager.generate_flow_skill(flow_id, name, description, llm_router=None) -> dict | None`, `SkillManager.get_flow_skill(flow_id) -> dict | None` (thin passthrough to the database method, for symmetry with `get_active_skills_prompt_for_agent`'s existing style of going through `self.database`). Five new endpoints under `/api/agents/{agent_id}/flows/{flow_id}/skill[...]`, consumed by Task 8 (backend) and Task 9 (frontend).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_agents_flow_skill_api.py`:

```python
"""Tests for the per-flow skill API endpoints under the agents router."""
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
    "graph_json": '{"nodes":[],"edges":[]}', "is_active": 1,
    "created_at": "2026-01-01", "updated_at": "2026-01-01",
}

SKILL_ROW = {
    "id": 3, "flow_id": 7, "name": "cuando-usar", "description": "d", "content": "c",
    "category": "custom", "is_active": 1, "is_builtin": 0, "worker_id": None, "agent_id": None,
}


@pytest.fixture(autouse=True)
def _mock_state(monkeypatch):
    db = MagicMock()
    db.get_flow = AsyncMock(return_value=FLOW_ROW)
    db.get_flow_skill = AsyncMock(return_value=None)
    db.update_skill = AsyncMock(return_value=True)
    db.delete_skill = AsyncMock(return_value=True)
    monkeypatch.setattr(_state, "database", db)

    brain = MagicMock()
    brain.skill_manager = MagicMock()
    brain.skill_manager.create_flow_skill = AsyncMock(return_value=SKILL_ROW)
    brain.skill_manager.generate_flow_skill = AsyncMock(return_value=SKILL_ROW)
    brain.llm_router = MagicMock()
    monkeypatch.setattr(_state, "brain", brain)

    yield db
    monkeypatch.setattr(_state, "database", None)
    monkeypatch.setattr(_state, "brain", None)


class TestGetFlowSkill:
    async def test_no_skill_returns_null(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/flows/7/skill")
        assert resp.status_code == 200
        assert resp.json() is None

    async def test_existing_skill_is_returned(self, app_client, _mock_state):
        _mock_state.get_flow_skill.return_value = SKILL_ROW
        async with app_client as ac:
            resp = await ac.get("/api/agents/42/flows/7/skill")
        assert resp.status_code == 200
        assert resp.json()["name"] == "cuando-usar"

    async def test_flow_belonging_to_a_different_agent_404s(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.get("/api/agents/999/flows/7/skill")
        assert resp.status_code == 404


class TestCreateFlowSkill:
    async def test_create_when_none_exists(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/skill", json={"name": "n", "description": "d", "content": "c"})
        assert resp.status_code == 200
        _state.brain.skill_manager.create_flow_skill.assert_awaited_once()

    async def test_create_when_one_already_exists_is_rejected(self, app_client, _mock_state):
        _mock_state.get_flow_skill.return_value = SKILL_ROW
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/skill", json={"name": "n", "description": "d", "content": "c"})
        assert resp.status_code == 409


class TestUpdateDeleteFlowSkill:
    async def test_update_existing_skill(self, app_client, _mock_state):
        _mock_state.get_flow_skill.return_value = SKILL_ROW
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/flows/7/skill", json={"content": "new content"})
        assert resp.status_code == 200
        _mock_state.update_skill.assert_awaited_once()

    async def test_update_when_none_exists_404s(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.put("/api/agents/42/flows/7/skill", json={"content": "x"})
        assert resp.status_code == 404

    async def test_delete_existing_skill(self, app_client, _mock_state):
        _mock_state.get_flow_skill.return_value = SKILL_ROW
        async with app_client as ac:
            resp = await ac.delete("/api/agents/42/flows/7/skill")
        assert resp.status_code == 200
        _mock_state.delete_skill.assert_awaited_once_with(3)


class TestGenerateFlowSkill:
    async def test_generate_calls_skill_manager(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/skill/generate", json={"name": "n", "description": "d"})
        assert resp.status_code == 200
        _state.brain.skill_manager.generate_flow_skill.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agents_flow_skill_api.py -v`
Expected: FAIL with 404s (routes don't exist yet).

- [ ] **Step 3: Implement**

In `src/openacm/core/skill_manager.py`, add these three methods after `get_active_skills_prompt_for_agent` (currently the last method in the file, ending at line 538):

```python

    async def get_flow_skill(self, flow_id: int) -> dict[str, Any] | None:
        """A flow's own singular skill, if it has one."""
        return await self.database.get_flow_skill(flow_id)

    async def create_flow_skill(
        self,
        flow_id: int,
        name: str,
        description: str,
        content: str,
    ) -> dict[str, Any] | None:
        """Create a flow's own skill. Unlike create_skill(), this never
        touches the ./skills/ file-sync path — see create_worker_skill()
        for why that matters. Callers must check get_flow_skill(flow_id)
        is None first — a flow has at most one skill (enforced at the API
        layer, not here, matching how create_worker_skill/create_agent_skill
        don't self-enforce agent/worker-level policy either)."""
        skill_id = await self.database.create_skill(
            name=name,
            description=description,
            content=content,
            category="custom",
            is_builtin=False,
            flow_id=flow_id,
        )
        return await self.database.get_skill(skill_id)

    async def generate_flow_skill(
        self,
        flow_id: int,
        name: str,
        description: str,
        llm_router=None,
    ) -> dict[str, Any] | None:
        """Generate a flow-scoped skill using the LLM — unlike
        generate_agent_skill()/generate_worker_skill(), the prompt is built
        from the flow's own graph (node types, descriptions, Start
        parameters) rather than from a user-supplied use_cases string, since
        the point is to describe THIS flow specifically."""
        if not llm_router:
            raise ValueError("LLM router required for skill generation")

        flow = await self.database.get_flow(flow_id)
        graph = json.loads(flow["graph_json"]) if flow else {"nodes": []}
        start_node = next((n for n in graph.get("nodes", []) if n["type"] == "start"), None)
        params_desc = ", ".join(
            f"{p['name']} ({p.get('type', 'string')}): {p.get('description', '')}"
            for p in (start_node["config"].get("parameters", []) if start_node else [])
        ) or "(sin parámetros)"
        node_types = ", ".join(n["type"] for n in graph.get("nodes", []) if n["type"] not in ("start", "end"))

        prompt = f"""Create a comprehensive skill guide for an AI assistant that decides when and how to call one specific tool (a "flow").

Flow Name: {name}
Flow Description: {description}
Flow's callable parameters: {params_desc}
Flow's internal steps (node types, in order): {node_types or '(ninguno)'}

Write the skill content in Markdown format following this structure:

# {name}

## Overview
Brief description of what this flow does and when it should be called.

## Guidelines
When to call this flow vs. not, and how to fill in its parameters correctly.

## Examples
Concrete example user requests that should trigger this flow.

## Common Pitfalls
What to avoid (e.g. calling it with the wrong parameter, calling it when a different tool is more appropriate).

Make it practical and actionable. The AI should be able to immediately apply this knowledge.
"""

        response = await llm_router.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        content = response.get("content", "")

        return await self.create_flow_skill(
            flow_id=flow_id,
            name=name,
            description=description,
            content=content,
        )
```

Add `import json` to the top of `skill_manager.py` if not already present (check — the current file imports `re`, `Path`, `Any`, `datetime`, but not `json`; add `import json` alongside the existing `import re` line).

In `src/openacm/web/routers/agents.py`, add these five endpoints right after the `test_agent_flow` endpoint (currently ending at line 233) and before the `# ─── Connections ────` comment (currently line 235):

```python
    @app.get("/api/agents/{agent_id}/flows/{flow_id}/skill")
    async def get_flow_skill(agent_id: int, flow_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        flow = await _state.database.get_flow(flow_id)
        if not flow or flow["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Flow not found")
        return await _state.database.get_flow_skill(flow_id)

    @app.post("/api/agents/{agent_id}/flows/{flow_id}/skill")
    async def create_flow_skill_endpoint(agent_id: int, flow_id: int, request: Request):
        if not _state.database or not _state.brain or not _state.brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        flow = await _state.database.get_flow(flow_id)
        if not flow or flow["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Flow not found")
        if await _state.database.get_flow_skill(flow_id) is not None:
            raise HTTPException(status_code=409, detail="Flow already has a skill — use PUT to update it")
        data = await request.json()
        return await _state.brain.skill_manager.create_flow_skill(
            flow_id=flow_id,
            name=data["name"],
            description=data.get("description", ""),
            content=data.get("content", ""),
        )

    @app.put("/api/agents/{agent_id}/flows/{flow_id}/skill")
    async def update_flow_skill_endpoint(agent_id: int, flow_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        flow = await _state.database.get_flow(flow_id)
        if not flow or flow["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Flow not found")
        skill = await _state.database.get_flow_skill(flow_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Flow has no skill yet")
        data = await request.json()
        # Database.update_skill (database.py:1461-1468) accepts description/
        # content/category/is_active only — no "name" parameter, so renaming
        # a flow-skill isn't supported by the underlying method. "name" is
        # deliberately excluded here rather than silently dropped by an
        # unsupported-kwarg failure.
        allowed_fields = {"description", "content"}
        kwargs = {k: v for k, v in data.items() if k in allowed_fields}
        await _state.database.update_skill(skill["id"], **kwargs)
        return await _state.database.get_flow_skill(flow_id)

    @app.delete("/api/agents/{agent_id}/flows/{flow_id}/skill")
    async def delete_flow_skill_endpoint(agent_id: int, flow_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        flow = await _state.database.get_flow(flow_id)
        if not flow or flow["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Flow not found")
        skill = await _state.database.get_flow_skill(flow_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Flow has no skill")
        await _state.database.delete_skill(skill["id"])
        return {"status": "ok", "deleted": True}

    @app.post("/api/agents/{agent_id}/flows/{flow_id}/skill/generate")
    async def generate_flow_skill_endpoint(agent_id: int, flow_id: int, request: Request):
        if not _state.database or not _state.brain or not _state.brain.skill_manager:
            raise HTTPException(status_code=503, detail="Skill manager not available")
        flow = await _state.database.get_flow(flow_id)
        if not flow or flow["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Flow not found")
        data = await request.json()
        try:
            return await _state.brain.skill_manager.generate_flow_skill(
                flow_id=flow_id,
                name=data["name"],
                description=data.get("description", ""),
                llm_router=_state.brain.llm_router,
            )
        except Exception as e:
            log.error("Failed to generate flow skill", error=str(e))
            raise HTTPException(status_code=500, detail="Failed to generate skill")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agents_flow_skill_api.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest -q`
Expected: no new failures beyond the known pre-existing baseline.

- [ ] **Step 6: Commit**

```bash
git add src/openacm/core/skill_manager.py src/openacm/web/routers/agents.py tests/unit/test_agents_flow_skill_api.py
git commit -m "feat(flows): per-flow skill CRUD + LLM-assisted generation from the flow's own graph"
```

---

### Task 8: Backend — wire flow-skill injection into `AgentRunner.run()`

**Files:**
- Modify: `src/openacm/tools/registry.py`
- Modify: `src/openacm/core/agent_runner.py`
- Test: `tests/unit/test_tool_registry.py`, `tests/unit/test_agent_runner_flows.py`

**Interfaces:**
- Consumes: `SkillManager.get_flow_skill(flow_id)` (Task 7).
- Produces: `ToolRegistry.is_relevant(message: str, text: str) -> bool`. Nothing consumed by later tasks.

**Why not `_AgentToolRegistry.get_tools_by_intent(message)`:** that method (pre-existing, `agent_runner.py:69-74`) unconditionally appends every one of the agent's active flow tools to its result, every single call, regardless of the message — `return base_schema + [t.to_openai_schema() for t in self._flow_tools.values()]`. That's intentional for its actual job (flow tools must always be callable, never hidden from the LLM by intent filtering), but it means every flow tool's name is ALWAYS in that list — using it as the "was this flow selected" signal would make the skill injection condition always true, i.e. always-on, exactly what the spec rejected. Flow tools also were never part of the static tool set `get_tools_semantic` precomputed embeddings for, so there is no existing per-flow-tool relevance signal anywhere in this codebase — `ToolRegistry.is_relevant` below adds a small, self-contained one.

- [ ] **Step 1: Write the failing test for `ToolRegistry.is_relevant`**

In `tests/unit/test_tool_registry.py`, add a new class (the file already has a `tool_registry` fixture from `conftest.py` with `_semantic_model` left `None` — matching `TestToolRegistryInit.test_semantic_embeddings_none_on_init`, so this test exercises the keyword-fallback path deterministically, no ML model needed):

```python
class TestIsRelevant:
    def test_matching_keyword_is_relevant(self, tool_registry):
        assert tool_registry.is_relevant("hay zapatos disponibles?", "Consulta disponibilidad de zapatos en la tienda") is True

    def test_no_matching_keyword_is_not_relevant(self, tool_registry):
        assert tool_registry.is_relevant("qué clima hace hoy?", "Consulta disponibilidad de zapatos en la tienda") is False

    def test_short_words_are_ignored_to_avoid_noise_matches(self, tool_registry):
        # "de" and "en" are 2 letters — must not cause an accidental match
        # against unrelated text that also happens to contain them.
        assert tool_registry.is_relevant("de qué color es el auto?", "Envía un correo de bienvenida") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tool_registry.py::TestIsRelevant -v`
Expected: FAIL with `AttributeError: 'ToolRegistry' object has no attribute 'is_relevant'`.

- [ ] **Step 3: Implement `is_relevant`**

In `src/openacm/tools/registry.py`, add this method to `class ToolRegistry`, right after `get_tools_semantic` (currently ending at line 158, before the `# Keyword-to-category mapping` comment at line 160):

```python
    def is_relevant(self, message: str, text: str) -> bool:
        """One-off semantic relevance check between an arbitrary message and
        an arbitrary text — for content that was never part of the
        precomputed tool-embedding matrix (e.g. a dynamically-registered
        flow tool's description), so get_tools_semantic's batch cosine
        similarity doesn't apply. Falls back to a keyword-overlap heuristic
        when the semantic model isn't loaded, same graceful-degradation
        shape as get_tools_by_intent uses for the static tool set."""
        if self._semantic_model is None:
            words = {w for w in re.findall(r"[a-zA-Z0-9áéíóúñÁÉÍÓÚÑ]{3,}", text.lower())}
            msg_lower = message.lower()
            return any(w in msg_lower for w in words)

        embeddings = self._semantic_model.encode(
            [message, text], convert_to_numpy=True, show_progress_bar=False
        )
        norm = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-8)
        similarity = float(norm[0] @ norm[1])
        return similarity >= SEMANTIC_TOOL_THRESHOLD
```

Note the fallback's minimum word length is 3 (not the `{4,}` you might reach for by habit) — the test `test_short_words_are_ignored_to_avoid_noise_matches` above only needs 2-letter words excluded, but keep it at 3 so single-purpose 3-letter domain words (e.g. "web", "SQL"-ish tokens) still match; the failing-test set above passes either way, this is just the concrete value to use.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tool_registry.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Write the failing tests for the `AgentRunner` wiring**

In `tests/unit/test_agent_runner_flows.py`, add a new class at the end of the file:

```python
class TestFlowSkillInjection:
    async def test_skill_present_when_the_message_is_relevant_to_the_flow(self):
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
        db.get_connection = AsyncMock(return_value=None)

        skill_manager = MagicMock()
        skill_manager.get_active_skills_prompt_for_agent = AsyncMock(return_value="")
        skill_manager.get_flow_skill = AsyncMock(
            return_value={"id": 1, "flow_id": 7, "name": "cuando-usar", "content": "Usa esto para disponibilidad."}
        )

        base_registry = MagicMock()
        base_registry.is_relevant = MagicMock(return_value=True)
        base_registry.tools = {"some_static_tool": MagicMock()}
        base_registry.get_tools_schema.return_value = [{"type": "function", "function": {"name": "some_static_tool"}}]
        base_registry.get_tools_by_intent.return_value = base_registry.get_tools_schema.return_value

        runner = AgentRunner(
            llm_router=MagicMock(), tool_registry=base_registry, memory=MagicMock(),
            event_bus=MagicMock(), database=db, skill_manager=skill_manager,
        )

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["config"] = config

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hay zapatos disponibles?")

        assert "Usa esto para disponibilidad." in captured["config"].system_prompt
        base_registry.is_relevant.assert_called_once_with(
            "hay zapatos disponibles?", "check-availability Checks product availability"
        )

    async def test_skill_absent_when_the_message_is_not_relevant_to_the_flow(self):
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
        db.get_connection = AsyncMock(return_value=None)

        skill_manager = MagicMock()
        skill_manager.get_active_skills_prompt_for_agent = AsyncMock(return_value="")
        skill_manager.get_flow_skill = AsyncMock(
            return_value={"id": 1, "flow_id": 7, "name": "cuando-usar", "content": "Usa esto para disponibilidad."}
        )

        base_registry = MagicMock()
        base_registry.is_relevant = MagicMock(return_value=False)
        base_registry.tools = {"some_static_tool": MagicMock()}
        base_registry.get_tools_schema.return_value = [{"type": "function", "function": {"name": "some_static_tool"}}]
        base_registry.get_tools_by_intent.return_value = base_registry.get_tools_schema.return_value

        runner = AgentRunner(
            llm_router=MagicMock(), tool_registry=base_registry, memory=MagicMock(),
            event_bus=MagicMock(), database=db, skill_manager=skill_manager,
        )

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["config"] = config

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="qué clima hace hoy?")

        assert "Usa esto para disponibilidad." not in captured["config"].system_prompt
        skill_manager.get_flow_skill.assert_not_awaited()

    async def test_no_flows_means_is_relevant_is_never_called(self):
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[])

        skill_manager = MagicMock()
        skill_manager.get_active_skills_prompt_for_agent = AsyncMock(return_value="")

        base_registry = MagicMock()
        base_registry.is_relevant = MagicMock(return_value=True)
        base_registry.tools = {"some_static_tool": MagicMock()}
        base_registry.get_tools_schema.return_value = [{"type": "function", "function": {"name": "some_static_tool"}}]
        base_registry.get_tools_by_intent.return_value = base_registry.get_tools_schema.return_value

        runner = AgentRunner(
            llm_router=MagicMock(), tool_registry=base_registry, memory=MagicMock(),
            event_bus=MagicMock(), database=db, skill_manager=skill_manager,
        )

        with patch("openacm.core.brain.Brain", MagicMock(return_value=MagicMock(process_message=AsyncMock(return_value="ok")))):
            await runner.run(agent=AGENT, message="hola")

        base_registry.is_relevant.assert_not_called()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/unit/test_agent_runner_flows.py::TestFlowSkillInjection -v`
Expected: FAIL — `get_flow_skill` is never called today, and its content never reaches `system_prompt`.

- [ ] **Step 7: Implement the wiring**

In `src/openacm/core/agent_runner.py`, add this import near the top (after `from openacm.tools.base import ToolDefinition`):

```python
from openacm.core.messages import MSG_SKILL_CONTEXT_HEADER, MSG_SKILL_CONTEXT_FOOTER
```

Replace the body of `run()` from the knowledge-fetch through the `Brain` construction (currently lines 154-209):

```python
        # Fetch knowledge and build enriched system prompt
        knowledge_items: list[dict] = []
        if self.database:
            try:
                knowledge_items = await self.database.get_agent_knowledge(agent["id"])
            except Exception as exc:
                log.warning("AgentRunner: failed to fetch knowledge", agent_id=agent["id"], error=str(exc))

        system_prompt = self._build_system_prompt(agent["system_prompt"], knowledge_items)

        config = AssistantConfig(
            name=agent["name"],
            system_prompt=system_prompt,
            max_tool_iterations=10,
            onboarding_completed=True,
            is_agent=True,
        )

        if channel_id is None:
            channel_id = f"agent_{agent['id']}"

        allowed = agent.get("allowed_tools", "all")

        flow_tools: dict[str, ToolDefinition] = {}
        active_flows: list[dict] = []
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

        agent_tool_registry = self.tool_registry if allowed != "none" else None
        if allowed != "none" and (allowed not in ("all",) or flow_tools):
            filtered_schema = self._get_tools(allowed) if allowed not in ("all", "none") else None
            agent_tool_registry = _AgentToolRegistry(self.tool_registry, filtered_schema, flow_tools)

        if self.skill_manager:
            skills_prompt = await self.skill_manager.get_active_skills_prompt_for_agent(agent["id"])
            if skills_prompt:
                system_prompt = f"{system_prompt}\n\n{skills_prompt}"

            # Flow-skills activate WITH their tool, not unconditionally like
            # agent skills above — checked via ToolRegistry.is_relevant
            # (Task 8's own new method), NOT via get_tools_by_intent, which
            # always includes every active flow tool regardless of message
            # (see this task's header note on why). Entirely self-contained
            # here — no changes to Brain's shared agentic loop.
            if flow_tools and self.tool_registry:
                for flow in active_flows:
                    relevance_text = f"{flow['name']} {flow['description']}"
                    if not self.tool_registry.is_relevant(message, relevance_text):
                        continue
                    flow_skill = await self.skill_manager.get_flow_skill(flow["id"])
                    if flow_skill:
                        system_prompt = (
                            f"{system_prompt}\n\n{MSG_SKILL_CONTEXT_HEADER}"
                            f"\n\n## {flow_skill['name']}\n\n{flow_skill['content']}"
                            f"{MSG_SKILL_CONTEXT_FOOTER}"
                        )

        config = AssistantConfig(
            name=agent["name"],
            system_prompt=system_prompt,
            max_tool_iterations=10,
            onboarding_completed=True,
            is_agent=True,
        )

        if channel_id is None:
            channel_id = f"agent_{agent['id']}"

        brain = Brain(
            config=config,
            llm_router=self.llm_router,
            memory=self.memory,
            event_bus=self.event_bus,
            tool_registry=agent_tool_registry,
        )
```

Note this restructure builds `config`/`channel_id` once, after `flow_tools`/`agent_tool_registry`/the skills prompt are all resolved — the original code built `config` too early (before flow_tools existed) and would need it rebuilt anyway once `system_prompt` gains the flow-skill content, so this consolidates both into one place. Double-check after editing that there is exactly one `config = AssistantConfig(...)` block and one `if channel_id is None:` block in the final file (the diff above shows the OLD early ones being removed as part of the same edit, not left duplicated).

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/unit/test_agent_runner_flows.py -v`
Expected: PASS (all tests, including the pre-existing ones from before this task — this task must not change behavior for flows/agents without a skill).

- [ ] **Step 9: Run the full backend test suite**

Run: `pytest -q`
Expected: no new failures beyond the known pre-existing baseline.

- [ ] **Step 10: Commit**

```bash
git add src/openacm/tools/registry.py tests/unit/test_tool_registry.py src/openacm/core/agent_runner.py tests/unit/test_agent_runner_flows.py
git commit -m "feat(flows): inject a flow's skill into context only when the message is actually relevant to that flow"
```

---

### Task 9: Frontend — flow-skill panel UI

**Files:**
- Create: `frontend/hooks/use-agent-flow-skill.ts`
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: Task 7's endpoints (`GET/POST/PUT/DELETE /api/agents/{agent_id}/flows/{flow_id}/skill`, `POST .../skill/generate`).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Create the hook**

Create `frontend/hooks/use-agent-flow-skill.ts`, mirroring `use-agent-flows.ts`'s existing structure:

```typescript
'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';

export interface FlowSkill {
  id: number;
  flow_id: number;
  name: string;
  description: string;
  content: string;
}

export function useAgentFlowSkill(agentId: number, flowId: number) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<FlowSkill | null>({
    queryKey: ['agent-flow-skill', flowId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/flows/${flowId}/skill`),
    enabled: isAuthenticated,
  });
}

export function useSaveFlowSkill(agentId: number, flowId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ exists, data }: { exists: boolean; data: { name: string; description?: string; content: string } }) =>
      fetchAPI(`/api/agents/${agentId}/flows/${flowId}/skill`, {
        method: exists ? 'PUT' : 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-flow-skill', flowId] }),
  });
}

export function useGenerateFlowSkill(agentId: number, flowId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      fetchAPI(`/api/agents/${agentId}/flows/${flowId}/skill/generate`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-flow-skill', flowId] }),
  });
}
```

- [ ] **Step 2: Wire the panel into `FlowCanvas.tsx`**

In `frontend/components/flow-editor/FlowCanvas.tsx`, add the import:

```typescript
import { useAgentFlowSkill, useSaveFlowSkill, useGenerateFlowSkill } from '@/hooks/use-agent-flow-skill';
```

Inside `FlowCanvasInner`, after the connection-related state (after `submitNewConnection`, before `const [testParams, ...`), add:

```typescript
  const { data: flowSkill } = useAgentFlowSkill(agentId, flow.id);
  const saveFlowSkill = useSaveFlowSkill(agentId, flow.id);
  const generateFlowSkill = useGenerateFlowSkill(agentId, flow.id);
  const [showSkillPanel, setShowSkillPanel] = useState(false);
  const [skillName, setSkillName] = useState(flowSkill?.name || flow.name);
  const [skillContent, setSkillContent] = useState(flowSkill?.content || '');
```

Add a "Skill" button next to the existing "Guardar flujo" button (currently line 314):

```typescript
        <button onClick={handleSave} className="btn-primary text-[11px] px-2 py-1 mt-2">Guardar flujo</button>
        <button onClick={() => { setSkillName(flowSkill?.name || flow.name); setSkillContent(flowSkill?.content || ''); setShowSkillPanel(true); }} className="btn-secondary text-[11px] px-2 py-1 mt-1">
          {flowSkill ? 'Editar skill' : '+ Skill'}
        </button>
```

Add the panel itself as a sibling of `{selectedNode && (...)}`, right before the closing `</div>` of the outer flex container (currently line 610):

```typescript
      {showSkillPanel && (
        <div className="shrink-0 p-2 text-[11px]" style={{ width: 260, border: '1px solid var(--acm-border)', borderRadius: 8, color: 'var(--acm-fg-2)' }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>Skill del flujo</div>
          <label>Nombre</label>
          <input className="acm-input w-full mb-2" value={skillName} onChange={e => setSkillName(e.target.value)} />
          <label>Contenido (qué debe saber el LLM para usar este flujo)</label>
          <textarea className="acm-input w-full mb-2" rows={8} value={skillContent} onChange={e => setSkillContent(e.target.value)} />
          <div className="flex gap-1 flex-wrap">
            <button
              className="btn-secondary text-[11px] px-2 py-1"
              disabled={generateFlowSkill.isPending}
              onClick={() => generateFlowSkill.mutate(
                { name: skillName, description: flow.description },
                { onSuccess: (skill: any) => setSkillContent(skill.content) },
              )}
            >
              {generateFlowSkill.isPending ? 'Generando...' : 'Generar con IA'}
            </button>
            <button
              className="btn-primary text-[11px] px-2 py-1"
              disabled={saveFlowSkill.isPending}
              onClick={() => saveFlowSkill.mutate({ exists: !!flowSkill, data: { name: skillName, content: skillContent } })}
            >
              Guardar
            </button>
            <button className="btn-secondary text-[11px] px-2 py-1" onClick={() => setShowSkillPanel(false)}>Cerrar</button>
          </div>
        </div>
      )}
```

- [ ] **Step 3: Verify types**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/hooks/use-agent-flow-skill.ts frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): flow-skill panel — edit or generate-with-AI, from the canvas toolbar"
```

---

### Task 10: Backend — `/test` endpoint returns per-node outputs

**Files:**
- Modify: `src/openacm/core/flow_executor.py`
- Modify: `src/openacm/core/agent_runner.py:22-44` (`_build_flow_tool`)
- Modify: `src/openacm/web/routers/agents.py` (`test_agent_flow`)
- Test: `tests/unit/test_flow_executor.py`, `tests/unit/test_agents_flows_api.py`

**Interfaces:**
- Consumes: Task 1/2/3's `run()` (the `previous_id` + cycle-cap version).
- Produces: `FlowExecutor.run()` now returns `tuple[str, dict[str, Any]]` (result string, outputs-by-node-id) instead of `str`. **Every existing caller of `.run()` must be updated in this same task** — there are exactly two: `agent_runner.py`'s `_build_flow_tool` handler, and `agents.py`'s `test_agent_flow`. (Tasks 1-3's tests all call `executor.run(...)` directly and assert on the return value — this task's Step 3 must also update every one of those call sites' assertions from `result == "..."` to `result, _ = await executor.run(...)` then `assert result == "..."`, or the whole suite breaks. Re-read `tests/unit/test_flow_executor.py` in full before starting Step 1 to get the exact current count and shape of these call sites.)

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_flow_executor.py`, add to `class TestFlowExecutorStartToEnd`:

```python
    async def test_run_returns_outputs_dict_alongside_the_result_string(self):
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
            result, outputs = await executor.run(graph, params={})

        assert result == "ok"
        assert outputs["http1"] == {"status": "ok"}
```

In `tests/unit/test_agents_flows_api.py`, add to `class TestTestFlowEndpoint`:

```python
    async def test_response_includes_per_node_outputs(self, app_client, _mock_state):
        async with app_client as ac:
            resp = await ac.post("/api/agents/42/flows/7/test", json={"params": {}})
        assert resp.status_code == 200
        assert "outputs" in resp.json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestFlowExecutorStartToEnd::test_run_returns_outputs_dict_alongside_the_result_string tests/unit/test_agents_flows_api.py::TestTestFlowEndpoint::test_response_includes_per_node_outputs -v`
Expected: FAIL — `run()` currently returns a bare string; unpacking `result, outputs = await executor.run(...)` raises `TypeError` today.

- [ ] **Step 3: Implement**

In `src/openacm/core/flow_executor.py`, update `run()`'s signature and every `return` statement inside it (the version from Task 3):

```python
    async def run(self, graph: dict, params: dict) -> tuple[str, dict[str, Any]]:
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        edges_by_source: dict[str, dict[str, str]] = {}
        for edge in graph.get("edges", []):
            edges_by_source.setdefault(edge["from"], {})[edge.get("fromHandle", "default")] = edge["to"]

        start_node = next((n for n in nodes.values() if n["type"] == "start"), None)
        if not start_node:
            return "Error: flow has no Start node", {}

        for param_def in start_node["config"].get("parameters", []):
            if param_def.get("required") and param_def["name"] not in params:
                return f"Error: missing required parameter '{param_def['name']}'", {}

        outputs: dict[str, Any] = {}
        current_id = edges_by_source.get(start_node["id"], {}).get("default")
        previous_id: str | None = None
        visits = 0

        while current_id:
            visits += 1
            if visits > self._MAX_NODE_VISITS:
                return "Error: flow exceeded maximum node visits (possible cycle)", outputs

            node = nodes.get(current_id)
            if node is None:
                return f"Error: flow references unknown node '{current_id}'", outputs

            if node["type"] == "end":
                template = node["config"].get("template", "")
                return substitute_templates(template, params, outputs), outputs

            if node["type"] == "set":
                if previous_id and previous_id in outputs:
                    value = outputs[previous_id]
                    outputs[node["id"]] = value
                    outputs[node["config"]["name"]] = value
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue

            if node["type"] == "get":
                name = node["config"]["name"]
                if name in outputs:
                    outputs[node["id"]] = outputs[name]
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue

            handler = self._HANDLERS.get(node["type"])
            if handler is None:
                return f"Error: unknown node type '{node['type']}'", outputs

            try:
                result = await handler(self, node, params, outputs)
            except Exception as exc:
                return f"Error in node '{node['id']}' ({node['type']}): {exc}", outputs

            if node["type"] == "conditional":
                outputs[node["id"]] = result["passthrough"]
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("true" if result["branch"] else "false")
            else:
                outputs[node["id"]] = result
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("default")

        return "Error: flow ended without reaching an End node", outputs
```

Update every existing test in `tests/unit/test_flow_executor.py` that calls `await executor.run(...)` and asserts on it directly as a string — change each `result = await executor.run(...)` to `result, _ = await executor.run(...)`. Re-read the full file (all classes: `TestFlowExecutorStartToEnd`, `TestHttpNode`, `TestConditionalNode`, `TestWooCommerceNode`, `TestSetNode`, `TestGetNode`, plus this task's and Tasks 1/3's new tests) and apply this change to every call site — do not skip any, or the suite fails with `TypeError: cannot unpack non-sequence` / `ValueError: too many values to unpack` depending on the exact assertion shape.

In `src/openacm/core/agent_runner.py`, update `_build_flow_tool`'s handler (currently lines 33-35):

```python
    async def handler(_brain=None, **kwargs) -> str:
        call_params = {k: v for k, v in kwargs.items() if not k.startswith("_")}
        result, _outputs = await executor.run(graph, call_params)
        return result
```

In `src/openacm/web/routers/agents.py`, update `test_agent_flow`'s final lines (the version from Task 2):

```python
        executor = FlowExecutor(get_connection=get_connection)
        result, outputs = await executor.run(graph, test_params)
        return {"result": result, "outputs": outputs}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py tests/unit/test_agents_flows_api.py tests/unit/test_agent_runner_flows.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest -q`
Expected: no new failures beyond the known pre-existing baseline.

- [ ] **Step 6: Commit**

```bash
git add src/openacm/core/flow_executor.py src/openacm/core/agent_runner.py src/openacm/web/routers/agents.py tests/unit/test_flow_executor.py tests/unit/test_agents_flows_api.py
git commit -m "feat(flows): run() and /test also return per-node outputs, for Inspector live preview"
```

---

### Task 11: Frontend — Inspector v2 (collapsible sections + live template preview)

**Files:**
- Create: `frontend/components/flow-editor/InspectorSection.tsx`
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: Task 10's `/test` response shape (`{ result: string; outputs: Record<string, unknown> }`).
- Produces: nothing consumed by later tasks — this is the final task.

- [ ] **Step 1: Create `InspectorSection`**

Create `frontend/components/flow-editor/InspectorSection.tsx`:

```typescript
'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

export function InspectorSection({ title, defaultOpen = true, children }: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mb-2">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1 w-full text-left mb-1"
        style={{ color: 'var(--acm-fg-4)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}
      >
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        {title}
      </button>
      {open && <div className="flex flex-col gap-1">{children}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Add the template-preview helper and cache the last test's outputs**

In `frontend/components/flow-editor/FlowCanvas.tsx`, add this pure function near the top of the file, after `toGraphJson` and before `maxNodeIdSuffix`:

```typescript
// Local re-implementation of flow_executor.py's substitute_templates rule
// (bare {{name}} whole-value, {{node_id.field}} one-level dict lookup,
// "[missing: ...]" marker) so the Inspector can preview a resolved value
// without a network round-trip per keystroke.
function previewTemplate(template: string, outputs: Record<string, unknown>): string {
  return template.replace(/\{\{([a-zA-Z0-9_]+)(?:\.([a-zA-Z0-9_]+))?\}\}/g, (_match, name, field) => {
    if (field === undefined) {
      return name in outputs ? String(outputs[name]) : `[missing: ${name}]`;
    }
    const value = outputs[name];
    if (value && typeof value === 'object' && field in (value as Record<string, unknown>)) {
      return String((value as Record<string, unknown>)[field]);
    }
    return `[missing: ${name}.${field}]`;
  });
}

function TemplatePreview({ value, outputs }: { value: string; outputs: Record<string, unknown> | null }) {
  if (!outputs) {
    return <div className="text-[9px] mt-1" style={{ color: 'var(--acm-fg-4)' }}>corré &quot;Probar flujo&quot; para ver valores reales acá</div>;
  }
  if (!value.includes('{{')) return null;
  return <div className="text-[9px] mt-1 p-1" style={{ background: 'var(--acm-base)', borderRadius: 4, color: 'var(--acm-fg-3)' }}>{previewTemplate(value, outputs)}</div>;
}
```

Change `runTest`'s response type and store the outputs (currently lines 160-177):

```typescript
  const [testParams, setTestParams] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testOutputs, setTestOutputs] = useState<Record<string, unknown> | null>(null);
  const [testing, setTesting] = useState(false);
  const { fetchAPI } = useAPI();

  const startNode = nodes.find(n => n.type === 'start');
  const startParams = (startNode?.data.parameters as Array<{ name: string }> | undefined) || [];

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const currentGraph = JSON.stringify(toGraphJson(nodes, edges));
      const res = (await fetchAPI(`/api/agents/${agentId}/flows/${flow.id}/test`, {
        method: 'POST',
        body: JSON.stringify({ params: testParams, graph_json: currentGraph }),
      })) as { result: string; outputs: Record<string, unknown> };
      setTestResult(res.result);
      setTestOutputs(res.outputs);
    } catch {
      setTestResult('Error al ejecutar la prueba.');
    } finally {
      setTesting(false);
    }
  };
```

- [ ] **Step 3: Apply sections to HTTP and Start, add preview to every templated field**

Import `InspectorSection` at the top of `FlowCanvas.tsx`:

```typescript
import { InspectorSection } from './InspectorSection';
```

Replace the Start node's Inspector block (currently lines 450-486):

```typescript
          {selectedNode.type === 'start' && (
            <InspectorSection title="Parámetros">
              {((selectedNode.data.parameters as StartParam[] | undefined) || []).map((p, i) => (
                <div key={i} className="flex flex-col gap-1 mb-2 p-1" style={{ border: '1px solid var(--acm-border)', borderRadius: 4 }}>
                  <input
                    className="acm-input w-full"
                    placeholder="nombre (ej: producto)"
                    value={p.name}
                    onChange={e => updateStartParam(i, { name: e.target.value })}
                  />
                  <select
                    className="acm-input w-full"
                    value={p.type}
                    onChange={e => updateStartParam(i, { type: e.target.value as StartParam['type'] })}
                  >
                    <option value="string">texto</option>
                    <option value="number">número</option>
                    <option value="boolean">verdadero/falso</option>
                  </select>
                  <input
                    className="acm-input w-full"
                    placeholder="descripción (ayuda al LLM a saber qué mandar)"
                    value={p.description}
                    onChange={e => updateStartParam(i, { description: e.target.value })}
                  />
                  <label className="flex items-center gap-1">
                    <input type="checkbox" checked={p.required} onChange={e => updateStartParam(i, { required: e.target.checked })} />
                    Obligatorio
                  </label>
                  <button onClick={() => removeStartParam(i)} className="text-[var(--acm-fg-4)] hover:text-[var(--acm-err)] self-end">
                    <Trash2 size={11} />
                  </button>
                </div>
              ))}
              <button onClick={addStartParam} className="btn-secondary w-full">+ Parámetro</button>
            </InspectorSection>
          )}
```

Replace the HTTP node's Inspector block (currently lines 488-512):

```typescript
          {selectedNode.type === 'http' && (
            <>
              <InspectorSection title="Request">
                <label>URL</label>
                <VariablePicker
                  names={availableVariableNames(nodes, edges, selectedNode.id)}
                  targetRef={urlInputRef}
                  value={String(selectedNode.data.url || '')}
                  onInsert={v => updateSelectedNodeData({ url: v })}
                />
                <input ref={urlInputRef} className="acm-input w-full" value={String(selectedNode.data.url || '')} onChange={e => updateSelectedNodeData({ url: e.target.value })} />
                <TemplatePreview value={String(selectedNode.data.url || '')} outputs={testOutputs} />
                <label>Método</label>
                <select className="acm-input w-full" value={String(selectedNode.data.method || 'GET')} onChange={e => updateSelectedNodeData({ method: e.target.value })}>
                  <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option>
                </select>
              </InspectorSection>
              <InspectorSection title="Headers & Body" defaultOpen={false}>
                <label>Cuerpo (para POST/PUT)</label>
                <VariablePicker
                  names={availableVariableNames(nodes, edges, selectedNode.id)}
                  targetRef={bodyInputRef}
                  value={String(selectedNode.data.body || '')}
                  onInsert={v => updateSelectedNodeData({ body: v })}
                />
                <textarea ref={bodyInputRef} className="acm-input w-full" rows={3} value={String(selectedNode.data.body || '')} onChange={e => updateSelectedNodeData({ body: e.target.value })} />
                <TemplatePreview value={String(selectedNode.data.body || '')} outputs={testOutputs} />
              </InspectorSection>
            </>
          )}
```

For Conditional, WooCommerce, and End (which stay flat, no `InspectorSection` wrapper per the spec — only their templated field gains a preview), add `<TemplatePreview .../>` right after each field's existing `<input>`/`<textarea>`:

- Conditional's `field` input (currently line 523): add `<TemplatePreview value={String(selectedNode.data.field || '')} outputs={testOutputs} />` right after it.
- WooCommerce's `search_term` input (currently line 568): add `<TemplatePreview value={String(selectedNode.data.search_term || '')} outputs={testOutputs} />` right after it.
- End's `template` textarea (currently line 581): add `<TemplatePreview value={String(selectedNode.data.template || '')} outputs={testOutputs} />` right after it.

- [ ] **Step 4: Verify types**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/flow-editor/InspectorSection.tsx frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): Inspector v2 — collapsible HTTP/Start sections, live template preview from last test run"
```

---

## Post-plan manual smoke test (end to end)

After all 11 tasks are merged, this needs an actual browser session — not just `tsc`/`pytest` — before it's considered done. Leave a durable note of what was confirmed in a progress ledger entry (this project's own history shows unmarked checkboxes and commit messages alone can drift from what was actually verified — see `.superpowers/sdd/progress.md`'s "MANUAL BROWSER VERIFICATION" lines for the pattern to follow).

1. **Merge:** build a flow with a Conditional whose `true` and `false` branches both connect to the same downstream Set node, then to the same End. Run "Probar flujo" with a param that takes the `true` branch, then again with one that takes `false` — confirm the End's output correctly reflects whichever branch actually ran each time, and that the merged node shows a small merge badge in the canvas.
2. **Cycle rejection:** manually draw an edge from a later node back to an earlier one (creating a real cycle) and click "Guardar flujo" — confirm it's rejected with an error naming the nodes in the cycle, not saved.
3. **Copy/paste:** select two connected nodes (not Start/End), `Ctrl+C`, then `Ctrl+V` — confirm two new nodes appear offset from the originals, connected to each other but not to the rest of the original graph.
4. **Flow-skill:** give a flow a skill via the new "Skill" panel (try "Generar con IA" too), then use the agent's "Test this agent" dashboard panel with a message that should select that flow's tool — confirm (via `/api/traces` or agent logs) the skill content reached the system prompt; send an unrelated message and confirm it did NOT.
5. **Inspector v2:** select an HTTP node, confirm "Request" and "Headers & Body" sections collapse/expand independently; run "Probar flujo" once, then edit a field containing `{{...}}` and confirm the preview below it shows a resolved value instead of the "corré Probar flujo..." hint.
6. **Open questions from this round, resolve them now:** confirm node delete (select a node, press Backspace/Delete) and multi-select (Shift+click two nodes, or Shift+drag a box) actually work — if either doesn't, that's a new, separately-scoped follow-up, not a regression from this plan. Also: whatever the user finds when re-testing Set/Get variables (raised as an unresolved concern during this plan's design) should get written down here or in a fresh ledger entry, so it stops being an open question carried forward silently.
