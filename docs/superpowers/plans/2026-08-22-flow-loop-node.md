# Flow Loop Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `loop` ("por cada") node type to OpenACM's flow editor, so a flow can run a chain of steps once per item in an array with no explicit "go back" wiring — the loop body's natural dead end is what advances the executor to the next item.

**Architecture:** Two tasks. Task 1 is backend-only: `FlowExecutor.run()` (`src/openacm/core/flow_executor.py`) gains a small iteration stack so that hitting a dead end while inside a loop advances to the next item (or falls through to `done`) instead of erroring, plus `validate_graph`'s handle-membership dicts learn the new node's pins. Task 2 is frontend-only: a new `LoopNode` component (`frontend/components/flow-editor/node-types.tsx`) built from the same `NodeCard`/`PinRow` primitives every other node uses, plus wiring it into `FlowCanvas.tsx`'s node-creation menu and Inspector.

**Tech Stack:** Python (backend), React/TypeScript/@xyflow/react (frontend). No new dependencies. No automated frontend test framework exists in this repo — frontend verification is `tsc --noEmit` + manual Playwright browser checks, this repo's established convention.

**Spec:** `docs/superpowers/specs/2026-08-22-flow-loop-node-design.md`

## Global Constraints

- `loop`'s `items` target pin is wire-only — no literal-text fallback.
- `loop`/`done` source handles are classified as **flow** pins (diamonds), not data pins, despite not being named `default` — same special-case pattern already used for Conditional's `true`/`false`.
- `item`/`index` source handles are ordinary **data** pins (circles), real and wireable, resolved via the existing `_resolve_pin_value`/`resolve_field` machinery with zero changes to either function.
- `max_iterations` config field, integer, default `200` when unset.
- `_MAX_NODE_VISITS` (global safety backstop) raised from `50` to `2000`.
- No changes to `detect_cycle` — the loop body needs no back-edge, so no cycle exists in the graph for this feature.
- No changes needed to `availableVariableSources`/`enumeratePaths` (the nested-path variable picker) or `_auto_layout` (the AI flow-building tool's layout heuristic) — both already walk generically by edge `kind`, not by handle name, so `loop`/`done` edges are picked up automatically.

---

### Task 1: Backend execution model

**Files:**
- Modify: `src/openacm/core/flow_executor.py:94` (`KNOWN_NODE_TYPES`), `:96-114` (`NODE_TARGET_HANDLES`/`NODE_SOURCE_HANDLES`), `:324` (`_MAX_NODE_VISITS`), `:440-541` (`run()`)
- Test: `tests/unit/test_flow_executor.py`

**Interfaces:**
- Consumes: nothing new — reuses `_resolve_pin_value`, `data_edges_by_target`, `edges_by_source`, `substitute_templates`, all exactly as they exist today.
- Produces: a `loop` node's runtime output shape, `outputs[loop_node_id] = {"item": <current item>, "index": <int>}` — consumed by Task 2 only for manual browser verification, not by any other code this plan touches.

- [ ] **Step 1: Write the failing tests**

Add these to `tests/unit/test_flow_executor.py`. Put the new test classes right after the existing `TestGetNode` class (before `TestValidateGraph`).

```python
class TestLoopNode:
    async def test_loop_runs_body_once_per_item_then_reaches_done(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/items", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {}},
                {"id": "seen", "type": "set", "config": {"name": "seen"}},
                {"id": "end", "type": "end", "config": {"template": "Last seen: {{seen}}, final index: {{loop1.index}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "seen", "fromHandle": "loop", "kind": "flow"},
                {"from": "loop1", "to": "seen", "fromHandle": "item", "toHandle": "value", "kind": "data"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        response = MagicMock()
        response.json.return_value = ["a", "b", "c"]
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, outputs = await executor.run(graph, params={})

        assert result == "Last seen: c, final index: 2"
        assert outputs["loop1"] == {"item": "c", "index": 2}

    async def test_empty_items_list_skips_straight_to_done(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/items", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {}},
                {"id": "marker", "type": "set", "config": {"name": "should_not_run"}},
                {"id": "end", "type": "end", "config": {"template": "{{should_not_run}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "marker", "fromHandle": "loop", "kind": "flow"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        response = MagicMock()
        response.json.return_value = []
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "[missing: should_not_run]"

    async def test_max_iterations_cap_trips_with_items_remaining(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/items", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {"max_iterations": 2}},
                {"id": "noop", "type": "set", "config": {"name": "noop"}},
                {"id": "end", "type": "end", "config": {"template": "unreachable"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "noop", "fromHandle": "loop", "kind": "flow"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        response = MagicMock()
        response.json.return_value = ["a", "b", "c", "d", "e"]
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "Error in node 'loop1' (loop): reached max_iterations (2) with more items remaining"

    async def test_items_pin_not_wired_returns_error(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "loop1", "type": "loop", "config": {}},
                {"id": "end", "type": "end", "config": {"template": "done"}},
            ],
            "edges": [
                {"from": "start", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        executor = FlowExecutor()
        result, _ = await executor.run(graph, params={})
        assert result == "Error in node 'loop1' (loop): 'items' pin is not wired to a list"

    async def test_end_node_inside_loop_body_terminates_the_whole_flow_immediately(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com/items", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {}},
                {"id": "end", "type": "end", "config": {"template": "Stopped at {{loop1.item}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "end", "fromHandle": "loop", "kind": "flow"},
            ],
        }
        response = MagicMock()
        response.json.return_value = ["a", "b", "c"]
        response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "Stopped at a"

    async def test_nested_loops_both_trackers_resolve_independently(self):
        """Outer loop (2 items) wraps an inner loop (3 items). The inner
        loop's own "done" pin is deliberately left UNWIRED — when the
        inner loop exhausts, it dead-ends too, which must cascade to
        advancing the OUTER frame (not error out), proving the stack
        (not a single value) is what tracks "which loop am I in"."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http_outer", "type": "http", "config": {"url": "https://example.com/outer", "method": "GET"}},
                {"id": "http_inner", "type": "http", "config": {"url": "https://example.com/inner", "method": "GET"}},
                {"id": "loop_outer", "type": "loop", "config": {}},
                {"id": "loop_inner", "type": "loop", "config": {}},
                {"id": "track", "type": "set", "config": {"name": "last_inner_seen"}},
                {"id": "end", "type": "end", "config": {
                    "template": "outer={{loop_outer.item}}:{{loop_outer.index}} inner={{loop_inner.item}}:{{loop_inner.index}} tracked={{last_inner_seen}}"
                }},
            ],
            "edges": [
                {"from": "start", "to": "http_outer", "fromHandle": "default", "kind": "flow"},
                {"from": "http_outer", "to": "http_inner", "fromHandle": "default", "kind": "flow"},
                {"from": "http_inner", "to": "loop_outer", "fromHandle": "default", "kind": "flow"},
                {"from": "http_outer", "to": "loop_outer", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop_outer", "to": "loop_inner", "fromHandle": "loop", "kind": "flow"},
                {"from": "http_inner", "to": "loop_inner", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop_inner", "to": "track", "fromHandle": "loop", "kind": "flow"},
                {"from": "loop_inner", "to": "track", "fromHandle": "item", "toHandle": "value", "kind": "data"},
                {"from": "loop_outer", "to": "end", "fromHandle": "done", "kind": "flow"},
            ],
        }
        response_outer = MagicMock()
        response_outer.json.return_value = ["x", "y"]
        response_outer.raise_for_status = MagicMock()
        response_inner = MagicMock()
        response_inner.json.return_value = [1, 2, 3]
        response_inner.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.side_effect = [response_outer, response_inner]
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "outer=y:1 inner=3:2 tracked=3"
```

Also add one case to the existing `TestValidateGraph` class (find it in the same file) — insert this method into that class:

```python
    def test_loop_node_with_valid_handles_has_no_errors(self):
        from openacm.core.flow_executor import validate_graph
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://x", "method": "GET"}},
                {"id": "loop1", "type": "loop", "config": {}},
                {"id": "end", "type": "end", "config": {"template": "{{loop1.item}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "loop1", "fromHandle": "default", "toHandle": "items", "kind": "data"},
                {"from": "loop1", "to": "end", "fromHandle": "done", "toHandle": "default", "kind": "flow"},
            ],
        }
        assert validate_graph(graph) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_flow_executor.py::TestLoopNode -v
```

Expected: every test in `TestLoopNode` FAILS — `loop` isn't a known node type yet, so `validate_graph`/`run()` reject or mishandle it (exact failure mode varies per test; the point is none pass yet).

- [ ] **Step 3: Add `loop` to `KNOWN_NODE_TYPES` and the handle dicts**

In `src/openacm/core/flow_executor.py`, change line 94:

```python
KNOWN_NODE_TYPES = {"start", "http", "conditional", "woocommerce", "set", "get", "end", "loop"}
```

And extend the two handle dicts (lines 96-114) by adding one key to each:

```python
NODE_TARGET_HANDLES: dict[str, set[str]] = {
    "start": set(),
    "http": {"default", "url", "body"},
    "conditional": {"default", "field", "value"},
    "woocommerce": {"default", "search_term"},
    "set": {"default", "value"},
    "get": set(),
    "end": {"default"},
    "loop": {"default", "items"},
}

NODE_SOURCE_HANDLES: dict[str, set[str]] = {
    "start": {"default"},
    "http": {"default"},
    "conditional": {"true", "false"},
    "woocommerce": {"default", "result", "count"},
    "set": {"default"},
    "get": {"default"},
    "end": set(),
    "loop": {"loop", "done", "item", "index"},
}
```

- [ ] **Step 4: Raise `_MAX_NODE_VISITS`**

In the `FlowExecutor` class body, change:

```python
    _MAX_NODE_VISITS = 50
```

to:

```python
    _MAX_NODE_VISITS = 2000
```

- [ ] **Step 5: Rewrite `run()`'s walk to support loops**

Replace the body of `run()` from the `outputs: dict[str, Any] = {}` line through the `while current_id:` loop's opening (currently around line 471-484) with:

```python
        outputs: dict[str, Any] = {}
        current_id = edges_by_source.get(start_node["id"], {}).get("default")
        previous_id: str | None = None
        visits = 0
        # Tracks "which loop(s) am I inside" as a stack (not a single
        # value) so nested loops need no special-casing — each `loop` node
        # entered pushes its own frame on top; a dead end always advances
        # whichever frame is on TOP, so an inner loop's exhaustion falls
        # through and advances the outer loop's frame automatically, even
        # when the inner loop's own "done" pin is left unwired.
        loop_stack: list[dict[str, Any]] = []

        while current_id or loop_stack:
            if current_id is None:
                # A dead end inside a loop body — the whole reason this
                # node type needs no explicit "go back" wiring. Advance the
                # innermost active loop instead of treating this as
                # "flow ended without reaching an End node".
                frame = loop_stack[-1]
                frame["index"] += 1
                if frame["index"] >= len(frame["items"]):
                    loop_stack.pop()
                    previous_id = frame["loop_node_id"]
                    current_id = edges_by_source.get(frame["loop_node_id"], {}).get("done")
                    continue
                if frame["index"] >= frame["max_iterations"]:
                    return (
                        f"Error in node '{frame['loop_node_id']}' (loop): "
                        f"reached max_iterations ({frame['max_iterations']}) with more items remaining"
                    ), outputs
                outputs[frame["loop_node_id"]] = {
                    "item": frame["items"][frame["index"]], "index": frame["index"],
                }
                previous_id = frame["loop_node_id"]
                current_id = edges_by_source.get(frame["loop_node_id"], {}).get("loop")
                continue

            visits += 1
            if visits > self._MAX_NODE_VISITS:
                return "Error: flow exceeded maximum node visits (possible cycle)", outputs

            node = nodes.get(current_id)
            if node is None:
                return f"Error: flow references unknown node '{current_id}'", outputs
```

**Then**, immediately after that (right before the existing `if node["type"] == "end":` block), insert the new `loop` branch:

```python
            if node["type"] == "loop":
                value_edge = data_edges_by_target.get((node["id"], "items"))
                items = None
                if value_edge is not None:
                    source_id, source_handle = value_edge
                    found, value = _resolve_pin_value(source_id, source_handle, nodes, outputs)
                    if found:
                        items = value
                if not isinstance(items, list):
                    return f"Error in node '{node['id']}' (loop): 'items' pin is not wired to a list", outputs
                if not items:
                    previous_id = current_id
                    current_id = edges_by_source.get(node["id"], {}).get("done")
                    continue
                loop_stack.append({
                    "loop_node_id": node["id"],
                    "items": items,
                    "index": 0,
                    "max_iterations": node["config"].get("max_iterations", 200),
                })
                outputs[node["id"]] = {"item": items[0], "index": 0}
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("loop")
                continue

            if node["type"] == "end":
                template = node["config"].get("template", "")
                return substitute_templates(template, params, outputs), outputs
```

Everything else in `run()` (the `set`/`get` branches, the `_HANDLERS` dispatch, the final `return "Error: flow ended without reaching an End node", outputs`) stays exactly as it is — only the loop-condition line, the new `current_id is None` branch, and the new `loop` node-type branch are added.

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/unit/test_flow_executor.py::TestLoopNode tests/unit/test_flow_executor.py::TestValidateGraph -v
```

Expected: all `TestLoopNode` tests PASS, and `TestValidateGraph::test_loop_node_with_valid_handles_has_no_errors` PASSES.

- [ ] **Step 7: Run the full backend test suite**

```bash
pytest -q
```

Expected: same baseline as before this task (688+ passing at time of writing this plan, plus these new tests; the pre-existing `gmail_classifier`/`gmail_summary` failures are unrelated and already known — confirm no *new* failures, don't chase those).

- [ ] **Step 8: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): add loop node execution model (FlowExecutor.run())"
```

---

### Task 2: Frontend — `LoopNode` component and editor wiring

**Files:**
- Modify: `frontend/components/flow-editor/node-types.tsx:14-22` (`NODE_CATEGORY`), `:57-65` (`classifyPin`), `:135-143` (`NODE_DESCRIPTIONS`), `:364-372` (`NODE_TYPES`) — plus a new `LoopNode` function
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx:398-408` (`NODE_CATEGORIES`/`NODE_LABELS`), and the Inspector's per-type sections (search for `selectedNode.type === 'get'` to find the insertion point — add the new `loop` section right after it)

**Interfaces:**
- Consumes: `NodeCard`, `PinRow`, `MergeBadge`, `pinProps`, `idStyle` — all already defined and exported/available within `node-types.tsx`, used exactly the way `ConditionalNode` uses them (read `ConditionalNode`, lines 270-300, as the closest reference — same two-flow-out-pin-with-labels shape).
- Produces: `LoopNode` React component, registered in `NODE_TYPES` under the key `"loop"`, matching the exact runtime node-`type` string Task 1's backend expects.

- [ ] **Step 1: Add `loop` to `NODE_CATEGORY`**

In `frontend/components/flow-editor/node-types.tsx`, add one line to the existing `NODE_CATEGORY` object (line 14-22):

```typescript
export const NODE_CATEGORY: Record<string, NodeCategory> = {
  start: 'flow',
  end: 'flow',
  conditional: 'logic',
  loop: 'logic',
  http: 'integration',
  woocommerce: 'integration',
  set: 'data',
  get: 'data',
};
```

- [ ] **Step 2: Extend `classifyPin` for `loop`/`done`**

In the same file, add one line to `classifyPin` (currently lines 57-65), right after the existing Conditional special-case:

```typescript
export function classifyPin(nodeType: string | undefined, handleId: string | null | undefined, handleKind: 'source' | 'target'): 'flow' | 'data' {
  const id = handleId || 'default';
  if (nodeType === 'get') return 'data';
  if (handleKind === 'target') {
    return id === 'default' ? 'flow' : 'data';
  }
  if (nodeType === 'conditional' && (id === 'true' || id === 'false')) return 'flow';
  if (nodeType === 'loop' && (id === 'loop' || id === 'done')) return 'flow';
  return id === 'default' ? 'flow' : 'data';
}
```

- [ ] **Step 3: Add a description for the header's `(?)` tooltip**

Add one entry to `NODE_DESCRIPTIONS` (currently lines 135-143):

```typescript
const NODE_DESCRIPTIONS: Record<string, string> = {
  start: 'Punto de entrada del flujo. Define los parámetros que recibe cuando se ejecuta.',
  http: 'Hace una petición web (GET/POST/...) a una URL y guarda la respuesta para usar en nodos siguientes.',
  conditional: 'Evalúa una condición sobre un valor y bifurca el flujo en dos ramas: true o false.',
  loop: 'Repite una cadena de nodos una vez por cada elemento de una lista. No hace falta conectar nada de vuelta: cuando la cadena del cuerpo llega a un punto muerto, sigue automáticamente con el próximo elemento.',
  woocommerce: 'Busca productos en una tienda WooCommerce conectada y devuelve los resultados.',
  set: 'Guarda un valor bajo un nombre para poder reutilizarlo más adelante en el flujo.',
  get: 'Recupera un valor guardado previamente por un nodo Guardar (Set), en cualquier punto del flujo.',
  end: 'Punto final del flujo. Arma la respuesta final combinando texto fijo y valores de nodos anteriores.',
};
```

- [ ] **Step 4: Write `LoopNode`**

Add this function right after `ConditionalNode`'s closing brace (after line 300):

```typescript
export function LoopNode({ id, data, selected }: NodeProps) {
  const flowIn = pinProps('loop', 'default', 'target', 'nodo anterior');
  const loopPin = pinProps('loop', 'loop', 'source', 'loop');
  const donePin = pinProps('loop', 'done', 'source', 'done');
  return (
    <NodeCard type="loop" icon="🔁" title="Bucle (Por cada)" selected={selected}>
      <MergeBadge id={id} />
      <PinRow nodeType="loop" handleId="items" handleKind="target" label="items" />
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <PinRow nodeType="loop" handleId="item" handleKind="source" label="item" />
      <PinRow nodeType="loop" handleId="index" handleKind="source" label="index" />
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      <Handle type="source" position={Position.Bottom} id="loop" style={{ ...loopPin.style, left: '30%' }} title={loopPin.title} />
      <Handle type="source" position={Position.Bottom} id="done" style={{ ...donePin.style, left: '70%' }} title={donePin.title} />
      {/* Same reasoning as Conditional's true/false labels: two flow-out
          pins on one node need persistent labels, unlike every other
          node's single flow-in/flow-out pair. pointerEvents: 'none' keeps
          them from stealing clicks meant for the diamond pins underneath. */}
      <div style={{ position: 'absolute', bottom: -14, left: '30%', transform: 'translateX(-50%)', fontSize: 8, color: 'var(--acm-fg-4)', pointerEvents: 'none' }}>loop</div>
      <div style={{ position: 'absolute', bottom: -14, left: '70%', transform: 'translateX(-50%)', fontSize: 8, color: 'var(--acm-fg-4)', pointerEvents: 'none' }}>done</div>
    </NodeCard>
  );
}
```

- [ ] **Step 5: Register `LoopNode` in `NODE_TYPES`**

Change `NODE_TYPES` (currently lines 364-372) to:

```typescript
export const NODE_TYPES = {
  start: StartNode,
  http: HttpNode,
  conditional: ConditionalNode,
  loop: LoopNode,
  woocommerce: WooCommerceNode,
  set: SetNode,
  get: GetNode,
  end: EndNode,
};
```

- [ ] **Step 6: Typecheck `node-types.tsx` in isolation**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors. (`FlowCanvas.tsx` will still be missing the `loop` entries from `NODE_CATEGORIES`/`NODE_LABELS` at this point — that's fine, those are plain object literals with no type that would fail to compile from an incomplete-but-valid subset; the type error you're watching for here is in `node-types.tsx` itself, e.g. a typo in the new `LoopNode`.)

- [ ] **Step 7: Wire `loop` into `FlowCanvas.tsx`'s node-creation menu**

In `frontend/components/flow-editor/FlowCanvas.tsx`, change `NODE_CATEGORIES` and `NODE_LABELS` (currently lines 398-408):

```typescript
const NODE_CATEGORIES: Array<{ label: string; types: Array<keyof typeof NODE_TYPES> }> = [
  { label: 'FLUJO', types: ['start', 'end'] },
  { label: 'LÓGICA', types: ['conditional', 'loop'] },
  { label: 'INTEGRACIONES', types: ['http', 'woocommerce'] },
  { label: 'DATOS', types: ['set', 'get'] },
];

const NODE_LABELS: Record<keyof typeof NODE_TYPES, string> = {
  start: '▶ Inicio', end: '■ Final', conditional: '◆ Condicional', loop: '🔁 Bucle (Por cada)',
  http: '🌐 HTTP Request', woocommerce: '🛒 WooCommerce', set: '💾 Guardar (Set)', get: '📤 Obtener (Get)',
};
```

- [ ] **Step 8: Add the Inspector's `max_iterations` field**

Find the `{selectedNode.type === 'get' && ( ... )}` block in `FlowCanvas.tsx` (search for that exact string — it's the last per-type Inspector section). Add a new `loop` section immediately after it, before the closing `</div>` of the Inspector panel:

```typescript
          {selectedNode.type === 'loop' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Bucle (Por cada)</div>
              <label>Máximo de iteraciones</label>
              <input
                type="number"
                min={1}
                className="acm-input w-full"
                value={String(selectedNode.data.max_iterations ?? 200)}
                onChange={e => updateSelectedNodeData({ max_iterations: Number(e.target.value) })}
              />
            </>
          )}
