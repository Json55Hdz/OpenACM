# Flow Editor Universal Data Pins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Unreal-Blueprint-style data-pin system to the flow editor — every node output becomes one or more named pins, every connectable input field can be wired from a pin or left as a typed literal (wire wins), and a new `kind: "flow" | "data"` distinction on edges keeps data connections from affecting execution order.

**Architecture:** The backend gets one small shared resolution helper (`resolve_field`, built on a lower-level `_resolve_pin_value`) that every node handler and the `set`-node branch call instead of resolving fields directly — `FlowExecutor.run()`'s flow-walk logic is otherwise untouched, and `detect_cycle` is updated to ignore data edges entirely. The frontend gets: (1) a small plumbing change so React Flow's `Edge` objects round-trip `kind`/`toHandle` through `graph_json` without losing them on save/load/paste, (2) new named `Handle`s on the canvas node components (`node-types.tsx`) for every wire-or-literal field, and (3) a shared `ConnectableField` wrapper component in the Inspector (`FlowCanvas.tsx`) that swaps a literal `<input>` for a "connected" chip whenever a data edge targets that field.

**Tech Stack:** Python 3.13, pytest + pytest-asyncio (auto mode), Next.js/React/TypeScript, `@xyflow/react` v12.

**Spec:** `docs/superpowers/specs/2026-08-21-flow-editor-universal-data-pins-design.md`

## Global Constraints

- **Backward compatibility is absolute:** an edge with no `kind` key is `kind: "flow"`, `toHandle: "flow"` — every flow saved before this ships (zero data edges, possibly an old-style Get wired into the flow chain) must run and render identically to before.
- **Dropdown/enum fields never become pins:** HTTP's `method`, Conditional's `operator`, WooCommerce's saved-Connection selector stay dropdown-only.
- **End's `template` field never becomes a pin** — it stays literal-only (a composition of many references, not a single value a pin could carry).
- **Data edges never affect `detect_cycle`** — only flow edges (`kind == "flow"` or absent) are checked; a data edge is explicitly allowed to point "backward" relative to flow order.
- **The Get-lazy-evaluation special case:** a data edge whose source is a `get`-type node resolves via `outputs.get(get_node.config["name"])`, never `outputs[get_node_id]` — Get has no flow handles, so `run()` never walks it and never populates `outputs[get_node_id]` the normal way.
- **The WooCommerce dict-with-`result`-key whole-value special case:** a bare `{{woo1}}` (no dot) reference resolves to `str(outputs["woo1"]["result"])` when `outputs["woo1"]` is a dict containing a `"result"` key — this is narrow and explicit, not a general change to whole-value substitution for every dict-shaped output.
- **Set's data-input `toHandle` is exactly `"value"`** — this name is shared by the backend (`flow_executor.py`) and the frontend (`SetNode`'s second `Handle`).
- **No new node type, no arbitrary code execution** — data edges are pure references between already-existing node outputs; nothing a flow couldn't already reach via typed `{{node_id.field}}` syntax becomes reachable.
- **No frontend test framework** — `cd frontend && npx tsc --noEmit` clean is this plan's frontend verification bar. Manual browser verification is still required before the plan is considered done (see the final section).

---

### Task 1: Backend — edge schema (`kind`/`toHandle`) + `resolve_field` + `detect_cycle` flow-only filter

**Files:**
- Modify: `src/openacm/core/flow_executor.py` (currently 264 lines — `detect_cycle` at 20-61, `substitute_templates` at 64-90, `run()` at 191-263; re-read the file fresh before editing, later tasks in this plan touch it too)
- Test: `tests/unit/test_flow_executor.py`

**Interfaces:**
- Consumes: nothing from other tasks — this is the first task.
- Produces:
  - `resolve_field(field_name: str, node_id: str, cfg: dict, data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict], params: dict, outputs: dict) -> str` — module-level, resolves one config field to a string, preferring a wired data edge over the field's literal value.
  - `_resolve_pin_value(source_id: str, source_handle: str, nodes: dict[str, dict], outputs: dict) -> tuple[bool, Any]` — module-level private helper; returns `(True, raw_value)` if the source pin has produced a value, else `(False, None)`. Shared by `resolve_field` (Task 1) and the `set`-node branch (Task 5) so the Get-lazy-evaluation special case exists in exactly one place.
  - `run()` builds `data_edges_by_target: dict[tuple[str, str], tuple[str, str]]` (keyed by `(node_id, field_name)` → `(source_node_id, source_handle)`) alongside `edges_by_source`, both now filtered so only `kind == "data"` edges populate the former and only `kind == "flow"`-or-absent edges populate the latter.
  - `detect_cycle`'s adjacency now skips any edge whose `kind` is present and not `"flow"`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_flow_executor.py`, add this test to the existing `TestDetectCycle` class (after `test_a_cycle_in_a_disconnected_component_is_detected`):

```python
    def test_a_backward_data_edge_is_never_flagged_as_a_cycle(self):
        from openacm.core.flow_executor import detect_cycle
        graph = {
            "nodes": [{"id": "start"}, {"id": "a"}, {"id": "b"}],
            "edges": [
                {"from": "start", "to": "a", "fromHandle": "default", "kind": "flow"},
                {"from": "a", "to": "b", "fromHandle": "default", "kind": "flow"},
                # A data edge pointing "backward" from b to a is allowed —
                # data edges carry no execution order and must never be
                # mistaken for a real cycle.
                {"from": "b", "to": "a", "fromHandle": "default", "toHandle": "value", "kind": "data"},
            ],
        }
        assert detect_cycle(graph) is None
```

Then add a new class after `TestSubstituteTemplates` (before `class TestFlowExecutorStartToEnd`):

```python
class TestResolveField:
    def test_no_data_edge_falls_back_to_literal_and_template(self):
        from openacm.core.flow_executor import resolve_field
        cfg = {"url": "https://example.com/{{producto}}"}
        result = resolve_field(
            "url", "http1", cfg, data_edges_by_target={}, nodes={},
            params={"producto": "zapatos"}, outputs={},
        )
        assert result == "https://example.com/zapatos"

    def test_data_edge_from_default_handle_resolves_whole_value(self):
        from openacm.core.flow_executor import resolve_field
        cfg = {"url": "https://ignored.example.com"}
        data_edges_by_target = {("http2", "url"): ("http1", "default")}
        nodes = {"http1": {"id": "http1", "type": "http", "config": {}}}
        result = resolve_field(
            "url", "http2", cfg, data_edges_by_target, nodes,
            params={}, outputs={"http1": "https://real-source.example.com"},
        )
        assert result == "https://real-source.example.com"

    def test_data_edge_with_named_handle_narrows_into_a_dict_value(self):
        from openacm.core.flow_executor import resolve_field
        cfg = {"search_term": "ignored"}
        data_edges_by_target = {("woo1", "search_term"): ("http1", "count")}
        nodes = {"http1": {"id": "http1", "type": "http", "config": {}}}
        result = resolve_field(
            "search_term", "woo1", cfg, data_edges_by_target, nodes,
            params={}, outputs={"http1": {"count": 7, "result": "..."}},
        )
        assert result == "7"

    def test_data_edge_from_a_get_source_resolves_via_the_variable_name_not_the_node_id(self):
        from openacm.core.flow_executor import resolve_field
        cfg = {"value": "ignored"}
        data_edges_by_target = {("cond1", "value"): ("get1", "default")}
        nodes = {"get1": {"id": "get1", "type": "get", "config": {"name": "mi_variable"}}}
        result = resolve_field(
            "value", "cond1", cfg, data_edges_by_target, nodes,
            params={}, outputs={"mi_variable": "hola"},  # get1's own id is NOT a key in outputs
        )
        assert result == "hola"

    def test_data_edge_from_a_source_that_has_not_executed_yet_is_a_missing_marker(self):
        from openacm.core.flow_executor import resolve_field
        cfg = {"url": "ignored"}
        data_edges_by_target = {("http2", "url"): ("http1", "default")}
        nodes = {"http1": {"id": "http1", "type": "http", "config": {}}}
        result = resolve_field(
            "url", "http2", cfg, data_edges_by_target, nodes,
            params={}, outputs={},  # http1 never ran (e.g. it's on the untaken branch)
        )
        assert result == "[missing: http1]"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_flow_executor.py::TestDetectCycle::test_a_backward_data_edge_is_never_flagged_as_a_cycle tests/unit/test_flow_executor.py::TestResolveField -v`
