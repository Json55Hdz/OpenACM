# Dashboard

The OpenACM dashboard is a built-in web interface available at `http://127.0.0.1:47821` (or whatever host/port you configure). It requires no extra setup — it starts with OpenACM.

---

## Accessing the Dashboard

1. Start OpenACM: `python -m openacm`
2. Open your browser to `http://127.0.0.1:47821`
3. If a `DASHBOARD_TOKEN` is set in your config, you'll be prompted to enter it on first load

The token is stored in your browser's `localStorage` and is checked automatically on all API calls.

---

## Pages Overview

### Chat

The primary interface. Full-featured chat with the OpenACM agent.

**Features:**
- **Real-time streaming** — responses appear word-by-word as generated
- **Cancel button** — while the agent is thinking, the send button turns into a red ✕ button; clicking it cancels the current request immediately
- **Conversation sidebar** — all past conversations listed on the left
- **New conversation** — each session gets a unique ID; history persists
- **New conversation badge** — conversations with no messages show a "New" indicator
- **Delete conversation** — hover over a conversation in the sidebar to reveal the delete button (external channel conversations only)
- **Tool execution log** — toggle to see each tool call and its result inline
- **File uploads** — drag-and-drop or click to attach images, PDFs, audio, text files
- **Image preview** — images sent by the agent render inline with a download button
- **Encryption badge** — a lock icon in the sidebar header when messages are encrypted at rest
- **Model indicator** — shows current provider and model in the chat header

**Slash commands** (type in the chat input):
```
/model ollama/llama3.2        Switch to a different model mid-conversation
/model anthropic/claude-opus-4-6
/new                          Start a fresh conversation (equivalent to new chat)
/models                       List available models
/tools                        List available tools
/config                       Show current configuration
/help                         Show all commands
```

**File upload behavior:**
- Images → sent as vision input to the LLM (if model supports it)
- Audio/voice → transcribed via Whisper and injected as text
- Documents (PDF, text) → content extracted and added to context

---

### Dashboard (Stats)

Go to **Dashboard** in the left navigation.

**Activity Chart** — Token usage over time (last 7/30 days). Shows prompt tokens vs. completion tokens as a bar chart.

**Stats Cards:**
- Total messages processed
- Total tokens used (prompt + completion)
- Total tool calls executed
- Average response time (ms)
- Current model (provider + model name)

**LLM Call Log** — Recent LLM requests with model, token counts, and elapsed time.

---

### Agents

Go to **Agents** in the left navigation.

Lists all sub-agents with their name, description, allowed tools, and (optional) Telegram bot status.

**Actions:**
- **New Agent** → form to create a new agent (name, description, system prompt, tool whitelist, Telegram token)
- **Edit** → modify an existing agent
- **Delete** → remove an agent
- **Test** → send a test message to an agent and see its response

---

### Tools

Go to **Tools** in the left navigation.

Lists all registered tools (built-in + runtime-created + MCP) grouped by category.

**For each tool:**
- Name, description, category, risk level
- Parameter schema
- Source (built-in, runtime, or MCP server name)

**Create Tool button** → opens an interface to create a new runtime tool (delegates to the `create_tool` agent command).

---

### Skills

Go to **Skills** in the left navigation.

Lists all skills in the `skills/` directory organized by subdirectory.

**For each skill:**
- Name, file path, description (extracted from markdown heading)
- Active/inactive status (whether it was injected in the last request)

**Create Skill button** → delegates to the `create_skill` tool.

---

### MCP

Go to **MCP** in the left navigation.

Lists all configured MCP servers with their connection status.

**For each server:**
- Name, transport type, command/URL
- Connected/Disconnected status with error message if failed
- Number of tools exposed
- Tool list (expandable)

**Actions:**
- **Add Server** → form to register a new MCP server
- **Connect / Disconnect** → toggle connection per server
- **Delete** → remove server configuration

---

### Config

Go to **Config** in the left navigation.

**Current Model** — Dropdown to switch the active LLM provider and model. Change persists across restarts.

**Custom Providers** — Add, edit, and remove custom OpenAI-compatible LLM endpoints.

