# Core Concepts

## The Agentic Loop

The core of OpenACM is an **agentic loop** — a cycle of LLM calls and tool executions that continues until the task is complete.

```
User Message
     │
     ▼
Build Context (system prompt + skills + conversation history)
     │
     ▼
Select Tools (semantic similarity → only relevant tools sent)
     │
     ▼
┌─── LLM Call ──────────────────────────────────────────┐
│   Returns: text response OR one or more tool calls    │
└────────────────────────────────────────────────────────┘
     │
     ├─── No tool calls → Return response to user ──────────────► DONE
     │
     ▼
Execute tool calls (in parallel if multiple)
     │
     ▼
Add tool results to conversation
     │
     └──► Repeat (max `assistant.max_tool_iterations`, 25 by default)
```

Each iteration the LLM sees the full conversation including all previous tool results. This allows it to chain tools intelligently — for example: search the web → summarize findings → write to file → send via email.

---

## Messages and Roles

Conversation history is a sequence of messages with roles:

| Role | Sender | Example |
|------|--------|---------|
| `system` | OpenACM (injected) | Base context, active skills, OS info |
| `user` | The human | "Search for AI news" |
| `assistant` | The LLM | Text responses and tool call requests |
| `tool` | Tool execution results | JSON output from `web_search` |

