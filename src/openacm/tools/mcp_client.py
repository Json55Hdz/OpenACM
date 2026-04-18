"""
MCP (Model Context Protocol) Client Manager.

Manages connections to MCP servers via stdio or SSE/HTTP transports,
exposes their tools, and registers them dynamically in the ToolRegistry.
"""

import asyncio
import json
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()


class MCPServerConfig:
    """Configuration for a single MCP server."""

    def __init__(self, data: dict):
        self.name: str = data["name"]
        self.transport: str = data.get("transport", "stdio")  # stdio | sse
        # stdio
        self.command: str = data.get("command", "")
        self.args: list[str] = data.get("args", [])
        self.env: dict[str, str] | None = data.get("env") or None
        # sse / http
        self.url: str = data.get("url", "")
        self.api_key: str = data.get("api_key", "")          # Bearer token for SSE
        self.headers: dict[str, str] = data.get("headers", {}) or {}
        self.auto_connect: bool = data.get("auto_connect", False)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "url": self.url,
            "api_key": self.api_key,
            "headers": self.headers,
            "auto_connect": self.auto_connect,
        }


class MCPConnection:
    """Live connection to an MCP server."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.session: Any = None
        self._exit_stack = AsyncExitStack()
        self.tools: list[dict] = []
        self.connected = False
        self.error: str | None = None


class MCPManager:
    """
    Manages MCP server connections.

    - Loads / saves server configs in ``config/mcp_servers.json``.
    - Connects to servers (stdio subprocess or SSE HTTP).
    - Dynamically registers each server's tools in the ToolRegistry
      with the name pattern ``mcp__{server}__{tool}``.
    - Unregisters tools on disconnect.
    """

    def __init__(self, config_path: Path, tool_registry=None):
        self.config_path = config_path
        self.tool_registry = tool_registry
        self.servers: dict[str, MCPServerConfig] = {}
        self.connections: dict[str, MCPConnection] = {}
        self._load_configs()

    # ── Config persistence ────────────────────────────────────────────────

    def _load_configs(self):
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                for s in data.get("servers", []):
                    cfg = MCPServerConfig(s)
                    self.servers[cfg.name] = cfg
                log.debug("MCP configs loaded", count=len(self.servers))
            except Exception as e:
                log.error("Failed to load MCP configs", error=str(e))

    def _save_configs(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"servers": [s.to_dict() for s in self.servers.values()]}
        self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── CRUD for server configs ───────────────────────────────────────────

    def add_server(self, config: dict) -> MCPServerConfig:
        cfg = MCPServerConfig(config)
        self.servers[cfg.name] = cfg
        self._save_configs()
        return cfg

    def update_server(self, name: str, config: dict) -> MCPServerConfig:
        if name not in self.servers:
            raise ValueError(f"Server '{name}' not found")
        config["name"] = name
        self.servers[name] = MCPServerConfig(config)
        self._save_configs()
        return self.servers[name]

    def remove_server(self, name: str):
        if name in self.connections:
            asyncio.create_task(self.disconnect(name))
        self.servers.pop(name, None)
        self._save_configs()

    # ── Connect / disconnect ──────────────────────────────────────────────

    async def connect(self, name: str) -> MCPConnection:
        """Connect to an MCP server and load its tools."""
        if name not in self.servers:
            raise ValueError(f"Server '{name}' not configured")

        # Clean up any stale connection first
        if name in self.connections:
            await self.disconnect(name)

        cfg = self.servers[name]
        conn = MCPConnection(cfg)
        self.connections[name] = conn

        try:
            from mcp import ClientSession

            if cfg.transport == "stdio":
                from mcp import StdioServerParameters
                from mcp.client.stdio import stdio_client

                params = StdioServerParameters(
                    command=cfg.command,
                    args=cfg.args,
                    env=cfg.env,
                )
                read, write = await conn._exit_stack.enter_async_context(
                    stdio_client(params)
                )
            elif cfg.transport in ("sse", "http", "streamable_http"):
                # Merge api_key as Bearer header + any custom headers
                http_headers: dict[str, str] = dict(cfg.headers)
                if cfg.api_key:
                    http_headers.setdefault("Authorization", f"Bearer {cfg.api_key}")

                if cfg.transport == "sse":
                    from mcp.client.sse import sse_client
                    read, write = await conn._exit_stack.enter_async_context(
                        sse_client(cfg.url, headers=http_headers or None)
                    )
                else:
                    # streamable_http — the modern MCP HTTP transport (e.g. unity-mcp)
                    from mcp.client.streamable_http import streamablehttp_client
                    read, write, _ = await conn._exit_stack.enter_async_context(
                        streamablehttp_client(cfg.url, headers=http_headers or None)
                    )
            else:
                raise ValueError(f"Unknown transport: {cfg.transport!r}")

            conn.session = await conn._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await conn.session.initialize()

            # Fetch tool list
            result = await conn.session.list_tools()
            conn.tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": (
                        t.inputSchema
                        if hasattr(t, "inputSchema") and t.inputSchema
                        else {"type": "object", "properties": {}}
                    ),
                }
                for t in result.tools
            ]
            conn.connected = True
            conn.error = None

            if self.tool_registry:
                self._register_tools(name, conn)

            log.info("MCP server connected", server=name, tools=len(conn.tools))

        except BaseException as e:
            # Catch BaseException so CancelledError (from anyio task groups in
            # streamablehttp_client) is also captured as a readable error message.
            err_msg = str(e) or type(e).__name__
            if "ConnectError" in type(e).__name__ or "connect" in err_msg.lower():
                err_msg = f"Could not reach server at {cfg.url} — is it running?"
            conn.error = err_msg
            conn.connected = False
            log.error("MCP connection failed", server=name, error=err_msg)
            try:
                await conn._exit_stack.aclose()
            except BaseException:
                pass

        return conn

    async def disconnect(self, name: str):
        """Disconnect from an MCP server and unregister its tools."""
        conn = self.connections.pop(name, None)
        if conn is None:
            return

        if self.tool_registry:
            self._unregister_tools(name, conn)

        try:
            await conn._exit_stack.aclose()
        except Exception as e:
            log.error("MCP disconnect error", server=name, error=str(e))

        conn.connected = False
        log.info("MCP server disconnected", server=name)

    # ── Dynamic tool registration ─────────────────────────────────────────

    @staticmethod
    def _sanitize(s: str) -> str:
        """Replace any char that isn't a letter, digit, underscore, or dash with '_'."""
        return re.sub(r"[^a-zA-Z0-9_-]", "_", s)

    @classmethod
    def _tool_name(cls, server: str, tool: str) -> str:
        return f"mcp__{cls._sanitize(server)}__{cls._sanitize(tool)}"

    def _register_tools(self, server_name: str, conn: MCPConnection):
        from openacm.tools.base import ToolDefinition

        for t in conn.tools:
            full_name = self._tool_name(server_name, t["name"])

            # Build a handler that calls through to the MCP session
            async def _handler(
                _server=server_name, _tool=t["name"], **kwargs
            ) -> str:
                # Strip internal context kwargs that the registry injects
                call_args = {
                    k: v
                    for k, v in kwargs.items()
                    if not k.startswith("_")
                }
                return await self.call_tool(_server, _tool, call_args)

            tool_def = ToolDefinition(
                name=full_name,
                description=f"[MCP:{server_name}] {t['description']}",
                parameters=t["inputSchema"],
                handler=_handler,
                risk_level="medium",
                category="mcp",
            )
            self.tool_registry.register(tool_def)

    def _unregister_tools(self, server_name: str, conn: MCPConnection):
        for t in conn.tools:
            full_name = self._tool_name(server_name, t["name"])
            self.tool_registry.tools.pop(full_name, None)
        # Invalidate embedding cache so MCP tools are removed from semantic search.
        self.tool_registry._tool_embeddings = None
        self.tool_registry._tool_names_order = []

    # ── Tool execution ────────────────────────────────────────────────────

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict
    ) -> str:
        conn = self.connections.get(server_name)
        if conn is None or not conn.connected or conn.session is None:
            return f"Error: MCP server '{server_name}' is not connected"

        try:
            result = await conn.session.call_tool(tool_name, arguments)
            parts: list[str] = []
            for content in result.content:
                if hasattr(content, "text"):
                    parts.append(content.text)
                else:
                    parts.append(str(content))
            return "\n".join(parts) if parts else "OK"
        except Exception as e:
            return f"Error calling MCP tool '{tool_name}': {e}"

    # ── Status ────────────────────────────────────────────────────────────

    def get_status(self) -> list[dict]:
        result = []
        for name, cfg in self.servers.items():
            conn = self.connections.get(name)
            result.append(
                {
                    "name": name,
                    "transport": cfg.transport,
                    "command": cfg.command,
                    "args": cfg.args,
                    "url": cfg.url,
                    "auto_connect": cfg.auto_connect,
                    "connected": conn.connected if conn else False,
                    "error": conn.error if conn else None,
                    "tools": conn.tools if (conn and conn.connected) else [],
                }
            )
        return result

    # ── Lifecycle helpers ─────────────────────────────────────────────────

    async def auto_connect_all(self):
        """Connect to all servers that have auto_connect=True."""
        for name, cfg in self.servers.items():
            if cfg.auto_connect:
                try:
                    await self.connect(name)
                except Exception as e:
                    log.error("Auto-connect failed", server=name, error=str(e))

    async def disconnect_all(self):
        """Gracefully disconnect from every connected server."""
        for name in list(self.connections.keys()):
            await self.disconnect(name)
