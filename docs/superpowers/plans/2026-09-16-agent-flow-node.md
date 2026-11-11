# Agent Flow Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `agent` node type to `FlowExecutor` so any Flow (triggered by chat, by a webhook connector, or by another agent's own flow tool) can invoke an OpenACM Agent as a step, feeding it a resolved message and exposing its text response to the rest of the flow — closing out the remaining half of the webhook-connectors + agent-flow-node design spec (the connectors half already shipped).

**Architecture:** `FlowExecutor` gains two new optional constructor dependencies — `get_agent` (async `agent_id -> dict | None` lookup) and `agent_runner` (a duck-typed object exposing async `.run(agent: dict, message: str) -> str`) — following the exact pattern `get_connection` already uses for the WooCommerce node. A new `_run_agent_node` handler resolves the node's `message` field (wire-or-literal, via the existing `resolve_field()`), looks up the agent by `agent_id`, and calls `agent_runner.run(agent, message)`, returning the plain text response as the node's whole output (available as `{{node_id}}` like any other node). The three existing places that construct a `FlowExecutor` (`AgentRunner.run()`'s own flow-tool executor, the `/api/agents/{id}/flows/{id}/test` endpoint, and the `/api/webhooks/{slug}` connector trigger route) are updated to pass these two new dependencies, built from whatever `AgentRunner`/database access is already available in that context. The frontend gets a matching `AgentNode` component (`node-types.tsx`) and a config panel + palette entry (`FlowCanvas.tsx`), mirroring the existing `WooCommerceNode`/HTTP patterns.

**Tech Stack:** Python (FastAPI-adjacent core module, no new dependencies), TypeScript/React (`@xyflow/react` custom node component).

**Spec:** `docs/superpowers/specs/2026-09-09-webhook-connectors-and-agent-flow-node-design.md` (component 4, "Nodo 'Agente' en `FlowExecutor`")

## Global Constraints

- Config shape is exactly `agent_id` (int, which Agent to call) + `message` (wire-or-literal string, resolved via `resolve_field()` the same way HTTP's `url` field is). (spec §4)
- Output is the agent's raw text response stored as the node's whole value (`outputs[node_id] = text`) — available as `{{node_id}}` from any later node, exactly like any other node's default output. No dict wrapper, no extra named pins beyond `default`. (spec §4)
- `FlowExecutor.__init__` must keep working with zero arguments and with only `get_connection` passed — every existing caller and every existing test that builds a bare `FlowExecutor()` or `FlowExecutor(get_connection=...)` must keep working unchanged. (mirrors the WooCommerce `get_connection` precedent already established in flow_executor.py)
- This is generic core infrastructure — no EnergiChat/EEP-specific naming or logic anywhere in this code. (spec, "Contexto y motivación", same constraint the webhook-connectors plan already established)
- No recursion guard for an Agent node whose target agent's own flow calls back into an Agent node (directly or via a cycle of agents) — out of scope per YAGNI, same spirit as the spec's existing scope cuts. `FlowExecutor`'s existing `_MAX_NODE_VISITS`/cycle detection do not apply across a nested `AgentRunner.run()` call.
- Every wiring site (Task 2) makes `get_agent`/`agent_runner` optional dependencies — if unavailable (e.g. no brain wired up yet in that process), a flow with no Agent node is completely unaffected, and a flow that DOES have one fails that single node with `Error in node '<id>' (agent): ...`, exactly like WooCommerce fails today when `get_connection` isn't configured.

---

## Task 1: `FlowExecutor` — the `agent` node type

**Files:**
- Modify: `src/openacm/core/flow_executor.py`
- Test: `tests/unit/test_flow_executor.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (for Task 2 to consume):
  - `FlowExecutor.__init__(self, get_connection=None, get_agent=None, agent_runner=None)` — two new keyword-only-by-convention params, both optional, both default `None`.
  - `get_agent: Callable[[int], Coroutine[Any, Any, dict | None]]` — same shape as `get_connection`, looked up by `agent_id`.
  - `agent_runner: Any` — any object with an async `.run(agent: dict, message: str) -> str` method (in production this is an `AgentRunner` instance; tests pass a fake/mock).
  - `"agent"` added to `KNOWN_NODE_TYPES`, `NODE_TARGET_HANDLES` (`{"default", "message"}`), `NODE_SOURCE_HANDLES` (`{"default"}`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flow_executor.py` (after the existing `TestWooCommerceNode` class, at the end of the file):

```python
def _agent_graph(agent_id=99, message="{{texto}}"):
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": [{"name": "texto", "type": "string", "required": True}]}},
            {"id": "agent1", "type": "agent", "config": {"agent_id": agent_id, "message": message}},
            {"id": "end", "type": "end", "config": {"template": "{{agent1}}"}},
        ],
        "edges": [
            {"from": "start", "to": "agent1", "fromHandle": "default"},
            {"from": "agent1", "to": "end", "fromHandle": "default"},
        ],
    }


class TestAgentNode:
    async def test_calls_agent_runner_with_resolved_message_and_exposes_output(self):
        async def get_agent(agent_id):
            return {"id": agent_id, "name": "Redactor"}

        fake_runner = AsyncMock()
        fake_runner.run.return_value = "respuesta final"

        executor = FlowExecutor(get_agent=get_agent, agent_runner=fake_runner)
        result, outputs = await executor.run(_agent_graph(), params={"texto": "hola"})

        assert result == "respuesta final"
        assert outputs["agent1"] == "respuesta final"
        fake_runner.run.assert_awaited_once_with({"id": 99, "name": "Redactor"}, "hola")

    async def test_missing_agent_is_an_error(self):
        async def get_agent(agent_id):
            return None

        fake_runner = AsyncMock()
        executor = FlowExecutor(get_agent=get_agent, agent_runner=fake_runner)
        result, _ = await executor.run(_agent_graph(), params={"texto": "hola"})

        assert result.startswith("Error in node 'agent1'")

    async def test_no_agent_runner_configured_is_an_error(self):
        executor = FlowExecutor()  # get_agent/agent_runner default to None
        result, _ = await executor.run(_agent_graph(), params={"texto": "hola"})

        assert result.startswith("Error in node 'agent1'")

    async def test_message_field_resolved_from_a_data_edge(self):
        async def get_agent(agent_id):
            return {"id": agent_id}

        fake_runner = AsyncMock()
        fake_runner.run.return_value = "ok"

        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "http1", "type": "http", "config": {"url": "https://source.example.com", "method": "GET"}},
                {"id": "agent1", "type": "agent", "config": {"agent_id": 1, "message": "ignored literal"}},
                {"id": "end", "type": "end", "config": {"template": "{{agent1}}"}},
            ],
            "edges": [
                {"from": "start", "to": "http1", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "agent1", "fromHandle": "default", "kind": "flow"},
                {"from": "agent1", "to": "end", "fromHandle": "default", "kind": "flow"},
                {"from": "http1", "to": "agent1", "fromHandle": "default", "toHandle": "message", "kind": "data"},
            ],
        }
        http_response = MagicMock()
        http_response.headers = {"content-type": "text/plain"}
        http_response.text = "texto real del http"
        http_response.json.side_effect = ValueError("not json")
        http_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request.return_value = http_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor(get_agent=get_agent, agent_runner=fake_runner)
            await executor.run(graph, params={})

        fake_runner.run.assert_awaited_once_with({"id": 1}, "texto real del http")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_flow_executor.py::TestAgentNode -v`
Expected: FAIL — `validate_graph`/`run()` reject `'agent'` as an unknown node type (`KeyError`/error-string mismatch), since `KNOWN_NODE_TYPES`/`_HANDLERS` don't know it yet.

- [ ] **Step 3: Add the node type to the type/handle tables**

In `src/openacm/core/flow_executor.py`, change line 104:

```python
KNOWN_NODE_TYPES = {"start", "http", "conditional", "woocommerce", "set", "get", "end", "loop", "agent"}
```

Add to `NODE_TARGET_HANDLES` (after `"loop": {"default", "items"},`):

```python
    "agent": {"default", "message"},
```

Add to `NODE_SOURCE_HANDLES` (after `"loop": {"loop", "done", "item", "index"},`):

```python
    "agent": {"default"},
```

- [ ] **Step 4: Add the constructor params and the handler**

In `FlowExecutor.__init__` (currently at line 435), change:

```python
    def __init__(self, get_connection: Callable[[int], Coroutine[Any, Any, dict | None]] | None = None):
        self.get_connection = get_connection
        self._HANDLERS: dict[str, Callable] = {
            "http": FlowExecutor._run_http_node,
            "conditional": FlowExecutor._run_conditional_node,
            "woocommerce": FlowExecutor._run_woocommerce_node,
        }
```

to:

```python
    def __init__(
        self,
        get_connection: Callable[[int], Coroutine[Any, Any, dict | None]] | None = None,
        get_agent: Callable[[int], Coroutine[Any, Any, dict | None]] | None = None,
        agent_runner: Any = None,
    ):
        self.get_connection = get_connection
        self.get_agent = get_agent
        self.agent_runner = agent_runner
        self._HANDLERS: dict[str, Callable] = {
            "http": FlowExecutor._run_http_node,
            "conditional": FlowExecutor._run_conditional_node,
            "woocommerce": FlowExecutor._run_woocommerce_node,
            "agent": FlowExecutor._run_agent_node,
        }
```

Add a new handler method right after `_run_woocommerce_node` (before `async def run(self, ...)`):

```python
    async def _run_agent_node(
        self, node: dict, params: dict, outputs: dict,
        data_edges_by_target: dict[tuple[str, str], tuple[str, str]], nodes: dict[str, dict],
    ) -> str:
        cfg = node["config"]
        message = resolve_field("message", node["id"], cfg, data_edges_by_target, nodes, params, outputs)

        if not self.get_agent or not self.agent_runner:
            raise RuntimeError("No agent lookup/runner configured for this flow executor")

        agent = await self.get_agent(cfg["agent_id"])
        if not agent:
            raise RuntimeError(f"Agent {cfg['agent_id']} not found")

        return await self.agent_runner.run(agent, message)
```

No changes to `run()` itself: the `agent` node isn't `"conditional"`, so it already falls into the existing generic `else: outputs[node["id"]] = result; current_id = edges_by_source.get(node["id"], {}).get("default")` branch, exactly like `http`/`woocommerce` today.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: all PASS, including the new `TestAgentNode` class and every pre-existing test in the file (no regressions).

- [ ] **Step 6: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): add agent node type to FlowExecutor"
```

---

## Task 2: Wire `get_agent`/`agent_runner` into the three FlowExecutor call sites

**Files:**
- Modify: `src/openacm/core/agent_runner.py:207-214`
- Modify: `src/openacm/web/routers/agents.py:275-279`
- Modify: `src/openacm/web/routers/webhooks.py:96-126`
- Test: `tests/unit/test_agent_runner_flows.py`, `tests/unit/test_agents_flows_api.py`, `tests/unit/test_webhooks_router.py`

**Interfaces:**
- Consumes: `FlowExecutor(get_connection=..., get_agent=..., agent_runner=...)` from Task 1.
- Produces: nothing new for later tasks — this is the last backend task.

- [ ] **Step 1: Write the failing test for `agent_runner.py`**

Append to `tests/unit/test_agent_runner_flows.py` (needs `patch` added to the existing `from unittest.mock import AsyncMock, MagicMock, patch` import at the top of the file — it's already imported there):

```python
AGENT_FLOW_WITH_AGENT_NODE = {
    "id": 9, "name": "redact", "description": "Uses another agent",
    "graph_json": json.dumps({
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": [{"name": "texto", "type": "string", "required": True}]}},
            {"id": "agent1", "type": "agent", "config": {"agent_id": 99, "message": "{{texto}}"}},
            {"id": "end", "type": "end", "config": {"template": "{{agent1}}"}},
        ],
        "edges": [
            {"from": "start", "to": "agent1", "fromHandle": "default"},
            {"from": "agent1", "to": "end", "fromHandle": "default"},
        ],
    }),
}

