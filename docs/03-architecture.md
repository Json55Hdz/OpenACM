# Architecture

## Overview

OpenACM is built as a layered, event-driven system. At its core is the **Brain** — an agentic loop that receives messages, selects tools, calls the LLM, executes tool calls, and returns responses. Everything else — channels, the web dashboard, channels, the activity watcher — communicates through the Brain or the shared **EventBus**.

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CHANNELS (Input)                           │
│   Web Chat    Telegram    Discord    WhatsApp    Console             │
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
│  │   6. Repeat until done (max 20 iterations)                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ events
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           EVENT BUS                                 │
│  message.received  message.sent  tool.called  tool.result           │
│  thinking  llm.request  memory.recall  skill.active                 │
└───────┬────────────────────────────────────────────────┬────────────┘
        │                                                │
        ▼                                                ▼
┌───────────────┐                            ┌───────────────────────┐
│  Tool Registry│                            │  Web Server (FastAPI)  │
│  42+ tools    │                            │  REST + WebSocket      │
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
- Manage the agentic loop (up to 20 tool-calling iterations)
- Select relevant tools via semantic similarity (or keyword fallback)
- Inject and parse tool call results back into the conversation
- Handle interruption and message queuing per channel
- Emit events for real-time frontend updates
- Passive learning: teach LocalRouter from tool usage patterns
- Track workflows for automation suggestions

**Key methods:**
- `process_message()` — public entry point; wraps `_run()` in a cancellable task
- `_run()` — builds context, selects tools, executes agentic loop
- `_prepare_messages_for_llm()` — optimizes history before each LLM call (truncates old tool results, strips reasoning content)
- `_execute_fast_path()` — skip LLM entirely for recognized simple intents

---

### LLM Router (`core/llm_router.py`)

Unified interface to 100+ LLM providers via LiteLLM.

**Capabilities:**
- Transparent failover between providers
- Streaming support (yields tokens in real-time)
- Token usage tracking (persisted to database)
- Model persistence across restarts
- Provider profile system (handles quirks like Gemini's strict message format, providers that don't support tool calling)
- Custom provider support (OpenAI-compatible endpoints)

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
- `OBSERVATION MODE` (default): classify silently in background, emit stats, never block LLM
- `FAST_PATH MODE`: intercept recognized intents and execute directly without LLM call

**Intents:** `OPEN_APP`, `PLAY_MEDIA`, `SCREENSHOT`, `SYSTEM_INFO`, `FILE_SIMPLE`, `WEB_SEARCH_SIMPLE`, `COMPLEX_TASK`

**Passive Learning:** When the LLM calls a tool on the first iteration (single tool call = unambiguous signal), the router learns to associate that message pattern with the tool's intent. No explicit labeling needed.

---

### Memory Manager (`core/memory.py`)

Per-conversation history management.

**Short-term memory:**
- In-memory cache (Python dict) keyed by `channel_id:user_id`
- Persisted to SQLite on every message
- Survives restarts: reloaded from DB on cache miss
- Truncation: drops oldest messages when over `max_context_messages` (default 50)
- Token budget: drops messages when estimated token count exceeds 16,000

**Conversation Compaction:**
After 25 messages, older messages are automatically summarized by the LLM into a single "summary" message. This keeps context window usage low in long conversations.

