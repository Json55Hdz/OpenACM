# Flow Editor Chat Builder — Design Spec

## Context

This is sub-project E of the flow-editor follow-up series (after A — universal data pins, D — Unreal-style pin visuals, and B/C — JSON import/export + the `create_or_update_agent_flow` tool, all shipped and verified). It's a small, self-contained addition on top of B/C: a chat panel embedded in the flow editor, so a user can describe a flow in plain language, have the agent ask clarifying questions, and watch the flow get built on the canvas — instead of typing into the agent's regular chat and then clicking over to Agentes → Flujos to see the result.

## What's new

### 1. A `channel_id` override on the dashboard test-chat path

Today, `POST /api/agents/{agent_id}/test` (`src/openacm/web/routers/agents.py:829-852`) always calls `runner.run(agent=agent, message=message, user_id="dashboard_test")` with no `channel_id`, so `AgentRunner.run()` defaults it to `f"agent_{agent_id}"` — every test-panel message for a given agent shares one channel, and (per `Database.get_conversation`, `storage/database.py:1120-1141`) that channel's history is never fetched or shown by the current "Test this agent" panel (it's local-state-only, resets on remount).

The endpoint gains an optional `channel_id` field in its request body. When present, it's passed straight through to `runner.run(channel_id=...)`. When absent, behavior is byte-identical to today (defaults to `agent_{agent_id}`, matching the existing "Test this agent" panel's current behavior — no change for existing callers).

**Why this is safe:** confirmed directly against the schema and code — the `messages` table's `channel_id` column has no FK, no CHECK constraint, no enum (`database.py:80-88`); `Database.log_message()` and the `Memory` cache both treat it as an opaque string key. A value like `agent_5_flow_12` works identically to `agent_5` today. Nothing needs to change anywhere else in the message pipeline.

### 2. A per-call, non-persisted system-prompt addition

`AgentRunner.run()` gains an optional `extra_system_context: str | None = None` parameter. When present, it's appended to the built system prompt for that one call only — the same pattern `run()` already uses for knowledge (`agent_runner.py` around line 165-167) and skills (`:190-208`) injection, just one more optional block. It is never persisted to the `messages` table (only the actual conversation turns are) and is recomputed fresh on every call, so it always reflects the current flow regardless of how many turns have passed.

`/test`'s request body gains a matching optional `extra_system_context` field, forwarded straight through to `runner.run(...)`.

**Content, set by the frontend for a flow-builder chat call:**

```
Estás editando el flujo "{flow.name}" (id={flow.id}) del agente. Si el usuario te pide crear o
modificar este flujo, llama a create_or_update_agent_flow con flow_id={flow.id} para EDITARLO
directamente — no crees un flujo nuevo salvo que el usuario lo pida explícitamente.
```

This is the entire mechanism for "the AI knows which flow it's editing." It does **not** include a snapshot of the current `graph_json` — the model's own memory of its prior tool calls in this channel's conversation history is the source of truth for "what's been built so far." See section 5 for the explicit tradeoff this implies.

### 3. Frontend: `FlowChatPanel` component

New file, `frontend/components/flow-editor/FlowChatPanel.tsx` — a self-contained component (own file, since `FlowCanvas.tsx` is already large and this is a distinct responsibility), rendered from `FlowCanvasInner` behind a toggle button ("💬 Chat con IA") in the existing left toolbar column, next to "Exportar"/"+ Skill".

**Props:** `{ agentId: number; flow: AgentFlow }` — everything else it needs (channel scoping, system-context string) is derived from these two, with zero extra API calls to determine them (confirmed both are already in scope everywhere `FlowCanvas` is rendered).

