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
- **No graph_json snapshot fed to the model each turn** — the model relies on its own conversation-history memory of what it already built via prior tool calls in this channel. If the user manually drags/edits nodes on the canvas *between* chat turns, the AI has no way to see that change and its next tool call could overwrite it. Accepted for v1: chatting-to-build and manual-dragging are largely separate workflows in one sitting, and solving this properly would mean serializing potentially-large graphs into every system prompt call, which is real added cost and complexity for a case that's rare in practice.
- **The canvas re-sync can discard unsaved manual canvas edits.** (Revised after implementation — the original design below used a `key={updated_at}` remount; the shipped version instead uses an in-place `useEffect` in `FlowCanvasInner`, keyed on `flow.graph_json`'s content rather than the `updated_at` timestamp, which re-derives `nodes`/`edges` via `setNodes`/`setEdges` without destroying the rest of the component's state — this was itself a final-review fix, since the original `key`-based remount also silently reset the chat panel's own open/closed state and, on the ordinary manual-save path, the ReactFlow viewport, the open node Inspector, and any in-progress "Probar flujo"/"+ Skill" state on every save, not just AI-driven ones.) The remaining tradeoff: if you've dragged nodes around but haven't clicked "Guardar flujo," and then the AI updates the flow via chat, the in-place sync still overwrites `nodes`/`edges` from the server's (AI-updated) state, silently dropping your unsaved drag. Same underlying tradeoff as the point above, from the other direction — content-conflict resolution between simultaneous manual and AI edits is still out of scope for v1.
- **Chat history is lost on a cold cache.** The model's "memory" of what it already built (section 2's whole design) lives in `Memory`'s in-memory cache within one warm process. `Memory._load_from_db` (used to repopulate that cache after a restart) deliberately strips both `role="tool"` rows and empty-content `role="assistant"` tool-call-planning rows — so after a server restart, the model only sees its own past prose replies, not the tool calls it made or their results. Its next edit in that conversation is effectively built from scratch, not from genuine memory of the current graph. Not fixed in this round; worth knowing if a chat spanning a restart behaves like the AI "forgot" what it built.
- **No separate "start a new flow via chat, before any flow exists" entry point** — "+ Nuevo flujo" already creates a real, saved skeleton flow (Start→End, from the earlier `_DEFAULT_NEW_FLOW_GRAPH` fix) and lands you in the editor immediately; the chat panel is available there from the first second, same as for any other flow. No new empty-state UI needed.
- **No changes to the public webhook** (`POST /api/agents/{id}/chat`) — this feature only touches the dashboard-authenticated `/test` path, which is the right fit (internal UI feature, not an external integration surface).

## Security

No new surface: `/test`'s existing dashboard-token auth is unchanged; the new `channel_id`/`extra_system_context` fields are plain strings passed through to already-generic, already-parameterized code paths (no SQL string-building, no new file/network access). A user with dashboard access could theoretically pass an arbitrary `channel_id` to read/write into any channel's message history via this endpoint — no worse than what dashboard access already implies today (the same user already has full API access via their Bearer token), and no different in kind from the existing `/api/conversations/{channel_id}/{user_id}` endpoints already being fully generic.

## Testing

- **Backend:** unit test that `/test` forwards `channel_id`/`extra_system_context` to `runner.run()` when provided, and that omitting them preserves today's exact default behavior (existing tests for this endpoint should keep passing unchanged). A unit test that `AgentRunner.run()` appends `extra_system_context` to the constructed `Brain`'s system prompt when passed, and that omitting it changes nothing (matching the existing pattern already covered for knowledge/skills injection).
- **Frontend:** `tsc --noEmit` clean. Manual browser verification (standing rule for canvas-interaction changes): open a flow, open the chat panel, ask for a flow in Spanish conversationally, confirm a clarifying-question round-trip works, confirm the canvas visibly updates after the AI builds it, close and reopen the flow and confirm the conversation history is still there, confirm an unrelated flow's chat panel starts with a clean/empty history (channel isolation actually works, not just claimed).