```
Before compaction (25 messages):
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

`send_file_to_chat` is always included regardless of similarity score.

**Tool Embeddings:** Pre-computed at startup once the sentence-transformer model finishes loading. Cached for the lifetime of the process (~1ms per request for similarity computation).

---

### Security Layer (`security/`)

**Three levels:**

| Level | Component | What it does |
|-------|-----------|--------------|
| Policy | `SecurityPolicy` | Blocks dangerous patterns before execution |
| Sandbox | `Sandbox` | Limits runtime: timeout, output size |
| Tool | `ToolDefinition.risk_level` | Annotates tools as low/medium/high risk |

**Execution Modes:**
- `confirmation` — ask user before executing medium/high risk tools
- `auto` — execute whitelisted tools automatically
- `yolo` — execute everything (use with caution)

**Always-blocked (hardcoded, no override):**
- Privilege escalation (`sudo su`, `RunAs /priv`, registry key manipulation)
- Credential file access (`.ssh/id_rsa`, SAM database, etc.)
- UAC/sudo dialog manipulation

---

### Database (`storage/database.py`)

Async SQLite wrapper using `aiosqlite`. All writes are non-blocking.

**Schema overview:**

| Table | Purpose |
|-------|---------|
| `messages` | Conversation history (content encrypted at rest) |
| `tool_executions` | Log of every tool call with args, result, timing |
| `llm_usage` | Token counts and cost per LLM call |
| `skills` | Skill definitions (name, description, markdown content) |
| `settings` | Key-value store (schema version, model preference) |
| `agents` | Agent definitions and credentials |
| `workflow_executions` | Tool sequence history for pattern detection |
| `activity_sessions` | OS app focus sessions (fields encrypted) |
| `detected_routines` | Automation patterns (fields encrypted) |
| `agent_custom_tools` | Dynamically created tools per agent |

**Migrations:** Automatic on startup. Current schema version: 5.

**Encryption:** AES-GCM via `ActivityEncryptor`. Key stored at `data/.activity_key`. Applies to:
- `messages.content`
- `activity_sessions.app_name`, `.window_title`, `.process_name`
- `detected_routines.name`, `.description`, `.apps`, `.trigger_data`

---

### Web Server (`web/server.py`)

FastAPI application serving:
- The Next.js compiled frontend (static files)
- ~60 REST API endpoints
- 3 WebSocket endpoints

**WebSockets:**

| Endpoint | Purpose |
|----------|---------|
| `/ws/chat` | Bidirectional chat — send messages, receive responses, or send `{type:"cancel"}` to abort |
| `/ws/events` | Server-sent events — real-time tool calls, thinking status, skill activation |
| `/ws/terminal?channel=<id>` | Full interactive PTY shell, one persistent session per channel. Powered by `pywinpty` (Windows) / `pty` (Linux/Mac) + xterm.js frontend |

**Authentication:** Token-based. Every request (REST + WS) must include the dashboard token either as `Authorization: Bearer <token>` header or `?token=<token>` query parameter. Public paths: `/`, `/static/`, `/_next/`, `/api/auth/check`, `/api/ping`.

---

### Event Bus (`core/events.py`)

Pub/sub system for decoupling components.

**Event Types:**

| Event | Emitted by | Consumed by |
|-------|------------|-------------|
| `message.received` | Channels | EventBus WebSocket (dashboard) |
| `message.sent` | Brain | Channels, EventBus WebSocket |
| `thinking` | Brain | EventBus WebSocket (spinner UI) |
| `tool.called` | Brain | EventBus WebSocket, channel's PTY terminal |
| `tool.result` | Brain | EventBus WebSocket |
| `tool.output_stream` | Tools (run_command, run_python…) | Channel's PTY terminal (real-time streaming) |
| `llm.request` | LLM Router | EventBus WebSocket |
| `llm.response` | LLM Router | EventBus WebSocket |
| `memory.recall` | Brain | EventBus WebSocket (memory indicator) |
| `skill.active` | Brain | EventBus WebSocket (skill badge) |
| `router.learned` | LocalRouter | EventBus WebSocket |
| `workflow.suggestion` | WorkflowTracker | EventBus WebSocket |

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
1. Load config (YAML + .env + env vars)
2. Initialize Database (SQLite, run migrations)
3. Initialize Security (policy + sandbox)
4. Initialize LLM Router (restore persisted model preference)
5. Initialize Memory Manager
6. Initialize RAG Engine (ChromaDB) [optional]
7. Initialize Skill Manager (sync skills/ folder to DB)
8. Initialize Brain (wires all components together)
9. Register all tools (42+ built-in, IoT, Stitch, MCP)
10. Start Channels (Discord, Telegram, WhatsApp)
11. Start Agent Bots (per-agent Telegram bots)
12. Start Activity Watcher
13. Start Web Server (FastAPI + Next.js frontend)
14. Print banner + token
15. Start LocalRouter warm-up in background (downloads model on first run)
    └─ On model loaded: precompute tool embeddings (semantic selection ready)
16. Enter console loop
```

---

## Frontend Architecture

Built with **Next.js 14** (App Router), **React 18**, **TypeScript**, **Tailwind CSS**.

**State management:** Zustand stores (`chat-store`, `dashboard-store`, `auth-store`, `terminal-store`).

**Data fetching:** React Query (`@tanstack/query`) for REST endpoints. WebSocket connections managed in `use-websocket.ts` hook, initialized globally in `AppLayout`.

**Real-time updates:** The `/ws/events` WebSocket stream drives all live indicators (thinking spinner, tool execution badges, memory recall indicator, skill active badge, router learning indicator).

**Build output:** `frontend/.next/` is copied to `src/openacm/web/static/` during the build step. FastAPI serves it as static files with SPA fallback.