Expected: `TestResolveField` FAILs with `ImportError: cannot import name 'resolve_field'`. `test_a_backward_data_edge_is_never_flagged_as_a_cycle` FAILs because today's `detect_cycle` treats the `kind: "data"` edge as a normal directed edge, forming `a -> b -> a`, a real 2-cycle.

- [ ] **Step 3: Implement `detect_cycle`'s flow-only filter**

In `src/openacm/core/flow_executor.py`, in `detect_cycle`, replace:

```python
    adjacency: dict[str, list[str]] = {}
    for edge in graph.get("edges", []):
        adjacency.setdefault(edge["from"], []).append(edge["to"])
```

with:

```python
    adjacency: dict[str, list[str]] = {}
    for edge in graph.get("edges", []):
        # Data edges carry no execution-order meaning and can legitimately
        # point "backward" relative to flow order (e.g. Set aliasing an
        # earlier node's output) — only flow edges can ever form a real
        # execution cycle.
        if edge.get("kind", "flow") != "flow":
            continue
        adjacency.setdefault(edge["from"], []).append(edge["to"])
```

- [ ] **Step 4: Implement `_resolve_pin_value` and `resolve_field`**

In `src/openacm/core/flow_executor.py`, add both functions after `substitute_templates` and before `class FlowExecutor`:

```python
def _resolve_pin_value(
    source_id: str, source_handle: str, nodes: dict[str, dict], outputs: dict[str, Any],
) -> tuple[bool, Any]:
    """Resolve a data edge's source pin to its RAW value (not stringified).
    Returns (True, value) if the source has produced a value, else
    (False, None). Shared by resolve_field() (which stringifies the result
    for template/text fields) and the `set`-node branch in run() (which
    needs the actual typed value — e.g. a WooCommerce result dict — not a
    stringified one), so the Get-node special case below lives in exactly
    one place.

    Get nodes have no flow handles (see the spec's "pure node" section) so
    run()'s flow-walk never visits one and outputs[get_node_id] is never
    populated the normal way. Evaluate the Get's own name-lookup on demand
    instead of expecting it to already be in outputs.
    """
    source_node = nodes.get(source_id)
    if source_node is not None and source_node["type"] == "get":
        name = source_node["config"]["name"]
        if name not in outputs:
            return False, None
        return True, outputs[name]

    if source_id not in outputs:
        return False, None
    value = outputs[source_id]
    if source_handle != "default" and isinstance(value, dict):
        if source_handle not in value:
            return False, None
        return True, value[source_handle]
    return True, value


def resolve_field(
    field_name: str,
    node_id: str,
    cfg: dict,
    data_edges_by_target: dict[tuple[str, str], tuple[str, str]],
    nodes: dict[str, dict],
    params: dict,
    outputs: dict,
) -> str:
    """Resolve one node config field's value, preferring a wired data edge
    over the field's literal value — the "wire wins" rule this spec
    introduces. Falls back to substitute_templates(cfg[field_name], ...)
    exactly as before when no data edge targets this field, so every flow
    saved before this shipped resolves this field identically to before.
    """
    edge_source = data_edges_by_target.get((node_id, field_name))
    if edge_source is None:
        return substitute_templates(cfg[field_name], params, outputs)

    source_id, source_handle = edge_source
    found, value = _resolve_pin_value(source_id, source_handle, nodes, outputs)
    if not found:
        marker = source_id if source_handle == "default" else f"{source_id}.{source_handle}"
        return f"[missing: {marker}]"
    return str(value)
```

- [ ] **Step 5: Wire `data_edges_by_target` into `run()`'s edge-building loop**

In `src/openacm/core/flow_executor.py`, in `run()`, replace:

```python
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        edges_by_source: dict[str, dict[str, str]] = {}
        for edge in graph.get("edges", []):
            edges_by_source.setdefault(edge["from"], {})[edge.get("fromHandle", "default")] = edge["to"]
```

with:

```python
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        edges_by_source: dict[str, dict[str, str]] = {}
        # Keyed by (target_node_id, field_name) -> (source_node_id,
        # source_handle) — built only from data edges, consulted by
        # resolve_field() and the set-node branch below. A data edge never
        # goes into edges_by_source: the flow-walk must never follow one.
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]] = {}
        for edge in graph.get("edges", []):
            if edge.get("kind", "flow") == "data":
                data_edges_by_target[(edge["to"], edge.get("toHandle", "value"))] = (
                    edge["from"], edge.get("fromHandle", "default")
                )
            else:
                edges_by_source.setdefault(edge["from"], {})[edge.get("fromHandle", "default")] = edge["to"]
```

Note: `data_edges_by_target` and `nodes` are not yet passed to the handlers or the `set` branch — that's Tasks 2-5. This step only makes the lookup exist; `run()`'s behavior is otherwise byte-identical (the `else` branch is exactly the old unconditional loop body).

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests, including the new ones — the rest of the suite is unaffected since `data_edges_by_target` isn't consumed by any handler yet).

- [ ] **Step 7: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): add resolve_field + data-edge lookup, detect_cycle ignores data edges"
```

---

### Task 2: Backend — wire `resolve_field` into the HTTP node handler

**Files:**
- Modify: `src/openacm/core/flow_executor.py` (re-read fresh — `_run_http_node` and `run()`'s handler dispatch)
- Test: `tests/unit/test_flow_executor.py`

**Interfaces:**
- Consumes: `resolve_field(...)` and `data_edges_by_target`/`nodes` from Task 1.
- Produces: `_run_http_node(self, node, params, outputs, data_edges_by_target, nodes)` — the new signature every later task's call site must match. `run()`'s handler-dispatch call site now passes `data_edges_by_target, nodes` to every handler — Tasks 3 and 4 do NOT need to touch this call site again, only their own handler's `def` line and body.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_flow_executor.py`, add a new class after `class TestHttpNode` (after `test_url_and_body_support_template_substitution`):

```python
class TestHttpNodeDataEdges:
    async def test_url_is_resolved_from_a_data_edge_when_one_targets_it(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http0", "type": "http", "config": {"url": "https://source.example.com", "method": "GET"}},
                {"id": "http1", "type": "http", "config": {"url": "https://ignored-literal.example.com", "method": "GET"}},
                {"id": "end", "type": "end", "config": {"template": "{{http1}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http0", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "http1", "fromHandle": "default", "toHandle": "url", "kind": "data"},
            ],
        }
        source_response = MagicMock()
        source_response.headers = {"content-type": "text/plain"}
        source_response.text = "https://real-target.example.com"
        source_response.json.side_effect = ValueError("not json")
        source_response.raise_for_status = MagicMock()

        target_response = MagicMock()
        target_response.headers = {"content-type": "text/plain"}
        target_response.text = "ok"
        target_response.json.side_effect = ValueError("not json")
        target_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request.side_effect = [source_response, target_response]
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            await executor.run(graph, params={})

        second_call_args = mock_client.request.call_args_list[1]
        assert second_call_args.args[1] == "https://real-target.example.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestHttpNodeDataEdges -v`
Expected: FAIL — `_run_http_node` still resolves `url` from `cfg["url"]` only (the literal), so `http1`'s request goes to `"https://ignored-literal.example.com"`, not the data-edge-resolved value.

- [ ] **Step 3: Implement**

In `src/openacm/core/flow_executor.py`, replace `_run_http_node`:

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

with:

```python
    async def _run_http_node(
        self, node: dict, params: dict, outputs: dict,
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict],
    ) -> Any:
        cfg = node["config"]
        url = resolve_field("url", node["id"], cfg, data_edges_by_target, nodes, params, outputs)
        method = cfg.get("method", "GET").upper()
        headers = {k: substitute_templates(v, params, outputs) for k, v in (cfg.get("headers") or {}).items()}
        # body is optional (defaults to None, not ""); only route it through
        # resolve_field when there's a literal to template-substitute OR a
        # data edge targets it — otherwise leave it exactly None, matching
        # the pre-existing behavior byte-for-byte for a flow saved before
        # this task shipped.
        if cfg.get("body") or (node["id"], "body") in data_edges_by_target:
            body = resolve_field("body", node["id"], cfg, data_edges_by_target, nodes, params, outputs)
        else:
            body = cfg.get("body")

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(method, url, headers=headers, content=body)
            response.raise_for_status()
            try:
                return response.json()
            except Exception:
                return response.text
```

