# Extending OpenACM

OpenACM is designed to be extended. Skills, agents, flows, cron jobs, swarms and MCP servers can be added at runtime from the dashboard or from chat; new tools, channels and whole features are added in Python — ideally as a [plugin](./24-plugins.md), which needs no changes to the core.

| Want to… | Use |
|----------|-----|
| Change how the AI behaves in a domain | [Skill](#creating-skills) |
| Build a specialized assistant | [Agent](#creating-agents) |
| Chain HTTP/store calls without code | [Flow](./28-agent-flows.md) |
| Let an external service trigger OpenACM | [Webhook connector](./29-webhook-connectors.md) |
| Add tools written in any language | [MCP server](#connecting-mcp-servers) |
| Add Python tools + API routes + UI + settings | [Plugin](./24-plugins.md) |
| Add a new messaging platform | [Custom channel](#adding-custom-channels) |

> **Runtime tool creation:** `src/openacm/tools/tool_creator.py` contains `create_tool` / `edit_tool` / `delete_tool` (a two-phase validate-then-apply flow), but in v0.4.7 that module is not registered at startup, so the agent cannot create Python tools from chat. Write a tool module or a plugin instead.

---

## Tool Code Structure

All tools are Python async functions. Here's the minimal structure:

```python
from openacm.tools.base import tool

@tool(
    name="my_tool",
    description="Brief description of what this tool does",
    parameters={
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "What param1 is for"
            },
            "param2": {
                "type": "integer",
                "description": "What param2 is for",
                "default": 10
            }
        },
        "required": ["param1"]
    },
    risk_level="low",      # "low", "medium", or "high"
    category="general",    # Category for semantic tool selection
)
async def my_tool(
    param1: str,
    param2: int = 10,
    _brain=None,
    **kwargs,          # absorbs the other injected context and unknown params
) -> str:
    """Implementation here. Must return a string."""
    result = f"Got: {param1}, {param2}"
    return result
```

**Key rules:**
- Must be `async def`
- Must return a `str` (anything else is converted with `str()`)
- Parameters matching the schema are passed as keyword arguments
- Context is injected automatically as keyword arguments: `_sandbox`, `_event_bus`, `_brain`, `_user_id`, `_channel_id`, `_channel_type`, `_confirm_callback` — end the signature with `**kwargs`
- Shared managers are reachable through `_brain.tool_registry` (`cron_scheduler`, `swarm_manager`, `mcp_manager`, `app_config`)
- Exceptions are caught by the registry and returned to the LLM as `Error: ...`, but returning a clear error string yourself gives better results

---

## Tool Categories

Choose a category to help with semantic tool selection:

| Category | When to use |
|----------|-------------|
| `general` | Always available; utility tools |
| `system` | OS commands, processes, system management |
| `file` | File system operations |
| `web` | HTTP, scraping, web services |
| `ai` | Memory, embeddings, ML operations |
| `media` | Images, audio, video, screen |
| `google` | Google Workspace APIs |
| `meta` | Tools that manage skills |
| `swarm` | Multi-agent swarms |
| `iot` | Smart home, IoT devices |
| `content` / `social` | Content generation and social media |
| `mcp` | MCP server tools (auto-assigned) |
| `custom_flow` | Agent flows (auto-assigned) |

Keyword fallbacks used before the embedding model is loaded live in `src/openacm/tools/intent_keywords.py` (plugins add theirs with `get_intent_keywords()`).

---

## Adding Tools to Source

For tools you want to include permanently:

1. Create `src/openacm/tools/my_module.py`
2. Define tools using the `@tool` decorator
3. Register the module in `src/openacm/app.py`:

```python
from openacm.tools import my_module
self.tool_registry.register_module(my_module)
```

The module is loaded on next startup and available forever. To ship tools without touching `app.py`, return the module from a plugin's `get_tool_modules()` instead — see [Plugins](./24-plugins.md).

---

## Creating Skills

Skills are markdown files that shape LLM behavior.

### Via chat
```
You: Create a skill for Rust development expertise. 
     It should emphasize memory safety, ownership rules, 
     and idiomatic Rust patterns.
```

### Manually
Create `skills/development/rust-expert.md`:

```markdown
# Rust Development Expert

When writing Rust code:

## Core Principles
- Always think about ownership and lifetimes first
- Prefer `&str` over `String` for read-only string parameters
- Use `Result<T, E>` for fallible operations, never `unwrap()` in library code
- Leverage the type system to make invalid states unrepresentable

## Common Patterns
- Error handling: `thiserror` for library errors, `anyhow` for application errors
- Async: `tokio` runtime, `async-trait` for async trait methods
- Serialization: `serde` with `derive(Serialize, Deserialize)`
- CLI: `clap` with derive macros

## Code Quality
- Run `clippy` before finalizing any code
- All public items must have doc comments (`///`)
- Write unit tests in the same file (`#[cfg(test)]`)
```

Restart OpenACM to sync the new file into the database (files must be inside a category folder such as `skills/development/`). Skills created from the dashboard or with `create_skill` are available immediately.

---

## Creating Agents

Agents are isolated instances with their own persona and tool set.

### Via dashboard
1. Go to **Agents** → **New Agent**
2. Set name, description, and system prompt
3. Choose which tools the agent can access
4. Optionally add knowledge, channels (Telegram / WhatsApp) and flows

### Via chat
```
You: Create an agent called "ResearchBot" that specializes in finding
     and summarizing information, with access to all tools.
     Give it a concise, academic tone.
```

### Via API
```bash
curl -X POST http://localhost:47821/api/agents \
  -H "Authorization: Bearer <dashboard-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ResearchBot",
    "description": "Finds and summarizes information",
    "system_prompt": "You are a research specialist. Be concise and cite sources.",
    "allowed_tools": "[\"web_search\", \"get_webpage\", \"remember_note\"]"
  }'
```

---

## Connecting MCP Servers

Model Context Protocol servers expose tools that OpenACM can use.

### Configuration
Add an entry to the `servers` array of `config/mcp_servers.json`:

```json
{
  "name": "my-server",
  "transport": "stdio",
  "command": "python",
  "args": ["-m", "my_mcp_server"],
  "env": {
    "API_KEY": "xxx"
  },
  "auto_connect": true
}
```

### Via dashboard
Go to **MCP** → **Add Server** and fill in the form.

### Tools are auto-named
A tool called `read_file` from server `filesystem` becomes `mcp__filesystem__read_file` in OpenACM's tool registry.

---

## Building a Custom MCP Server

You can build an MCP server that exposes any external service as tools OpenACM can use.

```python
# my_mcp_server.py
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("my-server")

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="get_stock_price",
            description="Get the current price of a stock symbol",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Stock ticker symbol"}
                },
                "required": ["symbol"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "get_stock_price":
        # Your implementation here
        price = await fetch_stock_price(arguments["symbol"])
        return [TextContent(type="text", text=f"${price:.2f}")]

async def main():
    async with stdio_server() as streams:
        await server.run(*streams, server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

Then add it to OpenACM:
```json
{
  "name": "stocks",
  "transport": "stdio",
  "command": "python",
  "args": ["my_mcp_server.py"],
  "auto_connect": true
}
```

---

## Adding Custom Channels

Implement the `BaseChannel` abstract class (`name` and `is_connected` are abstract properties; `start`, `stop` and `send_message` are abstract methods; `ready_event` must be set once connected — or on failure — because startup waits up to 15 s for it):

```python
# src/openacm/channels/my_channel.py
import asyncio
from openacm.channels.base import BaseChannel

class MyChannel(BaseChannel):
    def __init__(self, config, brain, event_bus):
        self.config = config
        self.brain = brain
        self.event_bus = event_bus
        self._connected = False
        self.ready_event = asyncio.Event()

    @property
    def name(self) -> str:
        return "mychannel"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def start(self):
        # Connect to your platform
        self._connected = True
        self.ready_event.set()

        # Listen for incoming messages
        async for message in self.receive_messages():
            response = await self.brain.process_message(
                content=message.text,
                user_id=message.user_id,
                channel_id=message.chat_id,
                channel_type=self.name,
            )
            await self.send_message(message.chat_id, response)

    async def stop(self):
        self._connected = False

    async def send_message(self, target_id: str, content: str, **kwargs) -> bool:
        # Send response to your platform
        return True
```

Register it in `OpenACM._init_channels()` in `app.py`:
```python
from openacm.channels.my_channel import MyChannel
channel = MyChannel(config, self.brain, self.event_bus)
self._channels.append(channel)
channel_tasks.append(asyncio.create_task(channel.start()))
```

---

## Modifying the System Prompt

The base OpenACM identity context is in `src/openacm/core/acm_context.py`. You can:

1. **Customize the assistant persona** via `assistant.system_prompt` in config
2. **Add persistent behavior** via skills (active skills are appended to the system prompt)
3. **Edit the base context** directly in `acm_context.py` for deep behavioral changes

The system prompt structure on each request:
```
[Pinned workspace note (if /workspace is set)]
[OPENACM base context (short version after first message)]
[User's custom system_prompt from config]
[Matching skill content (if any)]
[List of connected MCP servers (if any)]
[Plugin context extensions (get_context_extension)]
```

Relevant long-term memory fragments are added as a separate system message.
