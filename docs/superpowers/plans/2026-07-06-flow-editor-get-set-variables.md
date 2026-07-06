# Flow Editor Get/Set Variables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the just-shipped inline "Variable" node with an Unreal-style system: a Variables panel outside the canvas, `Get`/`Set` nodes created by dragging a variable onto the canvas (or by promoting a dragged-out connection), and named output pins on every node type.

**Architecture:** The backend barely changes — `FlowExecutor`'s existing `outputs` dict already resolves values by name/id independent of graph edges, so the inline "Variable" node's logic becomes `Set`'s logic verbatim (a rename), and `Get` is a small addition (no input, reads whatever's currently stored under its declared name). Everything else is frontend: `node-types.tsx` gets named pin labels plus `SetNode`/`GetNode` replacing `VariableNode`, and `FlowCanvas.tsx` gets a new Variables panel, drag-from-panel-to-canvas, and drag-a-connection-to-empty-space ("promote to variable").

**Tech Stack:** Python 3.13, pytest + pytest-asyncio (auto mode), Next.js/React/TypeScript, `@xyflow/react`.

## Global Constraints

- **This plan REPLACES the inline `variable` node type entirely** (from `docs/superpowers/plans/2026-07-05-flow-editor-unreal-style.md`, already merged) — it does not coexist with `Set`/`Get`. Every reference to `variable` as a node type (backend and frontend) is removed, not left dangling alongside the new types.
- **No new backend endpoint or database table for variables.** The Variables panel's list is a pure projection of the current graph's `Set`/`Get` node names — computed client-side from `nodes` state, never persisted separately. Saving the flow already persists this (the `Set`/`Get` nodes themselves are part of `graph_json`).
- **No second named data pin on any existing node type in this plan** — HTTP, Conditional, and WooCommerce each still produce exactly one value; they just get a *visible label* on the pin that already exists (`response`, `result`, `result` respectively). Adding more pins to any single node type later is a per-type, additive change, not something this plan needs to anticipate further.
- **No change to the linear-chain-plus-one-branch-point topology or to execution order.** `Set` sits in the chain exactly like the old `Variable` node did (one incoming edge, one outgoing edge). `Get` has no incoming edge at all — it's a read, not a step that transforms a value flowing through it — but it's still IN the linear chain for ordering purposes (it has exactly one outgoing edge to whatever comes next, same as `Start`).
- **Frontend tasks in this plan (2-5) all meaningfully change the canvas's visual/interaction behavior and each require an actual manual browser verification, not just `tsc --noEmit`.** Implementers must NOT attempt to stand up a dev server/browser themselves — write code, verify with `tsc --noEmit`, commit, and explicitly report manual verification as outstanding. The controller coordinates the actual verification with the human user afterward (this exact anti-pattern — an implementer trying to stand up a full local environment — caused a 30+-minute stall earlier in this project's history that required forcibly stopping the subagent).

---

### Task 1: Backend — rename `variable` to `set`, add `get`

**Files:**
- Modify: `src/openacm/core/flow_executor.py`
- Test: `tests/unit/test_flow_executor.py`

**Interfaces:**
- Consumes: the existing `run()` loop, `edges_by_target`/`edges_by_source` (already built).
- Produces: the `"variable"` loop-level case is renamed to `"set"` (identical logic, only the type string changes). A new `"get"` loop-level case: no incoming-edge lookup needed — reads `outputs.get(node["config"]["name"])` and, if a value was found, also stores it under `outputs[node["id"]]` (so `{{get_node_id}}` resolves the same way `{{set_node_id}}` already does for the renamed `set` case). If the name was never set, nothing is written for this node's own id either — falls through to the exact same missing-marker behavior `substitute_templates` already provides for any absent key.

- [ ] **Step 1: Write the failing tests**

