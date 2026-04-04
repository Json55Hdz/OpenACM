# MCP Integration

OpenACM supports the **Model Context Protocol (MCP)** — an open standard for connecting AI models to external tool servers. Any MCP-compatible server can expose its tools to OpenACM with zero code changes.

---

## What is MCP?

MCP is a protocol that lets external processes (running locally or remotely) expose tools to an AI agent over a standardized interface. OpenACM acts as an MCP **client** — it connects to MCP servers and registers their tools alongside its built-in tools.

Benefits:
- Drop-in tools from any MCP server without writing OpenACM-specific code
- Use existing MCP ecosystems (file system servers, browser automation, code execution sandboxes, etc.)
- Build specialized tool servers once and reuse across any MCP-compatible agent

---

## Transports

OpenACM supports three MCP transport types:

| Transport | When to use |
|-----------|------------|
| `stdio` | Local servers — spawned as child processes, communicate over stdin/stdout |
| `sse` | Remote servers — HTTP + Server-Sent Events |
| `streamable_http` | Modern HTTP transport (e.g., Unity MCP, newer MCP servers) |

---

## Connecting an MCP Server

### Via Dashboard
Go to **MCP** → **Add Server** and fill in the form. Click **Connect** to activate immediately.

### Via `config/mcp_servers.json`

```json
{
  "servers": [
    {
      "name": "filesystem",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
      "auto_connect": true
    },
    {
      "name": "unity-mcp",
      "transport": "streamable_http",
      "url": "http://localhost:6400/mcp",
      "auto_connect": true
    },
    {
      "name": "my-remote-server",
      "transport": "sse",
      "url": "https://mcp.example.com/sse",
      "api_key": "Bearer sk-...",
      "auto_connect": false
    }
  ]
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique identifier for the server |
| `transport` | string | `stdio`, `sse`, or `streamable_http` |
| `command` | string | (stdio) Executable to run |
| `args` | array | (stdio) Arguments to the command |
| `env` | object | (stdio) Extra environment variables |
| `url` | string | (sse/http) Server URL |
| `api_key` | string | (sse/http) Sent as `Authorization: Bearer <key>` |
| `headers` | object | (sse/http) Additional HTTP headers |
| `auto_connect` | bool | Connect automatically on startup |

---

## Tool Naming Convention

When a server is connected, its tools are automatically registered with the pattern:

```
mcp__{server_name}__{tool_name}
```

**Examples:**
- Server `filesystem`, tool `read_file` → `mcp__filesystem__read_file`
- Server `unity-mcp`, tool `create_gameobject` → `mcp__unity_mcp__create_gameobject`
- Server `my-server`, tool `do_thing` → `mcp__my_server__do_thing`

Special characters in names are replaced with `_`.

The tool description in the registry is prefixed with `[MCP:{server_name}]` so you can identify MCP tools at a glance.

---

## Managing Connections

### Via Dashboard
Go to **MCP** → click **Connect** / **Disconnect** per server. Connected servers show their tool count and status.

### Via API

```bash
# Connect
curl -X POST http://localhost:47821/api/mcp/servers/filesystem/connect \
  -H "Authorization: Bearer acm_xxx"

# Disconnect
curl -X POST http://localhost:47821/api/mcp/servers/filesystem/disconnect \
  -H "Authorization: Bearer acm_xxx"

# Status
curl http://localhost:47821/api/mcp/servers \
  -H "Authorization: Bearer acm_xxx"
```

Response from status:
```json
[
  {
    "name": "filesystem",
    "transport": "stdio",
    "connected": true,
    "tools": [
      {"name": "read_file", "description": "Read a file", "inputSchema": {...}},
      {"name": "write_file", "description": "Write a file", "inputSchema": {...}}
    ],
    "error": null
  }
]
```

---

## Building a Custom MCP Server

You can expose any external service or internal API as an MCP server that OpenACM can call.

### Python Example (stdio)

```python
# my_mcp_server.py
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import asyncio

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
                    "symbol": {
                        "type": "string",
                        "description": "Stock ticker (e.g. AAPL)"
                    }
                },
                "required": ["symbol"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "get_stock_price":
        symbol = arguments["symbol"]
        price = await fetch_price_from_api(symbol)  # your logic here
        return [TextContent(type="text", text=f"{symbol}: ${price:.2f}")]

async def main():
    async with stdio_server() as streams:
        await server.run(*streams, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

Register it in OpenACM:
```json
{
  "name": "stocks",
  "transport": "stdio",
  "command": "python",
  "args": ["my_mcp_server.py"],
  "auto_connect": true
}
```

### Streamable HTTP Example

For servers that should stay running independently:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-http-server")

@mcp.tool()
async def do_something(param: str) -> str:
    return f"Result: {param}"

mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)
```

Then connect via:
```json
{
  "name": "my-http-server",
  "transport": "streamable_http",
  "url": "http://localhost:8080/mcp",
  "auto_connect": true
}
```

---

## Security Considerations

- MCP tools are assigned `risk_level="medium"` by default and the `mcp` category
- They go through the same security sandbox as built-in tools
- For `stdio` servers, the subprocess inherits the OS user of the OpenACM process
- If a server requires an API key, it's stored in `config/mcp_servers.json` — secure this file the same way you secure `config/.env`
- Review what a server exposes before connecting — you're trusting its code to execute on behalf of the agent

---

## Lifecycle

On startup, OpenACM:
1. Loads `config/mcp_servers.json`
2. Connects to all servers where `auto_connect: true`
3. Registers their tools in the global ToolRegistry

On disconnect (or server crash):
1. Tools are unregistered from the registry
2. The agent can no longer call them
3. Reconnect manually via dashboard or API

---

## Popular MCP Servers

| Server | Install | What it provides |
|--------|---------|-----------------|
| `@modelcontextprotocol/server-filesystem` | `npx -y ...` | File system read/write |
| `@modelcontextprotocol/server-brave-search` | `npx -y ...` | Brave web search |
| `@modelcontextprotocol/server-github` | `npx -y ...` | GitHub API |
| `@modelcontextprotocol/server-sqlite` | `npx -y ...` | SQLite query/modify |
| Unity MCP | Separate install | Unity 3D scene control |

Find more at the [MCP server registry](https://modelcontextprotocol.io/servers).