```

- [ ] **Step 9: Typecheck the whole frontend**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 10: Build, deploy, and manually verify in the browser**

```bash
cd frontend && npm run deploy
```

Start the OpenACM server (same procedure used throughout this session: `(TELEGRAM_TOKEN="" DISCORD_TOKEN="" PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m openacm < <(tail -f /dev/null) > <logfile> 2>&1 &)` from the repo root, then poll `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:47821/agents` until `200`). Using Playwright, open an agent's Flujos tab, create a new flow (or edit an existing test flow — do not leave test pollution in any of the user's real flows when you're done), and:

- Right-click the canvas, confirm "🔁 Bucle (Por cada)" appears under the "LÓGICA" category, add one.
- Confirm the node shows: a header bar with the 🔁 icon and a `(?)` tooltip describing it, an `items` pin row on the left with no literal-value text next to it (it's wire-only), `item`/`index` pin rows on the right, and two diamond pins on the bottom edge labeled "loop" and "done".
- Click the node, confirm the orange selection glow appears, and confirm the Inspector shows a "Máximo de iteraciones" number field defaulting to 200.
- Wire an HTTP node's response (calling a public API that returns a JSON array at the top level, e.g. `https://jsonplaceholder.typicode.com/users`) into the loop's `items` pin, wire a `set` node into the loop's `loop` output (aliasing `{{loop_1.item}}` — no outgoing edge from that `set` node), and wire the loop's `done` output to an `end` node referencing `{{loop_1.index}}`.
- Save the flow, run "Probar flujo", confirm the result reflects the loop having iterated through to the end (final index matching the array length minus one) instead of erroring or stopping after one iteration.
- Clean up: delete this test flow (or revert it) before finishing, so nothing is left behind in the user's real agent data.

- [ ] **Step 11: Commit**

```bash
git add frontend/components/flow-editor/node-types.tsx frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(flows): add Loop node UI — LoopNode component, menu, Inspector"
```

---

## Final Verification

After both tasks:
- `pytest -q` from the repo root — same baseline as before this plan, plus `TestLoopNode`'s 6 new tests and `TestValidateGraph`'s 1 new test passing.
- `cd frontend && npx tsc --noEmit` clean.
- `git status --porcelain` clean except this plan's own commits (plus any pre-existing untracked files already present before this plan started — not this plan's concern).