First, update the EXISTING `TestVariableNode` test class in `tests/unit/test_flow_executor.py` (from the prior plan) to use `"set"` instead of `"variable"` as the node type in all four of its test graphs — find `_variable_graph` and the three inline graphs inside `TestVariableNode`'s methods, and change every `"type": "variable"` to `"type": "set"`. Rename the class from `TestVariableNode` to `TestSetNode` and the helper function from `_variable_graph` to `_set_graph`.

Then append a new test class for `Get`:

```python
def _get_graph(get_name="mi_variable"):
    """Start -> HTTP -> Set(name=get_name) -> Get(name=get_name) -> End(references the Get node's own id)."""
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": []}},
            {"id": "src1", "type": "http", "config": {"url": "https://example.com", "method": "GET"}},
            {"id": "set1", "type": "set", "config": {"name": get_name}},
            {"id": "get1", "type": "get", "config": {"name": get_name}},
            {"id": "end", "type": "end", "config": {"template": "Por id del Get: {{get1}}"}},
        ],
        "edges": [
            {"from": "start", "to": "src1", "fromHandle": "default"},
            {"from": "src1", "to": "set1", "fromHandle": "default"},
            {"from": "set1", "to": "get1", "fromHandle": "default"},
            {"from": "get1", "to": "end", "fromHandle": "default"},
        ],
    }


class TestGetNode:
    async def test_get_reads_a_previously_set_value_via_its_own_node_id(self):
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "hola desde get"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(_get_graph(), params={})

        assert result == "Por id del Get: hola desde get"

    async def test_get_by_friendly_name_directly_also_works(self):
        graph = _get_graph()
        graph["nodes"][4]["config"]["template"] = "Por nombre: {{mi_variable}}"
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "hola desde get"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(graph, params={})

        assert result == "Por nombre: hola desde get"

    async def test_get_before_any_set_with_that_name_resolves_to_missing_marker(self):
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "get1", "type": "get", "config": {"name": "nunca_seteada"}},
                {"id": "end", "type": "end", "config": {"template": "{{get1}}"}},
            ],
            "edges": [
                {"from": "start", "to": "get1", "fromHandle": "default"},
                {"from": "get1", "to": "end", "fromHandle": "default"},
            ],
        }
        executor = FlowExecutor()
        result = await executor.run(graph, params={})
        assert result == "[missing: get1]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestGetNode -v`
Expected: FAIL — `"get"` isn't handled by `run()` yet.

Also run: `pytest tests/unit/test_flow_executor.py::TestSetNode -v`
Expected: FAIL — `"set"` isn't handled by `run()` yet (still says `"variable"` in the executor).

- [ ] **Step 3: Implement**

In `src/openacm/core/flow_executor.py`, find the existing `variable` case:

```python
            if node["type"] == "variable":
                source_id = edges_by_target.get(node["id"])
                if source_id and source_id in outputs:
                    value = outputs[source_id]
                    outputs[node["id"]] = value
                    outputs[node["config"]["name"]] = value
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue
```

Replace `"variable"` with `"set"` (no other change — same logic, just the type string):

```python
            if node["type"] == "set":
                source_id = edges_by_target.get(node["id"])
                if source_id and source_id in outputs:
                    value = outputs[source_id]
                    outputs[node["id"]] = value
                    outputs[node["config"]["name"]] = value
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue
```

Add a `get` case right after it:

```python
            if node["type"] == "get":
                name = node["config"]["name"]
                if name in outputs:
                    outputs[node["id"]] = outputs[name]
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests, including the renamed `TestSetNode` and new `TestGetNode`)

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest -q`
Expected: no new failures beyond the known pre-existing baseline (7 errors in `gmail_classifier`, plus possibly 5 date-dependent failures in `test_gmail_summary.py` if the wall-clock date has rolled over — both unrelated, do not fix).

