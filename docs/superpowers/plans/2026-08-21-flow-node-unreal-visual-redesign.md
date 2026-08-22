# Flow Node Unreal Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the flow editor's node cards to read like an Unreal Blueprint graph (colored header bar, always-visible pin labels, inline literal-value previews, selection glow, per-node-type info tooltip) and replace hand-typed `{{node.field[0].sub}}` bracket paths with a click-to-insert picker built from the flow's last test run.

**Architecture:** Two independent frontend-only changes, no backend involvement. `node-types.tsx` gets two new shared rendering primitives (`NodeCard`, `PinRow`) that every one of the 7 existing node components is rewritten to use — no pin is added, removed, renamed, or repositioned; this is a rendering-only pass. `FlowCanvas.tsx`'s existing `VariablePicker`/`availableVariableNames` (which today only offers flat Set-node alias names) is extended into a two-level menu — one group per ancestor node, expanded into every real nested path found in that ancestor's last `testOutputs` entry.

**Tech Stack:** React, TypeScript, `@xyflow/react` (React Flow v12). No new dependencies. No automated frontend test framework exists in this repo (confirmed: no `test` script, no jest/vitest/@testing-library in `frontend/package.json`) — this repo's established convention for frontend work is `tsc --noEmit` + manual browser verification (Playwright), not unit tests. Both tasks below follow that convention.

**Spec:** `docs/superpowers/specs/2026-08-21-flow-node-unreal-visual-redesign-design.md`

## Global Constraints

- Flow (exec) pins keep their exact current position, shape, and `id` — top/bottom edges, diamond shape, vertical flow direction. Only DATA pins move into the new row-based layout.
- No node's Handle `id`, `type` (`source`/`target`), or `type` field's meaning changes — `classifyPin`/`pinProps` in `node-types.tsx` are consumed unchanged; existing saved flows' edges must keep resolving to the same visual pins.
- No backend changes. `flow_executor.py`'s template resolution already supports arbitrary `.field`/`[N]` paths (shipped earlier).
- `tsc --noEmit` must be clean after each task.
- No automated tests to write — verify manually in the browser per each task's checklist.

---

### Task 1: `NodeCard`/`PinRow` primitives — redesign all 7 node components

**Files:**
- Modify: `frontend/components/flow-editor/node-types.tsx` (full file, 300 lines — read it first)

**Interfaces:**
- Produces (consumed by Task 2 only indirectly — Task 2 touches a different file and does not import anything new from this one; both tasks can run in either order):
  - `NodeCard({ type: string; icon: string; title: string; selected?: boolean; children: React.ReactNode })` — the shared card wrapper (header bar + body).
  - `PinRow({ nodeType: string; handleId: string; handleKind: 'source' | 'target'; label: string; literalPreview?: string })` — one row per **data** pin only (never a flow pin).
  - `NODE_DESCRIPTIONS: Record<string, string>` — one-sentence description per node type, shown in the header's `(?)` tooltip.
  - `truncate(value: string, max?: number): string` — a small string-truncation helper reused by every node's literal-value preview.
- Consumes: nothing new — reuses this file's own existing `pinProps`, `CATEGORY_COLORS`, `NODE_CATEGORY`, `Handle`, `Position` exactly as today.

- [ ] **Step 1: Add `truncate`, `NODE_DESCRIPTIONS`, `InfoIcon`, `NodeCard`, `PinRow`**

Insert these right after the existing `mergeBadgeStyle`/`MergeBadge` block (after line 135, before `export function StartNode`):

