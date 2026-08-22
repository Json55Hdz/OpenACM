# Flow Editor — Loop ("Por cada") Node — Design Spec

## Context

Every flow today is a strictly linear chain with exactly one possible branch point (Conditional's `true`/`false`). There is no way to run a chain of steps once per item in an array — a hard blocker for the class of automation that motivated this work in the first place ("por cada producto que devolvió WooCommerce, hacé algo"). `FlowExecutor.run()` (`src/openacm/core/flow_executor.py`) is a single `while current_id:` walk over `edges_by_source`, and `detect_cycle`/`validate_graph` explicitly reject any cycle in flow edges at save time — so introducing real iteration is a genuine execution-model change, not a small tweak.

This spec adds one new node type, `loop`, modeled on Unreal Blueprint's `ForEachLoop`: you wire an array into it, connect whatever chain of existing node types you want as the loop body to its `loop` output, and connect whatever runs after the loop to its `done` output. Critically, **the loop body needs no "go back" wiring at all** — when the body chain hits a dead end (no further outgoing flow edge), the executor recognizes it's inside a loop and automatically advances to the next item, or falls through to `done` once the array is exhausted. Nested loops (a loop inside a loop's body) work with no special-casing, because the executor tracks "which loop(s) am I inside" as a stack, not a single value.

## What's new

### 1. Node contract — pins

`loop` gets four pin slots, split across flow and data exactly like every other node type:

| Handle | Kind | Direction | Meaning |
|---|---|---|---|
| `default` | flow | target | flow-in, same as every other node |
| `items` | data | target | **wire-only** — must be connected to a value that resolves to a list at runtime; no literal-text fallback (typing an array by hand doesn't make sense the way a URL or template string does) |
| `loop` | flow | source | fires once per item — connect the loop body's first node here |
| `done` | flow | source | fires exactly once, after the last item (or immediately, with zero iterations, if `items` resolved to an empty list) |
| `item` | data | source | the current iteration's item — real, wireable, exactly like WooCommerce's `result`/`count` pins |
| `index` | data | source | the current iteration's 0-based index — same pattern |

`loop`/`done` are classified as **flow** pins (diamonds) even though they're not named `default` — this needs one small addition to the frontend's `classifyPin()` (`node-types.tsx`), the same special-case pattern it already uses for Conditional's `true`/`false`. `item`/`index` are ordinary **data** pins (circles), no special-casing needed.

**Config:** one field, `max_iterations` (integer, default `200`) — see section 3.

### 2. Execution model (`flow_executor.py`)

`FlowExecutor.run()` gains a `loop_stack: list[dict]` local variable, empty at the start of every run. Each frame: `{"loop_node_id": str, "items": list, "index": int, "max_iterations": int}`.

**Entering a loop node** (reached via normal `current_id` dispatch, same as any other node type — handled inline in the `while` loop, the same way `set`/`get` are today, since it needs direct control over `current_id`):
1. Resolve `items` via the existing `data_edges_by_target`/`_resolve_pin_value` machinery (the same mechanism Set's `value` pin already uses) — must be a list. If the pin isn't wired, or resolves to something that isn't a list, return `f"Error in node '{node_id}' (loop): 'items' pin is not wired to a list"`.
2. If the list is empty: `current_id = edges_by_source.get(node_id, {}).get("done")` — skip straight past, no frame pushed.
3. Otherwise: push a new frame (`index=0`), set `outputs[node_id] = {"item": items[0], "index": 0}`, `current_id = edges_by_source.get(node_id, {}).get("loop")`.

**Hitting a dead end** (today: `current_id` becomes `None`, the `while current_id:` loop exits, and `run()` falls through to `"Error: flow ended without reaching an End node"`). The loop's outer condition changes to `while current_id or loop_stack:`, and a `current_id is None` branch is added at the top of the loop body:
- If `loop_stack` is empty: unchanged — this is a genuine "flow ended without reaching an End node" error, exactly as today.
- Otherwise, look at `loop_stack[-1]` (the innermost active loop) and advance it:
  - Increment its `index`.
  - If `index >= len(items)`: this loop is finished — pop the frame, `current_id = edges_by_source.get(loop_node_id, {}).get("done")`.
  - Else if `index >= max_iterations`: return `f"Error in node '{loop_node_id}' (loop): reached max_iterations ({max_iterations}) with more items remaining"` — the per-loop safety cap tripped (see section 3).
  - Else: update `outputs[loop_node_id] = {"item": items[index], "index": index}`, `current_id = edges_by_source.get(loop_node_id, {}).get("loop")` — next iteration.

Nested loops need no extra logic: an inner loop pushes its own frame on top of the outer's; when the inner loop's body dead-ends, only the top (inner) frame advances; the outer frame's `outputs[outer_id]` entry is untouched and still reflects the outer loop's current item throughout the inner loop's entire run.

**`item`/`index` as real data pins**, not just template-referenceable — resolved via `_resolve_pin_value`, completely unchanged: `outputs[loop_node_id]` is a dict with `item`/`index` keys, and `_resolve_pin_value`'s existing `if source_handle != "default" and isinstance(value, dict): ...` branch already handles this exactly the way it already handles WooCommerce's `result`/`count`. No changes needed to `_resolve_pin_value` or `resolve_field`.

**An `end` node reached inside a loop body still terminates the entire flow immediately**, exactly like today — this is intentional (an early-exit/"break with a result," e.g. "stop as soon as you find a match"), not a bug, and needs no special handling: the existing `if node["type"] == "end": return ...` fires regardless of `loop_stack`'s contents.

**No changes to `detect_cycle`.** Since the loop body never needs an explicit "go back" edge, there is no cycle in the graph for the loop construct to introduce — `detect_cycle` continues checking exactly what it checks today.

### 3. Safety caps

- **`max_iterations`** (per-node, default `200`, user-editable in the Inspector): the primary, loop-specific guard. Tripping it produces a clear error naming the exact loop node responsible (section 2).
- **`_MAX_NODE_VISITS`** (global constant, currently `50`): raised to `2000`. This remains a blunt backstop against runaway total work across an entire run (including nested loops), not the primary mechanism — `max_iterations` is expected to trip first and with a clearer diagnostic in the overwhelming majority of cases. `2000` comfortably covers a single loop at its default 200-iteration cap with a body of several nodes, or a couple of small nested loops, while still bounding worst-case total work per run.

### 4. Backend validation (`validate_graph`)

- `KNOWN_NODE_TYPES` gains `"loop"`.
- `NODE_TARGET_HANDLES["loop"] = {"default", "items"}`.
- `NODE_SOURCE_HANDLES["loop"] = {"loop", "done", "item", "index"}`.

No other change to `validate_graph` — the existing handle-membership checks and cycle detection apply unmodified.

### 5. Frontend (`node-types.tsx`, `FlowCanvas.tsx`)

- New `LoopNode` component, category `logic` (same color as Conditional — both are control-flow constructs), icon `🔁`, built from the same `NodeCard`/`PinRow` primitives every other node already uses:
  - `default` flow-in (top edge, unchanged pattern).
  - `items` as a `PinRow` (target, left) — no `literalPreview` (always `undefined`, since it's wire-only).
  - `item`/`index` as `PinRow`s (source, right).
  - `loop`/`done` as two flow diamonds on the bottom edge (`left: 30%`/`70%`, matching Conditional's `true`/`false` layout exactly), each with a persistent visible label underneath — same reasoning as Conditional's true/false labels: two flow-out pins on one node need labels, a single flow-in/flow-out pair doesn't.
- `classifyPin()` gains one line: for `nodeType === 'loop'` and `id === 'loop' || id === 'done'` on a source handle, classify as `'flow'` (mirrors the existing Conditional `true`/`false` special-case immediately above it).
- Inspector gains a `loop` section: one numeric input bound to `data.max_iterations` (defaulting to `200` when unset).
- `NODE_CATEGORIES`'s `'LÓGICA'` group and `NODE_LABELS` both gain `loop`.
- **No changes needed** to `availableVariableSources`/`enumeratePaths` (the nested-path variable picker) — a node inside a loop body already has the loop node as a normal ancestor via the `loop` flow edge, so `outputs['loop_1']` (populated at runtime exactly like any other node's output) is already picked up by the existing ancestor-walk and path-enumeration machinery with zero special-casing. Same for `_auto_layout` in `flow_tool.py` (the AI's flow-building tool) — it walks flow edges generically by `kind`, not by handle name, so `loop`/`done` edges are already included in its BFS depth calculation.

## Out of scope

- **Auto-layout imprecision for the loop body vs. what comes after `done`.** `_auto_layout`'s BFS-depth heuristic doesn't know the loop body's chain might be several hops long before naturally dead-ending, so a node placed right after `done` can land at a similar depth-band as the *start* of the loop body. This is an existing, already-accepted imprecision (the exact same thing already happens with Conditional's `true`/`false` branches converging back together) — not a new problem this design introduces, and not being solved here.
- **No "break" or "continue" node** for early-exiting a loop from partway through its body without using `end` (which exits the whole flow, not just the loop). Not requested; can be added later as its own node type if it turns out to be needed.
- **No parallel/concurrent iteration** — items are processed strictly one at a time, in order. Matches every other execution semantic in this system (fully sequential).

## Testing

- **Backend (`tests/unit/test_flow_executor.py`):** a loop over a 3-item literal-config-graph list resolving the body chain 3 times and reaching `done`; an empty-list case going straight to `done` with zero body executions; a `max_iterations` cap tripping with items still remaining, verifying the exact error message and which node it names; an `items` pin left unwired producing the clear error; nested loops (an outer 2-item loop wrapping an inner 3-item loop) producing 6 total inner-body executions with both `{{outer.item}}`/`{{outer.index}}` and `{{inner.item}}`/`{{inner.index}}` correctly resolvable at every point; an `end` node inside a loop body terminating the whole flow immediately on the first iteration, not looping to completion first.
- **Frontend:** `tsc --noEmit` clean. Manual browser verification (standing rule for canvas-interaction changes): build a flow with a `loop` node wired to a genuinely list-shaped source — an HTTP node calling a public API whose response is a JSON array at the top level (e.g. `https://jsonplaceholder.typicode.com/users`) is the simplest real source available; none of the other existing node types produce a bare list today (WooCommerce's `result` is a formatted string). Confirm the `loop`/`done` pins render as labeled diamonds, confirm `item`/`index` pins render as data circles, run "Probar flujo" and confirm the result reflects all iterations having run, confirm the variable picker on a node inside the loop body offers `{{loop_1.item...}}` paths once a test has run.