- [ ] **Step 6: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): rename Variable node to Set, add Get node"
```

---

### Task 2: Frontend — replace `VariableNode` with `SetNode`/`GetNode`, add named pin labels

**Files:**
- Modify: `frontend/components/flow-editor/node-types.tsx`
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: `NODE_CATEGORY`/`CATEGORY_COLORS` (already exist), `--acm-node-data` CSS var (already exists — reused for both `set` and `get`, both in the "Datos" category).
- Produces: `SetNode`/`GetNode` components replacing `VariableNode` in `NODE_TYPES`; `NODE_CATEGORY` maps `set`/`get` → `'data'` (no more `variable` key); every node's output `Handle` gets a small text label naming its pin (`response` for HTTP, `result` for Conditional and WooCommerce, `value` for Set and Get); `FlowCanvas.tsx`'s `addNodeAt` defaults, `NODE_CATEGORIES`, `NODE_LABELS`, the Inspector's per-type panel sections, and `availableVariableNames` are all updated to know about `set`/`get` instead of `variable`.

This is the largest task in this plan — it touches two files together as one atomic replacement (there is no working intermediate state where `variable` is half-removed). It requires manual browser verification before being marked complete.

- [ ] **Step 1: Replace `node-types.tsx`'s `VariableNode` with `SetNode`/`GetNode`, add pin labels to every type**

Replace the entire contents of `frontend/components/flow-editor/node-types.tsx`:

```typescript
'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';

export type NodeCategory = 'flow' | 'logic' | 'integration' | 'data';

export const CATEGORY_COLORS: Record<NodeCategory, string> = {
  flow: 'var(--acm-accent)',
  logic: 'var(--acm-node-logic)',
  integration: 'var(--acm-info)',
  data: 'var(--acm-node-data)',
};

export const NODE_CATEGORY: Record<string, NodeCategory> = {
  start: 'flow',
  end: 'flow',
  conditional: 'logic',
  http: 'integration',
  woocommerce: 'integration',
  set: 'data',
  get: 'data',
};

function baseStyleFor(type: string): React.CSSProperties {
  return {
    padding: '8px 12px', borderRadius: 8, fontSize: 11,
    background: 'var(--acm-elev)', border: `1px solid ${CATEGORY_COLORS[NODE_CATEGORY[type]]}`,
    color: 'var(--acm-fg-2)', minWidth: 140,
  };
}

const idStyle: React.CSSProperties = {
  fontFamily: 'monospace', fontSize: 10, color: 'var(--acm-accent)', marginTop: 4,
  userSelect: 'all', cursor: 'text',
};

const pinLabelStyle: React.CSSProperties = {
  fontSize: 9, color: 'var(--acm-fg-4)', marginTop: 2,
};

export function StartNode({ data }: NodeProps) {
  return (
    <div style={baseStyleFor('start')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.flow }}>▶ Inicio</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{(data.parameters as any[] || []).length} parámetro(s)</div>
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function HttpNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('http')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.integration }}>🌐 HTTP Request</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.method || 'GET')} {String(data.url || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: response</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function ConditionalNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('conditional')}>
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

export function WooCommerceNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('woocommerce')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.integration }}>🛒 WooCommerce</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.search_term || '')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: result</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function SetNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('set')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.data }}>💾 Guardar (Set)</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

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

export function EndNode({ data }: NodeProps) {
  return (
    <div style={baseStyleFor('end')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.flow }}>■ Final</div>
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
  set: SetNode,
  get: GetNode,
  end: EndNode,
};
```

Note `GetNode` has only a `source` Handle (no `target`) — it never receives an incoming data wire, matching the spec ("no input handle").

- [ ] **Step 2: Update `FlowCanvas.tsx`'s `availableVariableNames` to look for `set` nodes**

Find:

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
    const name = node?.type === 'variable' ? (node.data.name as string | undefined) : undefined;
    if (name) names.push(name);
    currentId = incomingBySource[currentId];
  }
  return names;
}
```

Change the one line that checks the node type — everything else (the backward-walk mechanics) is unchanged, since a `Set` node is exactly what the old `Variable` node was for this purpose (a `Get` node doesn't *declare* a name, it only *reads* one, so it's correctly excluded from this list — referencing a name that's already been Set doesn't need to go through a Get node at all):

