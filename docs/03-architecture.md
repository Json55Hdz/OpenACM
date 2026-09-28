# Architecture

## Overview

OpenACM is built as a layered, event-driven system. At its core is the **Brain** — an agentic loop that receives messages, selects tools, calls the LLM, executes tool calls, and returns responses. Everything else — channels, the web dashboard, agents, swarms, the cron scheduler, plugins — communicates through the Brain or the shared **EventBus**.

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CHANNELS (Input)                           │
│   Web Chat  Telegram  Discord  WhatsApp  Console  (+ agent channels)│
└───────────────────────────────┬─────────────────────────────────────┘
                                │ message
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                              BRAIN                                  │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────────────┐   │
│  │ LocalRouter  │   │    Memory    │   │    Skill Manager      │   │
│  │ (classifier) │   │  (history)   │   │   (inject prompts)    │   │
│  └──────────────┘   └──────────────┘   └───────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                     Agentic Loop                             │   │
│  │   1. Build system prompt                                     │   │
│  │   2. Select tools (semantic similarity)                      │   │
│  │   3. Call LLM  ──────────────────────────────────────┐       │   │
│  │   4. Parse response                                   │       │   │
│  │   5. Execute tool calls ──────────────────────────────┘       │   │
│  │   6. Repeat until done (max_tool_iterations, default 25)      │   │
│  └──────────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ events
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           EVENT BUS                                 │
│  message.received  message.sent  tool.called  tool.result           │
│  message.thinking  llm.request  memory.recall  skill.active  swarm:* │
└───────┬────────────────────────────────────────────────┬────────────┘
        │                                                │
        ▼                                                ▼
┌───────────────┐                            ┌───────────────────────┐
│  Tool Registry│                            │  Web Server (FastAPI)  │
│  70+ tools    │                            │  REST + WebSocket      │
│  + MCP tools  │                            │  Dashboard frontend    │
└───────────────┘                            └───────────────────────┘
        │                                                │
        ▼                                                ▼
┌───────────────┐                            ┌───────────────────────┐
│   Security    │                            │      Database          │
│   Sandbox     │                            │  SQLite (aiosqlite)    │
│   Policies    │                            │  ChromaDB (RAG)        │
└───────────────┘                            └───────────────────────┘
```

---

## Component Breakdown

### Brain (`core/brain.py`)

The central orchestrator. Receives a message + context, runs the full agentic loop, returns a response.

**Responsibilities:**
- Build and maintain system prompt (base context + active skills + MCP tool list)
- Manage the agentic loop (up to `assistant.max_tool_iterations` tool-calling iterations — 25 in the shipped `default.yaml`)
- Select relevant tools via semantic similarity (or keyword fallback)
- Inject and parse tool call results back into the conversation
- Handle interruption and message queuing per channel
- Emit events for real-time frontend updates
- Passive learning: teach LocalRouter from tool usage patterns
- Track workflows for automation suggestions

The Brain is split into mixins: `brain_loop.py` (agentic loop + message preparation), `brain_prompt.py` (system prompt, RAG and skill injection), `brain_multimodal.py` (attachments: images, PDFs, audio, office files) and `brain_workflow.py` (workflow suggestions).

**Key methods:**
- `process_message()` — public entry point; wraps the run in a cancellable task per channel
- `_prepare_messages_for_llm()` — optimizes history before each LLM call (nulls old tool results, strips old tool-call arguments and reasoning content, replaces already-seen images with placeholders)
- `_execute_fast_path()` — skip LLM entirely for recognized simple intents
- `structured_extract()` — typed extraction via Instructor (see [Third-Party Integrations](./25-third-party-integrations.md))

Agents run through `AgentRunner` (`core/agent_runner.py`), which reuses the same Brain loop with the agent's own prompt, tool allowlist, knowledge base and flow tools.

---

### LLM Router (`core/llm_router.py`)

Unified interface to 100+ LLM providers via LiteLLM.

**Capabilities:**
- Retries with exponential backoff on transient errors (5xx, dropped connections) and HTTP 429 rate limits (honors `Retry-After`)
- Streaming support (yields tokens in real-time)
- Token usage tracking (persisted to database)
- Model persistence across restarts
- Provider profile system (handles quirks like Gemini's strict message format, providers that don't support tool calling)
- Custom provider support (OpenAI-compatible endpoints) and CLI providers (`claude`, `gemini`, `opencode` binaries)
- Strips `<think>` blocks and reasoning content from responses

**Provider Profiles** define per-provider behavior:
- `needs_tool_enforcement` — some models need a system message forcing tool use
- `max_tools_per_call` — cap tool count (e.g. Gemini has limits)
- `supports_streaming` — whether to use streaming mode

---

### Local Router (`core/local_router.py`)

Offline intent classifier using sentence-transformers.

**Purpose:** Classify user intents to enable fast-path execution (skip LLM) and passive learning.

**Model:** `paraphrase-multilingual-MiniLM-L12-v2` — 50+ language support, ~470MB, CPU-friendly.

**Modes:**
- `FAST_PATH MODE` (default, `local_router.observation_mode: false`): intercept recognized intents above `confidence_threshold` (0.88) and execute directly without an LLM call
- `OBSERVATION MODE` (`observation_mode: true`): classify silently in background, emit stats, never block the LLM

**Intents:** `OPEN_APP`, `PLAY_MEDIA`, `SCREENSHOT`, `SYSTEM_INFO`, `FILE_SIMPLE`, `WEB_SEARCH_SIMPLE`, `COMPLEX_TASK`

**Passive Learning:** When the LLM calls a tool on the first iteration (single tool call = unambiguous signal), the router learns to associate that message pattern with the tool's intent. No explicit labeling needed.

---

### Memory Manager (`core/memory.py`)

Per-conversation history management.

**Short-term memory:**
- In-memory cache (Python dict) keyed by `channel_id:user_id`
- Persisted to SQLite on every message
- Survives restarts: reloaded from DB on cache miss
- Truncation: drops oldest messages when over `max_context_messages` (default 50), never splitting a tool-call/tool-result pair
- Hard ceiling: never lets the estimated context exceed 85% of the model's context window
- Per-agent memory policy: a conversation can be reset after N hours of inactivity (`memory_ttl_hours`); old messages stay in SQLite but are not loaded back

**Conversation Compaction:**
When the estimated tokens reach `assistant.compact_ratio` (default 0.60) of the model's context window, older messages are summarized by the LLM into a single summary message, keeping the last `compact_keep_recent` (default 6) messages verbatim. `/compact` forces it.

```
Before compaction:
[system] [msg1] [msg2] ... [msg19] [msg20] [msg21] [msg22] [msg23] [msg24] [msg25]