```tsx
function truncate(value: string, max = 24): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

// One sentence per node TYPE (not per instance) — "what does this kind of
// node do," shown via the header's (?) icon tooltip.
const NODE_DESCRIPTIONS: Record<string, string> = {
  start: 'Punto de entrada del flujo. Define los parámetros que recibe cuando se ejecuta.',
  http: 'Hace una petición web (GET/POST/...) a una URL y guarda la respuesta para usar en nodos siguientes.',
  conditional: 'Evalúa una condición sobre un valor y bifurca el flujo en dos ramas: true o false.',
  woocommerce: 'Busca productos en una tienda WooCommerce conectada y devuelve los resultados.',
  set: 'Guarda un valor bajo un nombre para poder reutilizarlo más adelante en el flujo.',
  get: 'Recupera un valor guardado previamente por un nodo Guardar (Set), en cualquier punto del flujo.',
  end: 'Punto final del flujo. Arma la respuesta final combinando texto fijo y valores de nodos anteriores.',
};

function InfoIcon({ description }: { description: string }) {
  if (!description) return null;
  return (
    <span
      title={description}
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        width: 13, height: 13, borderRadius: '50%', fontSize: 9, fontWeight: 700,
        color: 'var(--acm-fg-3)', border: '1px solid var(--acm-fg-4)', cursor: 'help',
        flexShrink: 0,
      }}
    >
      ?
    </span>
  );
}

// Shared card wrapper every node type below renders into: a category-tinted
// header bar (icon + title + info tooltip) separated from the body, an
// accent-colored glow when `selected` (a prop React Flow passes to every
// custom node component — see NodeProps), and `position: relative` so
// MergeBadge's absolute top-right offset resolves against the whole card
// regardless of how deep inside `children` it's rendered.
function NodeCard({ type, icon, title, selected, children }: {
  type: string; icon: string; title: string; selected?: boolean; children: React.ReactNode;
}) {
  const color = CATEGORY_COLORS[NODE_CATEGORY[type]];
  return (
    <div
      style={{
        borderRadius: 8, fontSize: 11, background: 'var(--acm-elev)',
        border: `1px solid ${color}`, color: 'var(--acm-fg-2)', minWidth: 160,
        position: 'relative', overflow: 'visible',
        boxShadow: selected ? '0 0 0 2px var(--acm-accent), 0 0 12px oklch(0.84 0.16 82 / 0.5)' : 'none',
      }}
    >
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px',
          borderRadius: '7px 7px 0 0', borderBottom: `1px solid ${color}`,
          background: `color-mix(in srgb, ${color} 18%, transparent)`,
          fontWeight: 600,
        }}
      >
        <span>{icon}</span>
        <span style={{ flex: 1 }}>{title}</span>
        <InfoIcon description={NODE_DESCRIPTIONS[type] || ''} />
      </div>
      <div style={{ padding: '6px 8px', display: 'flex', flexDirection: 'column', gap: 3 }}>
        {children}
      </div>
    </div>
  );
}

// One row per DATA pin (never a flow pin — those stay on the card's
// top/bottom edge, unchanged). The Handle renders with `position: 'static'`
// (overriding React Flow's own default `position: absolute` handle CSS via
// inline style, which always wins) so it sits in the row's normal flex flow
// instead of needing a manually-tuned percentage offset — React Flow
// measures each Handle's actual rendered DOM position for edge-anchoring,
// so this works regardless of nesting depth. Input rows read
// pin-then-label(-then-preview) left-aligned; output rows read
// label-then-pin right-aligned — matching an input's dot-on-the-left /
// output's dot-on-the-right convention.
function PinRow({ nodeType, handleId, handleKind, label, literalPreview }: {
  nodeType: string; handleId: string; handleKind: 'source' | 'target'; label: string; literalPreview?: string;
}) {
  const { style, title } = pinProps(nodeType, handleId, handleKind, label);
  const handleEl = (
    <Handle
      type={handleKind}
      position={handleKind === 'target' ? Position.Left : Position.Right}
      id={handleId}
      style={{ ...style, position: 'static' }}
      title={title}
    />
  );
  if (handleKind === 'target') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, minHeight: 16 }}>
        {handleEl}
        <span style={{ color: 'var(--acm-fg-3)' }}>{label}</span>
        {literalPreview && <span className="mono" style={{ color: 'var(--acm-fg-4)', fontSize: 9 }}>{literalPreview}</span>}
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 5, minHeight: 16 }}>
      <span style={{ color: 'var(--acm-fg-3)' }}>{label}</span>
      {handleEl}
    </div>
  );
}
```

- [ ] **Step 2: Rewrite `StartNode`**

Replace the existing `StartNode` function with:

```tsx
export function StartNode({ data, selected }: NodeProps) {
  const out = pinProps('start', 'default', 'source', 'inicio → siguiente nodo');
  return (
    <NodeCard type="start" icon="▶" title="Inicio" selected={selected}>
      <div style={{ color: 'var(--acm-fg-4)' }}>{(data.parameters as any[] || []).length} parámetro(s)</div>
      <Handle type="source" position={Position.Bottom} id="default" style={out.style} title={out.title} />
    </NodeCard>
  );
}
```

- [ ] **Step 3: Rewrite `HttpNode`**