```typescript
    const name = node?.type === 'set' ? (node.data.name as string | undefined) : undefined;
```

- [ ] **Step 3: Update `NODE_CATEGORIES` and `NODE_LABELS`**

Find:

```typescript
const NODE_CATEGORIES: Array<{ label: string; types: Array<keyof typeof NODE_TYPES> }> = [
  { label: 'FLUJO', types: ['start', 'end'] },
  { label: 'LÓGICA', types: ['conditional'] },
  { label: 'INTEGRACIONES', types: ['http', 'woocommerce'] },
  { label: 'DATOS', types: ['variable'] },
];

const NODE_LABELS: Record<keyof typeof NODE_TYPES, string> = {
  start: '▶ Inicio', end: '■ Final', conditional: '◆ Condicional',
  http: '🌐 HTTP Request', woocommerce: '🛒 WooCommerce', variable: '📦 Variable',
};
```

Replace with:

```typescript
const NODE_CATEGORIES: Array<{ label: string; types: Array<keyof typeof NODE_TYPES> }> = [
  { label: 'FLUJO', types: ['start', 'end'] },
  { label: 'LÓGICA', types: ['conditional'] },
  { label: 'INTEGRACIONES', types: ['http', 'woocommerce'] },
  { label: 'DATOS', types: ['set', 'get'] },
];

const NODE_LABELS: Record<keyof typeof NODE_TYPES, string> = {
  start: '▶ Inicio', end: '■ Final', conditional: '◆ Condicional',
  http: '🌐 HTTP Request', woocommerce: '🛒 WooCommerce', set: '💾 Guardar (Set)', get: '📤 Obtener (Get)',
};
```

- [ ] **Step 4: Update `addNodeAt`'s defaults**

Find:

```typescript
  const addNodeAt = (type: keyof typeof NODE_TYPES, x: number, y: number) => {
    const defaults: Record<string, Record<string, unknown>> = {
      start: { parameters: [] },
      http: { url: '', method: 'GET', headers: {}, body: '' },
      conditional: { field: '', operator: 'contains', value: '' },
      woocommerce: { connection_id: null, search_term: '' },
      variable: { name: '' },
      end: { template: '' },
    };
    setNodes(nds => [...nds, { id: nextNodeId(type), type, position: { x, y }, data: defaults[type] }]);
  };
```

Replace the `defaults` object's `variable` entry:

```typescript
  const addNodeAt = (type: keyof typeof NODE_TYPES, x: number, y: number) => {
    const defaults: Record<string, Record<string, unknown>> = {
      start: { parameters: [] },
      http: { url: '', method: 'GET', headers: {}, body: '' },
      conditional: { field: '', operator: 'contains', value: '' },
      woocommerce: { connection_id: null, search_term: '' },
      set: { name: '' },
      get: { name: '' },
      end: { template: '' },
    };
    setNodes(nds => [...nds, { id: nextNodeId(type), type, position: { x, y }, data: defaults[type] }]);
  };
```

- [ ] **Step 5: Replace the Inspector's `variable` panel section with `set`/`get` sections**

Find:

```typescript
          {selectedNode.type === 'variable' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Variable</div>
              <label>Nombre</label>
              <input
                className="acm-input w-full"
                placeholder="ej: resultado_busqueda"
                value={String(selectedNode.data.name || '')}
                onChange={e => updateSelectedNodeData({ name: e.target.value })}
              />
            </>
          )}
```

Replace it with two sections, one per type:

```typescript
          {selectedNode.type === 'set' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Guardar (Set)</div>
              <label>Nombre de la variable</label>
              <input
                className="acm-input w-full"
                placeholder="ej: resultado_busqueda"
                value={String(selectedNode.data.name || '')}
                onChange={e => updateSelectedNodeData({ name: e.target.value })}
              />
            </>
          )}
          {selectedNode.type === 'get' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Obtener (Get)</div>
              <label>Nombre de la variable</label>
              <input
                className="acm-input w-full"
                placeholder="ej: resultado_busqueda"
                value={String(selectedNode.data.name || '')}
                onChange={e => updateSelectedNodeData({ name: e.target.value })}
              />
            </>
          )}
```

- [ ] **Step 6: Verify with `tsc`**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 7: Manual browser verification (required for this task)**

Using a fresh dev server instance you're sure isn't someone else's active session: open an agent's Flujos tab, open a flow, right-click and confirm the "DATOS" category now shows "💾 Guardar (Set)" and "📤 Obtener (Get)" instead of the old "📦 Variable" entry. Create one of each and confirm they render with the cyan Datos-category color, their own `{{id}}` reference, and a "salida: value" label. Confirm HTTP/Conditional/WooCommerce nodes now show their new "salida: response"/"salida: result" labels. Select a Set node and confirm its Inspector panel shows a "Nombre de la variable" field; same for Get. Wire an HTTP node into a Set node, name it, then wire a Get node with the same name into an End node referencing `{{get_node_id}}` (or the friendly name) in its template, save, and use "Probar flujo" to confirm the value round-trips through Set → Get correctly.

- [ ] **Step 8: Commit**

```bash
git add frontend/components/flow-editor/node-types.tsx frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): replace inline Variable node with Set/Get nodes, add named output pin labels"
```

---

### Task 3: Frontend — Variables panel (derived list + "+ Nueva variable")

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: `nodes` state (already exists), `nextNodeId`/`addNodeAt` (already exist, from Task 2/prior plan).
- Produces: a new left-side "Variables" panel section listing every distinct `name` currently used by any `set`/`get` node in `nodes`, with a "+ Nueva variable" button that creates an unwired `set` node (following this file's existing default-naming convention — matching how `FlowsTab`'s "+ Nuevo flujo" creates a row named "Nuevo flujo" rather than prompting, this creates a `set` node named `variable_N` where `N` increments, letting the user rename it via the Inspector afterward — no native browser `prompt()` dialog, consistent with the rest of this codebase).

This task requires an actual manual browser verification before being marked complete.

- [ ] **Step 1: Add the derived variable-name list and a name-counter ref**

Inside `FlowCanvasInner`, alongside the other `useRef`/state declarations near the top, add:

```typescript
  const variableNameCounterRef = useRef(0);

  const variableNames = useMemo(() => {
    const names = new Set<string>();
    for (const n of nodes) {
      if ((n.type === 'set' || n.type === 'get') && typeof n.data.name === 'string' && n.data.name) {
        names.add(n.data.name);
      }
    }
    return Array.from(names).sort();
  }, [nodes]);
```

- [ ] **Step 2: Add the "create new variable" handler**

Add this function near `addNodeAt` (which it reuses):

```typescript
  const addNewVariable = () => {
    variableNameCounterRef.current += 1;
    const name = `variable_${variableNameCounterRef.current}`;
    const x = 100;
    const y = 100 + nodes.length * 90;
    setNodes(nds => [...nds, { id: nextNodeId('set'), type: 'set', position: { x, y }, data: { name } }]);
  };
```

- [ ] **Step 3: Render the Variables panel**

In the return block's left column, find the existing structure (right after the "Guardar flujo" button, before the "Probar flujo" section):

```typescript
        <div className="text-[10px]" style={{ color: 'var(--acm-fg-4)' }}>Clic derecho en el lienzo para agregar un nodo</div>
        <button onClick={handleSave} className="btn-primary text-[11px] px-2 py-1 mt-2">Guardar flujo</button>
        <div className="mt-2 pt-2" style={{ borderTop: '1px solid var(--acm-border)' }}>
          <div className="text-[11px] mb-1" style={{ color: 'var(--acm-fg-4)' }}>Probar flujo</div>
```

