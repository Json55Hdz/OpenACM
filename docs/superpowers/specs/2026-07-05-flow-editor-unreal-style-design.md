# Flow Editor — Unreal-Style Redesign — Design Spec

## Context

This is a follow-up polish sub-project for OpenACM's node-based flow builder (`frontend/components/flow-editor/`), which just shipped in full (`docs/superpowers/plans/2026-07-05-agent-node-flows.md`, 13 tasks, all merged). The user wants the editor's interaction model and visual language to feel closer to Unreal Engine's Blueprint editor: category-colored nodes, a right-click node-search menu organized by category, a visually named "variable" concept for referencing earlier nodes' outputs, and a more polished config side panel ("Inspector").

This was deliberately deferred until the base flow builder shipped and was verified working end to end, so as not to block that plan. It is purely additive — no existing node type, endpoint, or `FlowExecutor` behavior changes; the flow-topology rules (linear chain + one branch point at Conditional) and the plan's other Global Constraints all still apply unchanged.

## What's new

### 1. A new "Variable" node type

A node with exactly one input handle (`target`, `default`) and one output handle (`source`, `default`) — structurally a pass-through, same shape as the HTTP/WooCommerce nodes, so it doesn't change the graph's linear topology. Its config is a single field: `name` (the friendly variable name, e.g. `resultado_busqueda`).

Purpose: today, referencing an earlier node's output requires typing `{{node_id}}` by hand (e.g. `{{woo_3}}`) into a later node's config field — functional, but not visual, and the raw id isn't meaningful. Wiring a node's output into a Variable node and naming it lets every later node reference that value by its friendly name instead, and — per section 4 below — pick it from a dropdown rather than typing it.

**Backend change (the only one in this whole sub-project):** `FlowExecutor` (`src/openacm/core/flow_executor.py`) gains a `_run_variable_node` handler, registered in `_HANDLERS["variable"]`. Its job is trivial: pass its input through unchanged (same shape as the Conditional node's passthrough behavior, `outputs[node["id"]] = result`), and additionally alias that same value under the variable's declared `name` key in the `outputs` dict (`outputs[node["config"]["name"]] = result`), so `{{name}}` resolves exactly like `{{node_id}}` already does — no change to `substitute_templates`'s lookup logic, since it already checks `outputs` by whatever key is given. If two variable nodes in the same flow are given the same `name`, the later one silently wins (last-write-wins, consistent with how a Python dict key overwrite behaves) — this is an authoring mistake the canvas UI should discourage (see section 4) but the interpreter does not need to error on it.

### 2. Node color-coding by category (not by individual type)

Four categories, not six colors — HTTP and WooCommerce share one category since both are "call something external" actions:

| Category | Node types | Color |
|---|---|---|
| Flujo | Inicio, Final | `--acm-accent` (gold, already used for these two) |
| Lógica | Condicional | new: violet |
| Integraciones | HTTP Request, WooCommerce | `--acm-info` (blue, already exists) |
| Datos | Variable | new: cyan |

Each node's border and title color reflect its category's color — a small, centralized `CATEGORY_COLORS`/`NODE_CATEGORY` lookup in `node-types.tsx`, not per-node-type hardcoding, so adding a 7th node type later only requires assigning it to an existing or new category, not inventing a new color each time.

### 3. Right-click node search (replaces the static palette)

The left palette's static "+ type" buttons are removed entirely. Right-clicking anywhere on the empty canvas opens a floating menu at the click position: a text search input at the top, and below it the 6 node types grouped under their category headers (Flujo / Lógica / Integraciones / Datos), filtered live as you type. Selecting a node creates it at the exact position where the right-click happened (not a fixed offset like today). Clicking elsewhere on the canvas (or pressing Escape) closes the menu without creating anything. The "Guardar flujo" / "Probar flujo" buttons and the "Probar flujo" test-parameter inputs stay exactly where they are today — only the static add-node palette column is removed, replaced by this context menu.

### 4. Polished Inspector (config side panel)

Same fields as today (URL, method, operator, etc.) — this is a presentation/organization pass, not a new-fields pass. Changes:
- Header shows the node's category color as an accent bar/icon, plus its type name.
- Fields grouped with consistent label/input spacing (matching the rest of the dashboard's existing form conventions, e.g. `AgentSkillsTab`'s field groups).
- **Variable-reference fields** (HTTP's `url`/`body`, Conditional's `field`, WooCommerce's `search_term`, End's `template`) gain a small "Insertar variable" dropdown next to the text input, listing every Variable node's declared `name` reachable by walking backward from the selected node through incoming edges to Start. Since every node has exactly one incoming edge (the graph is a linear chain, branching only at Conditional), this backward walk is a single, unambiguous path — it does not require knowing which of a Conditional's branches will be "taken" at runtime, because tracing backward from a specific node only ever follows the one path that actually leads to it. Selecting a variable inserts `{{name}}` at the cursor position in that field — this is convenience on top of the existing free-text field, not a replacement for it; the field remains editable as plain text with `{{...}}` syntax same as today.
- The Start node's parameter editor (already shipped) and the WooCommerce node's Connection dropdown/inline-create form (already shipped) are visually restyled to match the new grouped-field convention but keep their exact current behavior.

## Explicitly out of scope

- Any change to `FlowExecutor`'s topology rules (still linear + one branch point) or to any of the 5 already-shipped node types' actual execution behavior.
- Field-level live validation (e.g. malformed-URL red-underline) — this was considered and explicitly deferred by the user in favor of the simpler visual-polish-only scope.
- A general "any node can read any other node's output regardless of order" capability — Variable nodes are a naming convenience over the existing chain-order rule, not a new capability to reference a node that hasn't executed yet.
- Node deletion UX, multi-select, copy/paste — unrelated pre-existing gaps noted in the base plan's final review, not part of this pass.
