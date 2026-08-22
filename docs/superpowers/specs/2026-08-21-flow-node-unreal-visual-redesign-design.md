# Flow Editor — Unreal-Style Node Visual Redesign — Design Spec

## Context

The flow editor's nodes already borrow some Unreal Blueprint visual language from an earlier round (diamond flow pins, circle data pins, dark minimap, a flujo/dato legend — see `node-types.tsx`'s `pinProps`/`CATEGORY_COLORS`). But the actual node cards still don't make it clear what goes in and what comes out: a pin's name only ever shows in a native `title` hover tooltip, unconnected field values are dumped as a loose text summary instead of sitting next to the pin they belong to, there's no header bar separating a node's title from its body, and there's no selection highlight at all. This spec redesigns the node cards to actually look and read like the reference (`DotBoxSpawnEmitter.jpg`, an Unreal Blueprint graph) — persistent pin labels, a colored header bar, inline default values, a selection glow, and a per-node-type info tooltip — while keeping the vertical (top-to-bottom) flow direction the last redesign round deliberately committed to (Unreal's own graphs run left-to-right only because that's how *their* content happens to read; ours reads top-to-bottom, and the pin positions stay that way).

Bundled into this same round: replacing hand-typed `{{node.field[0].sub}}` bracket paths (which `flow_executor.py`'s `substitute_templates` now resolves correctly, but which nobody can be expected to write from memory) with a click-to-insert picker driven by the flow's own last test run.

## What's new

### 1. Node card visual redesign

**Shared primitives, `node-types.tsx`:**

- `NodeCard` — replaces every node's current bare `<div style={baseStyleFor(type)}>...</div>` wrapper. Renders:
  - A **header bar**: category-colored background (via `color-mix(in srgb, ${CATEGORY_COLORS[cat]} 18%, transparent)`, computed inline — no new CSS variables needed, mirrors the existing `--acm-accent-tint` pattern used elsewhere), the node's icon+title text, and a small `(?)` info icon on the right end of the bar.
  - A **body**: everything below the header — subtitle/summary text, the `{{node_id}}` id chip, and the pin rows (below).
  - A **selection glow**: when React Flow's `selected` prop (passed to every custom node component via `NodeProps`) is true, an outer `box-shadow: 0 0 0 2px var(--acm-accent), 0 0 12px oklch(0.84 0.16 82 / 0.5)` — reuses the accent color already used for flow pins/edges, no new token.
  - Unchanged: rounded corners, dark `--acm-elev` body background, 1px category-colored border.
- `PinRow` — one row per data pin (not flow pins — see below), rendering the `<Handle>` itself plus a **persistent visible label** next to it (not just the existing `title=` hover tooltip, which stays as a supplementary hover detail): for a target (input) pin, dot on the left edge of the row with the label immediately to its right; for a source (output) pin, the label right-aligned with the dot on the right edge of the row. When the pin is a wire-or-literal field (url, body, field, value, search_term) and nothing is wired to it, the row also shows a compact preview of its current literal value (reusing the existing `data.url`/`data.body`/etc. already read today) truncated to ~24 chars — replaces today's separate "GET https://wttr.in/..." summary line, which duplicates what a pin row now shows directly.
- **Flow (exec) pins stay exactly where they are** — diamonds on the node's top/bottom edge, per the approved decision to keep vertical flow direction. A node with exactly one flow-in and one flow-out (the common case) gets no extra label on those pins — top-edge-in/bottom-edge-out is already self-explanatory from position, matching how Unreal doesn't bother labeling a node's single default exec pins either. **Conditional's `true`/`false` outputs are the one exception**: since there are two flow-out pins side by side at the bottom edge, each now carries a persistent visible label ("true"/"false") next to its diamond, not just the hover tooltip it has today.
- **Info tooltip**: the `(?)` icon in the header carries a native `title` attribute with a one-sentence, per-node-type description (a small `NODE_DESCRIPTIONS: Record<NodeType, string>` map, e.g. `http: "Hace una petición web (GET/POST/...) y guarda la respuesta para usar en nodos siguientes."`, `conditional: "Evalúa una condición sobre un valor y bifurca el flujo en dos ramas: true o false."`). One description per node type, not per instance — this is "what does this kind of node do," not per-flow documentation.

**Per-node-type changes** (all seven: `start`, `http`, `conditional`, `woocommerce`, `set`, `get`, `end`) — each is rewritten to use `NodeCard`/`PinRow` instead of its current bespoke `<div>`+manually-positioned `<Handle>` markup. No pin is added, removed, or repositioned — `classifyPin`/`pinProps`'s flow-vs-data classification and each node's exact handle `id`s are untouched, since those are load-bearing for `FlowExecutor` and for existing saved flows' edges. This is a rendering-only change.

### 2. Nested-path variable picker

**Problem:** `VariablePicker` (in `FlowCanvas.tsx`) already exists and inserts `{{name}}` at the cursor in a template/URL/body field, but `availableVariableNames()` only ever returns **Set-node custom names** — never a raw ancestor node id (`http1`, `weather`, ...), and never a nested path into that node's actual output shape. Writing `{{weather.current_condition[0].temp_C}}` today means typing it from memory with zero assistance.

**Fix**, entirely in `FlowCanvas.tsx`, no backend change (the backend already resolves arbitrary `.field`/`[N]` paths, shipped earlier today):

- `availableVariableNames` is renamed `availableVariableSources` and extended to also include the **raw node id of every ancestor**, not just Set-node names — walking the same edge graph it already walks, just no longer filtering to `type === 'set'`. (A Get node's `data.name` still contributes its aliased name too, unchanged.)
- New `enumeratePaths(value: unknown, basePath: string): Array<{ path: string; preview: string }>` — walks a JS value (a real `testOutputs[ancestorId]` entry, i.e. actual JSON from the last "Probar flujo" run) recursively, emitting one entry per **leaf** reached (a string/number/boolean, or an object/array not further descended because a depth or count cap was hit): `path` is the full dotted/bracketed suffix (`.current_condition[0].temp_C`), `preview` is the value stringified and truncated (~40 chars). Capped at depth 6 and 60 total entries — enough for any realistic API response shape, with a final "…" entry appended if the cap was hit (never a silent truncation).
- `VariablePicker` becomes a two-level `<select>` using `<optgroup>` per ancestor: the group label is the ancestor's name/id; if `testOutputs` has a recorded value for that ancestor, its options are every enumerated leaf path (rendered as `path → preview`, value = the full `{{id<path>}}` string ready to insert); if not (no test run yet, or that ancestor produced no output), the group falls back to today's single bare-name option (`{{id}}`). Clicking any option inserts exactly like today — same cursor-position insertion logic, unchanged.
- No behavior change when no test has ever been run: the picker degrades exactly to today's flat bare-name list, so this is purely additive.

## Files touched

- `frontend/components/flow-editor/node-types.tsx` — `NodeCard`, `PinRow`, `NODE_DESCRIPTIONS`, all seven node components rewritten to use them, selection glow via `NodeProps.selected`.
- `frontend/components/flow-editor/FlowCanvas.tsx` — `availableVariableNames` → `availableVariableSources` (extended), new `enumeratePaths`, `VariablePicker` rewritten for the two-level ancestor/path menu. No changes to graph state, edge validation, or the save/test/chat plumbing already in this file.

## Explicitly out of scope

- **Reroute/knot nodes** (the small oval labeled waypoints in the reference image) — deferred; doesn't address the actual complaint (pins being unreadable), and is a distinct new node type + insert-into-existing-edge interaction that deserves its own round.
- **Horizontal flow direction** — staying vertical, per the earlier explicit decision this session; the reference image's left-right exec pins are not being copied.
- **Backend changes** — the template-path resolution (`substitute_templates`/`_walk_template_path`) already ships correctly; this round is pure frontend rendering + a smarter picker over data that already exists (`testOutputs`).

## Testing

- `tsc --noEmit` clean.
- Manual browser verification (standing rule for canvas-interaction changes): open an existing flow, confirm every node type renders with a header bar, visible pin labels (no hover needed to read a pin's name), and inline literal-value previews on unconnected fields; confirm the `(?)` tooltip shows the right description per node type; click a node and confirm the orange selection glow appears; confirm Conditional's true/false pins show their labels without hovering. Run "Probar flujo" once, then open the picker on a template/URL/body field and confirm it now lists nested paths with real value previews from that run, and that clicking one inserts the correct `{{...}}` string that resolves correctly on the next test run. Also confirm the picker still degrades gracefully (bare names only) on a flow that's never been tested.
