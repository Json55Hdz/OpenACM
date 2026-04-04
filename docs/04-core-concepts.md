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
     └──► Repeat (max 20 iterations)
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

The LLM sees this entire history on each call. Memory compaction (after 25 messages) keeps the context window manageable.

---

## Tools vs Skills vs Agents

These three extension mechanisms serve distinct purposes:

### Tools
Executable Python functions that **do things**. They have inputs, run code, and return output. Tools are how OpenACM interacts with the world.

- Examples: `run_command`, `web_search`, `gmail_send`, `iot_control`
- Created with: `create_tool` tool or by adding `.py` files to `src/openacm/tools/`
- Invoked by: the LLM when it decides they're needed
- Registered in: `ToolRegistry`

### Skills
Markdown files that **change how OpenACM thinks**. They're injected into the system prompt when a skill is active. Skills have no code — they're behavior/persona instructions.

- Examples: "blender-modeling" (3D expert context), "agent-creator" (how to design agents)
- Created with: `create_skill` tool or adding `.md` files to `skills/`
- Activated: manually via dashboard, or auto-matched by the LLM based on message content
- Stored in: `skills/{category}/` directory + SQLite `skills` table

### Agents
Isolated instances of OpenACM with their own system prompt, a restricted set of tools, and optionally their own Telegram bot token. Agents are specialized sub-agents.

- Example: a "ResearchBot" that only has access to `web_search`, `get_webpage`, and `remember_note`
- Created via: dashboard or `create_agent` tool
- Can be messaged via: dedicated Telegram bot, REST API (`/api/agents/{id}/chat`), or web

### When to use which

| Need | Use |
|------|-----|
| Do something (API call, file op, system interaction) | Tool |
| Change how the agent thinks or responds | Skill |
| Create a specialized assistant with limited scope | Agent |
| Connect to an external tool server | MCP |

---

## Memory Architecture

OpenACM has two memory systems that work together:

### Short-term Memory (Conversation History)
- Scope: per user + channel pair
- Stored: SQLite + in-memory cache
- Lifetime: until conversation is cleared or deleted
- Compaction: after 25 messages, older ones are summarized by the LLM
- Encryption: message content encrypted at rest (AES-GCM)

### Long-term Memory (RAG / Vector Store)
- Scope: global across all conversations
- Stored: ChromaDB (persistent vector database)
- Lifetime: permanent until explicitly deleted
- Access: via `remember_note` (write) and `search_memory` (read)
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
  send_file_to_chat (always included) ✓
  web_search (0.09) < threshold ✗
  → 2 tools sent
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
  → EventBus: thinking {status: "processing"}

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

| Mode | Behavior |
|------|----------|
| `confirmation` | Ask user before executing medium/high risk tools |
| `auto` | Execute all approved tools automatically |
| `yolo` | Execute everything without restriction |

### Blocked Patterns (always enforced)
Even in `yolo` mode, certain patterns are always blocked:
- Privilege escalation (`sudo su`, `RunAs /priv`, SUID manipulation)
- Credential access (`.ssh/id_rsa`, `/etc/shadow`, Windows SAM)
- Security tool manipulation (UAC dialogs, sudo prompts)

### Tool Risk Levels
Every tool is annotated with a risk level:
- `low` — read-only, no side effects (web_search, read_file, system_info)
- `medium` — writes data, network calls (write_file, gmail_send, take_screenshot)
- `high` — arbitrary execution, privileged access (run_command, run_python, browser_agent)

---

## LLM Providers

OpenACM uses **LiteLLM** internally, which provides a unified interface to 100+ LLM providers. From OpenACM's perspective, all providers speak the same OpenAI-compatible API.

**Supported providers include:**
- Ollama (local, free)
- OpenAI (GPT-4o, o1, o3)
- Anthropic (Claude)
- Google Gemini
- Groq (fast inference)
- Together AI
- Mistral
- Cohere
- AWS Bedrock
- Azure OpenAI
- Any OpenAI-compatible endpoint (LM Studio, vLLM, etc.)

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
| Web dashboard | `web` | `web_<timestamp>` |
| Console | `console` | `console` |
| Telegram | Telegram chat ID | `tg_<chat_id>` |
| Discord | Guild ID | Discord user ID |
| WhatsApp | Phone number | Phone number |

The channel is responsible for: receiving messages, delivering responses, and translating platform-specific features (attachments, formatting) to/from OpenACM's internal format.
