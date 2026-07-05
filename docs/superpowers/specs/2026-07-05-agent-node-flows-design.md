# Agent Node Flows — Design Spec

## Context

This is sub-project 2 of the "subagent superpowers" initiative for OpenACM's **Agents** feature (`/agents` — standalone AI agents with their own Telegram/WhatsApp channel, knowledge base, and webhook). Sub-project 1 (tool + skill scoping — checkbox selection of existing tools, plus system/private skills) already shipped (`docs/superpowers/plans/2026-07-05-agent-tools-and-skills-scoping.md`) and is live on `/agents` in a 5-tab detail view (Config, Knowledge, Channels, Herramientas, Skills).

This sub-project adds a **visual node-based builder** for creating brand-new custom tools out of connected steps (e.g., "call this API, check a condition, query my WooCommerce store"), so agents can be built into much more capable chatbots — e.g. a sales assistant on WhatsApp Business that can check product availability on the user's own store.

Sub-projects 3 (import/export of an agent's full config) and 4 (full-screen editor — likely unnecessary for Agents, since the 5-tab detail view already covers this) remain future work, not part of this spec.

## Reference material

A divergent branch (`Cristian/woocommerce`, commit `0dffcbf`) already contains a hardcoded WooCommerce search tool (`woocommerce_search`) — `GET /wp-json/wc/v3/products` with HTTP Basic Auth using a WooCommerce REST API consumer key/secret, returning up to 5 formatted results (name, price, stock, truncated description, permalink). Per explicit user direction, **only this API-calling logic is reused** as the implementation template for this spec's WooCommerce node — the rest of that branch (schema version 31, direct `woo_*` columns on `agents`, unrelated date-injection/WhatsApp-formatting changes) is not part of this design; `main` has progressed well past that branch.

## What's new

### 1. Core architecture: a flow becomes a tool

A **Flow** is a sequence of connected nodes that, once saved, is dynamically registered as **one more tool** available to that agent — it shows up in the same tool list already built in sub-project 1 (Herramientas tab), and the agent's LLM decides when to call it, exactly like any other tool. This is not a parallel automation system that runs independently of the LLM (rejected n8n-style "always runs on every message" model) — a flow is a way to *build* a tool visually instead of in Python code, reusing the exact same "agent → tool list → LLM decides" pattern that already works everywhere else in the app.

```
User builds a flow visually (new "Flujos" tab)
        │
        ▼
Saved as JSON (nodes + edges) in the database
        │
        ▼
Dynamically exposed as a ToolDefinition: name, description, and
parameters come from the flow's Start node — the agent's LLM sees
it exactly like any other tool in its list
        │
        ▼
When the LLM calls it → FlowExecutor walks the graph:
Start → [HTTP / Conditional / WooCommerce...] → End
        │
        ▼
The End node's output becomes the tool call's return value
```

### 2. Data model

- **`flows`** (new table): `id, agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE, name TEXT, description TEXT, graph_json TEXT, is_active INTEGER DEFAULT 1, created_at, updated_at`. A flow is **100% private to one agent** — same scoping decision as sub-project 1's private skills, no sharing between agents. `description` is what the LLM reads to decide when to call it — same role as any other tool's description.
- **`connections`** (new table, reusable credentials): `id, agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE, name TEXT, type TEXT (e.g. 'woocommerce'), config TEXT (JSON: url, consumer_key, consumer_secret), created_at`. A Connection is created once (e.g. "Mi Tienda WooCommerce") and can be selected from any WooCommerce node in any flow belonging to that same agent — avoids re-entering credentials per-flow. Stored as plain text, consistent with every other secret in this codebase (`webhook_secret`, `telegram_token`, `DASHBOARD_TOKEN` are all plain-text columns/env vars protected by the dashboard's auth boundary, not field-level encryption — see Security section for why this spec doesn't introduce a new, inconsistent encryption scheme). Connection credentials are **never returned** in any API response after creation — only overwritable, matching the existing `webhook_secret` pattern.
- **`graph_json` shape**: `{"nodes": [{"id": str, "type": "start"|"http"|"conditional"|"woocommerce"|"end", "config": {...}, "position": {"x": num, "y": num}}], "edges": [{"from": str, "to": str, "fromHandle": "default"|"true"|"false"}]}`. `fromHandle` is what lets the Conditional node branch into two continuations (`true`/`false`); every other node has exactly one outgoing edge with `fromHandle: "default"`.

### 3. Node types (v1)

| Node | What it does | Configuration |
|---|---|---|
| **Start** | Declares the parameters the LLM can pass to this flow (e.g. `producto: string`). Exactly one per flow, always first. | List of `{name, type, description, required}` parameters — this becomes the flow's tool-call JSON schema. |
| **HTTP Request** | Calls any URL — GET/POST, headers, body. The result (parsed JSON or raw text) is available to the next node. | `url`, `method`, `headers`, `body` — any of these may reference `{{param_name}}` (from Start) or `{{node_id.field}}` (from an earlier node's output). |
| **Conditional** | Evaluates a single fixed-operator condition against the previous node's output and branches into two continuations. | `field` to evaluate, `operator` (`contains` / `equals` / `is_empty` / `is_error`), `value` to compare against. No arbitrary expression evaluation — operators are a closed set, not a scripting language, to avoid injection. |
| **WooCommerce Query** | Searches products by name/keyword against a saved Connection's store — same request shape as the reference implementation (`GET {url}/wp-json/wc/v3/products?search=...` with Basic Auth using the Connection's consumer key/secret), top 5 results formatted with name/price/stock/truncated description/permalink. | Which saved Connection to use, `search_term` (may reference `{{param_name}}`). |
| **End** | Declares what the flow returns to the LLM as the tool call's result. Exactly one per linear path, always last. | Free-text template referencing `{{previous_node.field}}`, or "return raw output" of the previous node. |

Any node (except Start/End) can fail (timeout, HTTP error, missing Connection). On failure, the flow stops at that node and returns an error string as the tool call's result — same behavior as any existing tool failing today, letting the LLM explain the failure to the end user rather than crashing the conversation.

### 4. Flow topology

Linear chain with exactly one branch point: nodes execute one after another in sequence, except the Conditional node, whose two outputs (`true`/`false`) each continue their own independent linear chain to their own End node. No loops, no multiple-inputs-into-one-node, no rejoining branches — this keeps both the execution engine and the visual canvas simple to build, validate (no cycle detection needed), and understand for a non-technical end user.

### 5. Node output & template substitution (precise semantics)

Every node's output is stored as a single value keyed by its node id. `{{node_id}}` alone always refers to that whole value. `{{node_id.field}}` does a one-level key lookup into it, only when the value is a JSON object — if it's a plain string (e.g. the WooCommerce node's formatted text, or an HTTP response that wasn't valid JSON) and a template references `.field` anyway, substitution resolves to an explicit `[missing: node_id.field]` marker rather than silently inserting an empty string, so a misconfigured flow fails loudly (visible in the End node's output, or during "Probar flujo") instead of quietly returning garbage to the LLM. Concretely, per node type:
- **HTTP Request**: response body, parsed as JSON if the `Content-Type` says so or it parses cleanly, else the raw response text.
- **Conditional**: passes its input through unchanged (it only decides which branch to take, it doesn't transform data).
- **WooCommerce Query**: the same formatted multi-line string the reference implementation already produces (name/price/stock/description/link per product) — a plain string, not structured JSON, so only whole-value `{{node_id}}` substitution applies to it, never `.field`.

### 6. Execution engine — `FlowExecutor`

A small, purpose-built Python interpreter — no new heavyweight workflow-engine dependency (rejected in favor of this, since v1 only needs 5 node types and one branch point, which a generic external engine would be overkill for):

```python
class FlowExecutor:
    async def run(self, graph_json: dict, params: dict, get_connection: Callable) -> str:
        # 1. Validates params against the Start node's declared schema
        # 2. Walks nodes in order (linear, following the single branch at
        #    a Conditional node based on its evaluated result)
        # 3. Each node type dispatches to its own handler:
        #    _run_http_node, _run_conditional_node, _run_woocommerce_node
        # 4. Each node's output is stored keyed by node id, available to
        #    later nodes via {{node_id.field}} template substitution
        # 5. The End node's resolved template is the return value
        # 6. Any handler exception stops the walk and returns an error
        #    string instead of raising — matches how every other tool
        #    reports failure to the LLM today
```

When a flow is saved and `is_active`, it is registered as a dynamic `ToolDefinition` (same dataclass every static `@tool`-decorated function uses) whose `handler` is a thin wrapper calling `FlowExecutor.run(graph_json, ...)` — the agent's LLM cannot tell the difference between this and a hand-written Python tool.

### 7. Backend API (under the existing `agents.py` router, same conventions as sub-project 1's skills endpoints)

- `GET /api/agents/{agent_id}/flows` — list flows (without full `graph_json`, for a lightweight list view).
- `GET /api/agents/{agent_id}/flows/{flow_id}` — full flow detail including `graph_json`, for opening the editor.
- `POST /api/agents/{agent_id}/flows` — create.
- `PUT /api/agents/{agent_id}/flows/{flow_id}` — update (the editor saves the whole `graph_json` on every change).
- `DELETE /api/agents/{agent_id}/flows/{flow_id}` — delete.
- `POST /api/agents/{agent_id}/flows/{flow_id}/test` — execute the flow immediately with test parameters, returning the result — lets the user verify a flow works before it goes live for the real agent, same idea as the existing "Test this agent" dashboard panel.
- `GET /api/agents/{agent_id}/connections` — list (name/type only, never credentials).
- `POST /api/agents/{agent_id}/connections` — create.
- `PUT /api/agents/{agent_id}/connections/{id}` — update (overwrite credentials; still never returns them).
- `DELETE /api/agents/{agent_id}/connections/{id}` — delete.

### 8. Frontend — new "Flujos" tab

A sixth tab in the existing agent detail view (`AgentDetailView`, alongside Config/Knowledge/Channels/Herramientas/Skills):

- A list of the agent's flows (name, description, active/inactive toggle, Edit/Delete) — same card-list pattern as Skills' private-skill list.
- Opening a flow (or creating a new one) opens a visual node editor built with **React Flow** (`@xyflow/react`) — the standard library for this in React; not currently a project dependency, needs to be added. Canvas with drag-and-drop node placement and connection-drawing, plus a side panel to configure whichever node is selected (fields differ per node type, per the table in section 3).
- The WooCommerce node's config includes a Connection dropdown (populated from `GET /api/agents/{agent_id}/connections`) plus a "+ New connection" action that opens a small form (name, store URL, consumer key, consumer secret) — posts to the Connections endpoint.
- A "Probar flujo" (Test flow) button runs the `/test` endpoint with user-entered sample parameters and displays the result inline, before the flow is marked active for the real agent.

### 9. Security

- **Connection credentials** are stored as plain text, consistent with every other secret already in this codebase (`webhook_secret`, `telegram_token`, `DASHBOARD_TOKEN`) — this project's file-encryption mechanism (`security/crypto.py`) is legacy/deprecated (new media files are stored unencrypted already), so introducing a new, different encryption scheme just for Connections would be inconsistent with the rest of the app's actual security model, which is "protect via the dashboard's own auth boundary," not per-field encryption. Credentials are never returned by any API response after creation.
- **No arbitrary code execution.** There is no "custom code" node type in v1 — the Conditional node's condition is a closed set of fixed operators (`contains` / `equals` / `is_empty` / `is_error`), never an evaluated expression, so there is no code-injection surface.
- **SSRF is an accepted, pre-existing risk, not newly introduced.** The HTTP node can target any URL from the server, including internal addresses — this spec does not add a URL allowlist/denylist, because no other HTTP-calling tool already in the codebase (the WooCommerce reference tool, `browser_agent.py`, `social_media_tool.py`) has one either, and the dashboard is a single-trusted-administrator surface, not multi-tenant. This keeps the new feature consistent with the existing trust model rather than introducing a stricter one only here.

### 10. Testing

- **Backend:** migration tests for `flows`/`connections`; `FlowExecutor` unit tests per node type with `httpx` mocked (no real network calls); CRUD endpoint tests for flows/connections; a test confirming an active flow is actually exposed as a callable `ToolDefinition` to the agent.
- **Frontend:** `tsc --noEmit` clean (no test framework exists for this file today, consistent with the rest of the project) **plus an actual manual browser verification of the node canvas before that task is marked complete** — sub-project 1 skipped this once and it was flagged as the single biggest unverified risk in that plan's final review; this sub-project treats it as a required step, not optional.

## Explicitly out of scope (this sub-project)

- Loops, multi-input nodes, or branches that rejoin (full generic DAG execution).
- A "custom code" node type (would require sandboxing arbitrary user code — not attempted here).
- Sharing/reusing a single flow across multiple agents (flows are 100% agent-private, matching skills).
- Import/export of flows (sub-project 3's concern).
- Any change to the existing Config/Knowledge/Channels/Herramientas/Skills tabs.