```tsx
export function HttpNode({ id, data, selected }: NodeProps) {
  const targetConnections = useNodeConnections({ id, handleType: 'target' });
  const urlWired = targetConnections.some(c => c.targetHandle === 'url');
  const bodyWired = targetConnections.some(c => c.targetHandle === 'body');
  const flowIn = pinProps('http', 'default', 'target', 'nodo anterior');
  const flowOut = pinProps('http', 'default', 'source', 'siguiente nodo');
  return (
    <NodeCard type="http" icon="🌐" title="HTTP Request" selected={selected}>
      <MergeBadge id={id} />
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.method || 'GET')}</div>
      <PinRow nodeType="http" handleId="url" handleKind="target" label="url" literalPreview={urlWired || !data.url ? undefined : truncate(String(data.url))} />
      <PinRow nodeType="http" handleId="body" handleKind="target" label="body" literalPreview={bodyWired || !data.body ? undefined : truncate(String(data.body))} />
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: response</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      <Handle type="source" position={Position.Bottom} id="default" style={flowOut.style} title={flowOut.title} />
    </NodeCard>
  );
}
```

- [ ] **Step 4: Rewrite `ConditionalNode`**

```tsx
export function ConditionalNode({ id, data, selected }: NodeProps) {
  const flowIn = pinProps('conditional', 'default', 'target', 'nodo anterior');
  const truePin = pinProps('conditional', 'true', 'source', 'true');
  const falsePin = pinProps('conditional', 'false', 'source', 'false');
  return (
    <NodeCard type="conditional" icon="◆" title="Condicional" selected={selected}>
      <MergeBadge id={id} />
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.operator || '')}</div>
      <PinRow nodeType="conditional" handleId="field" handleKind="target" label="field" literalPreview={data.field ? truncate(String(data.field)) : undefined} />
      <PinRow nodeType="conditional" handleId="value" handleKind="target" label="value" literalPreview={data.value ? truncate(String(data.value)) : undefined} />
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: result</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      <Handle type="source" position={Position.Bottom} id="true" style={{ ...truePin.style, left: '30%' }} title={truePin.title} />
      <Handle type="source" position={Position.Bottom} id="false" style={{ ...falsePin.style, left: '70%' }} title={falsePin.title} />
      {/* Unreal shows a label on every exec pin that isn't a lone default
          in/out — Conditional's two flow-out branches are exactly that
          case, so (unlike every other node's single flow-in/flow-out,
          which stays unlabeled per the spec) these two get a persistent
          label instead of relying only on the Handle's hover title. */}
      <div style={{ position: 'absolute', bottom: -14, left: '30%', transform: 'translateX(-50%)', fontSize: 8, color: 'var(--acm-fg-4)' }}>true</div>
      <div style={{ position: 'absolute', bottom: -14, left: '70%', transform: 'translateX(-50%)', fontSize: 8, color: 'var(--acm-fg-4)' }}>false</div>
    </NodeCard>
  );
}
```

- [ ] **Step 5: Rewrite `WooCommerceNode`**

```tsx
export function WooCommerceNode({ id, data, selected }: NodeProps) {
  const flowIn = pinProps('woocommerce', 'default', 'target', 'nodo anterior');
  const flowOut = pinProps('woocommerce', 'default', 'source', 'siguiente nodo');
  return (
    <NodeCard type="woocommerce" icon="🛒" title="WooCommerce" selected={selected}>
      <MergeBadge id={id} />
      <PinRow nodeType="woocommerce" handleId="search_term" handleKind="target" label="search_term" literalPreview={data.search_term ? truncate(String(data.search_term)) : undefined} />
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <PinRow nodeType="woocommerce" handleId="result" handleKind="source" label="result" />
      <PinRow nodeType="woocommerce" handleId="count" handleKind="source" label="count" />
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      <Handle type="source" position={Position.Bottom} id="default" style={flowOut.style} title={flowOut.title} />
    </NodeCard>
  );
}
```

- [ ] **Step 6: Rewrite `SetNode`**

```tsx
export function SetNode({ id, data, selected }: NodeProps) {
  const flowIn = pinProps('set', 'default', 'target', 'nodo anterior');
  const flowOut = pinProps('set', 'default', 'source', 'siguiente nodo');
  return (
    <NodeCard type="set" icon="💾" title="Guardar (Set)" selected={selected}>
      <MergeBadge id={id} />
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <PinRow nodeType="set" handleId="value" handleKind="target" label="valor (opcional)" />
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
      <Handle type="source" position={Position.Bottom} id="default" style={flowOut.style} title={flowOut.title} />
    </NodeCard>
  );
}
```

