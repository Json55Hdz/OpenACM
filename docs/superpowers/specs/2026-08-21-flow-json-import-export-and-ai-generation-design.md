# Flow JSON Import/Export + AI-Generated Flows — Design Spec

## Context

This is sub-projects B and C of the four-part follow-up to `docs/superpowers/specs/2026-08-20-flow-editor-power-upgrades-design.md`, coming after sub-project A (`docs/superpowers/specs/2026-08-21-flow-editor-universal-data-pins-design.md`, shipped and verified) and independent of sub-project D (Unreal-style pin visuals, shipped).

- **B — Export/import a flow as JSON**: lets a user download a flow, or paste one back in, as a portable JSON file.
- **C — AI generates a flow**: a tool any agent can call, in a normal chat conversation or administratively, to create or update one of its own flows by generating `graph_json` directly — no visual editor required.

C depends on B's format and, more importantly, on B's validation work — today the backend barely validates `graph_json` at all, and an AI generating one badly needs real, actionable errors back, not a silent bad save that only breaks at run time.

## What's new

### 1. A real `graph_json` validator (backend)

Today (confirmed by reading `src/openacm/web/routers/agents.py:31-42` and `src/openacm/core/flow_executor.py`), the only server-side checking is: valid JSON, and `detect_cycle` over flow-kind edges. Nothing checks node types, required config, dangling edge references, or handle-id validity — a malformed graph saves silently and only fails later as a runtime string like `"Error: unknown node type 'x'"` the next time the flow executes.

`flow_executor.py` gains `validate_graph(graph: dict) -> list[str]` (empty list = valid), next to the existing `detect_cycle`, using two new module-level constants mirroring the frontend's `node-types.tsx` handle table:

```python
KNOWN_NODE_TYPES = {"start", "http", "conditional", "woocommerce", "set", "get", "end"}

# handle id -> pin kind, per node type, target and source separately —
# mirrors classifyPin() in frontend/components/flow-editor/node-types.tsx
NODE_TARGET_HANDLES = {
    "start": set(), "http": {"default", "url", "body"},
    "conditional": {"default", "field", "value"}, "woocommerce": {"default", "search_term"},
    "set": {"default", "value"}, "get": set(), "end": {"default"},
}
NODE_SOURCE_HANDLES = {
    "start": {"default"}, "http": {"default"},
    "conditional": {"true", "false"}, "woocommerce": {"default", "result", "count"},
    "set": {"default"}, "get": {"default"}, "end": set(),
}
```

`validate_graph` checks, in order (collecting every failure rather than stopping at the first, so an AI fixing a bad graph sees everything wrong in one round-trip):