OTHER_AGENT = {"id": 99, "name": "Redactor", "system_prompt": "p", "allowed_tools": "none"}


class TestAgentNodeInsideAFlowTool:
    async def test_agent_node_calls_another_agent_and_its_output_flows_through(self):
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[AGENT_FLOW_WITH_AGENT_NODE])
        db.get_agent = AsyncMock(return_value=OTHER_AGENT)
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "redacted: " + kwargs["content"]

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")
            result = await captured["tool_registry"].execute("flow_9", {"texto": "hola"})

        assert result == "redacted: hola"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agent_runner_flows.py::TestAgentNodeInsideAFlowTool -v`
Expected: FAIL — the flow's `agent` node raises `RuntimeError("No agent lookup/runner configured...")`, surfacing as `result == "Error in node 'agent1' (agent): No agent lookup/runner configured for this flow executor"`.

- [ ] **Step 3: Wire `get_agent`/`agent_runner` in `agent_runner.py`**

In `src/openacm/core/agent_runner.py`, change (currently lines 207-214):

```python
                from openacm.core.flow_executor import FlowExecutor

                async def get_connection(connection_id: int):
                    return await self.database.get_connection(connection_id)

                executor = FlowExecutor(get_connection=get_connection)
                flow_tools = {f"flow_{f['id']}": _build_flow_tool(f, executor) for f in active_flows}