**Behavior**, modeled directly on the existing "Test this agent" panel (`app/agents/page.tsx`'s `TestPanel`, reused for its send/pending-state shape) plus the existing `useConversationHistory` hook (`hooks/use-api.ts:389-398`, already channel_id-agnostic — reused as-is, no changes needed) for history loading:

1. On mount (or first time the panel is opened — lazy, not fetched until the user actually opens it): `useConversationHistory(`agent_${agentId}_flow_${flow.id}`, 'dashboard_test')` loads prior turns for this specific flow's channel, so reopening a flow you were chatting about yesterday shows the same conversation. `user_id` stays the existing hardcoded `'dashboard_test'` value `/test` already uses server-side (not made configurable — unnecessary, since `channel_id` alone already fully isolates one flow's conversation from another's or from the generic "Test this agent" panel's `agent_{id}`-only channel: `get_conversation`'s lookup key is the `(user_id, channel_id)` pair, and varying `channel_id` alone already makes every pair unique).
2. A simple message list (user/assistant bubbles, no markdown rendering needed beyond what plain text needs — this is a much lighter surface than the main `/chat` page, matching `TestPanel`'s existing simplicity, not the full `/chat` page's `MessageBubble`/tool-call-card machinery) plus a text input and send button.
3. Sending calls the extended `/test` mutation with `{ message, channel_id: 'agent_${agentId}_flow_${flow.id}', extra_system_context: <the string from section 2> }`. While pending, shows the same `Loader2` + "Pensando..." spinner `TestPanel` already uses.
4. On a successful response: appends the assistant's reply to the local message list, **and** invalidates the `['agent-flow', flow.id]` and `['agent-flows', agentId]` react-query keys — this is what makes the canvas refresh (see section 4). No parsing of the response text to detect "did it actually call the tool" — invalidating unconditionally after every reply is cheap (one GET) and always correct, versus fragile response-text sniffing.

### 4. Canvas live refresh

`FlowsTab`'s render of `<FlowCanvas ... />` (`app/agents/page.tsx:1831-1840`) gains `key={editingFlow.updated_at}`. Today, `FlowCanvasInner`'s node/edge state is derived once via `useMemo(..., [flow.id])` (`FlowCanvas.tsx`, load path) — keyed only on `flow.id`, so it never re-derives when the same flow's `graph_json` changes underneath it. Keying the whole `<FlowCanvas>` element on `updated_at` instead forces a full remount whenever the flow's row changes (whether from a normal "Guardar flujo" click or an AI edit via the chat panel), which re-runs every `useMemo`/`useState` initializer against the fresh server data — the simplest correct way to reflect a change made from outside the currently-mounted canvas instance, with no new imperative "reload" plumbing needed inside `FlowCanvasInner` itself.

### 5. Explicitly out of scope / known tradeoffs (stated up front, not discovered later)

- **No live streaming of the AI's response** — same request/wait/full-response shape as today's "Test this agent" panel, not the `/chat` page's WebSocket streaming. A future enhancement, not this round.
- **(Superseded — see Addendum below) No graph_json snapshot fed to the model each turn.** As shipped for v1, the model relied on its own conversation-history memory of what it already built. A follow-up round (documented in the Addendum) changed this: `FlowChatPanel` now serializes the flow's current `graph_json` into `extra_system_context` on every send, so the model reads the live graph instead of remembering its own past tool calls. This closes the "manual edit between chat turns gets silently overwritten" gap described in the original paragraph below, at the cost storage/prompt-size the original paragraph called out — accepted, since in practice one flow's `graph_json` is small relative to the model's context window.
- **The canvas re-sync can discard unsaved manual canvas edits.** (Revised after implementation — the original design below used a `key={updated_at}` remount; the shipped version instead uses an in-place `useEffect` in `FlowCanvasInner`, keyed on `flow.graph_json`'s content rather than the `updated_at` timestamp, which re-derives `nodes`/`edges` via `setNodes`/`setEdges` without destroying the rest of the component's state — this was itself a final-review fix, since the original `key`-based remount also silently reset the chat panel's own open/closed state and, on the ordinary manual-save path, the ReactFlow viewport, the open node Inspector, and any in-progress "Probar flujo"/"+ Skill" state on every save, not just AI-driven ones.) The remaining tradeoff: if you've dragged nodes around but haven't clicked "Guardar flujo," and then the AI updates the flow via chat, the in-place sync still overwrites `nodes`/`edges` from the server's (AI-updated) state, silently dropping your unsaved drag. Same underlying tradeoff as the point above, from the other direction — content-conflict resolution between simultaneous manual and AI edits is still out of scope for v1.
- **Chat history is lost on a cold cache.** The model's "memory" of what it already built (section 2's whole design) lives in `Memory`'s in-memory cache within one warm process. `Memory._load_from_db` (used to repopulate that cache after a restart) deliberately strips both `role="tool"` rows and empty-content `role="assistant"` tool-call-planning rows — so after a server restart, the model only sees its own past prose replies, not the tool calls it made or their results. Its next edit in that conversation is effectively built from scratch, not from genuine memory of the current graph. Not fixed in this round; worth knowing if a chat spanning a restart behaves like the AI "forgot" what it built.
- **No separate "start a new flow via chat, before any flow exists" entry point** — "+ Nuevo flujo" already creates a real, saved skeleton flow (Start→End, from the earlier `_DEFAULT_NEW_FLOW_GRAPH` fix) and lands you in the editor immediately; the chat panel is available there from the first second, same as for any other flow. No new empty-state UI needed.
- **No changes to the public webhook** (`POST /api/agents/{id}/chat`) — this feature only touches the dashboard-authenticated `/test` path, which is the right fit (internal UI feature, not an external integration surface).

## Security

No new surface: `/test`'s existing dashboard-token auth is unchanged; the new `channel_id`/`extra_system_context` fields are plain strings passed through to already-generic, already-parameterized code paths (no SQL string-building, no new file/network access). A user with dashboard access could theoretically pass an arbitrary `channel_id` to read/write into any channel's message history via this endpoint — no worse than what dashboard access already implies today (the same user already has full API access via their Bearer token), and no different in kind from the existing `/api/conversations/{channel_id}/{user_id}` endpoints already being fully generic.

## Testing

- **Backend:** unit test that `/test` forwards `channel_id`/`extra_system_context` to `runner.run()` when provided, and that omitting them preserves today's exact default behavior (existing tests for this endpoint should keep passing unchanged). A unit test that `AgentRunner.run()` appends `extra_system_context` to the constructed `Brain`'s system prompt when passed, and that omitting it changes nothing (matching the existing pattern already covered for knowledge/skills injection).
- **Frontend:** `tsc --noEmit` clean. Manual browser verification (standing rule for canvas-interaction changes): open a flow, open the chat panel, ask for a flow in Spanish conversationally, confirm a clarifying-question round-trip works, confirm the canvas visibly updates after the AI builds it, close and reopen the flow and confirm the conversation history is still there, confirm an unrelated flow's chat panel starts with a clean/empty history (channel isolation actually works, not just claimed).

## Addendum (2026-08-21): live graph context, vertical auto-layout, markdown rendering, dark controls

Four small follow-up fixes shipped after the initial round, verified live in-browser:

1. **Live graph context** (supersedes the "No graph_json snapshot" tradeoff above) — `FlowChatPanel.send()` now reads `flow.graph_json` at send time and appends it to `extra_system_context`, so every turn carries the flow's actual current structure instead of relying on the model's memory of its own prior tool calls.
2. **Vertical auto-layout** — `flow_tool.py`'s `_auto_layout()` now drives a new node's position from BFS depth over flow edges into `y` (each step down the flow moves down the canvas) instead of `x`; nodes sharing a depth (a branch/merge point) spread out along `x`. Matches how a linear flow reads top-to-bottom.
3. **Markdown rendering** — `FlowChatPanel` renders assistant replies through `react-markdown`/`remark-gfm` (same libraries the main `/chat` page already uses) instead of raw text, so headings/tables/lists/bold render as real elements.
4. **Dark Controls** — `FlowCanvas`'s `<ReactFlow>` gained `colorMode="dark"`, which applies React Flow's built-in dark-theme CSS variables to the zoom/fit-view `Controls` group (previously rendering white-on-white against OpenACM's dark theme).

## Addendum (2026-08-21): test-results panel redesign & chat overflow containment

Two more fixes, prompted by the "Probar flujo" panel looking cramped/proportion-breaking and the chat panel's markdown occasionally overflowing its fixed width:

**Backend — a real error signal instead of string-sniffing.** `FlowExecutor.run()`'s failure paths (missing Start node, missing required param, cycle guard, unknown node/type, a node handler's exception) all return strings starting with `"Error: "` or `"Error in node "` — previously the only way to know a test run failed. Added `flow_executor.is_error_result(result) -> bool`, a single source of truth for that prefix set, and the `/api/agents/{id}/flows/{id}/test` endpoint now returns `{"result", "outputs", "error"}` instead of just `{"result", "outputs"}`. `FlowExecutor.run()`'s own return contract is untouched (still a 2-tuple) — widening it to a 3-tuple would have touched ~40 existing call sites in `tests/unit/test_flow_executor.py` and the production flow-as-tool path in `agent_runner.py`, disproportionate to a test-panel display fix. Known accepted edge case: an End node template whose own text happens to start with one of those two prefixes would be misclassified as an error — narrow and not worth widening the contract to avoid.

**Frontend — `FlowTestPanel.tsx`, a new component.** The "Probar flujo" param inputs, run button, and result used to live squeezed into the 120px toolbar sidebar column, with the result rendered as 10px `whitespace-pre-wrap` text with no scroll containment — long results (or the multi-line output typical of a templated End node) visually overflowed the layout. Pulled out into its own toggleable side panel (`▶ Probar flujo` button, same pattern as `💬 Chat con IA`, 320px wide like `FlowChatPanel`):
  - A status line reusing the existing `.dot`/`.dot-ok`/`.dot-err` indicator classes and `--acm-ok`/`--acm-err` tokens — "Éxito" or "Error en nodo "X"" instead of undifferentiated text.
  - `FlowExecutor`'s `"Error in node 'X' (type): message"` string is parsed client-side (`parseNodeError()`) to show the failing node's id/type as a small badge and the underlying exception message on its own, instead of the raw prefixed string.
  - The result/error text renders in a `max-height`-capped, `overflow-y-auto` monospace block instead of an unbounded `pre-wrap` blob.
  - **New:** a collapsible "Salidas por nodo" section surfaces `testOutputs` (per-node output values) — this data was already being fetched from the `/test` response for the Inspector's `TemplatePreview` use, but was never shown to the user directly until now.

**Frontend — `FlowChatPanel.tsx` overflow containment.** Added `table`/`th`/`td`/`pre` overrides to `MARKDOWN_COMPONENTS` (a GFM table now renders inside its own `overflow-x-auto` scroller instead of pushing its intrinsic column width past the panel), and added `break-words`/`overflowWrap: anywhere` to `p`/`code`/`a` (an unbroken long token — a URL, a query string — now wraps instead of forcing the fixed 320px panel wider). The panel's root and message-list containers gained `overflow-hidden`/`overflow-x-hidden` as a containment backstop.
