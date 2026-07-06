# Flow Editor Unreal-Style Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give OpenACM's already-shipped node-flow builder an Unreal Blueprint-style feel: a visual "Variable" node for naming an earlier node's output, category-colored nodes, a right-click node-search menu replacing the static add-node palette, and a polished, better-organized config side panel ("Inspector") with variable-picker dropdowns.

**Architecture:** One small backend addition (a `variable` node type in `FlowExecutor`, handled directly in the main loop since it needs the incoming edge to know which node's output to alias — not through the `_HANDLERS` dispatch table like the other node types). Everything else is frontend-only: `node-types.tsx` gains category-based coloring and a new `VariableNode` component; `FlowCanvas.tsx` gains a right-click context menu (replacing the static palette), a reusable `VariablePicker` dropdown wired into every template-string field, and matching visual polish in the Inspector panel.

**Tech Stack:** Python 3.13, pytest + pytest-asyncio (auto mode), Next.js/React/TypeScript, `@xyflow/react` (already a dependency).

## Global Constraints

- **No change to flow topology.** Still a linear chain with exactly one branch point at a Conditional node. The Variable node is a plain pass-through (one input, one output) — it does not introduce loops, multiple inputs, or rejoined branches.
- **The only backend change in this entire plan** is the `variable` node type in `src/openacm/core/flow_executor.py`. No other node type's behavior changes, `substitute_templates` is unchanged, and the API endpoints/DB layer are untouched.
- **Variable node semantics:** aliases whatever node its single incoming edge comes from. `outputs[node["id"]]` (like every node) AND `outputs[node["config"]["name"]]` (the friendly name) both get set to the same value — the value of the node the Variable node's incoming edge originates from. If two Variable nodes in the same flow share a `name`, the later one silently wins (last-write-wins on a dict key) — this is an authoring mistake for the UI to discourage, not something the interpreter errors on.
- **Node color by category, not by individual type.** Four categories: Flujo (Inicio, Final) → `--acm-accent` (existing), Lógica (Condicional) → new `--acm-node-logic` (violet), Integraciones (HTTP Request, WooCommerce) → `--acm-info` (existing), Datos (Variable) → new `--acm-node-data` (cyan). A centralized `NODE_CATEGORY`/`CATEGORY_COLORS` lookup in `node-types.tsx` — never a per-type hardcoded color.
- **Right-click REPLACES the static palette entirely** — the "+ start"/"+ http"/etc. buttons are removed, not kept alongside the new menu.
- **The Inspector's fields don't change what they store** — same config shape per node type as today (this plan is presentation/organization plus the additive Variable-node case, not a new-fields pass) with one explicit exception: the HTTP node's `body` field already exists in the backend's `_run_http_node` (`cfg.get("body")`) but has never had a UI control — this plan adds that missing textarea, since without it the variable-picker requirement for "HTTP's url/body" (from the approved spec) would have nothing to attach to, and it's a real, useful gap to close. `headers` remains out of scope (not requested, and the backend already defaults it to `{}` safely).
- **Frontend tasks in this plan (2, 3, 4) all meaningfully change the canvas's visual/interaction behavior and each require an actual manual browser verification, not just `tsc --noEmit`.** The base flow-builder plan's final review found that live human testing surfaced 3 real bugs no automated check would have caught — do not skip this a second time for a UI-heavy plan.

---

### Task 1: Backend — `variable` node type in `FlowExecutor`

**Files:**
- Modify: `src/openacm/core/flow_executor.py`
- Test: `tests/unit/test_flow_executor.py`

**Interfaces:**
- Consumes: the existing `run()` loop, `edges_by_source` (already built at the top of `run()`).
- Produces: a new `edges_by_target: dict[str, str]` lookup (built alongside `edges_by_source`, mapping each node id to the id of the ONE node whose edge points at it — safe because the graph is linear + one branch, so every node has exactly one incoming edge). A new `if node["type"] == "variable":` branch in the main loop, handled the same way `"end"` already is (a direct loop-level case, not a `_HANDLERS` entry) — because a Variable node needs the *edge* pointing at it (to know which node's value to alias), not just its own `config`, and `_HANDLERS` entries only ever receive `(self, node, params, outputs)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flow_executor.py`:

```python
def _variable_graph(source_type="http", var_name="mi_variable"):
    """Start -> source_node -> Variable(name=var_name) -> End(template referencing the variable)."""
    source_node = {"id": "src1", "type": source_type, "config": {}}
    if source_type == "http":
        source_node["config"] = {"url": "https://example.com", "method": "GET"}
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": []}},
            source_node,
            {"id": "var1", "type": "variable", "config": {"name": var_name}},
            {"id": "end", "type": "end", "config": {"template": "Valor: {{" + var_name + "}}"}},
        ],
        "edges": [
            {"from": "start", "to": "src1", "fromHandle": "default"},
            {"from": "src1", "to": "var1", "fromHandle": "default"},
            {"from": "var1", "to": "end", "fromHandle": "default"},
        ],
    }


class TestVariableNode:
    async def test_aliases_the_incoming_nodes_output_under_the_declared_name(self):
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
            result = await executor.run(_variable_graph(), params={})

        assert result == "Valor: hola mundo"

    async def test_variable_output_is_also_addressable_by_its_own_node_id(self):
        """{{var1}} (the node's own id) must still work too — the variable
        node is stored under both keys, not just the friendly name."""
        graph = _variable_graph()
        graph["nodes"][3]["config"]["template"] = "Por id: {{var1}}"
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
            result = await executor.run(graph, params={})

        assert result == "Por id: hola mundo"

    async def test_variable_with_no_incoming_edge_aliases_none(self):
        """A Variable node placed directly after Start (or otherwise with no
        real predecessor output to alias) resolves to the missing-marker,
        not a crash — substitute_templates already handles a None/missing
        outputs value via its existing missing-marker logic once the key
        is simply absent, so the variable handler stores nothing for a
        node with no incoming edge."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "var1", "type": "variable", "config": {"name": "huerfana"}},
                {"id": "end", "type": "end", "config": {"template": "{{huerfana}}"}},
            ],
            "edges": [
                {"from": "start", "to": "var1", "fromHandle": "default"},
                {"from": "var1", "to": "end", "fromHandle": "default"},
            ],
        }
        executor = FlowExecutor()
        result = await executor.run(graph, params={})
        assert result == "[missing: huerfana]"

    async def test_two_variables_with_the_same_name_last_one_wins(self):
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "segundo valor"
        mock_response.json.side_effect = ValueError("not json")
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "var1", "type": "variable", "config": {"name": "dup"}},
                {"id": "http1", "type": "http", "config": {"url": "https://example.com", "method": "GET"}},
                {"id": "var2", "type": "variable", "config": {"name": "dup"}},
                {"id": "end", "type": "end", "config": {"template": "{{dup}}"}},
            ],
            "edges": [
                {"from": "start", "to": "var1", "fromHandle": "default"},
                {"from": "var1", "to": "http1", "fromHandle": "default"},
                {"from": "http1", "to": "var2", "fromHandle": "default"},
                {"from": "var2", "to": "end", "fromHandle": "default"},
            ],
        }

        with patch("openacm.core.flow_executor.httpx.AsyncClient", return_value=mock_client):
            executor = FlowExecutor()
            result = await executor.run(graph, params={})

        assert result == "segundo valor"
```

Read the top of `tests/unit/test_flow_executor.py` to confirm `AsyncMock`, `MagicMock`, `patch` are already imported (they are, used by `TestHttpNode`) before running — don't re-import.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_flow_executor.py::TestVariableNode -v`
Expected: FAIL — `"variable"` isn't handled by `run()` yet, so the graph walk hits `Error: unknown node type 'variable'`.

- [ ] **Step 3: Implement**

In `src/openacm/core/flow_executor.py`, modify `run()`. Find this block (currently the first thing inside `run()`):

```python
    async def run(self, graph: dict, params: dict) -> str:
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        edges_by_source: dict[str, dict[str, str]] = {}
        for edge in graph.get("edges", []):
            edges_by_source.setdefault(edge["from"], {})[edge.get("fromHandle", "default")] = edge["to"]
```

Add a second lookup right after it:

```python
    async def run(self, graph: dict, params: dict) -> str:
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        edges_by_source: dict[str, dict[str, str]] = {}
        edges_by_target: dict[str, str] = {}
        for edge in graph.get("edges", []):
            edges_by_source.setdefault(edge["from"], {})[edge.get("fromHandle", "default")] = edge["to"]
            edges_by_target[edge["to"]] = edge["from"]
```

Then find the main loop's `if node["type"] == "end":` block:

```python
            if node["type"] == "end":
                template = node["config"].get("template", "")
                return substitute_templates(template, params, outputs)

            handler = self._HANDLERS.get(node["type"])
```

Add a `variable` case right after the `end` case, before the `_HANDLERS` dispatch:

```python
            if node["type"] == "end":
                template = node["config"].get("template", "")
                return substitute_templates(template, params, outputs)

            if node["type"] == "variable":
                source_id = edges_by_target.get(node["id"])
                value = outputs.get(source_id) if source_id else None
                outputs[node["id"]] = value
                outputs[node["config"]["name"]] = value
                current_id = edges_by_source.get(node["id"], {}).get("default")
                continue

            handler = self._HANDLERS.get(node["type"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_flow_executor.py -v`
Expected: PASS (all tests, including the 4 new `TestVariableNode` tests)

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest -q`
Expected: no new failures beyond the known pre-existing baseline (7 errors in `gmail_classifier`, plus possibly 5 date-dependent failures in `test_gmail_summary.py` if the wall-clock date has rolled over since this plan was written — both are unrelated to this change; do not attempt to fix either).

- [ ] **Step 6: Commit**

```bash
git add src/openacm/core/flow_executor.py tests/unit/test_flow_executor.py
git commit -m "feat(flows): add Variable node — aliases an earlier node's output under a friendly name"
```

---

### Task 2: Frontend — category colors + `VariableNode` component

**Files:**
- Modify: `frontend/app/globals.css`
- Modify: `frontend/components/flow-editor/node-types.tsx`
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: existing `--acm-accent`/`--acm-info` CSS vars.
- Produces: two new CSS vars (`--acm-node-logic`, `--acm-node-data`); exported `NODE_CATEGORY: Record<string, 'flow'|'logic'|'integration'|'data'>` and `CATEGORY_COLORS: Record<'flow'|'logic'|'integration'|'data', string>` from `node-types.tsx` (later tasks' right-click menu and Inspector header need these); a new `VariableNode` component and `variable` entry in `NODE_TYPES`; `FlowCanvas.tsx`'s `addNode` defaults gain a `variable: { name: '' }` entry so the (still-present-until-Task-3) palette button for it doesn't crash.

- [ ] **Step 1: Add the two new CSS variables**

In `frontend/app/globals.css`, find the existing color block (search for `--acm-info:`):

```css
  --acm-info:             oklch(0.74  0.06 230);
```

Add two new lines immediately after it:

```css
  --acm-info:             oklch(0.74  0.06 230);
  --acm-node-logic:       oklch(0.74  0.12 300);
  --acm-node-data:        oklch(0.74  0.10 195);
```

Find the corresponding `--color-acm-info` mapping (search for `--color-acm-info:`) and add matching entries the same way, immediately after it:

```css
  --color-acm-info:          var(--acm-info);
  --color-acm-node-logic:    var(--acm-node-logic);
  --color-acm-node-data:     var(--acm-node-data);
```

- [ ] **Step 2: Restyle `node-types.tsx` with category colors and add `VariableNode`**

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
  variable: 'data',
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
      <Handle type="target" position={Position.Top} id="default" />
      <Handle type="source" position={Position.Bottom} id="default" />
    </div>
  );
}

export function VariableNode({ id, data }: NodeProps) {
  return (
    <div style={baseStyleFor('variable')}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: CATEGORY_COLORS.data }}>📦 Variable</div>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <Handle type="target" position={Position.Top} id="default" />
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
  variable: VariableNode,
  end: EndNode,
};
```

- [ ] **Step 3: Add the `variable` default to `FlowCanvas.tsx`'s `addNode`**

In `frontend/components/flow-editor/FlowCanvas.tsx`, find `addNode`'s `defaults` object:

```typescript
    const defaults: Record<string, Record<string, unknown>> = {
      start: { parameters: [] },
      http: { url: '', method: 'GET', headers: {}, body: '' },
      conditional: { field: '', operator: 'contains', value: '' },
      woocommerce: { connection_id: null, search_term: '' },
      end: { template: '' },
    };
```

Add a `variable` entry:

```typescript
    const defaults: Record<string, Record<string, unknown>> = {
      start: { parameters: [] },
      http: { url: '', method: 'GET', headers: {}, body: '' },
      conditional: { field: '', operator: 'contains', value: '' },
      woocommerce: { connection_id: null, search_term: '' },
      variable: { name: '' },
      end: { template: '' },
    };
```

- [ ] **Step 4: Verify with `tsc`**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5: Manual browser verification (required for this task)**

Start a dev server on a port you're sure isn't already in use by anyone else's session (check first, don't assume). Open an agent's Flujos tab, create/open a flow, and confirm: the 5 existing node types now render with a colored border matching their category (gold for Start/End, blue for HTTP/WooCommerce, and — once you click "+ variable" in the still-present palette — the new Variable node renders in cyan with a `📦 Variable` label and its own `{{id}}` reference).

- [ ] **Step 6: Commit**

```bash
git add frontend/app/globals.css frontend/components/flow-editor/node-types.tsx frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): category-colored flow nodes + new Variable node type"
```

---

### Task 3: Frontend — right-click node search (replaces the static palette)

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: `NODE_CATEGORY`/`CATEGORY_COLORS` from Task 2.
- Produces: `FlowCanvas` becomes a thin wrapper around a new internal `FlowCanvasInner` component, so `useReactFlow()` (needed to convert a right-click's screen position into flow-graph coordinates) has a `<ReactFlowProvider>` ancestor. The static "+ type" palette column is removed. A right-click on the canvas background opens a positioned, searchable, category-grouped menu; selecting an entry creates that node type at the exact click position.

This task requires an actual manual browser verification before being marked complete — per this plan's Global Constraints, `tsc --noEmit` passing is not sufficient evidence.

- [ ] **Step 1: Wrap `FlowCanvas` in a `ReactFlowProvider`, rename the current body to `FlowCanvasInner`**

In `frontend/components/flow-editor/FlowCanvas.tsx`, update the import line:

```typescript
import {
  ReactFlow, ReactFlowProvider, useReactFlow, Background, Controls, MiniMap, addEdge, applyNodeChanges, applyEdgeChanges,
  type Node, type Edge, type Connection, type NodeChange, type EdgeChange,
} from '@xyflow/react';
```

Rename the exported function and add a thin wrapper. Find:

```typescript
export function FlowCanvas({ agentId, flow, onSave }: { agentId: number; flow: AgentFlow; onSave: (graphJson: string) => void }) {
```

Change it to:

```typescript
function FlowCanvasInner({ agentId, flow, onSave }: { agentId: number; flow: AgentFlow; onSave: (graphJson: string) => void }) {
```

And add this wrapper immediately after the function's closing brace (at the very end of the file, replacing the final `}`):

```typescript
export function FlowCanvas(props: { agentId: number; flow: AgentFlow; onSave: (graphJson: string) => void }) {
  return (
    <ReactFlowProvider>
      <FlowCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
```

- [ ] **Step 2: Add the context-menu state and node-category/label lookups**

Inside `FlowCanvasInner`, near the top (right after the existing `const nodeIdCounterRef = useRef(...)` line), add:

```typescript
  const { screenToFlowPosition } = useReactFlow();
  const canvasWrapperRef = useRef<HTMLDivElement>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; flowX: number; flowY: number } | null>(null);
  const [contextMenuSearch, setContextMenuSearch] = useState('');
```

Add these two constants at module scope, above the `FlowCanvasInner` function definition (not inside it):

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

Add the import for `NODE_CATEGORY`/`CATEGORY_COLORS` alongside the existing `NODE_TYPES` import:

```typescript
import { NODE_TYPES, NODE_CATEGORY, CATEGORY_COLORS } from './node-types';
```

- [ ] **Step 3: Replace `addNode` with `addNodeAt`, remove the palette**

Find the existing `addNode` function:

```typescript
  const addNode = (type: keyof typeof NODE_TYPES) => {
    const defaults: Record<string, Record<string, unknown>> = {
      start: { parameters: [] },
      http: { url: '', method: 'GET', headers: {}, body: '' },
      conditional: { field: '', operator: 'contains', value: '' },
      woocommerce: { connection_id: null, search_term: '' },
      variable: { name: '' },
      end: { template: '' },
    };
    setNodes(nds => [...nds, { id: nextNodeId(type), type, position: { x: 100, y: 100 + nds.length * 90 }, data: defaults[type] }]);
  };
```

Replace it with a position-taking version:

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

  const onPaneContextMenu = useCallback((event: React.MouseEvent | MouseEvent) => {
    event.preventDefault();
    const bounds = canvasWrapperRef.current?.getBoundingClientRect();
    if (!bounds) return;
    const flowPosition = screenToFlowPosition({ x: (event as MouseEvent).clientX, y: (event as MouseEvent).clientY });
    setContextMenu({
      x: (event as MouseEvent).clientX - bounds.left,
      y: (event as MouseEvent).clientY - bounds.top,
      flowX: flowPosition.x,
      flowY: flowPosition.y,
    });
    setContextMenuSearch('');
  }, [screenToFlowPosition]);
```

- [ ] **Step 4: Replace the palette column + wire the context menu into the render**

Find the return block's left column (the static palette):

```typescript
      <div className="flex flex-col gap-1 shrink-0" style={{ width: 120 }}>
        {(Object.keys(NODE_TYPES) as (keyof typeof NODE_TYPES)[]).map(t => (
          <button key={t} onClick={() => addNode(t)} className="btn-secondary text-[11px] px-2 py-1">+ {t}</button>
        ))}
        <button onClick={handleSave} className="btn-primary text-[11px] px-2 py-1 mt-2">Guardar flujo</button>
```

Replace the `{(Object.keys(NODE_TYPES) ...)}` block (only that block — keep everything else in this column, including "Guardar flujo" and the "Probar flujo" section below it, untouched):

```typescript
      <div className="flex flex-col gap-1 shrink-0" style={{ width: 120 }}>
        <div className="text-[10px]" style={{ color: 'var(--acm-fg-4)' }}>Clic derecho en el lienzo para agregar un nodo</div>
        <button onClick={handleSave} className="btn-primary text-[11px] px-2 py-1 mt-2">Guardar flujo</button>
```

Find the canvas wrapper div and `<ReactFlow>` element:

```typescript
      <div className="flex-1" style={{ border: '1px solid var(--acm-border)', borderRadius: 8 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_e, node) => setSelectedId(node.id)}
          onPaneClick={() => setSelectedId(null)}
          nodeTypes={NODE_TYPES}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
```

Replace it with a `position: relative` wrapper carrying the ref, `onPaneContextMenu`, closing the menu on a plain pane click, and the menu itself rendered as a sibling of `<ReactFlow>`:

```typescript
      <div ref={canvasWrapperRef} className="flex-1 relative" style={{ border: '1px solid var(--acm-border)', borderRadius: 8 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_e, node) => setSelectedId(node.id)}
          onPaneClick={() => { setSelectedId(null); setContextMenu(null); }}
          onPaneContextMenu={onPaneContextMenu}
          nodeTypes={NODE_TYPES}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
        {contextMenu && (
          <div
            className="absolute z-50 p-2"
            style={{ left: contextMenu.x, top: contextMenu.y, background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', borderRadius: 8, width: 200, maxHeight: 320, overflowY: 'auto' }}
          >
            <input
              autoFocus
              className="acm-input w-full mb-2 text-[11px]"
              placeholder="Buscar nodo..."
              value={contextMenuSearch}
              onChange={e => setContextMenuSearch(e.target.value)}
              onKeyDown={e => { if (e.key === 'Escape') setContextMenu(null); }}
            />
            {NODE_CATEGORIES.map(cat => {
              const filteredTypes = cat.types.filter(t => NODE_LABELS[t].toLowerCase().includes(contextMenuSearch.toLowerCase()));
              if (filteredTypes.length === 0) return null;
              return (
                <div key={cat.label} className="mb-1">
                  <div className="label text-[var(--acm-fg-4)] mb-1">{cat.label}</div>
                  {filteredTypes.map(t => (
                    <button
                      key={t}
                      className="btn-secondary w-full text-left text-[11px] px-2 py-1 mb-1"
                      style={{ borderColor: CATEGORY_COLORS[NODE_CATEGORY[t]] }}
                      onClick={() => { addNodeAt(t, contextMenu.flowX, contextMenu.flowY); setContextMenu(null); }}
                    >
                      {NODE_LABELS[t]}
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
        )}
      </div>
```

- [ ] **Step 5: Verify with `tsc`**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 6: Manual browser verification (required for this task)**

Using a fresh dev server instance (don't reuse a process you didn't start, and check first whether anything is already running on the port you pick): open an agent's Flujos tab, open a flow, right-click on empty canvas space — confirm a menu appears at the click position with a search box and 4 category headers (FLUJO, LÓGICA, INTEGRACIONES, DATOS). Type part of a node name (e.g. "http") and confirm the list filters live, hiding empty categories. Click a node type and confirm it's created exactly where you right-clicked (not at a fixed offset). Right-click again, press Escape, and confirm the menu closes without creating anything. Click elsewhere on the canvas (not right-click) and confirm any open menu also closes. Confirm the old "+ type" palette buttons are gone and "Guardar flujo"/"Probar flujo" still work as before.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): right-click node search menu replacing the static add-node palette"
```

---

### Task 4: Frontend — Inspector polish + variable-picker dropdowns

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: `NODE_CATEGORY`/`CATEGORY_COLORS` from Task 2, the `nodes`/`edges` state already in `FlowCanvasInner`.
- Produces: `availableVariableNames(nodes, edges, selectedNodeId): string[]` (a module-level pure function — walks backward from a node through incoming edges collecting Variable node names); a `VariablePicker` component wired into 5 fields: HTTP's `url` and a newly-added `body` textarea, Conditional's `field`, WooCommerce's `search_term`, End's `template`. The Inspector's header and field groups are restyled to match this codebase's established section-header convention (`<div className="label text-[var(--acm-fg-4)] mb-1">...</div>`, already used in `AgentSkillsTab`/`AgentToolsTab`).

This task requires an actual manual browser verification before being marked complete — per this plan's Global Constraints.

- [ ] **Step 1: Add `availableVariableNames` and the `VariablePicker` component**

Add these at module scope in `frontend/components/flow-editor/FlowCanvas.tsx`, near the top alongside the other module-level helpers (`toReactFlow`/`toGraphJson`/`maxNodeIdSuffix`):

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

function VariablePicker({ names, targetRef, value, onInsert }: {
  names: string[];
  targetRef: React.RefObject<HTMLInputElement | HTMLTextAreaElement | null>;
  value: string;
  onInsert: (newValue: string) => void;
}) {
  if (names.length === 0) return null;
  return (
    <select
      className="acm-input w-full mb-1 text-[10px]"
      value=""
      onChange={e => {
        const name = e.target.value;
        if (!name) return;
        const insertText = `{{${name}}}`;
        const el = targetRef.current;
        const start = el?.selectionStart ?? value.length;
        const end = el?.selectionEnd ?? value.length;
        onInsert(value.slice(0, start) + insertText + value.slice(end));
      }}
    >
      <option value="">Insertar variable...</option>
      {names.map(n => <option key={n} value={n}>{n}</option>)}
    </select>
  );
}
```

- [ ] **Step 2: Add refs for the 5 variable-picker target fields**

Inside `FlowCanvasInner`, alongside the other `useRef` declarations, add:

```typescript
  const urlInputRef = useRef<HTMLInputElement>(null);
  const bodyInputRef = useRef<HTMLTextAreaElement>(null);
  const conditionalFieldRef = useRef<HTMLInputElement>(null);
  const searchTermRef = useRef<HTMLInputElement>(null);
  const templateRef = useRef<HTMLTextAreaElement>(null);
```

- [ ] **Step 3: Restyle the Inspector header and wire in the variable pickers**

Find the Inspector panel's header:

```typescript
      {selectedNode && (
        <div className="shrink-0 p-2 text-[11px]" style={{ width: 220, border: '1px solid var(--acm-border)', borderRadius: 8, color: 'var(--acm-fg-2)' }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>{selectedNode.type}</div>
```

Replace the header line with one showing the category color and a friendlier label:

```typescript
      {selectedNode && (
        <div className="shrink-0 p-2 text-[11px]" style={{ width: 220, border: '1px solid var(--acm-border)', borderRadius: 8, color: 'var(--acm-fg-2)' }}>
          <div
            style={{
              fontWeight: 600, marginBottom: 8, paddingBottom: 6,
              borderBottom: `2px solid ${CATEGORY_COLORS[NODE_CATEGORY[selectedNode.type || 'http']]}`,
            }}
          >
            {NODE_LABELS[(selectedNode.type || 'http') as keyof typeof NODE_TYPES]}
          </div>
```

Find the `http` panel section:

```typescript
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
```

Replace it, adding the missing `body` field (a real, useful gap the backend already supports) plus both fields' variable pickers, and grouping the section under a `label` header matching this codebase's convention:

```typescript
          {selectedNode.type === 'http' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Petición HTTP</div>
              <label>URL</label>
              <VariablePicker
                names={availableVariableNames(nodes, edges, selectedNode.id)}
                targetRef={urlInputRef}
                value={String(selectedNode.data.url || '')}
                onInsert={v => updateSelectedNodeData({ url: v })}
              />
              <input ref={urlInputRef} className="acm-input w-full mb-2" value={String(selectedNode.data.url || '')} onChange={e => updateSelectedNodeData({ url: e.target.value })} />
              <label>Método</label>
              <select className="acm-input w-full mb-2" value={String(selectedNode.data.method || 'GET')} onChange={e => updateSelectedNodeData({ method: e.target.value })}>
                <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option>
              </select>
              <label>Cuerpo (para POST/PUT)</label>
              <VariablePicker
                names={availableVariableNames(nodes, edges, selectedNode.id)}
                targetRef={bodyInputRef}
                value={String(selectedNode.data.body || '')}
                onInsert={v => updateSelectedNodeData({ body: v })}
              />
              <textarea ref={bodyInputRef} className="acm-input w-full" rows={3} value={String(selectedNode.data.body || '')} onChange={e => updateSelectedNodeData({ body: e.target.value })} />
            </>
          )}
```

Find the `conditional` panel section:

```typescript
          {selectedNode.type === 'conditional' && (
            <>
              <label>Campo (ej: {'{{http1.status}}'})</label>
              <input className="acm-input w-full mb-2" value={String(selectedNode.data.field || '')} onChange={e => updateSelectedNodeData({ field: e.target.value })} />
              <label>Operador</label>
```

Add the section header and variable picker (leave the rest of this block — operator/value — unchanged):

```typescript
          {selectedNode.type === 'conditional' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Condición</div>
              <label>Campo (ej: {'{{http1.status}}'})</label>
              <VariablePicker
                names={availableVariableNames(nodes, edges, selectedNode.id)}
                targetRef={conditionalFieldRef}
                value={String(selectedNode.data.field || '')}
                onInsert={v => updateSelectedNodeData({ field: v })}
              />
              <input ref={conditionalFieldRef} className="acm-input w-full mb-2" value={String(selectedNode.data.field || '')} onChange={e => updateSelectedNodeData({ field: e.target.value })} />
              <label>Operador</label>
```

Find the `woocommerce` panel section's final two lines:

```typescript
              <label>Término de búsqueda</label>
              <input className="acm-input w-full" value={String(selectedNode.data.search_term || '')} onChange={e => updateSelectedNodeData({ search_term: e.target.value })} />
            </>
          )}
```

Replace with the variable picker added, and a section header at the top of that whole `woocommerce` block (find `{selectedNode.type === 'woocommerce' && (` and add the header line right after it, alongside these changes at the bottom):

```typescript
              <label>Término de búsqueda</label>
              <VariablePicker
                names={availableVariableNames(nodes, edges, selectedNode.id)}
                targetRef={searchTermRef}
                value={String(selectedNode.data.search_term || '')}
                onInsert={v => updateSelectedNodeData({ search_term: v })}
              />
              <input ref={searchTermRef} className="acm-input w-full" value={String(selectedNode.data.search_term || '')} onChange={e => updateSelectedNodeData({ search_term: e.target.value })} />
            </>
          )}
```

And add `<div className="label text-[var(--acm-fg-4)] mb-1">WooCommerce</div>` as the first line inside that `woocommerce` block (right after `{selectedNode.type === 'woocommerce' && (` and its opening `<>`).

Find the `end` panel section:

```typescript
          {selectedNode.type === 'end' && (
            <>
              <label>Plantilla de respuesta</label>
              <textarea className="acm-input w-full" rows={4} value={String(selectedNode.data.template || '')} onChange={e => updateSelectedNodeData({ template: e.target.value })} />
            </>
          )}
```

Replace it:

```typescript
          {selectedNode.type === 'end' && (
            <>
              <div className="label text-[var(--acm-fg-4)] mb-1">Respuesta</div>
              <label>Plantilla de respuesta</label>
              <VariablePicker
                names={availableVariableNames(nodes, edges, selectedNode.id)}
                targetRef={templateRef}
                value={String(selectedNode.data.template || '')}
                onInsert={v => updateSelectedNodeData({ template: v })}
              />
              <textarea ref={templateRef} className="acm-input w-full" rows={4} value={String(selectedNode.data.template || '')} onChange={e => updateSelectedNodeData({ template: e.target.value })} />
            </>
          )}
```

Add a `variable` panel section (there wasn't one before — Task 2 added the node type but no config UI for it yet). Find the `end` block you just edited and add this new block immediately after it, before the closing `</div>` of the Inspector panel:

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

Also add a section header (`<div className="label text-[var(--acm-fg-4)] mb-1">Parámetros</div>` style) as the first line of the existing `start` block, matching the same convention — find `{selectedNode.type === 'start' && (` and confirm its existing `<label>Parámetros que el LLM puede enviar</label>` line already serves this purpose; leave the `start` and existing `woocommerce`-internal-connection-form styling as-is otherwise, this task only adds section headers and variable pickers, it does not redesign those two sections' internals further.

- [ ] **Step 4: Verify with `tsc`**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5: Manual browser verification (required for this task)**

Using a fresh dev server instance: build a flow with an HTTP node, wire its output into a Variable node named `resultado`, and confirm: the HTTP node's Inspector panel now shows a "Cuerpo (para POST/PUT)" textarea in addition to URL/Método. Select the End node, confirm an "Insertar variable" dropdown appears above its template textarea listing `resultado`. Select it and confirm `{{resultado}}` is inserted at the current cursor position in the template (not always appended to the end — click into the middle of existing text first, then insert, to verify cursor-position insertion specifically). Confirm a node with NO Variable node anywhere before it in the chain shows no dropdown at all (the `names.length === 0` case). Confirm the Variable node itself has a working "Nombre" field in its own Inspector panel. Save, reload, and confirm everything round-trips correctly.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(agents): polished Inspector panel + variable-picker dropdowns, add missing HTTP body field"
```

---

## Post-plan manual smoke test (end to end)

After all 4 tasks are merged:

1. Right-click to add a Start node (with a required parameter, e.g. `producto`), an HTTP node, a Variable node (name it `resultado`, wire the HTTP node's output into it), and an End node using `{{resultado}}` in its template — confirm each node's color matches its category throughout.
2. Save, then use "Probar flujo" with a test value for `producto` and confirm the variable's value flows through correctly to the final result.
3. Confirm the agent's existing "Test this agent" dashboard panel still triggers this flow correctly via the LLM (unaffected by this plan, but worth reconfirming nothing broke end to end).