Then, in `run()`, find the handler dispatch (currently):

```python
            handler = self._HANDLERS.get(node["type"])
            if handler is None:
                return f"Error: unknown node type '{node['type']}'", outputs

            try:
                result = await handler(self, node, params, outputs)
            except Exception as exc:
                return f"Error in node '{node['id']}' ({node['type']}): {exc}", outputs
```

and change the call to:

```python
            handler = self._HANDLERS.get(node["type"])
            if handler is None:
                return f"Error: unknown node type '{node['type']}'", outputs

            try:
                result = await handler(self, node, params, outputs, data_edges_by_target, nodes)
            except Exception as exc:
                return f"Error in node '{node['id']}' ({node['type']}): {exc}", outputs
```

(`_run_conditional_node` and `_run_woocommerce_node` don't accept these two new params yet — Tasks 3 and 4 add them next. Until then, this call site change alone would break those two handlers; Steps 4-5 below fix that by landing all three signature changes as one commit unit for Task 2, OR — since this plan executes tasks in order — Tasks 3 and 4 must run immediately after to keep the suite green. To keep Task 2 self-contained and its own test suite green, also make the minimal signature-only change to the other two handlers in this same step, without changing their bodies.)

In `src/openacm/core/flow_executor.py`, change `_run_conditional_node`'s and `_run_woocommerce_node`'s `def` lines only (bodies untouched — Tasks 3 and 4 rewrite the bodies):

```python
    async def _run_conditional_node(
        self, node: dict, params: dict, outputs: dict,
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict],
    ) -> dict:
```

```python
    async def _run_woocommerce_node(
        self, node: dict, params: dict, outputs: dict,
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict],
    ) -> str:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests — `_run_conditional_node`/`_run_woocommerce_node` now accept the two extra params but ignore them, which is harmless since their bodies don't reference them yet).

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): HTTP node's url/body fields resolve from a wired data edge when present"
```

---

### Task 3: Backend — wire `resolve_field` into the Conditional node handler

**Files:**
- Modify: `src/openacm/core/flow_executor.py` (`_run_conditional_node` — signature already updated by Task 2, only the body changes here)
- Test: `tests/unit/test_flow_executor.py`

**Interfaces:**
- Consumes: `resolve_field`, `_run_conditional_node`'s signature (Tasks 1-2).
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_flow_executor.py`, add a new class after `class TestConditionalNode` (after `test_passthrough_output_is_the_evaluated_value_not_the_boolean`):

```python
class TestConditionalNodeDataEdges:
    async def test_field_is_resolved_from_a_data_edge_when_one_targets_it(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http0", "type": "http", "config": {"url": "https://source.example.com", "method": "GET"}},
                {"id": "cond1", "type": "conditional", "config": {"field": "{{ignored}}", "operator": "equals", "value": "zapatos"}},
                {"id": "end_true", "type": "end", "config": {"template": "YES"}},
                {"id": "end_false", "type": "end", "config": {"template": "NO"}},
            ],
            "edges": [
                {"from": "start", "to": "http0", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "cond1", "fromHandle": "default", "kind": "flow"},
                {"from": "cond1", "to": "end_true", "fromHandle": "true", "kind": "flow"},
                {"from": "cond1", "to": "end_false", "fromHandle": "false", "kind": "flow"},
                {"from": "http0", "to": "cond1", "fromHandle": "default", "toHandle": "field", "kind": "data"},
            ],
        }
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "zapatos"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        # field's literal is "{{ignored}}" (resolves to "[missing: ignored]")
        # — if the data edge weren't winning, equals would evaluate False.
        assert result == "YES"

    async def test_value_is_resolved_from_a_data_edge_when_one_targets_it(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": [{"name": "start_value", "type": "string", "required": True}]}},
                {"id": "http0", "type": "http", "config": {"url": "https://source.example.com", "method": "GET"}},
                {"id": "cond1", "type": "conditional", "config": {"field": "{{start_value}}", "operator": "equals", "value": "wrong-literal"}},
                {"id": "end_true", "type": "end", "config": {"template": "YES"}},
                {"id": "end_false", "type": "end", "config": {"template": "NO"}},
            ],
            "edges": [
                {"from": "start", "to": "http0", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "cond1", "fromHandle": "default", "kind": "flow"},
                {"from": "cond1", "to": "end_true", "fromHandle": "true", "kind": "flow"},
                {"from": "cond1", "to": "end_false", "fromHandle": "false", "kind": "flow"},
                {"from": "http0", "to": "cond1", "fromHandle": "default", "toHandle": "value", "kind": "data"},
            ],
        }
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "zapatos"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={"start_value": "zapatos"})

        assert result == "YES"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestConditionalNodeDataEdges -v`
Expected: FAIL — `_run_conditional_node` still ignores `data_edges_by_target` (it's an unused parameter after Task 2), so both tests take the `NO` branch.

- [ ] **Step 3: Implement**

In `src/openacm/core/flow_executor.py`, replace `_run_conditional_node`'s body:

```python
    async def _run_conditional_node(
        self, node: dict, params: dict, outputs: dict,
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict],
    ) -> dict:
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

with:

```python
    async def _run_conditional_node(
        self, node: dict, params: dict, outputs: dict,
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict],
    ) -> dict:
        cfg = node["config"]
        operator = cfg["operator"]
        if operator not in self._CONDITIONAL_OPERATORS:
            raise ValueError(f"Unknown conditional operator: {operator}")

        resolved = resolve_field("field", node["id"], cfg, data_edges_by_target, nodes, params, outputs)
        # value has no history of template substitution (it's a raw
        # comparison literal) — only route it through resolve_field when a
        # data edge actually targets it, so a flow saved before this task
        # shipped keeps its literal "value" exactly as-is, never templated.
        if (node["id"], "value") in data_edges_by_target:
            compare_value = resolve_field("value", node["id"], cfg, data_edges_by_target, nodes, params, outputs)
        else:
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): Conditional node's field/value fields resolve from a wired data edge when present"
```

---

### Task 4: Backend — WooCommerce structured output (`result`+`count`) + `search_term` via `resolve_field` + whole-value dict special case

**Files:**
- Modify: `src/openacm/core/flow_executor.py` (`_run_woocommerce_node` — signature already updated by Task 2; `substitute_templates`)
- Test: `tests/unit/test_flow_executor.py`

**Interfaces:**
- Consumes: `resolve_field`, `_run_woocommerce_node`'s signature (Tasks 1-2).
- Produces: `_run_woocommerce_node` now returns `{"result": str, "count": int}` instead of a bare string — Task 5's Set-node tests and Tasks 8/11 (frontend) depend on this exact shape (`result`/`count` are the two named source-pin ids the canvas exposes). `substitute_templates` gains the bare-`{{node_id}}`-resolves-to-`result` special case.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_flow_executor.py`, add two tests to `class TestSubstituteTemplates` (after `test_multiple_substitutions_in_one_template`):

```python
    def test_bare_reference_to_a_dict_with_a_result_key_resolves_to_that_key(self):
        result = substitute_templates(
            "{{woo1}}", params={}, outputs={"woo1": {"result": "formatted text", "count": 3}}
        )
        assert result == "formatted text"

    def test_bare_reference_to_a_dict_without_a_result_key_stringifies_the_whole_dict_unchanged(self):
        # Proves the special case is narrow: a dict-shaped output with no
        # "result" key still stringifies exactly as it always has.
        result = substitute_templates(
            "{{http1}}", params={}, outputs={"http1": {"status": "ok"}}
        )
        assert result == "{'status': 'ok'}"
```

Then add a new class after `class TestWooCommerceNode` (after `test_search_uses_basic_auth_with_connection_credentials`):