The LLM sees this entire history on each call. Memory compaction (triggered at 60% of the model's context window) keeps the context window manageable.

---

## Tools vs Skills vs Agents vs Flows

These extension mechanisms serve distinct purposes:

### Tools
Executable Python functions that **do things**. They have inputs, run code, and return output. Tools are how OpenACM interacts with the world.

- Examples: `run_command`, `web_search`, `gmail_send`, `ha_control`
- Created by: adding a `@tool` module to `src/openacm/tools/` (registered in `app.py`) or shipping it in a [plugin](./24-plugins.md); MCP servers add tools at runtime
- Invoked by: the LLM when it decides they're needed
- Registered in: `ToolRegistry`

### Skills
Markdown files that **change how OpenACM thinks**. They're injected into the system prompt when a skill is active. Skills have no code — they're behavior/persona instructions.

- Examples: "code-reviewer", "api-designer", "blender-modeling", "agent-creator"
- Created with: `create_skill` tool, the Skills page, or adding `.md` files to `skills/`
- Activated: toggled on/off in the dashboard; an active skill is injected only when the message is relevant to it (keyword or name match)
- Stored in: `skills/{category}/` directory + SQLite `skills` table (agents, swarm workers and flows can also have private skills)

### Agents
Specialized assistants with their own system prompt, a restricted set of tools, a knowledge base, a memory policy, and optionally their own Telegram bot / WhatsApp number.

- Example: a "ResearchBot" that only has access to `web_search`, `get_webpage`, and `remember_note`
- Created via: dashboard, `create_agent` tool, or `POST /api/agents`
- Can be messaged via: its own Telegram/WhatsApp channel, the dashboard chat, or the REST API (`/api/agents/{id}/chat`)

### Flows
Visual node graphs that belong to an agent. Every active flow becomes a tool (`flow_<id>`) the agent can call, and a flow can also be triggered by a public [webhook connector](./29-webhook-connectors.md).

- Example: "search the store for a product, and if nothing is found call a fallback API"
- Created via: the flow editor on the Agents page, the flow chat panel, or the `create_or_update_agent_flow` tool
- See [Agent Flows](./28-agent-flows.md)

### When to use which

| Need | Use |
|------|-----|
| Do something (API call, file op, system interaction) | Tool |
| Change how the agent thinks or responds | Skill |
| Create a specialized assistant with limited scope | Agent |
| A deterministic sequence of HTTP/store calls an agent can run | Flow |
| Let a third-party service trigger OpenACM | Webhook connector |
| Package a whole feature (tools + API + UI + settings) | Plugin |
| Connect to an external tool server | MCP |

---

## Memory Architecture

OpenACM has two memory systems that work together:

### Short-term Memory (Conversation History)
- Scope: per user + channel pair
- Stored: SQLite + in-memory cache
- Lifetime: until conversation is cleared or deleted
- Compaction: when the conversation reaches `compact_ratio` (60%) of the model's context window, older messages are summarized by the LLM
- Encryption: message content encrypted at rest (Fernet, key in `config/activity.key`)

### Long-term Memory (RAG / Vector Store)
- Scope: global across all conversations
- Stored: ChromaDB (persistent vector database)
- Lifetime: permanent until explicitly deleted
- Access: via `remember_note` (write) and `search_memory` (read); relevant fragments are also injected automatically when their distance is below `rag_relevance_threshold`
- Model: `all-MiniLM-L6-v2` embeddings, cosine similarity search

**How they interact:**
```
User: "Remember that my server IP is 192.168.1.100"
→ remember_note("Server IP: 192.168.1.100")

[Later, new conversation]
User: "What's my server IP again?"
→ search_memory("server IP") → returns the stored fact
→ Brain answers: "Your server IP is 192.168.1.100"
```

---

## Semantic Tool Selection

On each user message, OpenACM must decide which tools to send to the LLM. Sending all tools wastes tokens. The selection system works in layers:

**Layer 1: Conversational detection**
```
"hola!" → 0 tools sent (saves ~3K tokens)
"gracias" → 0 tools sent
"ok cool" → 0 tools sent
```

Short messages (≤80 chars) with no action keywords → no tools. Pure conversation doesn't need tool schemas.

**Layer 2: Semantic similarity**
```
"toma una captura de pantalla" →
  embed message → cosine similarity against all tool descriptions →
  take_screenshot (0.82) > threshold (0.28) ✓
  send_file_to_chat, run_command, read_file, write_file, web_search (always included) ✓
  gmail_send (0.04) < threshold ✗
```

The same multilingual model (`paraphrase-multilingual-MiniLM-L12-v2`) that runs the LocalRouter is used here. Tool descriptions are embedded at startup and cached. Each request costs ~1ms.

**Layer 3: Keyword fallback**
If the embedding model hasn't finished loading (first few seconds), falls back to keyword-based category matching. Same behavior, less accurate.

---

## Event System

All major actions emit events through the **EventBus**. The web dashboard subscribes to these events via WebSocket (`/ws/events`) to show real-time status.

```
User sends "search for AI news"
  → EventBus: message.received
  
Brain starts processing
  → EventBus: message.thinking {status: "processing"}

LLM calls web_search tool
  → EventBus: tool.called {tool: "web_search"}
  
web_search completes
  → EventBus: tool.result {tool: "web_search", result: "..."}

LLM generates response
  → EventBus: message.sent

Dashboard shows: thinking spinner → tool badge → response
```

---

## Security Model

OpenACM can execute arbitrary system commands and Python code — this is intentional and is what makes it powerful. Security is layered:

### Execution Modes

The execution mode governs shell commands run through `run_command`:

| Mode | Behavior |
|------|----------|
| `confirmation` (default) | Ask the user before running each command |
| `auto` | Run only commands whose executable is in `whitelisted_commands`; reject the rest |
| `yolo` | Run every command without asking |

### Blocked Patterns (always enforced)
Even in `yolo` mode, certain patterns are always blocked:
- Privilege escalation (`runas`, `gsudo`, `sudo -s`, `sudo -i`, `su -`, setuid/setgid `chmod`, `chown root`, adding Windows admin accounts)
- Credential files (`/etc/shadow`, `/etc/passwd`)
- Anything in your configured `blocked_patterns` / `blocked_paths` (by default `config/`, the database and the vector store are blocked too)

### Tool Risk Levels
Every tool is annotated with a risk level (shown in the dashboard and in `/tools`):
- `low` — read-only or harmless (list_directory, system_info, search_memory)
- `medium` — reads sensitive data or makes network calls (read_file, web_search, take_screenshot, calendar_create)
- `high` — arbitrary execution or destructive writes (run_command, run_python, write_file, edit_file, browser_agent, gmail_send)

---

## LLM Providers

OpenACM uses **LiteLLM** internally, which provides a unified interface to 100+ LLM providers. From OpenACM's perspective, all providers speak the same OpenAI-compatible API.

**Built-in provider presets:** OpenCode Go (default), OpenAI, Anthropic, Google Gemini, xAI, OpenRouter, Ollama (local). **CLI providers** (`claude`, `gemini`, `opencode` binaries) are auto-detected. **Any OpenAI-compatible endpoint** (LM Studio, vLLM, Groq, Together, DeepSeek…) can be added as a custom provider.

You can switch the active model mid-conversation with `/model provider/model-name`.

**Provider Profiles** handle quirks across providers:
- Some models don't support native tool calling → OpenACM prompts them to use tools via text
- Some models have tool count limits → OpenACM caps automatically
- Some models return thinking/reasoning tokens → stored but stripped from older context

---

## Channels

OpenACM is channel-agnostic. The same Brain handles messages from all channels identically.

Each channel has a unique `channel_id` and each user within that channel has a `user_id`. The combination `channel_id:user_id` uniquely identifies a conversation.

| Channel | channel_id | user_id |
|---------|-----------|---------|
| Web dashboard | `web` | `web` or `web_<timestamp>` (one per conversation) |
| Console | `console` | `console` |
| Telegram | Telegram chat ID | Telegram user ID |
| Discord | Discord channel ID | Discord user ID |
| WhatsApp | Sender phone number | Sender phone number |

The channel is responsible for: receiving messages, delivering responses, and translating platform-specific features (attachments, formatting) to/from OpenACM's internal format.