```

to:

```python
                from openacm.core.flow_executor import FlowExecutor

                async def get_connection(connection_id: int):
                    return await self.database.get_connection(connection_id)

                async def get_agent(agent_id: int):
                    return await self.database.get_agent(agent_id)

                executor = FlowExecutor(get_connection=get_connection, get_agent=get_agent, agent_runner=self)
                flow_tools = {f"flow_{f['id']}": _build_flow_tool(f, executor) for f in active_flows}
```

(`agent_runner=self` — the same `AgentRunner` instance already running this flow's owning agent can invoke any other agent, including itself; see the Global Constraints note on recursion being out of scope.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agent_runner_flows.py -v`
Expected: all PASS, no regressions in the rest of the file.

- [ ] **Step 5: Write the failing test for `agents.py`'s `/test` endpoint**

In `tests/unit/test_agents_flows_api.py`, add `patch` to the existing import line (`from unittest.mock import AsyncMock, MagicMock, patch`), then append:

```python
class TestTestFlowEndpointAgentNode:
    async def test_agent_node_in_a_tested_flow_calls_the_agent(self, app_client, _mock_state, monkeypatch):
        _mock_state.get_agent = AsyncMock(return_value={
            "id": 99, "name": "Redactor", "system_prompt": "p", "allowed_tools": "none",
        })
        _mock_state.get_agent_knowledge = AsyncMock(return_value=[])
        _mock_state.get_agent_flows = AsyncMock(return_value=[])

        fake_brain = MagicMock()
        fake_brain.llm_router = MagicMock()
        fake_brain.tool_registry = MagicMock()
        fake_brain.memory = MagicMock()
        fake_brain.event_bus = MagicMock()
        fake_brain.skill_manager = None
        monkeypatch.setattr(_state, "brain", fake_brain)

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                pass

            async def process_message(self, **kwargs):
                return "respuesta del agente: " + kwargs["content"]

        graph = _json.dumps({
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": [{"name": "texto", "type": "string", "required": True}]}},
                {"id": "agent1", "type": "agent", "config": {"agent_id": 99, "message": "{{texto}}"}},
                {"id": "end", "type": "end", "config": {"template": "{{agent1}}"}},
            ],
            "edges": [
                {"from": "start", "to": "agent1", "fromHandle": "default"},
                {"from": "agent1", "to": "end", "fromHandle": "default"},
            ],
        })

        with patch("openacm.core.brain.Brain", _FakeBrain):
            async with app_client as ac:
                resp = await ac.post(
                    "/api/agents/42/flows/7/test",
                    json={"params": {"texto": "hola"}, "graph_json": graph},
                )
        assert resp.status_code == 200
        assert resp.json()["result"] == "respuesta del agente: hola"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/unit/test_agents_flows_api.py::TestTestFlowEndpointAgentNode -v`