Insert a new Variables section between "Guardar flujo" and "Probar flujo":

```typescript
        <div className="text-[10px]" style={{ color: 'var(--acm-fg-4)' }}>Clic derecho en el lienzo para agregar un nodo</div>
        <button onClick={handleSave} className="btn-primary text-[11px] px-2 py-1 mt-2">Guardar flujo</button>
        <div className="mt-2 pt-2" style={{ borderTop: '1px solid var(--acm-border)' }}>
          <div className="label text-[var(--acm-fg-4)] mb-1">Variables</div>
          {variableNames.length === 0 ? (
            <div className="text-[10px] mb-1" style={{ color: 'var(--acm-fg-4)' }}>Ninguna todavía</div>
          ) : (
            variableNames.map(name => (
              <div
                key={name}
                className="text-[11px] px-2 py-1 mb-1 rounded"
                style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-node-data)', color: 'var(--acm-fg-2)', cursor: 'grab' }}
              >
                {name}
              </div>
            ))
          )}
          <button onClick={addNewVariable} className="btn-secondary w-full text-[11px] px-2 py-1">+ Nueva variable</button>
        </div>
        <div className="mt-2 pt-2" style={{ borderTop: '1px solid var(--acm-border)' }}>
          <div className="text-[11px] mb-1" style={{ color: 'var(--acm-fg-4)' }}>Probar flujo</div>
```

(The `cursor: 'grab'` style anticipates Task 4's drag behavior — this task only renders the list, dragging is wired in the next task.)

- [ ] **Step 4: Verify with `tsc`**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5: Manual browser verification (required for this task)**

Open a flow, confirm the new "Variables" section appears between "Guardar flujo" and "Probar flujo" showing "Ninguna todavía". Click "+ Nueva variable" and confirm a new `set` node named `variable_1` appears on the canvas AND the panel's list now shows `variable_1`. Click "+ Nueva variable" again and confirm it's `variable_2` (the counter increments) and both names are listed. Rename one via its Inspector panel and confirm the panel list updates to reflect the new name.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): Variables panel — derived list of Set/Get names + new-variable creation"
```

---

### Task 4: Frontend — drag a variable from the panel onto the canvas → Get/Set choice

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: `variableNames` (Task 3), `addNodeAt`/`screenToFlowPosition` (already exist).
- Produces: dragging a Variables-panel entry onto the canvas and releasing opens a small "Obtener / Guardar" choice menu at the drop position; picking one creates that node type there with `name` pre-filled to the dragged variable's name.

This task requires an actual manual browser verification before being marked complete.

- [ ] **Step 1: Make the variable list items draggable**

In the Variables panel block from Task 3, update the per-name `<div>` to be draggable, storing the name being dragged via the standard HTML5 drag-and-drop data transfer:

```typescript
              <div
                key={name}
                draggable
                onDragStart={e => e.dataTransfer.setData('application/flow-variable-name', name)}
                className="text-[11px] px-2 py-1 mb-1 rounded"
                style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-node-data)', color: 'var(--acm-fg-2)', cursor: 'grab' }}
              >
                {name}
              </div>
```

- [ ] **Step 2: Add drop-target state and handlers on the canvas wrapper**

Add new state alongside `contextMenu`/`contextMenuSearch`:

```typescript
  const [variableDropMenu, setVariableDropMenu] = useState<{ x: number; y: number; flowX: number; flowY: number; name: string } | null>(null);
```

Add these two handlers near `onPaneContextMenu`:

```typescript
  const onCanvasDragOver = useCallback((event: React.DragEvent) => {
    if (event.dataTransfer.types.includes('application/flow-variable-name')) {
      event.preventDefault();
    }
  }, []);

  const onCanvasDrop = useCallback((event: React.DragEvent) => {
    const name = event.dataTransfer.getData('application/flow-variable-name');
    if (!name) return;
    event.preventDefault();
    const bounds = canvasWrapperRef.current?.getBoundingClientRect();
    if (!bounds) return;
    const flowPosition = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    setVariableDropMenu({
      x: event.clientX - bounds.left,
      y: event.clientY - bounds.top,
      flowX: flowPosition.x,
      flowY: flowPosition.y,
      name,
    });
  }, [screenToFlowPosition]);
