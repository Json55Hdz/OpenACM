# Flow Editor Universal Data Pins — Design Spec

## Context

This is sub-project A of a four-part follow-up to `docs/superpowers/specs/2026-08-20-flow-editor-power-upgrades-design.md` (merge topology, copy/paste, per-flow skill, Inspector v2 — shipped and verified). The other three:

- **Sub-project B — flow import/export via JSON**: depends on this spec's final `graph_json` shape, so it comes after.
- **Sub-project C — AI generates a flow end-to-end from JSON**: depends on B's export format being stable.
- **Sub-project D — Minimap theming + "exactly like Unreal" Variables panel polish**: independent, can ship separately whenever.

This spec covers A only.

**The gap this closes:** today, a node's output is an opaque blob — the only way to reference a piece of it is by typing `{{node_id.field}}` into a text box by hand, and a Set node can only alias "whatever ran immediately before it in the chain," not any earlier node's output. The user wants this to work like Unreal Engine Blueprints: every node's output is one or more named, draggable pins, and every input field on every node can be *either* wired from another node's pin *or* left as a typed literal — with the wire winning when both exist.

## What's new

### 1. Two edge kinds: `flow` and `data`

`graph_json`'s `edges` array gains a `kind: "flow" | "data"` field. **Flow edges** are exactly what exists today — they define execution order, and `FlowExecutor.run()`'s walk follows only these. **Data edges** are new — they connect one node's named output pin to another node's named input field, and carry no execution-order meaning at all. `FlowExecutor.run()` never walks a data edge; it only consults them when resolving a specific field's value.

Edges also gain a `toHandle` (today only `fromHandle` exists, because every node had exactly one input). A flow edge's `toHandle` is always `"flow"`. A data edge's `toHandle` names the specific field it feeds (e.g. `"url"`, `"search_term"`, `"value"`).

**Backward compatibility:** an edge with no `kind` is treated as `kind: "flow"`, `toHandle: "flow"` — every graph saved before this ships keeps working unchanged, since nothing about flow-edge walking changes.

### 2. Get becomes a pure node (real behavior change)

Today a Get node sits *inside* the execution chain — it has a flow-in and flow-out handle, and `run()` walks through it like any other step. In Unreal, `Get` has no exec pins at all — it's a pure data source, referenced directly by whatever needs its value, wherever that is in the graph. Get's flow-in/flow-out handles are removed; it keeps only its data-output pin.

**Backward compatibility:** existing saved flows may have a Get node with real flow edges into and out of it (built under the old model). `FlowExecutor.run()` keeps honoring a flow edge that happens to target or originate from a Get node exactly as it does today (walks through it as a passthrough step) — this old shape still works, it's just never produced by the canvas anymore going forward. New flows never wire a Get node into the flow chain, because the canvas no longer gives it flow handles to connect.

### 3. Set keeps its flow pins, gains a separate data-input pin

Set still has to run at a specific point in the sequence — assignment is a side effect, exactly like Unreal's `Set <Variable>` node, which does have exec pins. What's new is a *second*, independent input handle for the value itself (rendered apart from the flow-in/flow-out handles), which can be wired from **any** node's output pin, not only the one immediately before it in the chain.

**Resolution order, backward compatible:** if a data edge targets Set's value-input handle, that wins. If none exists (every Set node saved before this ships), fall back to the current behavior — alias whatever node ran immediately before it (`previous_id`). Existing flows need no migration.

If the wired source node hasn't executed by the time this Set node runs (e.g. it sits on the untaken branch of a Conditional), the value resolves to `[missing: node_id]` / `[missing: node_id.field]` — the same "fail loud, never silent" rule this system already uses everywhere else.

### 4. Structured, named output pins on integration nodes

- **WooCommerce Query**: currently returns one formatted string. It now returns a small structured result with two named pins: `result` (the same human-formatted text as today — nothing lost) and `count` (the number of products found, as an integer). Both are independently connectable.
- **HTTP Request**: response shape is caller-defined and unknown at design time, so it gets exactly one data pin, `response` — the same parsed-JSON-or-raw-text value `run()` already produces today. Pulling a specific nested field out of it still goes through `{{http1.field}}` dot-notation (typed, in a literal field, or via a data edge whose `fromHandle` names the field — see section 6) — there's no way to give HTTP static named pins for a response whose shape isn't known until the request actually runs.

### 5. Every literal field becomes wire-or-literal

Every configurable text field on every node — HTTP's `url` and `body`, Conditional's `field` and `value`, WooCommerce's `search_term` — can now be the target of a data edge. Resolution, per field, before template substitution runs:

1. If a data edge targets this field (`toHandle` == the field name): resolve from `outputs[edge.from]`, narrowed by `edge.fromHandle` if the source node exposes more than one named pin (e.g. `count` vs `result` from WooCommerce) — `[missing: ...]` if the source hasn't executed yet.
2. Otherwise: use the field's literal value from `config`, exactly as today — including that a literal can still contain `{{...}}` template references by hand. This is pure fallback, not a parallel system; nothing about today's template substitution changes for a field with no data edge on it.