```python
class TestWooCommerceStructuredOutput:
    async def test_returns_a_dict_with_result_and_count(self):
        products = [
            {"name": "A", "price": "1", "stock_quantity": 1, "manage_stock": True, "short_description": "", "permalink": "https://x"},
            {"name": "B", "price": "2", "stock_quantity": 1, "manage_stock": True, "short_description": "", "permalink": "https://x"},
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

        graph = _woo_graph()
        graph["nodes"][2]["config"]["template"] = "{{woo1.count}}"

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            result, outputs = await executor.run(graph, params={"producto": "zapatos"})

        assert result == "2"
        assert outputs["woo1"]["count"] == 2
        assert isinstance(outputs["woo1"]["result"], str)

    async def test_count_reflects_the_top_5_slice_not_the_full_result_set(self):
        products = [
            {"name": f"P{i}", "price": "1", "stock_quantity": 1, "manage_stock": True, "short_description": "", "permalink": "https://x"}
            for i in range(8)
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

        graph = _woo_graph()
        graph["nodes"][2]["config"]["template"] = "{{woo1.count}}"

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            result, _ = await executor.run(graph, params={"producto": "zapatos"})

        assert result == "5"

    async def test_bare_reference_still_resolves_to_the_formatted_result_text(self):
        """{{woo1}} (no dot) must keep behaving exactly as it did before
        this task — the human-formatted listing — even though
        outputs['woo1'] is now a dict, via the new whole-value
        dict-with-result-key special case in substitute_templates."""
        products = [
            {"name": "Zapatos rojos", "price": "49.99", "stock_quantity": 3, "manage_stock": True,
             "short_description": "Comodos", "permalink": "https://tienda.example.com/zapatos-rojos"},
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
            result, _ = await executor.run(_woo_graph(), params={"producto": "zapatos"})

        assert "Zapatos rojos" in result
        assert "$49.99" in result

    async def test_no_products_found_is_also_a_result_count_dict(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        async def get_connection(conn_id):
            return _connection_row()

        graph = _woo_graph()
        graph["nodes"][2]["config"]["template"] = "{{woo1.count}}"

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_connection=get_connection)
            result, outputs = await executor.run(graph, params={"producto": "inexistente"})

        assert result == "0"
        assert "No products found" in outputs["woo1"]["result"]

    async def test_search_term_is_resolved_from_a_data_edge_when_one_targets_it(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http0", "type": "http", "config": {"url": "https://source.example.com", "method": "GET"}},
                {"id": "woo1", "type": "woocommerce", "config": {"connection_id": 1, "search_term": "ignored-literal"}},
                {"id": "end", "type": "end", "config": {"template": "{{woo1}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http0", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "woo1", "fromHandle": "default", "kind": "flow"},
                {"from": "woo1", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "http0", "to": "woo1", "fromHandle": "default", "toHandle": "search_term", "kind": "data"},
            ],
        }
        source_response = MagicMock()
        source_response.headers = {"content-type": "text/plain"}
        source_response.text = "zapatos"
        source_response.json.side_effect = ValueError("not json")
        source_response.raise_for_status = MagicMock()
        mock_http_client = AsyncMock()
        mock_http_client.request.return_value = source_response
        mock_http_client.__aenter__.return_value = mock_http_client
        mock_http_client.__aexit__.return_value = False

        products_response = MagicMock()
        products_response.json.return_value = []
        products_response.raise_for_status = MagicMock()
        mock_woo_client = AsyncMock()
        mock_woo_client.get.return_value = products_response
        mock_woo_client.__aenter__.return_value = mock_woo_client
        mock_woo_client.__aexit__.return_value = False

        async def get_connection(conn_id):
            return _connection_row()

        with patch("openacm.core.flow_executor.httpx.AsyncClient") as mock_cls:
            mock_cls.side_effect = [mock_http_client, mock_woo_client]
            executor = FlowExecutor(get_connection=get_connection)
            result, _ = await executor.run(graph, params={})

        assert "zapatos" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestWooCommerceStructuredOutput tests/unit/test_flow_executor.py::TestSubstituteTemplates -v`
Expected: FAIL — `_run_woocommerce_node` still returns a bare string, and `substitute_templates` has no `result`-key special case yet (`test_bare_reference_to_a_dict_with_a_result_key_resolves_to_that_key` fails since the current code stringifies the whole dict).

- [ ] **Step 3: Implement**

In `src/openacm/core/flow_executor.py`, replace `_run_woocommerce_node`:

```python
    async def _run_woocommerce_node(
        self, node: dict, params: dict, outputs: dict,
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict],
    ) -> str:
        cfg = node["config"]
        search_term = substitute_templates(cfg["search_term"], params, outputs)

        if not self.get_connection:
            raise RuntimeError("No connection lookup configured for this flow executor")

        connection = await self.get_connection(cfg["connection_id"])
        if not connection:
            raise RuntimeError(f"Connection {cfg['connection_id']} not found")

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

with:

```python
    async def _run_woocommerce_node(
        self, node: dict, params: dict, outputs: dict,
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict],
    ) -> dict:
        cfg = node["config"]
        search_term = resolve_field("search_term", node["id"], cfg, data_edges_by_target, nodes, params, outputs)

        if not self.get_connection:
            raise RuntimeError("No connection lookup configured for this flow executor")

        connection = await self.get_connection(cfg["connection_id"])
        if not connection:
            raise RuntimeError(f"Connection {cfg['connection_id']} not found")

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
            return {"result": f"No products found for query: '{search_term}'.", "count": 0}

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

        return {"result": "\n".join(output), "count": len(products[:5])}
```

Then, in `substitute_templates`, replace:

```python
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
```

with:

```python
    def _replace(match: re.Match) -> str:
        name, field = match.group(1), match.group(2)
        if field is None:
            if name in params:
                return str(params[name])
            if name in outputs:
                value = outputs[name]
                # A dict-shaped output that exposes a "result" key (today,
                # only WooCommerce's structured output) resolves its bare
                # {{node_id}} reference to that key specifically — this
                # keeps every {{woo1}} reference saved before this task
                # reading exactly as it always has (the human-formatted
                # listing), instead of stringifying the whole dict. This is
                # a narrow, explicit special case, not a general change to
                # whole-value substitution for every dict-shaped output.
                if isinstance(value, dict) and "result" in value:
                    return str(value["result"])
                return str(value)
            return f"[missing: {name}]"
        value = outputs.get(name)
        if isinstance(value, dict) and field in value:
            return str(value[field])
        return f"[missing: {name}.{field}]"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): WooCommerce node returns {result, count}, search_term wire-or-literal, bare {{woo1}} still reads as result"
```

---

### Task 5: Backend — Set node's data-input handle resolution with backward-compat fallback

**Files:**
- Modify: `src/openacm/core/flow_executor.py` (`run()`'s `set`-node branch)
- Test: `tests/unit/test_flow_executor.py`

**Interfaces:**
- Consumes: `_resolve_pin_value` (Task 1).
- Produces: nothing new consumed by later backend tasks. Confirms the exact `toHandle` name (`"value"`) that Task 7 (frontend `SetNode`) must match.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_flow_executor.py`, add a new class after `class TestSetNode` (after `test_set_node_downstream_of_a_merge_uses_the_branch_actually_taken`):

```python
class TestSetNodeDataEdge:
    async def test_set_value_handle_wired_to_a_far_back_node_aliases_it_correctly(self):
        """Old previous_id-only logic could only ever alias the node
        immediately before Set in the chain. A data edge on Set's "value"
        handle can reach back further — here Set sits after http_b (its
        immediate flow-predecessor) but is wired to alias http_a's output,
        several steps earlier."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http_a", "type": "http", "config": {"url": "https://a.example.com", "method": "GET"}},
                {"id": "http_b", "type": "http", "config": {"url": "https://b.example.com", "method": "GET"}},
                {"id": "set1", "type": "set", "config": {"name": "picked"}},
                {"id": "end", "type": "end", "config": {"template": "{{picked}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http_a", "fromHandle": "default", "kind": "flow"},
                {"from": "http_a", "to": "http_b", "fromHandle": "default", "kind": "flow"},
                {"from": "http_b", "to": "set1", "fromHandle": "default", "kind": "flow"},
                {"from": "set1", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "http_a", "to": "set1", "fromHandle": "default", "toHandle": "value", "kind": "data"},
            ],
        }
        response_a = MagicMock()
        response_a.headers = {"content-type": "text/plain"}
        response_a.text = "from A"
        response_a.json.side_effect = ValueError("not json")
        response_a.raise_for_status = MagicMock()
        response_b = MagicMock()
        response_b.headers = {"content-type": "text/plain"}
        response_b.text = "from B"
        response_b.json.side_effect = ValueError("not json")
        response_b.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request.side_effect = [response_a, response_b]
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(graph, params={})

        assert result == "from A"

    async def test_no_data_edge_on_value_handle_falls_back_to_previous_id_unchanged(self):
        # Byte-identical to pre-this-task behavior for every flow saved
        # before this shipped: no data edges at all, Set aliases its
        # immediate flow-predecessor via previous_id exactly as before.
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "hola mundo"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result, _ = await executor.run(_set_graph(), params={})

        assert result == "Valor: hola mundo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestSetNodeDataEdge -v`
