# Extending OpenACM

OpenACM is designed to be extended at runtime — without restarting, without editing source code, and without deep Python knowledge.

---

## Creating Tools at Runtime

The most powerful extension mechanism. Ask OpenACM to create a new tool for itself:

```
You: Create a tool called "weather" that fetches current weather for any city 
     using the Open-Meteo API (no API key required). 
     Parameters: city (string, required), units (celsius or fahrenheit, default celsius)
```

OpenACM will:
1. Write the Python async function
2. Run validation (syntax check, import check, security scan)
3. Execute a dry-run test
4. Show you the code and results
5. Ask for confirmation → call `create_tool(..., apply=True)` → live in registry

The tool is immediately available for the next message.

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
    # Context injected automatically — always use **ctx or list explicitly:
    _sandbox=None,
    _event_bus=None,
    _brain=None,
    _user_id: str = "",
    _channel_id: str = "",
    _channel_type: str = "",
) -> str:
    """Implementation here. Must return a string."""
    result = f"Got: {param1}, {param2}"
    return result
```

**Key rules:**
- Must be `async def`
- Must return a `str`
- Parameters matching the schema are passed as keyword arguments
- Context parameters (`_sandbox`, `_event_bus`, etc.) are injected automatically
- Never raise unhandled exceptions — catch them and return an error string

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
| `blender` | 3D modeling and rendering |
| `meta` | Tools that manage other tools or skills |
| `iot` | Smart home, IoT devices |
| `mcp` | MCP server tools (auto-assigned) |

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

The module is loaded on next startup and available forever.

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

Restart OpenACM or trigger a skill sync to discover the new file.

---

## Creating Agents

Agents are isolated instances with their own persona and tool set.

### Via dashboard
1. Go to **Agents** → **New Agent**
2. Set name, description, and system prompt
3. Choose which tools the agent can access
4. Optionally provide a Telegram bot token for a dedicated bot

### Via chat
```
You: Create an agent called "ResearchBot" that specializes in finding 
     and summarizing information. It should only have access to 
     web_search, get_webpage, and remember_note tools. 
     Give it a concise, academic tone.
```

### Via API
```bash
curl -X POST http://localhost:47821/api/agents \
  -H "Authorization: Bearer acm_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ResearchBot",
    "description": "Finds and summarizes information",
    "system_prompt": "You are a research specialist. Be concise and cite sources.",
    "allowed_tools": ["web_search", "get_webpage", "remember_note"]
  }'
```

---

## Connecting MCP Servers

Model Context Protocol servers expose tools that OpenACM can use.

### Configuration
Add to `config/mcp_servers.json`:

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

Implement the `BaseChannel` abstract class:

```python
# openacm/channels/my_channel.py
import asyncio
from openacm.channels.base import BaseChannel

class MyChannel(BaseChannel):
    name = "mychannel"
    
    def __init__(self, config, brain, event_bus):
        self.config = config
        self.brain = brain
        self.event_bus = event_bus
        self.is_connected = False
        self.ready_event = asyncio.Event()
    
    async def start(self):
        # Connect to your platform
        self.is_connected = True
        self.ready_event.set()
        
        # Listen for incoming messages
        async for message in self.receive_messages():
            response = await self.brain.process_message(
                content=message.text,
                user_id=message.user_id,
                channel_id=self.name,
                channel_type=self.name,
            )
            await self.send_message(message.user_id, response)
    
    async def stop(self):
        self.is_connected = False
    
    async def send_message(self, user_id: str, content: str):
        # Send response to your platform
        pass
```

Register it in `app.py`:
```python
from openacm.channels.my_channel import MyChannel
channel = MyChannel(config, self.brain, self.event_bus)
self._channels.append(channel)
```

---

## Modifying the System Prompt

The base OpenACM identity context is in `src/openacm/core/acm_context.py`. You can:

1. **Customize the assistant persona** via `assistant.system_prompt` in config
2. **Add persistent behavior** via skills (active skills are appended to the system prompt)
3. **Edit the base context** directly in `acm_context.py` for deep behavioral changes

The system prompt structure on each request:
```
[OPENACM base context (short version after first message)]
[User's custom system_prompt from config]
[Active skill content (if any)]
[MCP tool list (if any MCP servers connected)]
```