After compaction:
[system] [summary of msg1-msg19] [msg20] [msg21] [msg22] [msg23] [msg24] [msg25]
```

---

### Tool Registry (`tools/registry.py`)

Manages all available tools and selects relevant ones per request.

**Tool Selection Strategy:**

1. **Conversational detection** — if the message is clearly a greeting or short chitchat (≤80 chars, no action keywords), send zero tools. Saves ~2-3K tokens.

2. **Semantic selection** — embed the user message with the same multilingual model, compute cosine similarity against all tool description embeddings. Only send tools above threshold (0.28). Language-agnostic.

3. **Keyword fallback** — if the embedding model hasn't loaded yet (first few seconds of startup), fall back to keyword-based category matching.

A small set of core tools (`send_file_to_chat`, `run_command`, `read_file`, `write_file`, `web_search`) is always included regardless of similarity score. Selected tools are sent as *slim schemas* (first sentence of the description, no parameter descriptions).

**Tool Embeddings:** Pre-computed at startup once the sentence-transformer model finishes loading. Cached for the lifetime of the process (~1ms per request for similarity computation).

---

### Security Layer (`security/`)

**Three levels:**

| Level | Component | What it does |
|-------|-----------|--------------|
| Policy | `SecurityPolicy` | Blocks dangerous patterns before execution |
| Sandbox | `Sandbox` | Limits runtime: timeout, output size |
| Tool | `ToolDefinition.risk_level` | Annotates tools as low/medium/high risk |

**Execution Modes** (apply to shell commands run through `run_command`):
- `confirmation` (default) — ask the user before every command
- `auto` — only commands whose executable is in `whitelisted_commands` run; everything else is rejected
- `yolo` — execute everything (use with caution)

**Always-blocked (hardcoded, no override):**
- Privilege escalation (`runas`, `gsudo`, `sudo -s`, `sudo -i`, `su -`, setuid/setgid `chmod`, `chown root`, adding Windows users/admins)
- Credential files (`/etc/shadow`, `/etc/passwd`)

See [Security](./12-security.md).

---

### Database (`storage/database.py`)

Async SQLite wrapper using `aiosqlite`. All writes are non-blocking.

**Schema overview:**

| Table | Purpose |
|-------|---------|
| `messages` | Conversation history (content encrypted at rest) |
| `tool_executions` | Log of every tool call with args, result, timing |
| `llm_usage` | Token counts and cost per LLM call |
| `skills` | Skill definitions (global, agent-private, worker-private and flow skills) |
| `settings` | Key-value store (schema version, model preference, security mode…) |
| `agents` | Agent definitions (prompt, tool policy, memory policy, inactivity follow-up) |
| `agent_channels` | Per-agent Telegram / WhatsApp channels |
| `agent_knowledge` | Per-agent knowledge base entries |
| `agent_skills` | Global skills enabled per agent |
| `flows` / `connections` | Agent visual flows and their external connections (WooCommerce) |
| `customer_names` | Names saved per conversation by `save_customer_name` |
| `webhook_connectors` / `webhook_connector_events` | Public webhook connectors and their audit log |
| `workflow_executions` / `workflow_suggestions` | Tool sequence history for pattern detection |
| `app_activities` | OS app focus sessions (fields encrypted) |
| `detected_routines` | Automation patterns (fields encrypted) |
| `cron_jobs` / `cron_job_runs` | Scheduled jobs and their run history |
| `swarms` / `swarm_workers` / `swarm_tasks` / `swarm_messages` / `swarm_templates` | Multi-agent swarms |
| `content_queue` / `social_credentials` | Content Automation plugin |
| `gmail_*` | Gmail Classifier plugin |
| `plugin_state` | Plugin enabled flags and settings |

**Migrations:** Automatic on startup. Current schema version: 41.

**Encryption:** Fernet (AES-128-CBC + HMAC) via `ActivityEncryptor`. Key stored at `config/activity.key` (auto-generated, git-ignored). Applies to:
- `messages.content`
- `app_activities.app_name`, `.window_title`, `.process_name`
- `detected_routines.name`, `.description`, `.apps`, `.trigger_data`

---

### Web Server (`web/server.py`)

FastAPI application serving:
- The Next.js compiled frontend (static export, SPA fallback)
- ~250 REST API endpoints split into routers under `web/routers/` (system, config, chat, skills, agents, mcp, activity, cron, swarms, voice, webhooks, whatsapp_webhook) plus plugin routers mounted under `/api/`
- WebSocket endpoints: `/ws/chat`, `/ws/events`, `/ws/terminal`, `/ws/swarms/{id}`
- Interactive API docs at `/api/docs`

**WebSockets:**

| Endpoint | Purpose |
|----------|---------|
| `/ws/chat` | Bidirectional chat — send messages, receive responses, or send `{type:"cancel"}` to abort |
| `/ws/events` | Server-sent events — real-time tool calls, thinking status, skill activation |
| `/ws/terminal?channel=<id>` | Full interactive PTY shell, one persistent session per channel. Powered by `pywinpty` (Windows) / `pty` (Linux/Mac) + xterm.js frontend |

**Authentication:** Token-based. Every `/api/*` request must include the dashboard token either as `Authorization: Bearer <token>` header or `?token=<token>` query parameter; WebSockets pass `?token=`. Public exceptions: the SPA and static assets, `/api/auth/check`, `/api/ping`, `/api/system/info`, `/api/config/google/callback`, `POST /api/webhooks/{slug}` (connectors authenticate themselves), plugin-declared public paths, and the WhatsApp webhook `/webhooks/whatsapp` (verified with Meta's signature). See [API Reference](./10-api-reference.md#authentication).

---

### Event Bus (`core/events.py`)

Pub/sub system for decoupling components.

**Event Types:**

| Event | Emitted by | Consumed by |
|-------|------------|-------------|
| `message.received` | Brain | EventBus WebSocket (dashboard) |
| `message.sent` | Brain | Channels, EventBus WebSocket |
| `message.thinking` | Brain | EventBus WebSocket (spinner UI) |
| `message.reasoning` | Brain | EventBus WebSocket (thinking content of reasoning models) |
| `context:stats` | Brain | EventBus WebSocket (live context usage) |
| `tool.called` | Brain | EventBus WebSocket, channel's PTY terminal |
| `tool.result` | Brain | EventBus WebSocket |
| `tool.output_stream` | Tools (run_command, run_python…) | Channel's PTY terminal (real-time streaming) |
| `llm.request` | LLM Router | EventBus WebSocket |
| `llm.response` | LLM Router | EventBus WebSocket |
| `tool.confirmation_needed` | Web server confirmation callback | EventBus WebSocket (approval dialog) |
| `memory.recall` | Brain | EventBus WebSocket (memory indicator) |
| `memory.compacted` | MemoryManager | EventBus WebSocket |
| `skill.active` | Brain | EventBus WebSocket (skill badge) |
| `router.learned` | LocalRouter | EventBus WebSocket |
| `swarm:*` | SwarmManager | EventBus WebSocket, `/ws/swarms/{id}` |
| `voice:daemon_state` | VoiceDaemon | EventBus WebSocket |
| `ha:state_changed` | Home Assistant plugin | EventBus WebSocket |
| `channel:send` | Agent inactivity follow-ups, plugins (e.g. Gmail daily summary) | Agent channels (proactive outbound messages) |

---

## Data Flow: A Single Message

```
1. User sends "take a screenshot"
   └─ via WebSocket /ws/chat

2. Brain.process_message() invoked
   ├─ LocalRouter.observe() → SCREENSHOT (confidence 0.94) [async, background]
   ├─ Memory.get_or_create() → conversation history loaded
   ├─ ToolRegistry.get_tools_by_intent()
   │   ├─ _is_conversational() → False (action keyword detected)
   │   └─ get_tools_semantic() → [take_screenshot, send_file_to_chat] (similarity > 0.28)
   └─ Agentic loop begins

3. Iteration 1:
   ├─ _prepare_messages_for_llm() → optimize history
   ├─ LLMRouter.chat() → model returns tool_call: take_screenshot({})
   ├─ EventBus.emit(tool.called) → dashboard shows "Executing take_screenshot..."
   ├─ ToolRegistry.execute(take_screenshot) → captures screen, saves to /api/media/screenshot_xxx.png
   └─ EventBus.emit(tool.result)

4. Iteration 2:
   ├─ LLMRouter.chat() → model returns tool_call: send_file_to_chat({path: "..."})
   ├─ ToolRegistry.execute(send_file_to_chat) → returns "ATTACHMENT:screenshot_xxx.png"
   └─ generated_attachments = ["screenshot_xxx.png"]

5. Iteration 3:
   ├─ LLMRouter.chat() → model returns text: "Here's your screenshot!"
   └─ Loop exits

6. Response sent:
   ├─ WebSocket.send_json({type: "response", content: "Here's your screenshot!", attachments: ["screenshot_xxx.png"]})
   ├─ EventBus.emit(message.sent) → other channels notified
   ├─ Memory.add_message() → saved to DB (encrypted)
   └─ Database.log_llm_usage() → token counts persisted

7. Frontend renders:
   ├─ Text: "Here's your screenshot!"
   └─ Image preview + Download button (parsed from attachments array)
```

---

## Startup Sequence

```
1. Load config (default.yaml + local.yaml + config/.env + env vars; auto-detect CLI providers)
2. Initialize Database (SQLite, run migrations; activity encryption key)
3. Initialize Security (policy + sandbox), LLM Router, Memory Manager
4. Initialize RAG Engine (ChromaDB)
5. Initialize Skill Manager (sync skills/ folder to DB)
6. Restore persisted model + security mode, initialize Brain + WorkflowTracker
7. Register tools (built-in modules; browser_agent unless features.browser_agent=false) + connect MCP servers
8. Start Channels (Discord, Telegram, WhatsApp) and wait until each is ready
9. Start Agent Channels (per-agent Telegram bots / WhatsApp numbers)
10. Generate or load the dashboard token
11. Start watchers: Activity Watcher, Code Resurrection, Cron Scheduler, Swarm Manager, Voice daemon (unless features.voice=false)
12. Load and start plugins (their tools, keywords, skills and routers)
13. Start Web Server (FastAPI + Next.js frontend)
14. Print status panel + token
15. Start LocalRouter warm-up in background (downloads model on first run)
    └─ On model loaded: precompute tool embeddings (semantic selection ready)
16. Enter console loop (or, without a TTY — Docker/systemd — just stay alive until SIGTERM)
```

---

## Frontend Architecture

Built with **Next.js 16** (App Router, static export), **React 19**, **TypeScript**, **Tailwind CSS 4**, **@xyflow/react** (flow editor), **xterm.js** (terminal) and **kokoro-js** (in-browser TTS).

**State management:** Zustand stores (`chat-store`, `dashboard-store`, `auth-store`, `terminal-store`, `sidebar-store`, `ha-store`, `tamagotchi-store`).

**Data fetching:** React Query (`@tanstack/query`) for REST endpoints. WebSocket connections managed in `use-websocket.ts` hook, initialized globally in `AppLayout`.

**Real-time updates:** The `/ws/events` WebSocket stream drives all live indicators (thinking spinner, tool execution badges, memory recall indicator, skill active badge, router learning indicator).

**Build output:** `next build` writes a static export to `frontend/dist/`, which is copied to `src/openacm/web/static/` (`npm run deploy`, or automatically by the setup/run/update scripts and the Docker build). FastAPI serves it as static files with SPA fallback.