Expected: `test_set_value_handle_wired_to_a_far_back_node_aliases_it_correctly` FAILs — `set1` still resolves via `previous_id` (`http_b`, giving `"from B"`), ignoring the data edge to `http_a`. `test_no_data_edge_on_value_handle_falls_back_to_previous_id_unchanged` already PASSes (it's a regression guard, included now so Step 4 proves nothing broke).

- [ ] **Step 3: Implement**

In `src/openacm/core/flow_executor.py`, in `run()`, replace the `set`-node branch:

```python
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
```

with:

```python
            if node["type"] == "set":
                # A data edge targeting Set's "value" handle wins if one
                # exists — it can alias ANY earlier node's output, not just
                # the immediate flow-predecessor. If none exists (every Set
                # node saved before this task shipped), fall back to the
                # old previous_id behavior exactly as it worked before:
                # previous_id is the node actually visited just before this
                # one IN THIS RUN — correct even when this node has multiple
                # incoming edges in the graph (a merge point after a
                # Conditional's two branches), since only one of those
                # edges is ever the real predecessor on any given run.
                value_edge = data_edges_by_target.get((node["id"], "value"))
                if value_edge is not None:
                    source_id, source_handle = value_edge
                    found, value = _resolve_pin_value(source_id, source_handle, nodes, outputs)
                    if found:
                        outputs[node["id"]] = value
                        outputs[node["config"]["name"]] = value
                elif previous_id and previous_id in outputs:
                    value = outputs[previous_id]
                    outputs[node["id"]] = value
                    outputs[node["config"]["name"]] = value
                previous_id = current_id
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest -q`
Expected: no new failures beyond the known pre-existing baseline (gmail_classifier + date-dependent gmail_summary tests, per every prior flow-editor plan's final review).

- [ ] **Step 6: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): Set node's data-input handle (toHandle=value) can alias any earlier node's output"
```

---

### Task 6: Frontend — Get node loses its flow handles (audit + confirm)

**Files:**
- Modify: `frontend/components/flow-editor/node-types.tsx` (re-read fresh — `GetNode`, currently a self-contained function with no target `Handle`)
- Audit only (no functional changes expected): `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing consumed by later tasks — this is a documentation/audit task confirming the canvas already matches the spec's "Get is a pure node" design.

- [ ] **Step 1: Confirm `GetNode` already has no flow handles**

Read `frontend/components/flow-editor/node-types.tsx`'s current `GetNode` function. It already renders only one `<Handle type="source" position={Position.Bottom} id="default" />` and no `<Handle type="target" .../>` — Get already has no flow-in handle in this codebase (this was true even before this plan; the prior flow-editor plan's Task 4 explicitly excluded `GetNode` from receiving a `MergeBadge` "since neither [StartNode nor GetNode] has a target handle"). No functional change is needed here — only Step 2's explanatory comment.

- [ ] **Step 2: Add the explanatory comment**

In `frontend/components/flow-editor/node-types.tsx`, replace:

```typescript
export function GetNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('get')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.data }}>📤 Obtener (Get)</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}
```

with:

```typescript
// Get is a pure data node — no flow-in/flow-out handles, matching Unreal
// Blueprint's pure (non-exec) nodes. It's referenced directly by whatever
// needs its value, wherever that node sits in the graph, via a data edge
// (or the existing {{name}}/{{get_id}} template syntax) — never walked by
// FlowExecutor.run()'s flow-edge traversal. See resolve_field's Get
// special case in flow_executor.py (_resolve_pin_value) for how a
// never-walked Get node's value still gets computed on demand.
export function GetNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('get')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.data }}>📤 Obtener (Get)</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}
```

- [ ] **Step 3: Audit `FlowCanvas.tsx` for flow-in-handle assumptions on Get**

Search `frontend/components/flow-editor/FlowCanvas.tsx` for every reference to `'get'`. As of this plan's writing there are exactly four: the `NODE_CATEGORIES` label list (line ~152), the `variableNames` computation (`n.type === 'set' || n.type === 'get'`, line ~297), the `variableDropMenu`'s "📤 Obtener (Get)" button (line ~537, which creates a bare Get node with NO edges at all — the user wires it manually), and the Inspector's `selectedNode.type === 'get'` block (line ~718, name-only field, no handle assumptions). None of these create a flow edge to/from a Get node or assume Get has a flow-in handle — confirm this by re-reading each site fresh (line numbers shift as earlier tasks in this plan edit the file). No code changes are required here.

- [ ] **Step 4: Verify types**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/flow-editor/node-types.tsx
git commit -m "docs(flows): explain why GetNode has no flow handles (pure node, audited FlowCanvas.tsx for assumptions)"
```

---

### Task 7: Frontend — edge `kind`/`toHandle` plumbing + Set node gains a second target handle for its data input

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx` (re-read fresh — `GraphJson`, `toReactFlow`, `toGraphJson`, `onConnect`, `onConnectEnd`, `onCanvasPaste`)
- Modify: `frontend/components/flow-editor/node-types.tsx` (`SetNode`)

**Interfaces:**
- Consumes: nothing from other frontend tasks (Task 6 is independent/parallel).
- Produces: `GraphJson`'s edge shape gains `toHandle: string` and `kind: 'flow' | 'data'`, matching the backend's `graph_json` shape from Task 1. React Flow `Edge` objects now carry `targetHandle` and `data: { kind: 'flow' | 'data' }`, round-tripped through `toReactFlow`/`toGraphJson`/copy-paste/`onConnectEnd`. **This is the shared plumbing Tasks 8-12 all depend on** — any new edge created anywhere in the canvas from this task forward must set `targetHandle` and `data.kind` correctly, or it will save as a flow edge by default (safe fallback, but wrong for a real data pin). `SetNode` gains `<Handle type="target" position={Position.Left} id="value" />` — the exact `toHandle` name Task 5's backend already expects.

- [ ] **Step 1: Extend `GraphJson`'s edge shape and the two conversion functions**

In `frontend/components/flow-editor/FlowCanvas.tsx`, replace:

```typescript
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
```

with:

```typescript
interface GraphJson {
  nodes: Array<{ id: string; type: string; config: Record<string, unknown>; position: { x: number; y: number } }>;
  edges: Array<{ from: string; to: string; fromHandle: string; toHandle: string; kind: 'flow' | 'data' }>;
}

function toReactFlow(graph: GraphJson): { nodes: Node[]; edges: Edge[] } {
  return {
    nodes: graph.nodes.map(n => ({ id: n.id, type: n.type, position: n.position, data: n.config })),
    edges: graph.edges.map(e => ({
      id: `${e.from}-${e.to}-${e.fromHandle}-${e.toHandle || 'flow'}`,
      source: e.from,
      target: e.to,
      sourceHandle: e.fromHandle,
      targetHandle: e.toHandle || 'flow',
      // React Flow's Edge type has no first-class "kind" field — stash it
      // in `data` so it survives every state update (applyEdgeChanges,
      // copy/paste, etc.) and toGraphJson can read it back out on save.
      // An edge with no kind saved before this shipped defaults to "flow",
      // matching the backend's identical backward-compat rule.
      data: { kind: (e.kind || 'flow') as 'flow' | 'data' },
    })),
  };
}

function toGraphJson(nodes: Node[], edges: Edge[]): GraphJson {
  return {
    nodes: nodes.map(n => ({ id: n.id, type: n.type || 'http', config: n.data as Record<string, unknown>, position: n.position })),
    edges: edges.map(e => ({
      from: e.source,
      to: e.target,
      fromHandle: e.sourceHandle || 'default',
      toHandle: e.targetHandle || 'flow',
      kind: ((e.data as { kind?: 'flow' | 'data' } | undefined)?.kind) || 'flow',
    })),
  };
}
```