Expected: FAIL — `test_agent_flow` builds `FlowExecutor(get_connection=get_connection)` with no `get_agent`/`agent_runner`, so the response's `error` is `True` and `result` is the "No agent lookup/runner configured" error string, not `200` with the expected text (the assertion on `resp.json()["result"]` fails).

- [ ] **Step 7: Wire `get_agent`/`agent_runner` in the `/test` endpoint**

In `src/openacm/web/routers/agents.py`, change (currently lines 275-279):

```python
        async def get_connection(connection_id: int):
            return await _state.database.get_connection(connection_id)

        executor = FlowExecutor(get_connection=get_connection)
        result, outputs = await executor.run(graph, test_params)
```

to:

```python
        async def get_connection(connection_id: int):
            return await _state.database.get_connection(connection_id)

        agent_runner = None
        get_agent = None
        if _state.brain:
            from openacm.core.agent_runner import AgentRunner

            agent_runner = AgentRunner(
                llm_router=_state.brain.llm_router, tool_registry=_state.brain.tool_registry,
                memory=_state.brain.memory, event_bus=_state.brain.event_bus,
                database=_state.database, skill_manager=_state.brain.skill_manager,
            )

            async def get_agent(agent_id: int):
                return await _state.database.get_agent(agent_id)

        executor = FlowExecutor(get_connection=get_connection, get_agent=get_agent, agent_runner=agent_runner)
        result, outputs = await executor.run(graph, test_params)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/unit/test_agents_flows_api.py -v`