Note: the old standalone hint text "entrada: valor (opcional — sin conexión usa el nodo anterior)" is dropped as a separate line — its full explanation now lives in the pin's hover tooltip (already provided by `pinProps`'s `title`, unchanged), with the row's own visible label shortened to "valor (opcional)".

- [ ] **Step 7: Rewrite `GetNode`**

`GetNode` is a pure node (no flow pins at all) with exactly one output representing its whole value — not one of several named pins, so it keeps its existing bottom-edge `Handle` placement unchanged, just wrapped in `NodeCard` for the header/selection-glow/tooltip:

```tsx
export function GetNode({ id, data, selected }: NodeProps) {
  const out = pinProps('get', 'default', 'source', 'value');
  return (
    <NodeCard type="get" icon="📤" title="Obtener (Get)" selected={selected}>
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.name || '(sin nombre)')}</div>
      <div style={idStyle}>{'{{'}{id}{'}}'}</div>
      <div style={pinLabelStyle}>salida: value</div>
      <Handle type="source" position={Position.Bottom} id="default" style={out.style} title={out.title} />
    </NodeCard>
  );
}
```

- [ ] **Step 8: Rewrite `EndNode`**

```tsx
export function EndNode({ id, data, selected }: NodeProps) {
  const flowIn = pinProps('end', 'default', 'target', 'nodo anterior');
  return (
    <NodeCard type="end" icon="■" title="Final" selected={selected}>
      <MergeBadge id={id} />
      <div style={{ color: 'var(--acm-fg-4)' }}>{String(data.template || '')}</div>
      <Handle type="target" position={Position.Top} id="default" style={flowIn.style} title={flowIn.title} />
    </NodeCard>
  );
}
```

- [ ] **Step 9: Remove the now-dead `baseStyleFor` function**

After Steps 2–8, `baseStyleFor` (currently defined right before `idStyle`, around line 100) is no longer called anywhere — every node type now goes through `NodeCard` instead. Delete the `baseStyleFor` function entirely. Verify nothing else references it:

```bash
grep -n "baseStyleFor" frontend/components/flow-editor/node-types.tsx
```

Expected: no output (the function definition itself is gone, and there were never any other call sites).

- [ ] **Step 10: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors. If `color-mix` or `NodeProps`'s `selected` field produce a type error, read the exact message — `NodeProps` from `@xyflow/react` includes `selected: boolean` natively, and `color-mix(...)` is a plain CSS string value (no TS involvement), so a real error here means something else was mistyped in one of the steps above, not a library gap.

- [ ] **Step 11: Build, deploy, and manually verify in the browser**

```bash
cd frontend && npm run deploy
```

Start the OpenACM server (see any earlier server-start command used this session — `TELEGRAM_TOKEN="" DISCORD_TOKEN="" PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m openacm < <(tail -f /dev/null) > <logfile> 2>&1 &`, then poll `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:47821/agents` until `200`). Using Playwright, open an agent's Flujos tab, edit an existing flow with at least one HTTP node and one Conditional node (e.g. "Clima Mundial - wttr.in API"), and confirm:
- Every node shows a colored header bar with an icon, title, and a `(?)` icon that shows a description on hover.
- Every data pin (HTTP's url/body, Conditional's field/value) shows its label directly next to the dot, readable without hovering.
- An unconnected url/body/field/value pin shows a small preview of its current literal text right in its row.
- Conditional's true/false pins each show a persistent "true"/"false" label under their diamond.
- Clicking a node shows an orange glow around the whole card; clicking elsewhere removes it.
- The flow still saves and runs correctly ("Guardar flujo" then "Probar flujo" in the FlowTestPanel) — this step changes rendering only, so a successful test run here is the proof no pin/handle wiring broke.

- [ ] **Step 12: Commit**

```bash
git add frontend/components/flow-editor/node-types.tsx
git commit -m "feat(flows): Unreal-style node cards — header bar, visible pin labels, selection glow"
```

---

### Task 2: Nested-path variable picker

**Files:**
- Modify: `frontend/components/flow-editor/FlowCanvas.tsx`

**Interfaces:**
- Consumes: nothing from Task 1 — this task only touches `FlowCanvas.tsx`, and none of its changes import anything new from `node-types.tsx`.
- Produces: nothing consumed by another task — this is the plan's last task.