1. `nodes` is a list, `edges` is a list.
2. Every node has a string `id`, and ids are unique.
3. Every node's `type` is in `KNOWN_NODE_TYPES`.
4. Exactly one node has `type == "start"`.
5. At least one node has `type == "end"` — an existence check only, not reachability; whether that `end` node is actually reachable from `start` is a graph-shape question `detect_cycle`-style full reachability analysis would need to answer, and is deliberately not attempted here (see Out of scope).
6. Every edge's `from`/`to` reference an existing node id.
7. Every edge's `fromHandle` is in `NODE_SOURCE_HANDLES[<from node's type>]`, and `toHandle` is in `NODE_TARGET_HANDLES[<to node's type>]` — skipped for a given edge if its node-id checks (6) already failed, to avoid a confusing cascade of unrelated handle errors.
8. `detect_cycle(graph)` (existing, unchanged) — reported as one more entry in the same list.

A node missing `config` entirely is treated as `config: {}` (every node handler already reads config keys with `.get(...)` and a default, per `flow_executor.py`'s existing handlers) — this validator does not enforce per-type required config keys, since every handler already degrades gracefully to an empty/default value rather than crashing. Enforcing that would duplicate logic that already lives in the handlers and would need to be kept in sync by hand; skipped deliberately (see Out of scope).

### 2. Wiring the validator in

`_parse_and_validate_graph` (`agents.py:31-42`) changes from "parse + cycle-check" to "parse + `validate_graph`", and its `HTTPException` message becomes the full, joined list of problems instead of just the cycle chain — every caller of this helper (today: `update_agent_flow`, `test_agent_flow`) gets the stronger check for free, with no call-site changes.

`create_agent_flow`'s request body (`agents.py`, `POST /api/agents/{agent_id}/flows`) gains an optional `graph_json` field (string, same shape as everywhere else). When present, it goes through `_parse_and_validate_graph` before being passed to `db.create_flow(..., graph_json=...)` — which already accepts this kwarg today (`database.py:1654`, just never exercised by this endpoint). When absent, behavior is unchanged (empty flow, exactly as today). This turns "create with content" from a create-then-update two-call sequence into one atomic call — needed by both B's import and C's tool.

### 3. Export (frontend)

A "Exportar" button in `FlowCanvas.tsx`'s left toolbar, next to the existing "Guardar flujo" (around line 564, which already computes `toGraphJson(nodes, edges)` for the save path). Clicking it builds:

```json
{
  "kind": "openacm-flow",
  "version": 1,
  "name": "<flow.name>",
  "description": "<flow.description>",
  "graph_json": { "nodes": [...], "edges": [...] }
}
```

— `graph_json` embedded as a real object (not a double-escaped string) so the file is readable and editable by hand or by an AI reading it back. Downloads as `<flow-name-slugified>.json` via a `Blob` + object URL (no backend round-trip needed — the canvas already has everything in memory). Deliberately excludes `id`, `agent_id`, `is_active`, timestamps — those are instance-specific and meaningless (or actively wrong) once moved to a different agent.

### 4. Import (frontend)

An "Importar flujo" button in `FlowsTab` (`app/agents/page.tsx`, next to "+ Nuevo flujo" in the list view, ~line 1814). Opens a small panel with a single textarea ("pega el JSON aquí") and an "Importar" button — no file picker, to keep this equally easy whether the JSON came from a downloaded file or was pasted straight out of a chat with an AI. On submit:

1. Client-side `JSON.parse` — parse errors shown inline immediately, no request sent.
2. Basic envelope check: `kind === "openacm-flow"` and `graph_json` present — anything else shown as an inline error ("esto no parece un flujo de OpenACM exportado").
3. `POST /api/agents/{agent_id}/flows` with `{name: parsed.name || "Flujo importado", description: parsed.description || "", graph_json: JSON.stringify(parsed.graph_json)}` — server-side `validate_graph` is the real gate; a structurally-broken `graph_json` (e.g. hand-edited badly) comes back as a 400 with the full problem list, shown inline the same way.
4. On success: closes the panel, opens the newly created flow in the editor (same UX as clicking "+ Nuevo flujo" today) — always a new flow, never overwrites anything, per your answer.

The `version: 1` field isn't enforced yet (nothing to migrate from), but is there from day one so a future format change has something to switch on.

### 5. The AI-generates-a-flow tool (C)

New module `src/openacm/tools/flow_tool.py`, registered in `app.py::_init_tools` exactly like `cron_tool`/`agent_tool` (`from openacm.tools import flow_tool` + `self.tool_registry.register_module(flow_tool)`).

```python
@tool(
    name="create_or_update_agent_flow",
    description="<full node/handle vocabulary — see below>",
    parameters={...},  # name, graph_json, description?, flow_id?, agent_id?
)
async def create_or_update_agent_flow(
    name: str, graph_json: dict, description: str = "",
    flow_id: int | None = None, agent_id: int | None = None,
    _brain=None, _channel_id=None, **kwargs,
) -> str:
```

**Resolving which agent** — per your "las dos" answer, two paths, checked in this order:
1. If `agent_id` is passed explicitly, use it (lets the primary/administrative assistant build or edit a flow for any agent by id, from normal `/chat`).
2. Otherwise, parse `_channel_id` for the `agent_<id>` prefix (`agent_runner.py:224`'s existing convention, the same one swarm code already relies on) — this is set whenever the call happens from inside an agent's own run, so an agent can build its own flows conversationally with zero extra parameters.
3. Neither present → return a clear error string ("no se pudo determinar a qué agente pertenece este flujo — pasa agent_id explícitamente") rather than guessing.

**Auto-layout** — if a node in `graph_json["nodes"]` has no `position`, one is computed: a BFS over flow-kind edges from the `start` node assigns each node a depth (its column, `x = depth * 260`), and nodes sharing a depth stack vertically in visit order (`y = index_in_column * 140`). This means the AI never has to reason about pixel coordinates — it only has to get the graph's logical shape right. Nodes that already specify a position keep it untouched (so re-saving an AI-tweaked, human-arranged flow doesn't scramble the layout).

**Validation and persistence**: runs `graph_json` through the same `validate_graph()` from section 1. If it fails, the tool returns the joined error list as its string result (matching every other tool's "return a human-readable string" convention) — inside the agentic loop, this becomes the tool result the LLM sees next, and it can retry with a corrected graph in the same conversation. If it passes: creates a new flow (`flow_id` omitted) or updates an existing one owned by the resolved agent (`flow_id` given — 404-equivalent string error if it belongs to a different agent, matching the REST endpoints' own scoping). Success returns a short confirmation with a dashboard link, e.g. `"Flujo 'Buscar en WooCommerce' creado (id 12). Ábrelo en http://.../agents para verlo, o pídeme que lo pruebe."` — matching `cron_tool.py`'s existing link-back-to-dashboard convention.

**Tool description contents** (drafted in full during implementation, not here) must teach the LLM: the 7 node types and their config keys, the target/source handle-id table from section 1's constants, the two edge kinds (`flow` vs `data`) and when to use each, and the `{{name}}` / `{{node_id.field}}` template syntax available in literal fields — everything a human builds by dragging pins, but as prose a model can act on.

## Security

No new surface: the tool only writes to `flows` rows already scoped to a resolved `agent_id`, through the same `db.create_flow`/`db.update_flow` methods the REST layer already uses — no new SQL, no new file access, no code execution. The stronger validator is a net security *improvement* (rejects more malformed input earlier). Import's client-side `JSON.parse` + server-side `validate_graph` means a hand-crafted malicious import can't do anything a malicious hand-edit through the visual editor couldn't already do — it still has to pass the same checks either way.

## Out of scope

- Per-node-type required-config-key validation (section 1) — every handler already degrades gracefully; enforcing this too would duplicate logic that lives in the handlers.
- A "list my flows" tool for the AI to check before creating/updating — not needed for a first version; the AI can always create new and let the user delete duplicates via the existing UI. Can be added later if it turns out to matter.
- Format migrations for `version` — nothing to migrate from yet; the field exists so a future change has something to check.
- Import overwriting the currently-open flow — always creates new, per your answer.
- Any change to the actual node/pin/handle model — this reuses exactly what sub-project A shipped, unchanged.
- Reachability analysis (is the `end` node actually reachable from `start`, are there orphaned unreachable nodes) — existence-only checks per section 1, point 5.

## Testing

- **Backend**: unit tests for `validate_graph` covering each of its 8 checks independently (unknown type, zero/two start nodes, zero end nodes, duplicate ids, dangling edge target, invalid handle for a node's actual type, a cyclic graph) plus a fully-valid graph passing clean. A test that `POST .../flows` with `graph_json` in the body creates a flow with that content in one call, and that an invalid one is rejected with the joined error list. A test for the tool: valid graph → flow created with auto-computed positions; invalid graph → error string returned, no DB write; `flow_id` given → updates instead of creating; wrong-agent `flow_id` → rejected; `agent_id` explicit vs. `_channel_id`-derived, both resolve correctly.
- **Frontend**: `tsc --noEmit` clean. Manual browser verification (this codebase's standing rule for canvas-interaction and now cross-agent-write changes): export a real flow, confirm the downloaded JSON's shape; paste it back in via Import, confirm it creates a new flow that opens correctly and executes identically; paste deliberately-broken JSON, confirm the inline error list is legible.