**Canvas behavior:** a field with an incoming data edge hides its text input and shows a small "🔌 connected to `{{http1.count}}`" chip with a way to disconnect (which just deletes that data edge and reveals the literal input again, unchanged). A field with no data edge looks and behaves exactly as it does today.

### 6. Explicitly scoped boundary — not every field becomes a pin

Dropdown/enum fields — HTTP's `method`, Conditional's `operator`, WooCommerce's saved-Connection selector — stay dropdown-only, no pin. Wiring a dynamic choice of *which* operator or *which* saved connection to use at runtime is a real but rare need that would require a distinct "enum pin" type this spec doesn't introduce. The End node's `template` field also stays literal-only (text with `{{...}}`) — it's structurally a composition of many references, not a single value a pin could carry.

## Data model

`graph_json` edge shape becomes:

```json
{"from": "http_1", "fromHandle": "count", "to": "set_2", "toHandle": "value", "kind": "data"}
{"from": "start", "fromHandle": "default", "to": "http_1", "toHandle": "flow", "kind": "flow"}
```

Node `config` shapes are unchanged — literal values still live exactly where they do today; data edges are additive, never a replacement for what's stored in `config`.

## Backend — `FlowExecutor` changes

- `run()`'s walk logic is unchanged except: it only follows edges where `kind == "flow"` (or `kind` is absent, per the back-compat rule).
- A new resolution step runs before each node handler builds its config: for every field the handler is about to read, check for a matching data edge (`kind == "data"`, `to == this node`, `toHandle == field name`) before falling back to the literal + `substitute_templates`. This is a small, shared helper used by `_run_http_node`, `_run_conditional_node`, `_run_woocommerce_node`, and the `set`-node branch in `run()`'s main loop — not five separate implementations.
- `_run_woocommerce_node` returns `{"result": <str>, "count": <int>}` instead of a bare string. Decision: a bare `{{woo1}}` (no dot) reference resolves to `result` specifically, not `str({"result": ..., "count": ...})` — this preserves every existing saved flow's `{{woo1}}` reference exactly as it already reads today (the human-formatted product listing), while `{{woo1.count}}` and `{{woo1.result}}` both work via the new dict. This is a small, explicit special case in the whole-value substitution rule for dict-shaped outputs that expose a `result` key, not a general behavior change to substitution for every node type.

## Frontend — canvas and Inspector changes

- `SetNode`/`GetNode` components are restructured per sections 2–3 above (Get loses its flow handles entirely; Set gains a second target handle).
- `WooCommerceNode` gains a second labeled source handle (`count`) alongside its existing one (relabeled `result`).
- Every Inspector field for a connectable value (HTTP url/body, Conditional field/value, WooCommerce search_term) gets a handle rendered at its row, plus the connected/disconnected dual rendering described in section 5.
- The variable-picker union-walk (already handles multi-predecessor traversal for merges) needs to also traverse data edges when computing "what's referenceable from here," not just flow edges — a node fed by a data edge from three hops back should still offer that source in the picker.

## Security

No new surface: still no arbitrary code execution, still no new field-level encryption, still the same accepted SSRF posture as the original spec. Data edges are pure references between already-existing node outputs — they don't let a flow read anything it couldn't already reach via typed `{{node_id.field}}` syntax; they only make that reference draggable instead of typed.

## Explicitly out of scope (this sub-project)

- Import/export of a flow's JSON (sub-project B).
- AI-assisted flow generation (sub-project C).
- Minimap theming and Variables-panel visual polish (sub-project D — unrelated to this data-model change, ships independently).
- An "enum pin" type for dropdown fields (section 6).
- True cycles or loops — still rejected; data edges carry no execution order, so they can't create an execution cycle even if drawn "backward" in the canvas (only flow edges are checked by `detect_cycle`, and that check is unaffected by this spec).
- Typed variables (int/string/bool with color-coded pins) — `count` being a real integer in this spec's WooCommerce change is the one concrete typed value introduced; a general type system for all pins is not part of this round.

## Testing

- **Backend:** unit tests per node handler confirming a data-edge-targeted field is resolved from the wired source (including the `.field` narrowing case and the `[missing: ...]` case for a not-yet-executed source), and that an untargeted field still resolves via the existing literal+template path unchanged. A dedicated test for the WooCommerce dict-output shape, including the whole-value stringification behavior chosen above. A back-compat test: a saved graph with old-style flow edges into/out of a Get node still executes correctly.
- **Frontend:** `tsc --noEmit` clean, plus the same required manual browser verification this codebase's history treats as non-optional for canvas-interaction changes: wiring a WooCommerce `count` pin into a Set node's new data-input handle and confirming it resolves correctly on "Probar flujo"; confirming a field with a connected data edge shows the chip instead of its text input and can be disconnected back to literal mode; confirming an old, previously-saved flow (built before this ships) still opens and runs correctly with no data edges at all.
