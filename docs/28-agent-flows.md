# Agent Flows

**Flows** are visual automations that belong to an [agent](./07-agents.md). A flow is a node graph — a Start node with parameters, some steps (HTTP calls, conditions, loops, WooCommerce product search, variables) and an End node that returns text. Every **active** flow becomes a tool the agent can call, so the LLM decides *when* to run it and the flow decides *exactly how*. A flow can also be triggered from outside through a [webhook connector](./29-webhook-connectors.md).

Flows run deterministically in `FlowExecutor` (`src/openacm/core/flow_executor.py`) — no LLM is involved while a flow executes.

---

## Where to find them

**Agents → (open an agent) → Flujos (Flows)**:
- **+ Nuevo flujo** creates a flow with a valid Start → End skeleton
- **Importar flujo** pastes a previously exported JSON
- The checkbox next to each flow marks it **active** (only active flows become tools)
- Clicking a flow opens the **flow editor**

---

## The Flow Editor

An Unreal-Blueprint-style node canvas (built on `@xyflow/react`):

- **Add nodes** by right-clicking the canvas (categories: FLUJO, LÓGICA, INTEGRACIONES, DATOS) or by dragging them in
- **Wire pins**: white *flow* pins define execution order; coloured *data* pins pass a value from one node's output into another node's input field
- **Inspector**: select a node to edit its config; text fields offer a variable picker populated with the real output shape of the last test run (including nested paths)
- **Guardar flujo** saves; the graph is validated on the server (`400` with the reasons if invalid)
- **▶ Probar flujo** runs the current canvas — even unsaved — with test parameters and shows each node's output and the final result
- **Exportar** downloads the flow as JSON (`{"kind": "openacm-flow", "version": 1, "name", "description", "graph_json"}`)
- **Chat panel**: describe what you want ("when the product isn't found, call this API…") and the agent builds or edits the flow for you with the `create_or_update_agent_flow` tool, using the current graph as context. Nodes without a position are laid out automatically
- **+ Skill**: attach a skill that explains to the agent when and how to use this flow (write it or generate it with AI)

---

## Node Types

| Node | Config | Flow pins | Data pins |
|------|--------|-----------|-----------|
| `start` | `parameters: [{name, type: string\|number\|boolean, description, required}]` | out: `default` | — (parameters are referenced as `{{name}}`) |
| `http` | `url`, `method` (GET/POST/PUT/DELETE), `headers`, `body` | in/out: `default` | in: `url`, `body` · out: `response` |
| `conditional` | `field`, `operator` (`contains`, `equals`, `is_empty`, `is_error`), `value` | in: `default` · out: `true`, `false` | in: `field`, `value` · out: `result` |
| `woocommerce` | `connection_id`, `search_term` | in/out: `default` | in: `search_term` · out: `result`, `count` |
| `loop` | `max_iterations` (default 200) | in: `default` · out: `loop` (per item), `done` | in: `items` (must be wired to a list) · out: `item`, `index` |
| `set` | `name` | none (pure node) | in: `value` (must be wired) · out: `value` — readable as `{{name}}` |
| `get` | `name` | none (pure node) | out: `default` |
| `end` | `template` | in: `default` | — returns the template with `{{…}}` substituted |

Rules enforced by the validator: exactly one `start`, at least one `end`, unique node ids, edges pointing at existing nodes, known node types, no flow-edge cycles (loops iterate through the `loop` node, never through a back-edge), and a flow-out pin can't be wired into a data-in pin.

### Behaviour notes

- **HTTP**: 15 s timeout; a non-2xx response is an error. The response is parsed as JSON when possible, otherwise kept as text.
- **Conditional**: `contains` / `equals` compare the resolved `field` with `value`; `is_empty` checks for an empty string; `is_error` checks whether the value starts with "error" — useful after an HTTP node.
- **Loop**: the chain wired to `loop` runs once per item; when that chain reaches a dead end the executor advances to the next item automatically (no back-wire needed), then follows `done`. Loops can be nested.
- **WooCommerce**: searches published products (up to 10) in the store of a WooCommerce **connection**, returning a formatted list (name, price, stock, link) and a count. Products without a price are reported as out of stock.
- A run is capped at 2,000 node visits as a safety net.

---

## Templates

Any text field that is not fed by a data wire can use templates:

| Template | Resolves to |
|----------|-------------|
| `{{param}}` | A Start parameter, or a variable saved by a `set` node |
| `{{node_id}}` | The whole output of a node |
| `{{node_id.field}}` | A field of a node's output (JSON) |
| `{{node_id.items[0].name}}` | Nested paths with array indexes and multiple hops |

---

## Connections

Flows reach external systems through per-agent **connections**. Currently the only type is **WooCommerce** (store URL + REST API consumer key/secret). Manage them from the flow editor or via `/api/agents/{id}/connections`. A `woocommerce` node references a connection by `connection_id`.

---

## Flows as Agent Tools

When an agent runs, each active flow is exposed to the LLM as a tool:

- **Name:** `flow_<id>`
- **Description:** the flow's description (or its name) — write it so the LLM knows when to use it
- **Parameters:** the Start node's parameters (with their types, descriptions and `required` flags)
- **Result:** the End node's rendered template (or an `Error: …` string)

Flow tools are added on top of the agent's tool allowlist (they are disabled only when the agent's tools are `"none"`). If the flow has a **skill**, that skill is injected into the prompt when the user's message is relevant to the flow's name/description.

### Example

"Search the store; if nothing is found, say so politely":

```json
{
  "nodes": [
    {"id": "start", "type": "start", "config": {"parameters": [
      {"name": "query", "type": "string", "description": "What the customer is looking for", "required": true}
    ]}},
    {"id": "search", "type": "woocommerce", "config": {"connection_id": 1, "search_term": "{{query}}"}},
    {"id": "check", "type": "conditional", "config": {"field": "{{search.count}}", "operator": "equals", "value": "0"}},
    {"id": "none", "type": "end", "config": {"template": "No products found for {{query}}."}},
    {"id": "found", "type": "end", "config": {"template": "{{search.result}}"}}
  ],
  "edges": [
    {"from": "start", "to": "search", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
    {"from": "search", "to": "check", "fromHandle": "default", "toHandle": "default", "kind": "flow"},
    {"from": "check", "to": "none", "fromHandle": "true", "toHandle": "default", "kind": "flow"},
    {"from": "check", "to": "found", "fromHandle": "false", "toHandle": "default", "kind": "flow"}
  ]
}
```

---

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/agents/{id}/flows` | List flows |
| `POST /api/agents/{id}/flows` | Create (`name`, `description`, optional `graph_json` string) |
| `PUT /api/agents/{id}/flows/{flow_id}` | Update `name`, `description`, `graph_json`, `is_active` |
| `DELETE /api/agents/{id}/flows/{flow_id}` | Delete |
| `POST /api/agents/{id}/flows/{flow_id}/test` | Run with `{"params": {...}, "graph_json"?}` → `{"result", "outputs", "error"}` |
| `…/flows/{flow_id}/skill` (+ `/generate`) | The flow's skill |

`graph_json` is sent and stored as a JSON **string**. From chat, the main assistant can create or edit flows with the `create_or_update_agent_flow` tool (pass `agent_id`; inside an agent's own chat it is detected automatically).
