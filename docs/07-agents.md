# Agents

Agents are specialized assistants that run on OpenACM's shared infrastructure (LLM router, tool registry, memory) but have their own system prompt, a restricted set of tools, a knowledge base, a memory policy, their own channels (Telegram bot, WhatsApp number) and their own visual flows. While the main OpenACM agent is a generalist, agents are specialists — for example a customer-service bot for a store, or a research assistant.

---

## How Agents Work

Each agent has:
- **Name and description** — displayed in the dashboard
- **System prompt** — defines the agent's persona, rules and expertise
- **Tools access** (`allowed_tools`) — `"all"`, `"none"` (text only), or a JSON list of tool names
- **Knowledge base** — text snippets and uploaded files injected into its prompt
- **Skills** — global skills enabled for it, plus its own private skills
- **Flows** — visual automations it can call as tools (see [Agent Flows](./28-agent-flows.md))
- **Channels** — optional Telegram bot, WhatsApp Business number (Cloud API) or WhatsApp Web bridge
- **Memory policy** — remember forever, or reset context after N hours of inactivity
- **Inactivity follow-up** — optional nudge message if the customer goes silent
- **Webhook secret** — for the `/api/agents/{id}/chat` API

When an agent receives a message, `AgentRunner` runs it through the same agentic loop as the main agent (with at most 10 tool iterations per message), using a fresh copy of the agent's configuration so edits in the dashboard take effect immediately. The tool allowlist is enforced at the registry level, not just in the prompt. Each agent's conversations live in their own channel namespace (`agent_<id>` by default), isolated from the main chat and from other agents.

---

## Creating an Agent

### Via Dashboard
**Agents** → **New Agent** → fill in the form. You can also describe the agent you want (optionally attaching a document) and let the LLM generate the name, description and system prompt (`POST /api/agents/generate`).

### Via Chat
```
You: Create an agent called "ResearchBot" that specializes in finding
     and summarizing online information. Give it access to all tools.
     It should be concise, cite sources, and prefer primary sources.
```

The main agent uses the `create_agent` tool (`allowed_tools` is `"all"` or `"none"` from chat; restrict it to a list from the dashboard).

### Via API
```bash
curl -X POST http://localhost:47821/api/agents \
  -H "Authorization: Bearer <dashboard-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ResearchBot",
    "description": "Finds and summarizes information",
    "system_prompt": "You are a research specialist. Always cite sources. Prefer academic and primary sources.",
    "allowed_tools": "[\"web_search\", \"get_webpage\", \"remember_note\"]",
    "memory_mode": "persistent"
  }'
```

`name` and `system_prompt` are required. The creation response includes the agent's `webhook_secret` (it is stripped from later reads; fetch it again with `GET /api/agents/{id}/secret`).

---

## Tools Access

| Value | Meaning |
|-------|---------|
| `"all"` | Every registered tool |
| `"none"` | No tools — text-only answers (flows are disabled too) |
| `["web_search", "get_webpage"]` (JSON string) | Only those tools |

An agent's **active flows** are always added on top of its allowlist as `flow_<id>` tools (unless tools are `"none"`).

---

## Knowledge Base

The **Knowledge** tab stores reference material for the agent: business hours, prices, FAQs, policies…

- Add **text** entries (title + content) or upload **files** — plain text is read directly; PDFs, Office documents and other binary formats are converted to text with MarkItDown.
- On every message, all entries are injected at the top of the agent's system prompt under a "Base de conocimiento" section, capped at 40,000 characters.

API: `GET/POST /api/agents/{id}/knowledge`, `POST /api/agents/{id}/knowledge/text`, `POST /api/agents/{id}/knowledge/file`, `PATCH/DELETE /api/agents/{id}/knowledge/{kid}`.

---

## Memory Policy

| `memory_mode` | Behavior |
|---------------|----------|
| `persistent` (default) | The agent remembers each conversation forever (subject to normal compaction) |
| `session_ttl` | If the last message of a conversation is older than `memory_ttl_hours` (default 24), the context starts fresh. Old messages stay in SQLite for audit; they are just not reloaded |

### Customer name

Independently of the memory policy, the `save_customer_name` tool stores the customer's name per conversation. It survives every reset and is injected into the agent's prompt so it can keep greeting the customer by name.

---

## Inactivity Follow-up

Set `inactivity_timeout_minutes` (0 = off) and optionally `inactivity_message`. After the agent replies, a timer starts; if the customer does not write again before it expires, the agent proactively sends the follow-up message on the same channel (Telegram / WhatsApp) and records it in the conversation. Any new customer message cancels the timer.