- [ ] **Step 2: Classify new edges as `flow` or `data` at connect-time**

In `frontend/components/flow-editor/FlowCanvas.tsx`, replace:

```typescript
  const onConnect = useCallback((connection: Connection) => setEdges(eds => addEdge(connection, eds)), []);
```

with:

```typescript
  const onConnect = useCallback((connection: Connection) => {
    // A data edge always targets a NAMED field/value handle (e.g. "url",
    // "value", "search_term") — every node's flow-in handle is always id
    // "default", so that's the one signal available at connect-time to
    // tell a flow edge from a data edge without a node-type lookup here.
    const kind: 'flow' | 'data' = connection.targetHandle && connection.targetHandle !== 'default' ? 'data' : 'flow';
    setEdges(eds => addEdge({ ...connection, data: { kind } }, eds));
  }, []);
```

- [ ] **Step 3: Preserve `kind`/`targetHandle` through the flow-out-drag-to-empty-canvas Set promotion and through copy/paste**

In `frontend/components/flow-editor/FlowCanvas.tsx`'s `onConnectEnd`, replace:

```typescript
    setNodes(nds => [...nds, { id: newId, type: 'set', position: flowPosition, data: { name } }]);
    setEdges(eds => [...eds, {
      id: `${connectionState.fromNode!.id}-${newId}-${connectionState.fromHandle?.id || 'default'}`,
      source: connectionState.fromNode!.id,
      target: newId,
      sourceHandle: connectionState.fromHandle?.id || 'default',
    }]);
```

with:

```typescript
    setNodes(nds => [...nds, { id: newId, type: 'set', position: flowPosition, data: { name } }]);
    setEdges(eds => [...eds, {
      id: `${connectionState.fromNode!.id}-${newId}-${connectionState.fromHandle?.id || 'default'}-flow`,
      source: connectionState.fromNode!.id,
      target: newId,
      sourceHandle: connectionState.fromHandle?.id || 'default',
      // Always a flow edge — dragging a flow-out handle to empty canvas
      // promotes a new Set node into the CHAIN (its flow-in "default"
      // handle), never wires a data pin.
      targetHandle: 'default',
      data: { kind: 'flow' },
    }]);
```

In `onCanvasPaste`, replace:

```typescript
    const pastedEdges: Edge[] = clip.edges.map(e => ({
      id: `${idMap[e.source]}-${idMap[e.target]}-${e.sourceHandle || 'default'}`,
      source: idMap[e.source],
      target: idMap[e.target],
      sourceHandle: e.sourceHandle,
    }));
```

with:

```typescript
    const pastedEdges: Edge[] = clip.edges.map(e => ({
      id: `${idMap[e.source]}-${idMap[e.target]}-${e.sourceHandle || 'default'}-${e.targetHandle || 'flow'}`,
      source: idMap[e.source],
      target: idMap[e.target],
      sourceHandle: e.sourceHandle,
      targetHandle: e.targetHandle,
      data: e.data,
    }));
```

- [ ] **Step 4: Give `SetNode` its second, independent data-input handle**

In `frontend/components/flow-editor/node-types.tsx`, replace:

```typescript
export function SetNode({ id, data }: NodeProps) {
  return (
    <div style={{ ...baseStyleFor('set'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.data }}>💾 Guardar (Set)</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}
```

with:

```typescript
export function SetNode({ id, data }: NodeProps) {
  return (
    <div style={{ ...baseStyleFor('set'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.data }}>💾 Guardar (Set)</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>entrada: valor (opcional — sin conexión usa el nodo anterior)</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="target" position={Position.Top} id="default" />
      {/* Second, independent target handle for Set's data-input pin
          (toHandle="value", matching flow_executor.py's Set-node branch) —
          can be wired from ANY node's output, not just the flow-immediate
          predecessor. Falls back to the old previous_id behavior when
          nothing is wired here. */}
      <Handle type="target" position={Position.Left} id="value" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}
```

