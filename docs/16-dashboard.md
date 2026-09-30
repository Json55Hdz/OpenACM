# Dashboard

The OpenACM dashboard is a built-in web interface available at `http://127.0.0.1:47821` (or whatever host/port you configure). It requires no extra setup — it starts with OpenACM. It is a Next.js app exported to static files and served by the FastAPI server.

---

## Accessing the Dashboard

1. Start OpenACM (`openacm start`, `run.bat` / `./run.sh`, or `python -m openacm`)
2. Open your browser to `http://127.0.0.1:47821`
3. Enter the dashboard token printed in the terminal (also stored as `DASHBOARD_TOKEN` in `config/.env`)

The token is stored in your browser and sent automatically on all API calls and WebSocket connections. On a fresh install you are taken to the **Onboarding** wizard to choose an LLM provider.

---

## Pages Overview

The sidebar shows the core pages plus items contributed by enabled plugins. With a [client profile](./11-configuration.md#client-deployments-features-and-client_profile) active, only the allowed pages are shown.

### Dashboard

Real-time overview:
- **Token Analytics** — tokens and cost over a selectable date range, by model
- **Stats cards** — requests, tokens, tool calls, conversations, current provider/model
- **Live events** and recent files

---

### Chat

The primary interface. Full-featured chat with the OpenACM agent.

**Features:**
- **Live responses** — partial text appears while tools run, plus a thinking indicator and (for reasoning models) the model's reasoning
- **Cancel button** — while the agent is thinking, the send button turns into a red ✕ button; clicking it cancels the current request immediately
- **Conversation sidebar** — web conversations, external-channel conversations (Telegram, WhatsApp, Discord, with channel icons) and **one folder per agent**; folders remember whether they are open or collapsed, and long lists are paginated
- **New conversation** — each session gets a unique ID; history persists
- **Delete conversation** — hover over a conversation in the sidebar to reveal the delete button
- **Tool execution log** — toggle to see each tool call and its result inline
- **Command approvals** — in `confirmation` mode, commands the agent wants to run pop up for approve/deny
- **File uploads** — drag-and-drop or click to attach images, PDFs, audio, Office documents, text files
- **Image preview** — images sent by the agent render inline with a download button
- **Terminal panel** — a real interactive shell per conversation that also shows the AI's commands and their live output
- **Encryption badge** — a lock icon when messages are encrypted at rest
- **Context indicator** — live context-window usage
- **Model indicator** — shows current provider and model

**Slash commands** (type in the chat input):
```
/new                          Start a fresh conversation
/reset                        Emergency reset of this conversation's memory
/compact                      Summarize the conversation now
/model ollama/llama3.2        Switch to a different model mid-conversation
/stats                        Token usage and request counts
/export                       Export the conversation
/workspace <path>|clear       Pin or clear the working directory
/help                         Show all commands
```

**File upload behavior:**
- Images → sent as vision input to the LLM (if model supports it)
- Audio/voice → transcribed (OpenAI Whisper API, local faster-whisper, or MarkItDown) and injected as text
- Documents (PDF, Office, text) → content extracted (Docling / pypdf / MarkItDown) and added to context

---

### Swarms

Create a swarm from a goal (optionally with context files), answer the clarification questions, review the planned team and tasks, start/pause it, change worker models, and follow the activity feed in real time. See [Swarms](./22-swarms.md).

---

### Daemon

Controls the always-on **voice daemon**: engine status and missing dependencies (with an install button), microphone selection, wake word / assistant name, TTS provider and voice, enable/disable voice, and the animated companion skins. See [Voice](./30-voice.md).

---

### Routines

Activity-watcher status (current app, hours monitored, sessions, top apps) and the routines detected by the pattern analyzer.

**For each routine:**
- Name and description (LLM-generated)
- App list
- Trigger type (`time_based` or `manual`), time and days
- Confidence score and occurrence count

**Actions:** **Analyze now**, run, activate/deactivate (activating a time-based routine schedules a cron job), edit, delete; start/stop the watcher.

---

### Cron

Create jobs with a cron expression (with presets and a human-readable preview), choose the action, run a job now, enable/disable it, and browse the execution history. See [Cron Scheduler](./19-cron-scheduler.md).

---

### Tools

Lists all registered tools (built-in, plugin and MCP) with name, description, category, risk level and parameter schema, plus the **Execution log** (arguments, result, timing, success) of recent tool calls.

---

### Skills

Lists all skills with category and active status. Create a skill manually (name, description, category, content) or describe the skill you need and let the LLM generate it; edit, toggle and delete skills. See [Skills System](./06-skills-system.md).

---

### Agents

Lists agents; create one manually or generate it from a description. Each agent has tabs for:
- **Config** — name, description, system prompt, **Tools access** (all / none), **Memory** policy (persistent or reset after N hours), inactivity follow-up, show in chat
- **Knowledge** — text entries and uploaded files
- **Channels** — Telegram, WhatsApp Business (Cloud API) or WhatsApp Web bridge, with connection status and restart
- **Herramientas** (Tools) — pick exactly which tools the agent may use, grouped by category
- **Skills** — enable system skills for this agent, or generate private ones
- **Flujos** (Flows) — list, create, import/export and activate flows; opens the visual **flow editor** with an inspector, WooCommerce connections, a test panel ("Probar flujo") and a chat panel that builds the flow for you

See [Agents](./07-agents.md) and [Agent Flows](./28-agent-flows.md).

---

### MCP

Lists all configured MCP servers with their connection status.

**For each server:**
- Name, transport type, command/URL
- Connected/Disconnected status with error message if failed
- Tool list

**Actions:**
- **Add Server** → form to register a new MCP server
- **Connect / Disconnect** → toggle connection per server
- **Delete** → remove server configuration

---

### Connectors

Lists [webhook connectors](./29-webhook-connectors.md) with their public URL (`/api/webhooks/{slug}`) and auth scheme, lets you turn each one on/off, and shows its activity log (received time, status, result). Connectors are created through the API.

---

### Traces

The loop debugger: for each recent request, every agentic iteration with message count, context size, LLM time, tool calls and their timings, and the outcome (success / error / timeout).

---

### Configuration

- **Assistant Identity** — name and personality
- **Model** — active provider/model and per-model parameters; **Custom Providers** (OpenAI-compatible endpoints); CLI providers
- **Voice Interface** — wake word, TTS provider and language
- **Memory & RAG** — RAG relevance threshold, compaction ratio / keep-recent, memory stats and wipe
- **Local Intent Router** — enable/disable and confidence threshold
- **WhatsApp** — Cloud API credentials or bridge URL
- **Google Services** — upload OAuth credentials and authorize Gmail/Calendar/Drive/YouTube
- **Google Stitch** — API key for UI generation
- **Security** — execution mode (`confirmation`, `auto`, `yolo`), debug logging
- **Code Resurrection** — folders to index
- **Advanced** — raw config view

---

### Plugins

Every discovered plugin with an enable/disable toggle (applies after restart — a banner offers to restart), a settings form for plugins that declare a config schema, and a button that opens a plugin's own dashboard embedded inside the app (`/plugins/view`). See [Plugins](./24-plugins.md).

### Plugin pages

- **Gmail** (`/gmail-classifier`) — [Gmail Classifier](./31-gmail-classifier.md)
- **Home Assistant** (`/home-assistant`) — devices grouped by type with live state, areas and scenes
- **Content** (`/content`) — approve or reject social posts queued by the Content Automation plugin

---

## WebSocket Protocol

The dashboard communicates with the backend via WebSockets (`/ws/chat`, `/ws/events`, `/ws/terminal`, `/ws/swarms/{id}`), all authenticated with `?token=`. Message formats are documented in the [API Reference](./10-api-reference.md#websocket-chat-wschat).

---

## Production Considerations

By default, the dashboard binds to `127.0.0.1` (localhost only). To expose it on a network:

```yaml
# config/local.yaml
web:
  host: "0.0.0.0"
  port: 47821
```

**If exposing to a network:**
1. Keep `DASHBOARD_TOKEN` secret (it is the only credential — there is no user management)
2. Put the server behind a reverse proxy (nginx, Caddy, Nginx Proxy Manager) with HTTPS and WebSocket support
3. Restrict access by IP at the network level
4. Do not expose it to the public internet without HTTPS

The dashboard has full agent access — anyone with the token can execute tools, read files, and run commands on your machine. See [Deploy on a VPS](./DEPLOY_VPS.md).
