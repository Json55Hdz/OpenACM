# API Reference

OpenACM exposes a REST API and several WebSocket endpoints. All endpoints (except the public ones listed below) require authentication.

**Base URL:** `http://127.0.0.1:47821` (configurable with `web.host` / `web.port`)

Interactive OpenAPI docs (Swagger UI) are served at **`/api/docs`**.

---

## Authentication

All protected endpoints require the dashboard token (the `DASHBOARD_TOKEN` value in `config/.env`, printed at startup) as a Bearer token or query parameter:

```http
Authorization: Bearer <dashboard-token>
```

Or as a query parameter:

```http
GET /api/conversations?token=<dashboard-token>
```

WebSocket endpoints take the token as `?token=<dashboard-token>`.

**Public endpoints (no dashboard token):**
- `GET /api/ping`
- `GET|POST /api/auth/check`
- `GET /api/system/info`
- `GET /api/config/google/callback` (Google OAuth redirect)
- `POST /api/webhooks/{slug}` — each [webhook connector](./29-webhook-connectors.md) authenticates the request itself
- API paths a plugin declares public via `get_public_api_paths()` (routes that verify their own signature)
- `GET|POST /webhooks/whatsapp` — Meta WhatsApp webhook (outside `/api/`; POSTs are verified with `WHATSAPP_APP_SECRET`)
- The dashboard SPA and static assets

A request without a valid token gets `401 {"error": "Unauthorized. Provide a valid token."}`.

---

## System

### `GET /api/ping`
Health check. Returns immediately.

```json
{ "ok": true }
```

### `GET /api/system/info`
Version and system flags.

```json
{ "version": "0.4.7", "messages_encrypted": true }
```

### `POST /api/system/restart`
Restart the OpenACM process (replaces the process image via `os.execv`). Returns before the restart completes.

```json
{ "status": "restarting" }
```

### `POST /api/auth/check`
Verify a dashboard token (`GET /api/auth/check?token=...` also works).

**Request:**
```json
{ "token": "<dashboard-token>" }
```

**Response:** `200 {"valid": true}` or `401 {"valid": false}`.

### `GET /api/system/pick-folder`
Open a native folder picker on the host (desktop use). Returns `{"path": "..."}`.

---