- [ ] **Step 5: Verify types**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx frontend/components/flow-editor/node-types.tsx
git commit -m "feat(agents): edges carry kind/toHandle end-to-end, Set gains a second data-input handle"
```

---

### Task 8: Frontend — WooCommerce node gains two named source handles (`result`, `count`)

**Files:**
- Modify: `frontend/components/flow-editor/node-types.tsx` (`WooCommerceNode`)

**Interfaces:**
- Consumes: nothing new from Task 7 directly (this only touches the canvas node's `Handle`s, not edge state).
- Produces: `WooCommerceNode` has three source handles total: `"default"` (flow-out, UNCHANGED position/id — every flow saved before this ships keeps rendering its existing flow edge correctly), `"result"`, and `"count"` (both new, for data edges only — matching Task 4's backend `{"result": ..., "count": ...}` shape). Task 11 adds a fourth handle (`"search_term"`, a target) to this same component.

- [ ] **Step 1: Implement**

In `frontend/components/flow-editor/node-types.tsx`, replace:

```typescript
export function WooCommerceNode({ id, data }: NodeProps) {
  return (
    <div style={{ ...baseStyleFor('woocommerce'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.integration }}>🛒 WooCommerce</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.search_term || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: result</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}
```

with:

```typescript
export function WooCommerceNode({ id, data }: NodeProps) {
  return (
    <div style={{ ...baseStyleFor('woocommerce'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.integration }}>🛒 WooCommerce</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.search_term || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: result</div>
      <div style={pinLabelStyle}>salida: count</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
      {/* Named data-output pins (Task 4's backend {"result": ..., "count":
          ...} shape) — independent of the flow-out "default" handle above,
          which keeps its old id/position unchanged so every flow saved
          before this shipped still renders its existing flow edge
          correctly. */}
      <Handle type="source" position={Position.Right} id="result" style={{ top: '40%' }} />
      <Handle type="source" position={Position.Right} id="count" style={{ top: '65%' }} />
    </div>
  );
}
```

- [ ] **Step 2: Verify types**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/flow-editor/node-types.tsx
git commit -m "feat(agents): WooCommerce node exposes named result/count data-output pins"
```

---

### Task 9: Frontend — HTTP node per-field pins (`url`, `body`) with connected/disconnected UI

**Files:**
- Modify: `frontend/components/flow-editor/node-types.tsx` (`HttpNode`)
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx` (new shared `ConnectableField` component; HTTP's Inspector block)

**Interfaces:**
- Consumes: `useNodeConnections` (already imported in `node-types.tsx` for `MergeBadge`), the `edges`/`setEdges` state and `Edge.data.kind`/`targetHandle` plumbing from Task 7.
- Produces: **the reusable pattern Tasks 10 and 11 copy exactly:**
  - A named `Handle` (`type="target"`) on the canvas node component, one per wire-or-literal field, positioned at `Position.Left` with a distinct `top` offset per field.
  - The shared component `ConnectableField({ nodeId, fieldName, edges, setEdges, children }: { nodeId: string; fieldName: string; edges: Edge[]; setEdges: React.Dispatch<React.SetStateAction<Edge[]>>; children: React.ReactNode })`, defined once in `FlowCanvas.tsx`, imported/used as-is by Tasks 10-11 with no changes to its own definition — only new call sites with different `fieldName`s.

**Design note (per this task's investigation requirement):** React Flow's `Handle` component must be a descendant of the actual canvas node component registered in `nodeTypes` — it computes its connection point from that node's own DOM position, so it cannot be rendered from the separate Inspector side panel (`FlowCanvas.tsx`'s selected-node detail column), which targets an arbitrary node by id from outside the canvas tree. The draggable `Handle` therefore lives in `node-types.tsx` on `HttpNode` itself; the connected/disconnected chip-vs-literal-input toggle (which only needs to read/write the `edges` array, not render inside the canvas node) lives in the Inspector, in `FlowCanvas.tsx`.

- [ ] **Step 1: Add the `url`/`body` target handles to `HttpNode`, with a canvas-level connected indicator**

In `frontend/components/flow-editor/node-types.tsx`, replace:

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

with:

```typescript
export function HttpNode({ id, data }: NodeProps) {
  const targetConnections = useNodeConnections({ id, handleType: 'target' });
  const urlWired = targetConnections.some(c => c.targetHandle === 'url');
  const bodyWired = targetConnections.some(c => c.targetHandle === 'body');
  return (
    <div style={{ ...baseStyleFor('http'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.integration }}>🌐 HTTP Request</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>
        {String(data.method || 'GET')} {urlWired ? '🔌 url conectada' : String(data.url || '')}
      </div>
      {bodyWired && <div style={{ color: 'var(--acm-fg-4)' }}>🔌 body conectado</div>}
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: response</div>
      <Handle type="target" position={Position.Top} id="default" />
      {/* Data-input pins for HTTP's wire-or-literal "url"/"body" fields —
          independent of the flow-in "default" handle above. method/headers
          stay literal-only, no pin, per the spec's explicit
          dropdown/template boundary. */}
      <Handle type="target" position={Position.Left} id="url" style={{ top: '55%' }} />
      <Handle type="target" position={Position.Left} id="body" style={{ top: '75%' }} />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}
```

If `useNodeConnections`'s type signature doesn't match (e.g. the connection object's field names), check `node_modules/@xyflow/react/dist/esm/hooks/useNodeConnections.d.ts` and adjust the call/field access to match rather than casting past the error.

- [ ] **Step 2: Add the shared `ConnectableField` component**

In `frontend/components/flow-editor/FlowCanvas.tsx`, add this after `TemplatePreview` and before `maxNodeIdSuffix`:

```typescript
// Shared connected/disconnected rendering for a single wire-or-literal
// Inspector field (HTTP url/body — this task; Conditional field/value and
// WooCommerce search_term reuse this exact component unchanged in later
// tasks). A `kind: "data"` edge whose `targetHandle` matches `fieldName`
// and whose `target` matches `nodeId` hides the literal input (`children`)
// and shows a small chip with a disconnect action instead; with no such
// edge, `children` renders exactly as it did before this feature.
function ConnectableField({ nodeId, fieldName, edges, setEdges, children }: {
  nodeId: string;
  fieldName: string;
  edges: Edge[];
  setEdges: React.Dispatch<React.SetStateAction<Edge[]>>;
  children: React.ReactNode;
}) {
  const dataEdge = edges.find(e =>
    e.target === nodeId &&
    e.targetHandle === fieldName &&
    (e.data as { kind?: string } | undefined)?.kind === 'data'
  );
  if (!dataEdge) return <>{children}</>;
  const sourceLabel = dataEdge.sourceHandle && dataEdge.sourceHandle !== 'default'
    ? `${dataEdge.source}.${dataEdge.sourceHandle}`
    : dataEdge.source;
  return (
    <div className="flex items-center gap-1 mb-1 p-1" style={{ background: 'var(--acm-base)', border: '1px solid var(--acm-node-data)', borderRadius: 4 }}>
      <span className="text-[10px] flex-1" style={{ color: 'var(--acm-fg-3)' }}>
        🔌 conectado a {'{{'}{sourceLabel}{'}}'}
      </span>
      <button
        className="text-[var(--acm-fg-4)] hover:text-[var(--acm-err)]"
        onClick={() => setEdges(eds => eds.filter(e => e.id !== dataEdge.id))}
        title="Desconectar"
      >
        <Trash2 size={11} />
      </button>
    </div>
  );
}
```

- [ ] **Step 3: Wrap HTTP's `url`/`body` Inspector fields**

In `frontend/components/flow-editor/FlowCanvas.tsx`, in the `selectedNode.type === 'http'` Inspector block, replace:

```typescript
                <input ref={urlInputRef} className="acm-input w-full" value={String(selectedNode.data.url || '')} onChange={e => updateSelectedNodeData({ url: e.target.value })} />
                <TemplatePreview value={String(selectedNode.data.url || '')} params={testParams} outputs={testOutputs} />
```

with:

```typescript
                <ConnectableField nodeId={selectedNode.id} fieldName="url" edges={edges} setEdges={setEdges}>
                  <input ref={urlInputRef} className="acm-input w-full" value={String(selectedNode.data.url || '')} onChange={e => updateSelectedNodeData({ url: e.target.value })} />
                  <TemplatePreview value={String(selectedNode.data.url || '')} params={testParams} outputs={testOutputs} />
                </ConnectableField>
```

and replace:

```typescript
                <textarea ref={bodyInputRef} className="acm-input w-full" rows={3} value={String(selectedNode.data.body || '')} onChange={e => updateSelectedNodeData({ body: e.target.value })} />
                <TemplatePreview value={String(selectedNode.data.body || '')} params={testParams} outputs={testOutputs} />
```

with:

```typescript
                <ConnectableField nodeId={selectedNode.id} fieldName="body" edges={edges} setEdges={setEdges}>
                  <textarea ref={bodyInputRef} className="acm-input w-full" rows={3} value={String(selectedNode.data.body || '')} onChange={e => updateSelectedNodeData({ body: e.target.value })} />
                  <TemplatePreview value={String(selectedNode.data.body || '')} params={testParams} outputs={testOutputs} />
                </ConnectableField>
```

Do NOT touch `method` (dropdown) or the `headers` block — out of scope per the spec's explicit boundary.

- [ ] **Step 4: Verify types**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/flow-editor/node-types.tsx frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): HTTP node's url/body fields are wire-or-literal, with connected-chip UI"
```

---

### Task 10: Frontend — Conditional node per-field pins (`field`, `value`)

**Files:**
- Modify: `frontend/components/flow-editor/node-types.tsx` (`ConditionalNode`)
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx` (Conditional's Inspector block — reuses `ConnectableField` from Task 9, unchanged)

**Interfaces:**
- Consumes: `ConnectableField` exactly as defined in Task 9 — no changes to its definition, only new call sites.
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Add the `field`/`value` target handles to `ConditionalNode`**

In `frontend/components/flow-editor/node-types.tsx`, replace:

```typescript
export function ConditionalNode({ id, data }: NodeProps) {
  return (
    <div style={{ ...baseStyleFor('conditional'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.logic }}>◆ Condicional</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.field || '')} {String(data.operator || '')} {String(data.value || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: result</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="true" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="false" style={{ left: '70%' }} />
    </div>
  );
}
```

with:

```typescript
export function ConditionalNode({ id, data }: NodeProps) {
  return (
    <div style={{ ...baseStyleFor('conditional'), position: 'relative' }}>
      <MergeBadge id={id} />
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.logic }}>◆ Condicional</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.field || '')} {String(data.operator || '')} {String(data.value || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: result</div>
      <Handle type="target" position={Position.Top} id="default" />
      {/* Data-input pins for Conditional's wire-or-literal "field"/"value"
          fields — independent of the flow-in "default" handle above.
          operator stays dropdown-only, no pin, per the spec's explicit
          boundary. */}
      <Handle type="target" position={Position.Left} id="field" style={{ top: '55%' }} />
      <Handle type="target" position={Position.Left} id="value" style={{ top: '75%' }} />
      <Handle type="source" position={Position.Bottom} id="true" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="false" style={{ left: '70%' }} />
    </div>
  );
}
```

- [ ] **Step 2: Wrap Conditional's `field`/`value` Inspector fields**

In `frontend/components/flow-editor/FlowCanvas.tsx`, in the `selectedNode.type === 'conditional'` Inspector block, replace:

```typescript
              <input ref={conditionalFieldRef} className="acm-input w-full mb-2" value={String(selectedNode.data.field || '')} onChange={e => updateSelectedNodeData({ field: e.target.value })} />
              <TemplatePreview value={String(selectedNode.data.field || '')} params={testParams} outputs={testOutputs} />
```

with:

```typescript
              <ConnectableField nodeId={selectedNode.id} fieldName="field" edges={edges} setEdges={setEdges}>
                <input ref={conditionalFieldRef} className="acm-input w-full mb-2" value={String(selectedNode.data.field || '')} onChange={e => updateSelectedNodeData({ field: e.target.value })} />
                <TemplatePreview value={String(selectedNode.data.field || '')} params={testParams} outputs={testOutputs} />
              </ConnectableField>
```

and replace:

```typescript
              <label>Valor</label>
              <input className="acm-input w-full" value={String(selectedNode.data.value || '')} onChange={e => updateSelectedNodeData({ value: e.target.value })} />
```

with:

```typescript
              <label>Valor</label>
              <ConnectableField nodeId={selectedNode.id} fieldName="value" edges={edges} setEdges={setEdges}>
                <input className="acm-input w-full" value={String(selectedNode.data.value || '')} onChange={e => updateSelectedNodeData({ value: e.target.value })} />
              </ConnectableField>
```

Do NOT touch `operator` (dropdown) — out of scope per the spec's explicit boundary.

- [ ] **Step 3: Verify types**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/flow-editor/node-types.tsx frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): Conditional node's field/value fields are wire-or-literal"
```

---

### Task 11: Frontend — WooCommerce node per-field pin (`search_term`)

**Files:**
- Modify: `frontend/components/flow-editor/node-types.tsx` (`WooCommerceNode`, building on Task 8's version)
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx` (WooCommerce's Inspector block — reuses `ConnectableField` from Task 9, unchanged)

**Interfaces:**
- Consumes: `ConnectableField` exactly as defined in Task 9 — no changes to its definition, only a new call site. `WooCommerceNode`'s Task 8 shape (three handles: `default`, `result`, `count`).
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Add the `search_term` target handle to `WooCommerceNode`**

In `frontend/components/flow-editor/node-types.tsx`, in `WooCommerceNode` (as left by Task 8), replace:

```typescript
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
      {/* Named data-output pins (Task 4's backend {"result": ..., "count":
          ...} shape) — independent of the flow-out "default" handle above,
          which keeps its old id/position unchanged so every flow saved
          before this shipped still renders its existing flow edge
          correctly. */}
      <Handle type="source" position={Position.Right} id="result" style={{ top: '40%' }} />
      <Handle type="source" position={Position.Right} id="count" style={{ top: '65%' }} />
```

with:

```typescript
      <Handle type="target" position={Position.Top} id="default" />
      {/* Data-input pin for WooCommerce's wire-or-literal "search_term"
          field — independent of the flow-in "default" handle above. The
          Connection selector stays dropdown-only, no pin, per the spec's
          explicit boundary. */}
      <Handle type="target" position={Position.Left} id="search_term" style={{ top: '55%' }} />
      <Handle type="source" position={Position.Bottom} id="default" />
      {/* Named data-output pins (Task 4's backend {"result": ..., "count":
          ...} shape) — independent of the flow-out "default" handle above,
          which keeps its old id/position unchanged so every flow saved
          before this shipped still renders its existing flow edge
          correctly. */}
      <Handle type="source" position={Position.Right} id="result" style={{ top: '40%' }} />
      <Handle type="source" position={Position.Right} id="count" style={{ top: '65%' }} />
```

- [ ] **Step 2: Wrap WooCommerce's `search_term` Inspector field**

In `frontend/components/flow-editor/FlowCanvas.tsx`, in the `selectedNode.type === 'woocommerce'` Inspector block, replace:

```typescript
              <input ref={searchTermRef} className="acm-input w-full" value={String(selectedNode.data.search_term || '')} onChange={e => updateSelectedNodeData({ search_term: e.target.value })} />
              <TemplatePreview value={String(selectedNode.data.search_term || '')} params={testParams} outputs={testOutputs} />
```

with:

```typescript
              <ConnectableField nodeId={selectedNode.id} fieldName="search_term" edges={edges} setEdges={setEdges}>
                <input ref={searchTermRef} className="acm-input w-full" value={String(selectedNode.data.search_term || '')} onChange={e => updateSelectedNodeData({ search_term: e.target.value })} />
                <TemplatePreview value={String(selectedNode.data.search_term || '')} params={testParams} outputs={testOutputs} />
              </ConnectableField>
```

Do NOT touch the Connection `<select>` — out of scope per the spec's explicit boundary.

- [ ] **Step 3: Verify types**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/flow-editor/node-types.tsx frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): WooCommerce node's search_term field is wire-or-literal"
```

---

### Task 12: Frontend — variable-picker union-walk traverses data edges too

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx` (`availableVariableNames` — comment only; verify no functional change is needed)

**Interfaces:**
- Consumes: the `edges` array now containing both flow and data edges (Task 7).
- Produces: nothing consumed by later tasks — this is the final task.

**Why this is (almost) already done:** `availableVariableNames` walks `incomingBySource`, built from `for (const e of edges) { (incomingBySource[e.target] ||= []).push(e.source); }` — every edge in the array, with no `kind` filter at all. Now that `edges` includes data edges (Task 7 onward), a data edge's `source` is automatically discovered as a reachable ancestor the same way a flow edge's `source` always was — no change to the walk's logic is needed, only a comment explaining why, and a written trace confirming it in the manual smoke test below.

- [ ] **Step 1: Add the explanatory comment**

In `frontend/components/flow-editor/FlowCanvas.tsx`, replace the comment above `availableVariableNames` (function body unchanged):

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
  //
  // This walk deliberately does NOT filter by edge kind — `edges` now
  // contains both flow AND data edges (see toReactFlow/toGraphJson), so a
  // node fed by a data edge from several hops back is discovered as an
  // ancestor exactly the same way a flow-edge ancestor always was. No
  // separate data-edge traversal is needed.
```

- [ ] **Step 2: Verify types**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 3: Write the confirming trace**

Build (on paper, for this step's record — not code): `http_a --(flow)--> http_b --(flow)--> http_c --(flow)--> set1`, plus a data edge `http_a --(data, toHandle="value")--> set1`. Selecting `set1`: `incomingBySource["set1"] = ["http_c", "http_a"]` (one entry per incoming edge, flow AND data both present). The walk's queue starts as `["http_c", "http_a"]`; `http_a` is popped and visited directly from `set1`'s own incoming list (no need to traverse through `http_b`/`http_c` at all, since `http_a` is already a first-hop entry via the data edge) — so `http_a` appears in the picker even though it is three hops back along the flow chain. A flow-edge-only walk (if `incomingBySource` were built only from `kind === "flow"` edges) would need `set1 -> http_c -> http_b -> http_a`, which still reaches `http_a` in this particular linear example — the meaningful case is a data edge whose source is NOT on `set1`'s own flow ancestry at all (e.g. a sibling branch's node) still gets included, since the walk trusts every entry in `edges`, not only ones on the currently-selected node's flow path.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "docs(agents): confirm variable-picker union-walk already traverses data edges"
```

---

## Post-plan manual smoke test (end to end)

After all 12 tasks are merged, this needs an actual browser session — not just `tsc`/`pytest` — before it's considered done. Leave a durable note of what was confirmed in a progress ledger entry (per this project's own convention — see `.superpowers/sdd/progress.md`'s "MANUAL BROWSER VERIFICATION" lines for the pattern to follow).

1. **WooCommerce `count` into Set's data-input:** build a flow with a WooCommerce node, drag from its `count` source pin to a downstream Set node's new left-side "value" target handle, run "Probar flujo" with a search term that returns products — confirm the Set node's variable resolves to the real integer count (not the formatted text, not a missing marker).
2. **Disconnect reverts to literal:** on an HTTP node with its `url` field wired via a data edge (chip visible in the Inspector), click the chip's disconnect button — confirm the literal `<input>` reappears immediately, pre-populated with whatever was last typed into `config.url` (or empty if never set), and the underlying data edge is gone from the canvas.
3. **Old saved flow still runs unchanged:** open a flow saved before this plan shipped (zero data edges, possibly a Get node still wired into the flow chain from the old model) — confirm it opens without console errors, its existing flow edges render correctly (including through the old-style Get), and "Probar flujo" produces the exact same result as before this plan.
4. **Get feeding an HTTP field via a data edge:** add a Get node (referencing a variable set earlier by a Set node), drag from its output pin to an HTTP node's `url` target handle, run "Probar flujo" — confirm the request goes to the Get-resolved value even though the Get node itself is never walked by the flow (no flow edges into/out of it at all).
5. **Cycle rejection still works with data edges present:** build a flow with a "backward" data edge (e.g. Set's value pin wired to a node several steps downstream of it) alongside normal flow edges — confirm "Guardar flujo" succeeds (data edges never trigger the cycle check), then separately draw a genuine backward FLOW edge and confirm that one is still rejected with a named cycle, unaffected by this plan.
