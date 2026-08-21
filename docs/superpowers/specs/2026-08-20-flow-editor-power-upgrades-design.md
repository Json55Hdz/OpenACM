# Flow Editor Power Upgrades — Design Spec

## Context

This is the next round of work on the Agent Node Flows feature (`/agents` → Flujos tab), building on three already-shipped, human-verified plans: `2026-07-05-agent-node-flows` (core engine + canvas), `2026-07-05-flow-editor-unreal-style` (category colors, right-click node search, Inspector polish v1), and `2026-07-06-flow-editor-get-set-variables` (Set/Get nodes + Variables panel). See `.superpowers/sdd/progress.md` for that history.

This round covers four independent-but-related upgrades, chosen from a longer list of deferred/out-of-scope items surfaced while auditing the prior work: branch-rejoin topology, copy/paste, a per-flow skill, and Inspector polish v2. Each is scoped tightly enough to ship in one implementation plan; none requires touching the shared `Brain` agentic loop that both Agents and the main assistant depend on.

Two items raised in conversation are explicitly **not** part of this spec, pending the user's own browser verification first: node delete + multi-select (React Flow's defaults already wire this up via `applyNodeChanges`/`applyEdgeChanges` — nothing in the codebase disables it, so it may already work) and any changes to Set/Get variables (the user suspects something is off but hasn't confirmed what after testing).

## What's new

### 1. Branch-rejoin (merge) topology

Today, a Conditional node's `true`/`false` branches must each end in their own End node — if both branches need to do the same thing afterward (e.g. both format a response the same way), that logic has to be duplicated on both paths. This adds the ability for both branches to point to the **same downstream node** instead.

**Why this doesn't need a general DAG engine:** a Conditional only ever takes one branch per execution — never both. So "merge" here is not a join that waits for two inputs; it's simply allowing two edges to share a target. `FlowExecutor.run()` is already a single `current_id` pointer walking the graph one node at a time (`src/openacm/core/flow_executor.py:146-206`) — it never inspected incoming-edge count, so most node types already handle a shared target correctly with zero changes.

The one place this breaks today: the `set` node resolves its source via `edges_by_target.get(node["id"])` (`flow_executor.py:175`), a static reverse-edge map built once from the whole graph — with two incoming edges, that map can only remember one of them (dict overwrite), silently picking the wrong source depending on iteration order. Fix: replace the static `edges_by_target` lookup with a `previous_id` variable the `run()` loop already updates every iteration — it always reflects the node actually visited just before, correct regardless of how many edges point at the current node in the *graph*, because only one of them is ever the *real* predecessor in a given run. `edges_by_target` is removed entirely once nothing else needs it.

**Cycle safety (two layers, since this loosens edge constraints):**
- **Save-time validation:** `PUT /flows/{id}` (and the `/test` endpoint's live `graph_json` override) runs a cycle check over the graph before persisting/executing. A cycle is rejected with an error naming the nodes involved — caught in the editor, not mid-conversation when an agent actually calls the tool.
- **Runtime cap (defense in depth):** `FlowExecutor.run()`'s `while current_id:` loop gets a hard iteration cap (e.g. 50 node visits) that returns `"Error: flow exceeded maximum node visits (possible cycle)"` rather than hanging — covers any cycle that somehow reaches runtime despite the save-time check (e.g. a row edited directly, or a future code path that writes `graph_json` without going through the validated endpoint).

**Frontend:** `onConnect` needs no change — React Flow's default `addEdge` never restricted incoming-edge count. What does need fixing is the Inspector's variable-picker backward walk (`FlowCanvas.tsx:60-76`, `incomingBySource`), which also assumes one predecessor per node. It becomes a union over every path that can reach the selected node, so a variable-picker shows references from either branch — consistent with the existing rule that an unreachable-at-runtime reference resolves to `[missing: node_id.field]` rather than being hidden. A node with 2+ incoming edges gets a small visual marker (e.g. a merge-point badge) so it reads as an intentional join, not an accidental duplicate connection.

### 2. Copy/paste

`Ctrl+C` over the current selection (one or more nodes) stores a copy in component state (not the OS clipboard, so it doesn't fight with native copy/paste in text fields elsewhere on the page). `Ctrl+V` creates fresh nodes with new ids, offset by a fixed amount (e.g. +40px/+40px) from the originals. Only edges *between copied nodes* are preserved — an edge to a node outside the copied selection is dropped, so pasting never creates a dangling connection into the original graph. Start and End are singleton per flow (enforced elsewhere in the spec chain) and are silently excluded from the copy if selected — no error, they just don't duplicate.

Delete and multi-select are believed to already work via React Flow's built-in keyboard/selection handling and the existing `onNodesChange`/`onEdgesChange` → `applyNodeChanges`/`applyEdgeChanges` wiring (`FlowCanvas.tsx:194-195`) — no code in the canvas disables this. This spec does not change them; they should be confirmed in the manual verification pass (Testing section) and only get their own follow-up work if that confirms an actual gap.

### 3. Per-flow skill

A flow can carry one optional "skill" — richer guidance for the LLM than the flow's plain `description` field, following the same pattern already used three times in this codebase for global/worker/agent skills (`skills.worker_id`, `skills.agent_id`).

**Data model:** `skills.flow_id INTEGER REFERENCES flows(id) ON DELETE CASCADE` (nullable), plus a unique index on `(name, flow_id) WHERE flow_id IS NOT NULL` and updating the existing global-uniqueness index to also exclude `flow_id IS NOT NULL` — same shape as migrations 32/33. Unlike agent/worker skills (many togglable global skills per scope), a flow-skill is **singular**: a flow has zero or one of its own, private, non-togglable skill. No join table needed.

**Activation — deliberately not the existing always-on mechanism.** Agent skills are injected unconditionally into the system prompt in `AgentRunner.run()`, before `Brain` is even constructed (`src/openacm/core/agent_runner.py:164-167`) — that happens too early to know which tools (including which flow-tools) will actually be relevant to this specific message, and doing it unconditionally doesn't scale if an agent has many flows each with a long skill. Instead: `AgentRunner.run()` already builds the flow-tools dict and already has the incoming `message` in scope: reordered slightly, it calls the same intent-based tool selection (`_AgentToolRegistry.get_tools_by_intent(message)`) it already uses elsewhere, and only for whichever `flow_<id>` tools that selection actually surfaces for this message does it look up and append that flow's skill content to the system prompt. This is entirely self-contained inside `agent_runner.py` — no changes to the shared `Brain`/agentic-loop code the main assistant also runs through.

**API:** `GET/POST/PUT/DELETE /api/agents/{agent_id}/flows/{flow_id}/skill`, plus `POST /api/agents/{agent_id}/flows/{flow_id}/skill/generate` reusing the existing LLM-assisted skill-drafting flow (`generate_agent_skill`'s pattern) — the generator reads the flow's own graph (node types, descriptions, Start parameters) to draft when/how to use it.

**Frontend:** a "Skill" button in the canvas toolbar (next to "Guardar flujo" / "Probar flujo") opens a panel with an editable name + content field and a "Generar con IA" action.

### 4. Inspector v2 — sections + live template preview

**Collapsible sections** are added only where a node genuinely has more than one logical group of fields — HTTP ("Request": url + method / "Headers & Body") and Start (general info / parameter list). Conditional, WooCommerce, Set, and Get stay flat (1-2 fields each); wrapping them in a collapsible section would add clicks without adding clarity. A reusable `InspectorSection` component is introduced for this, adoptable later if another node type grows enough fields to need it.

**Live template preview:** any field that accepts `{{...}}` (HTTP url/headers/body, Conditional `field`, WooCommerce `search_term`, End `template`) gets a small preview showing what the template would currently resolve to. This requires the `/test` endpoint to also return the full `outputs` dict (keyed by node id) alongside the existing result string — not a new security exposure, since node outputs never include Connection credentials. The frontend caches that `outputs` dict after each "Probar flujo" run; while editing a field, the preview resolves locally against the cached outputs (no network round-trip per keystroke). Before any test has run in the current editor session, the preview area shows a hint ("corré 'Probar flujo' para ver valores reales acá") instead of blank space that could be mistaken for an empty resolution.

## Explicitly out of scope (this round)

- Real loops/cycles as a feature (foreach, retry/poll-until-condition) — the user confirmed the actual need was branch-rejoin, not iteration; true cycles remain rejected at save time.
- A "custom code" node type — still rejected for the same injection-surface reason as the original spec.
- Copy/paste across different flows or agents — flows remain 100% private per agent, consistent with every prior decision in this feature.
- Any change to Set/Get variables or to node delete/multi-select — pending the user's own manual re-verification; each becomes its own follow-up only if that verification finds a real gap.
- Toggling/sharing a flow-skill across multiple flows, or making it a many-per-flow list — a flow-skill is singular by design in this round.
- Full-screen editor and import/export of a flow's config (previously deferred sub-projects 3/4) — untouched here.

## Testing

- **Backend:** unit tests for the `previous_id`-based `set` node fix specifically under a merge (two incoming edges), the save-time cycle-detection function (accepts a valid graph with a merge, rejects a graph with a real cycle, names the cycle's nodes in the error), the runtime iteration cap, and the flow-skill CRUD + generate endpoints (including that generated/stored skill content is only injected when `get_tools_by_intent` actually selects that flow's tool for a given test message, and is absent otherwise).
- **Frontend:** `tsc --noEmit` clean, plus **required manual browser verification** before this plan is considered complete — this codebase's own history shows plan checkboxes and even commit messages can drift from what was actually verified, so the verification session itself should leave a durable note (progress ledger entry, not just an unmarked checkbox) confirming: a merge point renders and resolves correctly for both branches; a save with a real cycle is rejected in the editor; copy/paste round-trips only internal edges; a flow-skill's content is visible in context only when its flow-tool is actually selected; the Inspector's new sections collapse/expand and the live preview updates after a test run. The same pass should also finally confirm or deny node delete + multi-select and the Set/Get variables concern raised in conversation, so those stop being open questions.

## Explicitly out of scope note on prior audit gaps

This spec doesn't re-litigate whether the three prior plans (agent-node-flows, flow-editor-unreal-style, flow-editor-get-set-variables) are complete — `.superpowers/sdd/progress.md` confirms all three were implemented, reviewed, and human-verified in browser. This spec only adds new surface on top of that confirmed baseline.