**Security** — Shows current execution mode (`sandbox`, `confirm`, `direct`) and allows changing it.

**System Prompt** — View and edit the assistant's custom system prompt from the dashboard.

---

### Routines

Go to **Routines** in the left navigation.

Displays patterns detected by the Activity Watcher's Pattern Analyzer.

**For each routine:**
- Name and description (LLM-generated)
- App list with process names
- Trigger type (`time_based` or `manual`)
- Trigger time and days
- Confidence score (0–100%)
- Occurrence count (how many times detected)

**Actions:**
- **Analyze now** → trigger a fresh pattern analysis
- **Delete** → remove a routine
- **Toggle active** → enable/disable a routine

---

### Activity

Go to **Activity** in the left navigation (if enabled in config).

Shows the current Activity Watcher status and recent app focus sessions.

**Current App** — Real-time display of the currently focused application.

**Recent Sessions** — Table of the last N app focus records:
- App name and window title
- Focus duration
- Timestamp

**Watcher controls:**
- **Start / Stop** — toggle the background watcher

---

## WebSocket Protocol

The chat interface communicates with the backend via three WebSocket connections:

### Chat WebSocket
```
ws://127.0.0.1:47821/ws/chat?token=<your_token>
```

Client sends a message:
```json
{
  "message": "What's my disk usage?",
  "target_user_id": "web",
  "target_channel_id": "web"
}
```

Client cancels the current request:
```json
{
  "type": "cancel",
  "target_user_id": "web",
  "target_channel_id": "web"
}
```

Server sends:
```json
{"type": "response", "content": "Your disk usage is 87% full.", "attachments": []}
```

### Events WebSocket
```
ws://127.0.0.1:47821/ws/events?token=<your_token>
```

Server-only stream of real-time events (tool calls, thinking status, skill activation, memory recall). See `10-api-reference.md` for the full event type list.

### Terminal WebSocket
```
ws://127.0.0.1:47821/ws/terminal?token=<your_token>&channel=<channel_id>
```

A **real interactive PTY shell** — one persistent session per chat channel. The terminal panel in the dashboard connects here. Powered by xterm.js on the frontend and `pywinpty` (Windows) / `pty` (Linux/Mac) on the backend.

**Key behaviors:**
- The shell session **persists** across WS reconnects — SSH connections, running servers, and shell state are preserved
- Each chat channel (`web`, `telegram-xxx`, etc.) gets its own isolated shell
- Supports full ANSI colors, the current path in the prompt (`PS1`), tab completion, and Ctrl+C
- When the AI runs `run_command`, its output streams directly into the correct channel's terminal in real time

Client sends:
```json
{"type": "input",  "data": "ls -la\n"}
{"type": "signal", "data": "SIGINT"}
{"type": "resize", "cols": 220, "rows": 50}
```

Server sends:
```json
{"type": "output",      "data": "\u001b[32muser@host\u001b[0m:/home$ "}
{"type": "ai_command",  "tool": "run_command", "data": "npm install"}
{"type": "ai_output",   "tool": "run_command", "data": "added 142 packages"}
{"type": "exit",        "data": "shell process exited"}
{"type": "error",       "data": "Failed to start shell: ..."}
```

---

## Authentication

If `DASHBOARD_TOKEN` is set, all `/api/` endpoints require:
```
Authorization: Bearer <token>
```

Or via query string:
```
GET /api/stats?token=<token>
```

WebSocket connections pass the token as a query parameter:
```
ws://127.0.0.1:47821/ws/chat?token=<token>
```

The token is checked against the configured value. There is no user management — all valid tokens have full access.

---

## Production Considerations

By default, the dashboard binds to `127.0.0.1` (localhost only). To expose it on a network:

```yaml
# config/default.yaml
server:
  host: "0.0.0.0"
  port: 47821
```

**If exposing to a network:**
1. Set a strong `DASHBOARD_TOKEN` in `config/.env`
2. Put the server behind a reverse proxy (nginx, Caddy) with HTTPS
3. Restrict access by IP at the network level
4. Do not expose it to the public internet without authentication

The dashboard has full agent access — anyone with the token can execute tools, read files, and run commands on your machine.