---

## Channels

Each agent can have one active channel of each type (**Agents → Channels**):

| Type | Required config | Notes |
|------|-----------------|-------|
| `telegram` | `token` | The agent gets its own Telegram bot (create it with @BotFather) |
| `whatsapp` | `access_token`, `phone_number_id` (+ `verify_token`, `app_secret`) | Official Meta WhatsApp Cloud API. Messages arrive through the shared `/webhooks/whatsapp` webhook and are routed to the agent by `phone_number_id` |
| `whatsapp_web` | `bridge_url` | Unofficial whatsapp-web.js bridge; each agent needs its own bridge instance |

Channels start automatically with OpenACM and can be restarted from the dashboard (`POST /api/agents/{id}/channels/{cid}/restart`). Secrets are masked in API responses. See [WhatsApp Setup](./WHATSAPP_SETUP.md) for the Meta side.

In the dashboard **Chat** page, conversations coming from agent channels are grouped into one folder per agent. Uncheck **show in chat** (`show_in_chat: false`) to hide an agent's folder.

---

## Skills

The **Skills** tab of an agent lets you:
- Enable global skills for this agent only (`POST/DELETE /api/agents/{id}/skills/{skill_id}`)
- Generate private skills with the LLM (`POST /api/agents/{id}/skills/generate`) that only this agent sees

---

## Flows and Connections

The **Flows** tab opens the visual flow editor. Every active flow becomes a tool the agent can call. Flows can use **connections** (currently WooCommerce stores: URL + consumer key/secret) configured per agent. See [Agent Flows](./28-agent-flows.md).

---

## Messaging an Agent

### Via its channels
Customers message the agent's Telegram bot or WhatsApp number directly.

### Via the dashboard
Use the agent's **Test** panel (`POST /api/agents/{id}/test`) to chat with it; flow chat panels use the same endpoint.

### Via API
```bash
curl -X POST http://localhost:47821/api/agents/1/chat \
  -H "Authorization: Bearer <dashboard-token>" \
  -H "X-Agent-Secret: <webhook_secret>" \
  -H "Content-Type: application/json" \
  -d '{"message": "What are your opening hours?", "user_id": "customer-42"}'
```

Response: `{"response": "...", "agent": "ResearchBot"}`. The agent must be active (`is_active`); the `X-Agent-Secret` header must match its webhook secret. Like every `/api/*` route, this endpoint is also behind the dashboard token.

---

## Use Cases

### Customer Service Bot
```
Agent: "StoreBot"
Channels: WhatsApp Business
Knowledge: opening hours, shipping policy, return policy
Flows: "search products" (WooCommerce node)
Memory: session_ttl, 24 h · Inactivity follow-up: 10 min
Prompt: "You are the assistant of Acme Store. Answer only with information from the knowledge base and the product search."
```

### Specialized Bots
Give friends or colleagues Telegram bots with limited, safe capabilities:

```
Agent: "ScheduleBot"
Tools: ["calendar_list", "calendar_create", "gmail_read"]
Prompt: "Help users manage their schedule. Only create events they explicitly confirm."
```

### Research Assistants
```
Agent: "ResearchBot"
Tools: ["web_search", "get_webpage", "remember_note", "search_memory"]
Prompt: "Research topics thoroughly. Store key findings in memory. Synthesize, don't just copy."
```

### IoT Controller
```
Agent: "HomeBot"
Tools: ["ha_devices", "ha_control", "ha_status"]
Prompt: "Control smart home devices. Always confirm before turning off devices that might be in use."
```

---

## Agent vs Main Agent

| Feature | Main Agent | Agent |
|---------|-----------|-----------|
| Tool access | All registered tools | Allowlist + its own flows |
| Memory | Shared conversation DB | Separate per-agent conversations, optional TTL |
| System prompt | Config default + skills | Custom per-agent + knowledge base + agent skills |
| Channels | Web, Console, global Telegram/Discord/WhatsApp | Own Telegram bot / WhatsApp number |
| Max tool iterations | `assistant.max_tool_iterations` (25) | 10 |

---

## Security Considerations

- Agents are isolated by tool allowlist — they cannot call tools outside their allowed list (plus their own flows)
- Agent conversations are stored separately in the database (by agent channel)
- If you give an agent `run_command` (or `"all"`), it has the same OS access as the main agent — anyone who can message its public Telegram/WhatsApp channel can then drive it. Keep customer-facing agents on a minimal allowlist
- The `run_command` confirmation prompt appears in the dashboard, not in the customer's chat
