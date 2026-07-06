# Flow Editor — Get/Set Variables (Revision) — Design Spec

## Context

This revises the just-shipped "Variable" node (`docs/superpowers/plans/2026-07-05-flow-editor-unreal-style.md`, Tasks 1-4, merged to `main`) after the user clarified that a truly Unreal-Blueprint-faithful variable system needs three things the inline node didn't provide: named output pins per node (not one generic handle), a separate Variables panel outside the canvas, and Get/Set nodes created by dragging a variable from that panel onto the canvas. This spec **replaces** the inline "Variable" node entirely, per explicit user direction — it does not coexist with it.

## Key realization: the backend barely changes

`FlowExecutor`'s existing model already resolves a node's value by id/name lookup in a flat `outputs` dict, independent of graph edges — edges only ever determine **execution order**, never data availability (`substitute_templates` does a plain dict lookup, it doesn't trace edges). This means:
- The just-shipped Variable node's logic (pass its input through, alias it under a declared name) is **exactly** what a "Set" node needs to do. Renaming it costs nothing semantically.
- A "Get" node is new, but trivial: no input pin, one output pin, and at runtime its value is simply `outputs.get(name)` — whatever the last node to write that name produced by the time execution reaches it.
- "Dragging a wire from WooCommerce's `result` pin into a Set node" is not a new data-flow mechanism — it's the *existing* single-edge, linear-chain connection, just drawn between two now-*named* pins instead of two generic dots. A Set node sitting directly after its source in the chain, connected by one edge, is indistinguishable at the graph level from what a "pulled wire" would produce.

So this revision is almost entirely a **frontend** change, plus a small **rename + one new backend node type**.

## What's new

### 1. Named output pins (visual only)

Every node type's output `Handle` gets a visible label instead of an unlabeled dot: HTTP → `response`, Conditional → `result`, WooCommerce → `result`, Get → `value`, Set → `value` (pass-through). This is a labeling change to the existing single-output-per-node shape — no node gains a second data pin in this revision. (The user chose "multiple pins per node" as the longer-term direction; this spec ships the single-named-pin foundation first — adding a second named pin to a given node type later is an additive, per-type change, not an architecture change, since pins are already keyed by name/id in `outputs`.)

### 2. `Set` node (renames/replaces the inline `Variable` node)

Same backend behavior already shipped for `variable` in `FlowExecutor`: one input, one output (pass-through), config `{ name }`. **Rename**, not reimplement — `_HANDLERS`/loop-level handling stays the same shape, just the type string changes from `"variable"` to `"set"` (and the frontend's `NODE_TYPES["variable"]` entry is removed, replaced by `NODE_TYPES["set"]`).

### 3. `Get` node (new)

No input handle. One output handle (`value`). Config: `{ name }`. At runtime: `outputs.get(node["config"]["name"])` — if nothing has Set that name yet by the time execution reaches this Get node, it resolves to the same missing/undefined value a `{{name}}` template reference would, via the existing lookup path.

### 4. Variables panel (new UI, left of the canvas, outside the node map)

A list of variable names currently in use anywhere in this flow's graph — **derived**, not separately persisted: computed as the de-duplicated set of every `Set`/`Get` node's `name` currently in `nodes`. No new database table, no new `graph_json` field — it's a live projection of the existing graph state, so there's nothing to keep in sync and nothing new to save. A "+ Nueva variable" button prompts for a name and creates a `Set` node (unwired, dropped at a default canvas position) with that name pre-filled — placing an unwired Set node is the mechanism for "declaring" a variable that doesn't have a source yet; the user connects it afterward.

### 5. Drag a variable from the panel onto the canvas → Get/Set choice

Starting a drag on a panel entry and dropping it on empty canvas space opens a small menu at the drop position with two options, "Obtener" (Get) and "Guardar" (Set) — selecting one creates that node type at the drop position, with `name` pre-filled to the dragged variable's name.

### 6. "Promote to Variable" (new)

Dragging a connection from any node's output pin and releasing it on empty canvas space (not onto another node's input handle) opens a small prompt for a variable name, then creates a `Set` node at the release position, pre-wired (one edge) from the source pin — in one motion, this both declares the variable (it now appears in the Variables panel, since a Set node with that name exists) and captures the value.

## Explicitly out of scope (this revision)

- A second named data pin on any existing node type (WooCommerce exposing e.g. both `result` and a count) — the panel/Get/Set architecture supports this later without further redesign, but no additional pins ship now.
- Any new backend endpoint or database table for variables — they remain a pure projection of `Set`/`Get` node names already in the graph.
- Renaming a variable across all its usages at once (renaming today means editing each `Set`/`Get` node's `name` field individually) — a "rename everywhere" convenience is a possible future polish, not required now.
- Any change to the linear-chain-plus-one-branch-point topology rule, or to how execution order is determined — unchanged from every prior flow-editor plan this session.