- [ ] **Step 1: Add `enumeratePaths` and `truncatePreview`**

Insert immediately after the existing `walkTemplatePath` function (around line 118, right before the `previewTemplate` function):

```tsx
interface PathEntry { path: string; preview: string }

function truncatePreview(value: unknown, max = 40): string {
  const s = typeof value === 'string' ? value : JSON.stringify(value);
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

// Walks a real testOutputs[ancestorId] value and enumerates every LEAF
// reachable via a dotted/bracketed path — mirroring exactly the path shape
// flow_executor.py's substitute_templates resolves (".field" for a dict
// key, "[N]" for a list index), so every entry this produces is guaranteed
// to resolve correctly once inserted as {{ancestorId<path>}}. `path` is
// empty string for a non-nested (scalar) value at the top level; every
// nested entry's `path` starts with "." or "[" ready to concatenate
// directly after the ancestor id. Capped at depth 6 / 60 total entries (a
// real API response can nest arbitrarily) — the cap appends one final
// "…" entry rather than silently dropping the rest.
function enumeratePaths(value: unknown, basePath: string, depth = 0, budget = { count: 0 }): PathEntry[] {
  const MAX_DEPTH = 6;
  const MAX_ENTRIES = 60;
  if (depth >= MAX_DEPTH || value === null || typeof value !== 'object') {
    budget.count += 1;
    return [{ path: basePath, preview: truncatePreview(value) }];
  }
  const entries: PathEntry[] = [];
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i++) {
      if (budget.count >= MAX_ENTRIES) { entries.push({ path: `${basePath}[…]`, preview: '' }); break; }
      entries.push(...enumeratePaths(value[i], `${basePath}[${i}]`, depth + 1, budget));
    }
  } else {
    for (const key of Object.keys(value as Record<string, unknown>)) {
      if (budget.count >= MAX_ENTRIES) { entries.push({ path: `${basePath}.…`, preview: '' }); break; }
      entries.push(...enumeratePaths((value as Record<string, unknown>)[key], `${basePath}.${key}`, depth + 1, budget));
    }
  }
  return entries;
}
```

- [ ] **Step 2: Replace `availableVariableNames` with `availableVariableSources`**

Replace the entire existing `availableVariableNames` function (lines 207–240) with:

```tsx
interface VariableSource { id: string; label: string }

// Every ancestor reachable via any incoming edge (flow or data — see the
// walk below, unchanged from the function this replaces), surfaced as an
// insertable source: its own raw node id (e.g. "weather", "http1") always,
// PLUS a Set node's custom alias name (its config.name) if it has one — a
// Set node is reachable under BOTH its id and its friendly name, since
// flow_executor.py's Set-node branch writes the value under both keys in
// `outputs`. Get nodes contribute no separate alias: referencing a Get
// node's own id resolves to whatever it aliased, exactly like any other
// node's id would.
function availableVariableSources(nodes: Node[], edges: Edge[], selectedNodeId: string): VariableSource[] {
  const incomingBySource: Record<string, string[]> = {};
  for (const e of edges) {
    (incomingBySource[e.target] ||= []).push(e.source);
  }
  const seen = new Set<string>();
  const sources: VariableSource[] = [];
  const visited = new Set<string>();
  const queue: string[] = [...(incomingBySource[selectedNodeId] || [])];
  while (queue.length > 0) {
    const currentId = queue.shift()!;
    if (visited.has(currentId)) continue;
    visited.add(currentId);
    const node = nodes.find(n => n.id === currentId);
    if (node && !seen.has(node.id)) {
      seen.add(node.id);
      sources.push({ id: node.id, label: node.id });
    }
    const setName = node?.type === 'set' ? (node.data.name as string | undefined) : undefined;
    if (setName && !seen.has(setName)) {
      seen.add(setName);
      sources.push({ id: setName, label: setName });
    }
    queue.push(...(incomingBySource[currentId] || []));
  }
  return sources;
}
```

- [ ] **Step 3: Rewrite `VariablePicker`**

Replace the entire existing `VariablePicker` function (lines 242–267) with:

```tsx
function VariablePicker({ nodeId, nodes, edges, targetRef, value, onInsert, outputs }: {
  nodeId: string;
  nodes: Node[];
  edges: Edge[];
  targetRef: React.RefObject<HTMLInputElement | HTMLTextAreaElement | null>;
  value: string;
  onInsert: (newValue: string) => void;
  outputs: Record<string, unknown> | null;
}) {
  const sources = availableVariableSources(nodes, edges, nodeId);
  if (sources.length === 0) return null;

  const insert = (fullRef: string) => {
    const insertText = `{{${fullRef}}}`;
    const el = targetRef.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    onInsert(value.slice(0, start) + insertText + value.slice(end));
  };

  return (
    <select
      className="acm-input w-full mb-1 text-[10px]"
      value=""
      onChange={e => { if (e.target.value) insert(e.target.value); }}
    >
      <option value="">Insertar variable...</option>
      {sources.map(source => {
        const val = outputs?.[source.id];
        const expandable = val !== null && val !== undefined && typeof val === 'object';
        if (!expandable) {
          return <option key={source.id} value={source.id}>{source.label}</option>;
        }
        const paths = enumeratePaths(val, '');
        return (
          <optgroup key={source.id} label={source.label}>
            <option value={source.id}>{source.label} (todo el valor)</option>
            {paths.map(p => (
              <option key={`${source.id}${p.path}`} value={`${source.id}${p.path}`}>
                {p.path || '(valor)'} → {p.preview}
              </option>
            ))}
          </optgroup>
        );
      })}
    </select>
  );
}
```

- [ ] **Step 4: Update all 5 call sites**

Run this to find them (line numbers will have shifted from this plan's writing time):

```bash
grep -n "<VariablePicker" frontend/components/flow-editor/FlowCanvas.tsx
```

Each looks like this today (HTTP's URL field shown; the other four — HTTP's body, Conditional's field, WooCommerce's search_term, End's template — are the same shape with a different `value`/`onInsert` field):

```tsx
<VariablePicker
  names={availableVariableNames(nodes, edges, selectedNode.id)}
  targetRef={urlInputRef}
  value={String(selectedNode.data.url || '')}
  onInsert={v => updateSelectedNodeData({ url: v })}
/>
```

Replace the `names={...}` line in **every one of the 5 occurrences** with the three new props (`targetRef`/`value`/`onInsert` stay exactly as they are — only the `names` line changes):

```tsx
<VariablePicker
  nodeId={selectedNode.id}
  nodes={nodes}
  edges={edges}
  outputs={testOutputs}
  targetRef={urlInputRef}
  value={String(selectedNode.data.url || '')}
  onInsert={v => updateSelectedNodeData({ url: v })}
/>
```

(Again: only the prop list changes shape — `targetRef`/`value`/`onInsert` keep whatever field-specific ref/value/handler each of the 5 call sites already had before this step.)

- [ ] **Step 5: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6: Build, deploy, and manually verify in the browser**

```bash
cd frontend && npm run deploy
```

With the server running (same start procedure as Task 1 Step 11), open the "Clima Mundial - wttr.in API" flow (or any flow with an HTTP node), and:
- Before running a test: open the End node's Inspector, open the "Insertar variable" picker on its template field — confirm it shows a flat list of ancestor ids/names only (no expansion), matching today's behavior.
- Click "Probar flujo" in the FlowTestPanel, run it with a real city.
- Reopen the same picker: confirm the HTTP node's id now expands (via `<optgroup>`) into real nested paths with live value previews (e.g. `.current_condition[0].temp_C → 18`).
- Click one such option, confirm it inserts the exact `{{weather.current_condition[0].temp_C}}`-shaped string at the cursor.
- Run "Probar flujo" again and confirm the inserted reference resolves to the real value in the result (not `[missing: ...]`).

- [ ] **Step 7: Commit**

```bash
git add frontend/components/flow-editor/FlowCanvas.tsx
git commit -m "feat(flows): nested-path variable picker from last test run's real output shape"
```

---

## Final Verification

After both tasks:
- `cd frontend && npx tsc --noEmit` clean.
- `cd /c/Trabajo/JsonProductions/OpenACM && python -m pytest -q` — should show the same baseline as before this plan (no backend files touched by this plan, so no test count should change; a full baseline was last confirmed as 690 passed / 5 failed / 7 errors, all pre-existing and unrelated to the flow editor — see this session's history).
- `git status --porcelain` clean except the two commits above (plus any pre-existing untracked files noted earlier this session, e.g. `frontend/tsconfig.tsbuildinfo`, `.superpowers/`, `docs/actas/` — none of this plan's concern).