```

- [ ] **Step 3: Wire the handlers onto the canvas wrapper div and render the choice menu**

Find the canvas wrapper div:

```typescript
      <div ref={canvasWrapperRef} className="flex-1 relative" style={{ border: '1px solid var(--acm-border)', borderRadius: 8 }}>
```

Add the drag handlers:

```typescript
      <div
        ref={canvasWrapperRef}
        className="flex-1 relative"
        style={{ border: '1px solid var(--acm-border)', borderRadius: 8 }}
        onDragOver={onCanvasDragOver}
        onDrop={onCanvasDrop}
      >
```

Find the existing `onPaneClick` (used to close the right-click context menu) and also close the new drop menu there:

```typescript
          onPaneClick={() => { setSelectedId(null); setContextMenu(null); }}
```

becomes:

```typescript
          onPaneClick={() => { setSelectedId(null); setContextMenu(null); setVariableDropMenu(null); }}
```

Add the choice-menu rendering as a sibling of the existing `{contextMenu && (...)}` block:

```typescript
        {variableDropMenu && (
          <div
            className="absolute z-50 p-2 flex flex-col gap-1"
            style={{ left: variableDropMenu.x, top: variableDropMenu.y, background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', borderRadius: 8, width: 160 }}
          >
            <div className="text-[10px] mb-1" style={{ color: 'var(--acm-fg-4)' }}>{variableDropMenu.name}</div>
            <button
              className="btn-secondary text-[11px] px-2 py-1"
              onClick={() => {
                setNodes(nds => [...nds, { id: nextNodeId('get'), type: 'get', position: { x: variableDropMenu.flowX, y: variableDropMenu.flowY }, data: { name: variableDropMenu.name } }]);
                setVariableDropMenu(null);
              }}
            >
              📤 Obtener (Get)
            </button>
            <button
              className="btn-secondary text-[11px] px-2 py-1"
              onClick={() => {
                setNodes(nds => [...nds, { id: nextNodeId('set'), type: 'set', position: { x: variableDropMenu.flowX, y: variableDropMenu.flowY }, data: { name: variableDropMenu.name } }]);
                setVariableDropMenu(null);
              }}
            >
              💾 Guardar (Set)
            </button>
          </div>
        )}
```

- [ ] **Step 4: Verify with `tsc`**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5: Manual browser verification (required for this task)**

Create a variable via "+ Nueva variable" (or reuse one from an existing Set node). Drag its entry from the Variables panel onto empty canvas space. Confirm a small menu appears at the drop position offering "Obtener (Get)" / "Guardar (Set)". Click "Obtener (Get)" and confirm a new Get node appears at that position with the dragged variable's name already filled in. Repeat, choosing "Guardar (Set)" this time, and confirm a Set node appears instead. Confirm dragging and dropping elsewhere on the canvas (not on the Variables panel) doesn't interfere with normal node-dragging/panning.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): drag a variable from the panel onto the canvas to create a Get/Set node"
```

---

### Task 5: Frontend — "Promote to Variable" (drag a connection to empty space)

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: `@xyflow/react`'s `onConnectEnd` callback, `addNodeAt`-equivalent node creation, `nextNodeId`.
- Produces: dragging a connection from any node's output handle and releasing it on empty canvas space (not landing on another node's handle) creates a new `set` node at the release position, pre-wired from the source, with an auto-generated name (same `variable_N` convention as Task 3 — no native `prompt()` dialog).

**Before implementing:** `@xyflow/react`'s `onConnectEnd` signature and the shape of the connection-state object it receives can vary slightly by version. Before writing this task's code, check the actual installed types: read `frontend/node_modules/@xyflow/react/dist/esm/types/general.d.ts` (or search that package for `onConnectEnd`/`FinalConnectionState`) to confirm the exact parameter shape. The code below is written against the documented v12 shape (`onConnectEnd(event, connectionState)` where `connectionState` has `isValid: boolean`, `fromNode`, `fromHandle`, `toNode`) — if the installed version differs, adapt the field names accordingly rather than guessing further.

This task requires an actual manual browser verification before being marked complete.

- [ ] **Step 1: Add the `onConnectEnd` handler**

Add this inside `FlowCanvasInner`, near `onPaneContextMenu`:

```typescript
  const onConnectEnd = useCallback((event: MouseEvent | TouchEvent, connectionState: { isValid: boolean | null; fromNode: Node | null; fromHandle: { id?: string | null } | null }) => {
    if (connectionState.isValid || !connectionState.fromNode) return; // landed on a real target — nothing to promote
    const bounds = canvasWrapperRef.current?.getBoundingClientRect();
    if (!bounds) return;
    const point = 'changedTouches' in event ? event.changedTouches[0] : event;
    const flowPosition = screenToFlowPosition({ x: point.clientX, y: point.clientY });

    variableNameCounterRef.current += 1;
    const name = `variable_${variableNameCounterRef.current}`;
    const newId = nextNodeId('set');

    setNodes(nds => [...nds, { id: newId, type: 'set', position: flowPosition, data: { name } }]);
    setEdges(eds => [...eds, {
      id: `${connectionState.fromNode!.id}-${newId}-${connectionState.fromHandle?.id || 'default'}`,
      source: connectionState.fromNode!.id,
      target: newId,
      sourceHandle: connectionState.fromHandle?.id || 'default',
    }]);
  }, [screenToFlowPosition]);
```

- [ ] **Step 2: Wire `onConnectEnd` onto `<ReactFlow>`**

Find:

```typescript
          onConnect={onConnect}
          onNodeClick={(_e, node) => setSelectedId(node.id)}
```

Add the new prop:

```typescript
          onConnect={onConnect}
          onConnectEnd={onConnectEnd}
          onNodeClick={(_e, node) => setSelectedId(node.id)}
```

- [ ] **Step 3: Verify with `tsc`**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors. If the `connectionState` parameter type doesn't match what `@xyflow/react` actually exports, `tsc` will report a type mismatch on the `onConnectEnd` prop or inside the handler — adjust the inline type annotation to match the installed package's actual exported type (check `ConnectionState`/`FinalConnectionState` in the package's type definitions) rather than casting past the error.

- [ ] **Step 4: Manual browser verification (required for this task)**

Using a fresh dev server instance: add an HTTP node, start dragging a connection from its output handle, and release the drag on empty canvas space (not on another node). Confirm a new Set node appears at the release position, already wired (a visible edge) from the HTTP node, with an auto-generated `variable_N` name. Confirm the new variable also now appears in the Variables panel (Task 3's derived list). Confirm dragging a connection and releasing it ON a valid node's input handle still behaves as a normal connection (does NOT also create a spurious Set node) — this is the `connectionState.isValid` guard's job, verify it actually works.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): promote a dragged-out connection to a new Set-variable node"
```

---

## Post-plan manual smoke test (end to end)

After all 5 tasks are merged:

1. Build a flow: Start (parameter `producto`) → HTTP node → drag its output connection to empty space, promote it to a Set-variable → rename the auto-generated variable to something meaningful via its Inspector → drag that same variable from the Variables panel onto another spot, choosing "Get" → wire the Get node into an End node whose template references it.
2. Save, then use "Probar flujo" and confirm the value flows through HTTP → Set → Get → End correctly.
3. Confirm the agent's existing "Test this agent" dashboard panel still triggers this flow correctly via the LLM.
4. Confirm no trace of the old inline "Variable" node type remains anywhere in the UI (right-click menu, Inspector, Variables panel) — only Set/Get.