## Statistics

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats` | Session totals: requests, tokens, cost, tool calls, conversations, current provider/model |
| `GET /api/stats/history?days=30` | Daily token and request usage |
| `GET /api/stats/channels` | Per-channel message counts |
| `GET /api/stats/detailed` | Token/cost breakdown: totals, by model, today, history |

---

## Conversations

### `GET /api/conversations`
List conversations with agent, channel and customer metadata. `?include_hidden=true` also returns conversations of agents with `show_in_chat: false`.

### `GET /api/conversations/{channel_id}/{user_id}`
Get conversation history.

**Query params:**
- `limit` (int, default 50) — max messages to return

### `DELETE /api/conversations/{channel_id}/{user_id}`
Delete all messages for a conversation (memory + database).

```json
{ "status": "ok", "deleted_rows": 18 }
```

---

## Chat

### `POST /api/chat/upload`
Upload a file to attach to the next message.

**Request:** `multipart/form-data` with a `file` field.

**Response:**
```json
{
  "file_id": "3f2a9c1e.png",
  "filename": "screenshot.png",
  "size": 284920,
  "content_type": "image/png"
}
```

Pass the returned `file_id` in the `attachments` array of the next `/ws/chat` message.

### `POST /api/chat/command`
Execute a slash command via REST.

**Request:**
```json
{ "command": "/new", "user_id": "web_xxx", "channel_id": "web" }
```

**Response:**
```json
{ "text": "Conversation cleared.", "data": null }
```

### `GET /api/terminal/history`
Recent terminal output for the dashboard terminal panel.

---

## Media

### `GET /api/media`
List files in `data/media/`.

### `GET /api/media/{file_name}`
Serve a media file. Images, video, audio and PDFs render inline; other files download.

**Query params:**
- `download=true` — force download (`Content-Disposition: attachment`)

---

## Tools

### `GET /api/tools`
List all registered tools.

```json
[
  {
    "name": "run_command",
    "description": "[OpenACM Tool] Execute commands directly in the operating system terminal...",
    "risk_level": "high",
    "parameters": { "type": "object", "properties": { "command": { "type": "string" } } },
    "category": "general"
  }
]
```

### `GET /api/tools/executions?limit=50`
Recent tool execution log (tool, arguments, truncated result, success, elapsed ms).

### `POST /api/tool/confirm`
Resolve a pending `run_command` confirmation (the dashboard's approval dialog uses this).

```json
{ "confirm_id": "…", "approved": true, "always_session": false, "command": "ls -la" }
```

---

## Configuration

| Endpoint | Description |
|----------|-------------|
| `GET /api/config` | Full configuration (API keys masked) |
| `GET /api/config/status` | Whether setup is still needed (no provider configured) |
| `GET /api/config/providers` | Which providers have credentials, plus Telegram/WhatsApp/Stitch flags |
| `POST /api/config/setup` | Write keys to `config/.env` (e.g. `{"OPENAI_API_KEY": "sk-..."}`) and hot-restart Telegram/WhatsApp when their keys change |
| `GET /api/config/model` | Current model: `{"model": "...", "provider": "..."}` |
| `POST /api/config/model` | Switch model: `{"provider": "ollama", "model": "llama3.2"}` (persisted) |
| `GET /api/config/available_models` | Models exposed by the current provider's API |
| `GET /api/config/model-params` | Stored `temperature` / `max_tokens` / `top_p` (current model, or `?provider=&model=`) |
| `PATCH /api/config/model-params` | Save params: `{"provider", "model", "temperature", "max_tokens", "top_p"}` |
| `GET /api/config/custom_providers` | List custom OpenAI-compatible providers (keys masked, `has_key`) |
| `POST /api/config/custom_providers` | Add one: `{"name", "base_url", "default_model", "api_key"}` |
| `PUT /api/config/custom_providers/{id}` | Update one |
| `DELETE /api/config/custom_providers/{id}` | Delete one |
| `PATCH /api/config/security` | `{"execution_mode": "confirmation" \| "auto" \| "yolo"}` (persisted) |
| `GET /api/config/assistant` / `PATCH /api/config/assistant` | Assistant identity (name, system prompt…) |
| `GET /api/config/local_router` / `POST /api/config/local_router` | Local router status/stats; set `enabled`, `confidence_threshold` (0.5–1.0) at runtime |
| `GET /api/config/rag_threshold` / `POST /api/config/rag_threshold` | RAG relevance threshold (persisted to `config/local.yaml`) |
| `GET /api/config/compaction` / `POST /api/config/compaction` | `compact_ratio`, `compact_keep_recent` (persisted to `config/local.yaml`) |
| `GET/POST/DELETE /api/config/resurrection_paths` | Code Resurrection folders (`{"path": "..."}`) |
| `POST /api/config/verbose_channels` | `{"enabled": false}` stops sending tool logs to external channels |
| `GET /api/config/debug_mode` / `POST /api/config/debug_mode` | Toggle DEBUG-level logging |
| `GET /api/config/client-profile` | Client profile (`active`, `name`, `allowed_pages`) |
| `GET /api/ollama/status` | Whether Ollama is running and its models |
| `GET /api/cli/status?binary=claude` | Whether a CLI binary is on PATH |

### Google OAuth

| Endpoint | Description |
|----------|-------------|
| `GET /api/config/google` | Whether credentials/token exist |
| `POST /api/config/google` | Upload the OAuth client JSON: `{"credentials_json": "..."}` → `config/google_credentials.json` |
| `DELETE /api/config/google` | Remove credentials and token |
| `POST /api/config/google/start_auth` | Start the OAuth flow → `{"url": "<Google consent URL>", "state": "..."}` |
| `GET /api/config/google/callback` | OAuth redirect target (public); stores `config/google_token.json` |

---

## Memory

| Endpoint | Description |
|----------|-------------|
| `GET /api/memory/stats` | RAG stats: total documents, breakdown by type, folder size |
| `DELETE /api/memory/all` | Delete **all** documents from the vector store |

Notes are added by the agent with `remember_note`; there is no REST endpoint to add individual notes.

---

## Skills

| Endpoint | Description |
|----------|-------------|
| `GET /api/skills` | List all skills (`id`, `name`, `description`, `category`, `is_active`, `is_builtin`…) |
| `GET /api/skills/active` | Currently active skills |
| `POST /api/skills` | Create: `{"name", "description", "content", "category"}` |
| `PUT /api/skills/{skill_id}` | Update |
| `DELETE /api/skills/{skill_id}` | Delete |
| `POST /api/skills/{skill_id}/toggle` | Flip active/inactive → `{"status": "ok", "toggled": true}` |
| `POST /api/skills/generate` | Generate a skill with the LLM from a description |

---

## Agents

### Core

| Endpoint | Description |
|----------|-------------|
| `GET /api/agents` | List agents (webhook secret stripped) |
| `POST /api/agents` | Create (see body below); the response includes `webhook_secret` |
| `GET /api/agents/{id}` | Get one |
| `PUT /api/agents/{id}` | Update any of: `name`, `description`, `system_prompt`, `allowed_tools`, `is_active`, `memory_mode`, `memory_ttl_hours`, `inactivity_timeout_minutes`, `inactivity_message`, `show_in_chat` |
| `DELETE /api/agents/{id}` | Delete (stops its channels) |
| `GET /api/agents/{id}/secret` | `{"webhook_secret": "..."}` |
| `POST /api/agents/generate` | Generate name/description/prompt from a description (JSON, or multipart with optional `file` documents) |
| `POST /api/agents/{id}/test` | Chat with the agent from the dashboard: `{"message", "channel_id"?, "extra_system_context"?}` → `{"response"}` |

**Create body:**
```json
{
  "name": "StoreBot",
  "description": "Answers customer questions",
  "system_prompt": "You are the assistant of Acme Store...",
  "allowed_tools": "all",
  "memory_mode": "session_ttl",
  "memory_ttl_hours": 24,
  "inactivity_timeout_minutes": 10,
  "inactivity_message": "Are you still there?",
  "show_in_chat": true
}
```

### `POST /api/agents/{agent_id}/chat`
Send a message to an agent from another system.

**Headers:** dashboard token **and** `X-Agent-Secret: <webhook_secret>`

**Request:**
```json
{ "message": "What are your opening hours?", "user_id": "customer-42" }
```

**Response:**
```json
{ "response": "We are open from 9am to 6pm.", "agent": "StoreBot" }
```

Errors: `401` wrong secret, `403` agent disabled, `404` unknown agent.

### Skills

| Endpoint | Description |
|----------|-------------|
| `GET /api/agents/{id}/skills` | `{"global_skills": [... "enabled"], "private_skills": [...]}` |
| `POST /api/agents/{id}/skills/{skill_id}` | Enable a global skill for this agent |
| `DELETE /api/agents/{id}/skills/{skill_id}` | Disable it |
| `POST /api/agents/{id}/skills/generate` | Generate a private skill: `{"name", "description", "use_cases"}` |

### Knowledge base

| Endpoint | Description |
|----------|-------------|
| `GET /api/agents/{id}/knowledge` | List entries (content omitted, `char_count` included) |
| `POST /api/agents/{id}/knowledge/text` | `{"title", "content"}` |
| `POST /api/agents/{id}/knowledge/file` | Multipart `file` (+ optional `title`); text is extracted |
| `PATCH /api/agents/{id}/knowledge/{kid}` | Update `title` / `content` |
| `DELETE /api/agents/{id}/knowledge/{kid}` | Delete |

### Channels

| Endpoint | Description |
|----------|-------------|
| `GET /api/agents/{id}/channels` | List (secrets masked, `is_connected`) |
| `POST /api/agents/{id}/channels` | `{"type": "telegram" \| "whatsapp" \| "whatsapp_web", "config": {...}}` |
| `PATCH /api/agents/{id}/channels/{cid}` | Update config / `is_active` |
| `DELETE /api/agents/{id}/channels/{cid}` | Delete (stops it) |
| `POST /api/agents/{id}/channels/{cid}/restart` | Restart → `{"ok": true, "connected": true}` |

Required config: `telegram` → `token`; `whatsapp` → `access_token`, `phone_number_id`; `whatsapp_web` → `bridge_url`.

### Flows

| Endpoint | Description |
|----------|-------------|
| `GET /api/agents/{id}/flows` | List flows |
| `GET /api/agents/{id}/flows/{flow_id}` | Get one (includes `graph_json`) |
| `POST /api/agents/{id}/flows` | Create `{"name", "description", "graph_json"?}` — without a graph, a valid Start→End skeleton is created |
| `PUT /api/agents/{id}/flows/{flow_id}` | Update `name`, `description`, `graph_json`, `is_active` (graph is validated, `400` if invalid) |
| `DELETE /api/agents/{id}/flows/{flow_id}` | Delete |
| `POST /api/agents/{id}/flows/{flow_id}/test` | Run it: `{"params": {...}, "graph_json"?: "<unsaved graph>"}` → `{"result", "outputs", "error"}` |
| `GET/POST/PUT/DELETE /api/agents/{id}/flows/{flow_id}/skill` | The flow's skill (one per flow; `409` if it already exists on POST) |
| `POST /api/agents/{id}/flows/{flow_id}/skill/generate` | Generate the flow's skill with the LLM |

### Connections

| Endpoint | Description |
|----------|-------------|
| `GET /api/agents/{id}/connections` | List |
| `POST /api/agents/{id}/connections` | `{"name", "type": "woocommerce", "url", "consumer_key", "consumer_secret"}` |
| `PUT /api/agents/{id}/connections/{cid}` | Update |
| `DELETE /api/agents/{id}/connections/{cid}` | Delete |

---

## Webhook Connectors

| Endpoint | Auth | Description |
|----------|------|-------------|
| `POST /api/webhooks/{slug}` | Connector's own scheme | Run the connector's flow with the request; returns `{"result": "..."}` |
| `GET /api/webhook-connectors` | Dashboard token | List (secrets masked as `***`) |
| `GET /api/webhook-connectors/{id}` | Dashboard token | Get one |
| `POST /api/webhook-connectors` | Dashboard token | Create `{"slug", "name", "auth_scheme", "auth_config", "flow_id", "dedupe_header"?}` |
| `PATCH /api/webhook-connectors/{id}` | Dashboard token | Update (sending `"***"` keeps a stored secret) |
| `DELETE /api/webhook-connectors/{id}` | Dashboard token | Delete |
| `GET /api/webhook-connectors/{id}/events` | Dashboard token | Audit log + stats |

See [Webhook Connectors](./29-webhook-connectors.md) for auth schemes and status codes.

---

## MCP Servers

| Endpoint | Description |
|----------|-------------|
| `GET /api/mcp/servers` | Configured servers with connection status and tools |
| `POST /api/mcp/servers` | Add: `{"name", "transport", "command", "args", "env", "url", "api_key", "headers", "auto_connect"}` |
| `PUT /api/mcp/servers/{name}` | Update |
| `DELETE /api/mcp/servers/{name}` | Remove (disconnects if connected) |
| `POST /api/mcp/servers/{name}/connect` | Connect → `{"status": "ok" \| "error", "connected", "error", "tools"}` |
| `POST /api/mcp/servers/{name}/disconnect` | Disconnect → `{"status": "ok", "disconnected": "<name>"}` |

---

## Cron Scheduler

| Endpoint | Description |
|----------|-------------|
| `GET /api/cron/jobs` | List jobs |
| `POST /api/cron/jobs` | Create `{"name", "description", "cron_expr", "action_type", "action_payload", "is_enabled"}` |
| `GET /api/cron/jobs/{id}` | Get one |
| `PUT /api/cron/jobs/{id}` | Update (only the fields sent) |
| `DELETE /api/cron/jobs/{id}` | Delete (and its run history) |
| `POST /api/cron/jobs/{id}/trigger` | Run now |
| `POST /api/cron/jobs/{id}/toggle` | Enable/disable |
| `GET /api/cron/runs?job_id=&limit=50` | Run history `{"runs": [...]}` |
| `GET /api/cron/status` | Scheduler status |

Details in [Cron Scheduler](./19-cron-scheduler.md).

---

## Routines & Activity

| Endpoint | Description |
|----------|-------------|
| `GET /api/routines` | Detected routines |
| `POST /api/routines/{id}/execute` | Launch a routine's apps → `{"status": "ok", "results": [...]}` |
| `PUT /api/routines/{id}` | Update (name, trigger, active…) |
| `DELETE /api/routines/{id}` | Delete |
| `POST /api/routines/analyze` | Run the pattern analyzer → `{"status": "ok", "new_routines": 2, "routines": [...]}` |
| `GET /api/activity/stats` | `{"apps": [...], "total_hours": 12.5, "session_count": 284}` |
| `GET /api/activity/sessions?limit=30` | Recent app focus sessions (decrypted) |
| `GET /api/watcher/status` | `{"running", "current_app", "current_title", "current_project", "sessions_recorded", "encrypted", "key_path"}` |
| `POST /api/watcher/toggle` | Start/stop the activity watcher → `{"running": false}` |

---

## Swarms

| Endpoint | Description |
|----------|-------------|
| `GET /api/swarms` | List |
| `POST /api/swarms` | Create (multipart: `name`, `goal`, `global_model`, files) |
| `GET /api/swarms/{id}` | Detail with workers and tasks |
| `DELETE /api/swarms/{id}` | Delete |
| `POST /api/swarms/{id}/clarify` | Generate clarification questions |
| `POST /api/swarms/{id}/clarify/answer` | Answer them and plan |
| `POST /api/swarms/{id}/plan` | Plan the team and tasks |
| `POST /api/swarms/{id}/start` / `stop` | Start/resume, or pause |
| `POST /api/swarms/{id}/tasks/{tid}/retry` | Retry a failed task (optional guidance) |
| `POST /api/swarms/{id}/tasks/{tid}/complete` | Mark a failed task done with a user-provided result |
| `PUT /api/swarms/{id}/workers/{wid}` | Update a worker (e.g. model) |
| `GET/POST/DELETE /api/swarms/{id}/workers/{wid}/skills[...]` | Worker skills (list, generate, enable/disable) |
| `GET /api/swarms/{id}/messages` | Activity feed |
| `GET /api/swarms/{id}/conversations[/{channel}/{user}]` | Worker conversations |
| `POST /api/swarms/{id}/message` | Send feedback to the swarm |
| `POST /api/swarms/{id}/complete` | Mark completed |
| `POST /api/swarms/{id}/check-reuse` / `reset` | Check whether the team fits a new goal / reset the swarm for re-use |
| `GET/POST /api/swarm-templates`, `DELETE /api/swarm-templates/{id}` | Saved swarm templates (usable from cron `run_swarm_template`) |
| `WS /ws/swarms/{id}` | Real-time swarm events |

Details in [Swarms](./22-swarms.md).

---

## Voice

| Endpoint | Description |
|----------|-------------|
| `GET/PATCH /api/voice/config` | Voice settings |
| `GET /api/voice/providers` | TTS providers (Kokoro, browser, OpenAI, ElevenLabs) |
| `GET /api/voice/voices` | Voices of the configured TTS provider |
| `POST /api/voice/tts` | Synthesize speech server-side |
| `GET /api/voice/daemon/status` | Voice daemon state and dependency check |
| `POST /api/voice/daemon/start` / `stop` | Start/stop the always-on daemon |
| `POST /api/voice/daemon/install` | Install optional voice deps (streams pip output) |
| `GET /api/voice/server-tts/voices` | edge-tts voices for server-side TTS |
| `GET /api/voice/devices` | Audio input devices on the server |
| `GET /api/voice/model/status` | Availability of server-side voice models |

See [Voice](./30-voice.md).

---

## Plugins

| Endpoint | Description |
|----------|-------------|
| `GET /api/plugins` | All plugins with enabled flag, config schema presence and `has_custom_ui` |
| `GET /api/plugins/nav` | Sidebar items contributed by enabled plugins |
| `POST /api/plugins/{name}/toggle` | Enable/disable (applies after restart) |
| `GET /api/plugins/{name}/config` | Config schema + saved values (passwords masked) |
| `POST /api/plugins/{name}/config` | Save config (`"***"` keeps a stored password) |
| `GET /api/plugins/docs` | Plugin authoring guide (Markdown) |

Plugin routers are mounted under `/api/` — e.g. `/api/gmail-classifier/*` ([Gmail Classifier](./31-gmail-classifier.md)) and `/api/home-assistant/*` (`devices`, `areas`, `devices/{entity_id}/control`, `scenes`, `scenes/{entity_id}/activate`).

---

## Content Automation

| Endpoint | Description |
|----------|-------------|
| `GET /api/content/queue` | Queued posts |
| `POST /api/content/queue/{id}/approve` / `reject` | Approve (publish) or reject |
| `DELETE /api/content/queue/{id}` | Delete |
| `GET /api/content/pending-count` | Number of posts waiting for approval |
| `GET /api/content/sessions` | Captured content sessions |
| `GET/POST /api/social/credentials`, `POST /api/social/credentials/{platform}/verify`, `DELETE /api/social/credentials/{platform}` | Facebook / Reddit credentials |

---

## Debug

### `GET /api/debug/traces?limit=20`
Most recent agentic loop traces (newest first).

```json
[
  {
    "user_message": "take a screenshot",
    "iterations": [
      {
        "iteration": 1,
        "message_count": 4,
        "context_chars": 2400,
        "llm_elapsed_ms": 834,
        "tool_calls": [
          { "tool": "take_screenshot", "result_chars": 45, "elapsed_ms": 312 }
        ]
      }
    ],
    "total_elapsed_ms": 1842,
    "outcome": "success"
  }
]
```

`outcome` is `running`, `success`, `error` or `timeout`.

### `DELETE /api/debug/traces`
Clear stored traces.

---

## WhatsApp Cloud API Webhook

| Endpoint | Description |
|----------|-------------|
| `GET /webhooks/whatsapp` | Meta's verification handshake (`hub.verify_token` must match the global or an agent's verify token) |
| `POST /webhooks/whatsapp` | Incoming messages; validated with `X-Hub-Signature-256` and routed to an agent channel by `phone_number_id`, or to the global channel |

---

## WebSocket: Chat (`/ws/chat`)

Connect with token:
```
ws://127.0.0.1:47821/ws/chat?token=<dashboard-token>
```

### Client → Server

**Send a message:**
```json
{
  "message": "Take a screenshot of my screen",
  "target_user_id": "web",
  "target_channel_id": "web",
  "attachments": []
}
```

`user_id` / `channel_id` are accepted as aliases. Messages starting with `/` are handled as slash commands.

**Cancel current request** (stops the active agentic task for this channel):
```json
{
  "type": "cancel",
  "target_user_id": "web",
  "target_channel_id": "web"
}
```

### Server → Client

**Response message:**
```json
{
  "type": "response",
  "content": "Here's your screenshot!",
  "attachments": ["screenshot_1775274080.png"]
}
```

**Error:**
```json
{
  "type": "error",
  "content": "Connection to LLM failed"
}
```

**Command result:**
```json
{
  "type": "command",
  "content": "Conversation cleared.",
  "data": null
}
```

If no chat client is connected when a response is ready, it is buffered and delivered to the next client that connects.

---

## WebSocket: Events (`/ws/events`)

Connect with token:
```
ws://127.0.0.1:47821/ws/events?token=<dashboard-token>
```

Server-only stream. Every event is sent as `{"type": "<event name>", ...payload}`. Event names: `message.received`, `message.sent`, `message.thinking`, `message.reasoning`, `message.reasoning_stream`, `tool.called`, `tool.result`, `tool.confirmation_needed`, `tool.validation`, `llm.request`, `llm.response`, `router.learned`, `skill.active`, `memory.recall`, `memory.compacted`, `context:stats`, `swarm:*`, `content:*`, `voice:daemon_state`, `ha:state_changed`.

**Thinking status:**
```json
{
  "type": "message.thinking",
  "status": "processing",
  "message": "🔄 Step 2/25...",
  "iteration": 2,
  "user_id": "web_xxx",
  "channel_id": "web",
  "channel_type": "web"
}
```

**Tool called:**
```json
{
  "type": "tool.called",
  "tool": "web_search",
  "arguments": "{\"query\": \"AI news\"}",
  "user_id": "web_xxx",
  "channel_id": "web",
  "channel_type": "web"
}
```

**Tool result:**
```json
{
  "type": "tool.result",
  "tool": "web_search",
  "result": "1. OpenAI releases...",
  "user_id": "web_xxx",
  "channel_id": "web",
  "channel_type": "web"
}
```

**Message sent (partial):**
```json
{
  "type": "message.sent",
  "content": "I'll search for that now...",
  "partial": true,
  "channel_type": "web",
  "channel_id": "web"
}
```

**Memory recall:**
```json
{
  "type": "memory.recall",
  "status": "found",
  "count": 2,
  "channel_id": "web",
  "channel_type": "web"
}
```

**Skill active:**
```json
{
  "type": "skill.active",
  "skills": ["code-reviewer"],
  "channel_id": "web",
  "channel_type": "web"
}
```

---

## WebSocket: Terminal (`/ws/terminal`)

Connect with token and channel:
```
ws://127.0.0.1:47821/ws/terminal?token=<dashboard-token>&channel=web
```

**`channel`** — the chat channel ID this terminal belongs to (e.g. `web`, a Telegram chat id). Each channel gets its own persistent PTY shell session. The session survives WebSocket reconnects, so SSH connections and running processes are not interrupted.

The terminal is a **full interactive PTY** (Windows: ConPTY via `pywinpty`; Linux/Mac: `pty` module). The frontend renders it with [xterm.js](https://xtermjs.org/) for proper ANSI color support, prompt display, and keyboard handling.

### Client → Server

**User input** (keystroke data, exactly as xterm.js produces it):
```json
{"type": "input", "data": "ls -la\n"}
```

**Signal** (Ctrl+C):
```json
{"type": "signal"}
```

**Terminal resize** (sent automatically when the panel resizes):
```json
{"type": "resize", "cols": 220, "rows": 50}
```

### Server → Client

**Shell output** (raw PTY bytes, includes ANSI escape codes):
```json
{"type": "output", "data": "\u001b[32muser@host\u001b[0m:/home/user$ "}
```

**AI tool command** (shown in magenta in the terminal):
```json
{"type": "ai_command", "tool": "run_command", "data": "npm install"}
```

**AI tool streaming output**:
```json
{"type": "ai_output", "tool": "run_command", "data": "added 142 packages in 3.2s\n"}
```

**Shell exited**:
```json
{"type": "exit", "data": "shell process exited"}
```

**Error** (e.g. PTY failed to start):
```json
{"type": "error", "data": "Failed to start shell: ..."}
```

---

## WebSocket: Swarm (`/ws/swarms/{id}`)

Real-time events for one swarm (`swarm:updated`, `swarm:task_updated`, `swarm:message`, …). See [Swarms](./22-swarms.md#events).

---

## Error Codes

| HTTP Code | Meaning |
|-----------|---------|
| 200 | Success |
| 400 | Bad request (missing field, invalid flow graph, invalid JSON) |
| 401 | Missing or invalid token / secret / webhook signature |
| 403 | Forbidden (e.g. agent disabled) |
| 404 | Resource not found |
| 409 | Conflict (duplicate connector slug, flow already has a skill) |
| 422 | Validation error (invalid request body) |
| 500 | Server error (e.g. misconfigured webhook connector flow) |
| 502 | A webhook connector's flow failed at runtime |
| 503 | Service not available (Brain or Database not initialized) |