Expected: all PASS, no regressions in the rest of the file.

- [ ] **Step 9: Write the failing test for the webhook connector trigger route**

In `tests/unit/test_webhooks_router.py`, add `patch` to the existing `from unittest.mock import AsyncMock, MagicMock` import (making it `AsyncMock, MagicMock, patch`), then append:

```python
AGENT_FLOW_GRAPH = json.dumps({
    "nodes": [
        {"id": "start", "type": "start", "config": {"parameters": []}},
        {"id": "agent1", "type": "agent", "config": {"agent_id": 99, "message": "{{body.matricula}}"}},
        {"id": "end", "type": "end", "config": {"template": "{{agent1}}"}},
    ],
    "edges": [
        {"from": "start", "to": "agent1", "fromHandle": "default"},
        {"from": "agent1", "to": "end", "fromHandle": "default"},
    ],
})


class TestAgentNodeThroughWebhook:
    async def test_connector_flow_with_an_agent_node_calls_the_agent(self, app_client, _mock_state, monkeypatch):
        _mock_state.get_flow.return_value = {"id": 7, "graph_json": AGENT_FLOW_GRAPH}
        _mock_state.get_agent = AsyncMock(return_value={
            "id": 99, "name": "Redactor", "system_prompt": "p", "allowed_tools": "none",
        })
        _mock_state.get_agent_knowledge = AsyncMock(return_value=[])
        _mock_state.get_agent_flows = AsyncMock(return_value=[])

        fake_brain = MagicMock()
        fake_brain.llm_router = MagicMock()
        fake_brain.tool_registry = MagicMock()
        fake_brain.memory = MagicMock()
        fake_brain.event_bus = MagicMock()
        fake_brain.skill_manager = None
        monkeypatch.setattr(_state, "brain", fake_brain)

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                pass

            async def process_message(self, **kwargs):
                return "hola " + kwargs["content"]

        with patch("openacm.core.brain.Brain", _FakeBrain):
            async with app_client as ac:
                resp = await ac.post(
                    "/api/webhooks/pagos",
                    headers={"Authorization": "Bearer s3cr3t"},
                    json={"matricula": "511659"},
                )
        assert resp.status_code == 200
        assert resp.json()["result"] == "hola 511659"
```

- [ ] **Step 10: Run test to verify it fails**

Run: `pytest tests/unit/test_webhooks_router.py::TestAgentNodeThroughWebhook -v`
Expected: FAIL — `trigger_connector` builds a bare `FlowExecutor()`, so the response is `502` with the "No agent lookup/runner configured" error, not `200`.

- [ ] **Step 11: Wire `get_agent`/`agent_runner` in the webhook trigger route**

In `src/openacm/web/routers/webhooks.py`, change (currently lines 124-126):

```python
        start = time.monotonic()
        executor = FlowExecutor()
        result, _outputs = await executor.run(graph, {"headers": dict(request.headers), "body": body})
```

to:

```python
        start = time.monotonic()

        agent_runner = None
        get_agent = None
        if _state.brain:
            from openacm.core.agent_runner import AgentRunner

            agent_runner = AgentRunner(
                llm_router=_state.brain.llm_router, tool_registry=_state.brain.tool_registry,
                memory=_state.brain.memory, event_bus=_state.brain.event_bus,
                database=_state.database, skill_manager=_state.brain.skill_manager,
            )

            async def get_agent(agent_id: int):
                return await _state.database.get_agent(agent_id)

        executor = FlowExecutor(get_agent=get_agent, agent_runner=agent_runner)
        result, _outputs = await executor.run(graph, {"headers": dict(request.headers), "body": body})
```

- [ ] **Step 12: Run test to verify it passes**

Run: `pytest tests/unit/test_webhooks_router.py -v`
Expected: all PASS, no regressions in the rest of the file.

- [ ] **Step 13: Run the full backend suite and commit**

Run: `pytest -q`
Expected: no new failures anywhere in the suite (the 7 pre-existing, unrelated `gmail_classifier` sqlite-column-mismatch errors — see `tests/unit/plugins/gmail_classifier/test_thread_endpoints.py` — are already red before this change and are out of scope here).

```bash
git add src/openacm/core/agent_runner.py src/openacm/web/routers/agents.py src/openacm/web/routers/webhooks.py \
        tests/unit/test_agent_runner_flows.py tests/unit/test_agents_flows_api.py tests/unit/test_webhooks_router.py
git commit -m "feat(flows): wire the agent node's dependencies into flow-tool, test, and webhook-connector executors"
```

---

## Task 3: Frontend — Agent node UI

**Files:**
- Modify: `frontend/components/flow-editor/node-types.tsx`
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: the `agent`/`message` config shape and `default`/`message` handle ids from Task 1; `useAgents()` from `frontend/hooks/use-agents.ts` (already exists — returns `Agent[]` with `id`/`name`).
- Produces: nothing for a later task — this is the last task in the plan.

- [ ] **Step 1: Add the `agent` node type to `node-types.tsx`'s tables**

In `frontend/components/flow-editor/node-types.tsx`, add to `NODE_CATEGORY` (line 14, after `woocommerce: 'integration',`):

```typescript
  agent: 'integration',
```

Add to the handle-shape comment block (after the `woocommerce:` line, around line 47) for documentation parity with the backend table:

```typescript
//   agent:        target "default" -> flow; target "message"      -> data;
//                 source "default" -> flow (this node's whole output is
//                 the agent's text response)
```

Add to `NODE_DESCRIPTIONS` (line 145, after the `woocommerce:` entry):

```typescript
  agent: 'Invoca a un Agente de OpenACM (LLM) con un mensaje y expone su respuesta de texto al resto del flujo.',
```

- [ ] **Step 2: Add the `AgentNode` component**

In `frontend/components/flow-editor/node-types.tsx`, add a new component right after `WooCommerceNode` (after its closing `}` around line 353):

```typescript
export function AgentNode({ id, data, selected }: NodeProps) {
  const targetConnections = useNodeConnections({ id, handleType: 'target' });
  const messageWired = targetConnections.some(c => c.targetHandle === 'message');
  const flowIn = pinProps('agent', 'default', 'target', 'nodo anterior');
  const flowOut = pinProps('agent', 'default', 'source', 'siguiente nodo');
  return (
    <NodeCard type="agent" icon="🤖" title="Agente" selected={selected}>
      <MergeBadge id={id} />
      <div style={{ color: 'var(--acm-fg-4)' }}>{data.agent_id ? `Agente #${data.agent_id}` : '(sin agente)'}</div>
      <PinRow nodeType="agent" handleId="message" handleKind="target" label="message" literalPreview={messageWired || !data.message ? undefined : truncate(String(data.message))} />
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      <Handle type="source" position={Position.Bottom} id="default" style={flowOut.style} title={flowOut.title} />
    </NodeCard>
  );
}
```

Register it in `NODE_TYPES` (line 401, after `woocommerce: WooCommerceNode,`):

```typescript
  agent: AgentNode,
```

- [ ] **Step 3: Add the palette entry and default config in `FlowCanvas.tsx`**

In `frontend/components/flow-editor/FlowCanvas.tsx`, change `NODE_CATEGORIES` (line 419) from:

```typescript
  { label: 'INTEGRACIONES', types: ['http', 'woocommerce'] },
```

to:

```typescript
  { label: 'INTEGRACIONES', types: ['http', 'woocommerce', 'agent'] },
```

Change `NODE_LABELS` (lines 423-426) to add:

```typescript
  http: '🌐 HTTP Request', woocommerce: '🛒 WooCommerce', agent: '🤖 Agente', set: '💾 Guardar (Set)', get: '📤 Obtener (Get)',
```

Add to `addNodeAt`'s `defaults` map (line 619, after `woocommerce: { connection_id: null, search_term: '' },`):

```typescript
      agent: { agent_id: null, message: '' },
```

- [ ] **Step 4: Fetch the agents list and add a ref for the message field**

Add the import (alongside the existing `useAgentConnections` import at line 11):

```typescript
import { useAgents } from '@/hooks/use-agents';
```

Add the hook call and a ref, near the existing `useAgentConnections(agentId)` call (around line 465):

```typescript
  const { data: agents } = useAgents();
```

Add a ref alongside the other field refs (around line 463, after `const templateRef = useRef<HTMLTextAreaElement>(null);`):

```typescript
  const agentMessageRef = useRef<HTMLTextAreaElement>(null);
```

- [ ] **Step 5: Add the config panel block**

In `frontend/components/flow-editor/FlowCanvas.tsx`, add a new block right after the `{selectedNode.type === 'woocommerce' && (...)}` block closes (after line 1114's `)}`):

```typescript
          {selectedNode.type === 'agent' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Agente</div>
              <label>Agente a invocar</label>
              <select
                className="acm-input w-full mb-2"
                value={String(selectedNode.data.agent_id ?? '')}
                onChange={e => updateSelectedNodeData({ agent_id: Number(e.target.value) })}
              >
                <option value="">Seleccionar...</option>
                {(agents || []).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
              <label>Mensaje</label>
              <VariablePicker
                nodeId={selectedNode.id}
                nodes={nodes}
                edges={edges}
                outputs={testOutputs}
                targetRef={agentMessageRef}
                value={String(selectedNode.data.message || '')}
                onInsert={v => updateSelectedNodeData({ message: v })}
              />
              <ConnectableField nodeId={selectedNode.id} fieldName="message" edges={edges} setEdges={setEdges}>
                <textarea ref={agentMessageRef} className="acm-input w-full" rows={3} value={String(selectedNode.data.message || '')} onChange={e => updateSelectedNodeData({ message: e.target.value })} />
                <TemplatePreview value={String(selectedNode.data.message || '')} params={testParams} outputs={testOutputs} />
              </ConnectableField>
            </>
          )}
```

- [ ] **Step 6: Manual verification**

Run the frontend dev server (`npm run dev` in `frontend/`), open an agent's flow editor, right-click the canvas and confirm "🤖 Agente" appears under INTEGRACIONES in the node menu. Add one, select it, confirm the Inspector shows an "Agente a invocar" dropdown populated with the account's existing agents and a "Mensaje" field with the variable picker. Wire a Start parameter into the message field, wire the node's flow-in/flow-out into a small Start → Agente → Final graph, save, and run "Probar flujo" — confirm it returns the target agent's actual response text and that `{{agent1}}` in the End node's template resolves to that text. Confirm no console errors.

- [ ] **Step 7: Build and commit**

```bash
cd frontend
npm run build
```
Expected: build succeeds with no new TypeScript errors.

```bash
cd ..
git add frontend/components/flow-editor/node-types.tsx frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(flow-editor): add Agent node UI"
```

---

## Final verification

- [ ] Run the full backend test suite: `pytest -q` from the repo root — no regressions beyond the 7 pre-existing, unrelated `gmail_classifier` errors.
- [ ] Run `npm run build` in `frontend/` — no new errors.
- [ ] Manually build a flow with Start → Agent → End against a real second agent on a running instance, trigger it via "Probar flujo", and confirm the End node's output is that agent's real response.
