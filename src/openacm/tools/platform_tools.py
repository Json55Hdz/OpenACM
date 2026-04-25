"""
Platform Management Tools — let the LLM manage all OpenACM features from chat.

Covers: MCP servers, LLM config, routines, and system status.
The MCPManager reference is injected by app.py after initialization.
"""

import os
import structlog
from openacm.tools.base import tool

log = structlog.get_logger()

# Injected by app.py
_mcp_manager = None
_config = None  # AppConfig instance


def _port() -> str:
    return os.environ.get("OPENACM_PORT", "47821")


def _get_db(brain):
    if brain and hasattr(brain, "memory") and brain.memory:
        return brain.memory.database
    return None


# ─── MCP Server Tools ─────────────────────────────────────────────────────────

@tool(
    name="list_mcp_servers",
    description=(
        "List all configured MCP (Model Context Protocol) servers and their connection status. "
        "Shows which servers are connected and what tools they expose."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    risk_level="low",
    category="system",
)
async def list_mcp_servers(_brain=None, **kwargs) -> str:
    if _mcp_manager is None:
        return "MCP manager no disponible."
    servers = _mcp_manager.get_status()
    port = _port()
    if not servers:
        return (
            f"No hay servidores MCP configurados aún.\n\n"
            f"[Gestionar MCP →](http://localhost:{port}/settings/mcp)"
        )
    lines = [f"**Servidores MCP ({len(servers)}):**\n"]
    for s in servers:
        status = "🟢 conectado" if s["connected"] else "🔴 desconectado"
        tool_count = len(s.get("tools", []))
        transport = s.get("transport", "stdio")
        lines.append(
            f"- **{s['name']}** ({transport}) — {status}"
            + (f" | {tool_count} tools" if s["connected"] else "")
            + (f"\n  Error: {s['error']}" if s.get("error") else "")
        )
    lines.append(f"\n[Gestionar MCP →](http://localhost:{port}/settings/mcp)")
    return "\n".join(lines)


@tool(
    name="add_mcp_server",
    description=(
        "Add a new MCP (Model Context Protocol) server to OpenACM. "
        "Supports stdio (local process) and SSE/HTTP (remote URL) transports. "
        "After adding, use connect_mcp_server to activate it. "
        "EXAMPLES: 'add the filesystem MCP server', 'connect to a remote MCP at http://...'"
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Unique identifier for this server (no spaces, e.g. 'filesystem')",
            },
            "transport": {
                "type": "string",
                "description": "Connection type: 'stdio' for local process, 'sse' or 'streamable_http' for remote URL",
                "enum": ["stdio", "sse", "streamable_http"],
                "default": "stdio",
            },
            "command": {
                "type": "string",
                "description": "Executable to run (stdio only, e.g. 'npx' or 'uvx')",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Arguments for the command (stdio only)",
            },
            "url": {
                "type": "string",
                "description": "Server URL (SSE/HTTP only, e.g. 'http://localhost:8080/sse')",
            },
            "api_key": {
                "type": "string",
                "description": "Bearer token for authenticated SSE/HTTP servers",
            },
            "auto_connect": {
                "type": "boolean",
                "description": "Connect automatically on OpenACM startup",
                "default": False,
            },
        },
        "required": ["name", "transport"],
    },
    risk_level="medium",
    category="system",
)
async def add_mcp_server(
    name: str,
    transport: str = "stdio",
    command: str = "",
    args: list | None = None,
    url: str = "",
    api_key: str = "",
    auto_connect: bool = False,
    _brain=None,
    **kwargs,
) -> str:
    if _mcp_manager is None:
        return "MCP manager no disponible."

    if transport == "stdio" and not command:
        return "Error: 'command' es requerido para el transporte stdio."
    if transport in ("sse", "streamable_http") and not url:
        return "Error: 'url' es requerido para el transporte SSE/HTTP."

    config_data = {
        "name": name,
        "transport": transport,
        "command": command,
        "args": args or [],
        "url": url,
        "api_key": api_key,
        "auto_connect": auto_connect,
    }

    try:
        _mcp_manager.add_server(config_data)
        port = _port()
        return (
            f"✅ Servidor MCP **{name}** agregado ({transport}).\n\n"
            f"Dime que lo conecte o usa el botón Connect en la UI.\n\n"
            f"[Gestionar MCP →](http://localhost:{port}/settings/mcp)"
        )
    except Exception as e:
        return f"Error al agregar servidor MCP: {e}"


@tool(
    name="connect_mcp_server",
    description=(
        "Connect to a configured MCP server to load its tools into the AI. "
        "After connecting, the server's tools are immediately available."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the MCP server to connect",
            },
        },
        "required": ["name"],
    },
    risk_level="medium",
    category="system",
)
async def connect_mcp_server(name: str, _brain=None, **kwargs) -> str:
    if _mcp_manager is None:
        return "MCP manager no disponible."
    if name not in _mcp_manager.servers:
        configured = list(_mcp_manager.servers.keys())
        return (
            f"Servidor '{name}' no encontrado. Servidores configurados: {configured or 'ninguno'}.\n"
            f"Usa add_mcp_server para agregarlo primero."
        )
    try:
        conn = await _mcp_manager.connect(name)
        port = _port()
        if conn.connected:
            tool_names = [t["name"] for t in conn.tools]
            tools_str = ", ".join(tool_names[:10]) + ("..." if len(tool_names) > 10 else "")
            return (
                f"🟢 MCP **{name}** conectado — {len(conn.tools)} tools disponibles.\n"
                f"Tools: {tools_str}\n\n"
                f"[Gestionar MCP →](http://localhost:{port}/settings/mcp)"
            )
        else:
            return f"❌ Error al conectar **{name}**: {conn.error}"
    except Exception as e:
        return f"Error al conectar MCP: {e}"


@tool(
    name="disconnect_mcp_server",
    description="Disconnect from an MCP server and unload its tools.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the MCP server to disconnect",
            },
        },
        "required": ["name"],
    },
    risk_level="low",
    category="system",
)
async def disconnect_mcp_server(name: str, _brain=None, **kwargs) -> str:
    if _mcp_manager is None:
        return "MCP manager no disponible."
    try:
        await _mcp_manager.disconnect(name)
        port = _port()
        return (
            f"🔴 MCP **{name}** desconectado.\n\n"
            f"[Gestionar MCP →](http://localhost:{port}/settings/mcp)"
        )
    except Exception as e:
        return f"Error al desconectar MCP: {e}"


# ─── Config Tools ─────────────────────────────────────────────────────────────

@tool(
    name="get_openacm_config",
    description=(
        "Get the current OpenACM configuration: active LLM model, security mode, "
        "local router status, and other key settings."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    risk_level="low",
    category="system",
)
async def get_openacm_config(_brain=None, **kwargs) -> str:
    if _brain is None:
        return "Brain no disponible."
    port = _port()
    lines = ["**Configuración actual de OpenACM:**\n"]

    try:
        cfg = _config
        if cfg:
            lines.append(f"- **Modelo LLM:** {cfg.llm.default_provider}")
            lines.append(f"- **Modo seguridad:** {cfg.security.execution_mode}")
            lines.append(f"- **Router local:** {'habilitado' if cfg.local_router.enabled else 'deshabilitado'}")
            lines.append(f"- **Max context msgs:** {cfg.assistant.max_context_messages}")
            lines.append(f"- **Max tool iterations:** {cfg.assistant.max_tool_iterations}")
        if hasattr(_brain, "llm_router") and _brain.llm_router:
            current_model = getattr(_brain.llm_router, "current_model", None)
            if current_model:
                lines.append(f"- **Modelo activo:** {current_model}")
    except Exception as e:
        lines.append(f"(Error leyendo config: {e})")

    lines.append(f"\n[Ir a Configuración →](http://localhost:{port}/settings)")
    return "\n".join(lines)


@tool(
    name="switch_llm_model",
    description=(
        "Change the active LLM model for OpenACM chat. "
        "Accepts any LiteLLM model string such as 'anthropic/claude-opus-4-6', "
        "'openai/gpt-4o', 'ollama/llama3', or provider shortcuts. "
        "EXAMPLES: 'switch to Claude Opus', 'use GPT-4o', 'switch to local llama3'"
    ),
    parameters={
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "LiteLLM model string, e.g. 'anthropic/claude-opus-4-6'",
            },
        },
        "required": ["model"],
    },
    risk_level="low",
    category="system",
)
async def switch_llm_model(model: str, _brain=None, **kwargs) -> str:
    if _brain is None or not hasattr(_brain, "llm_router") or not _brain.llm_router:
        return "LLM router no disponible."
    try:
        old_model = getattr(_brain.llm_router, "current_model", "desconocido")
        _brain.llm_router.current_model = model
        port = _port()
        return (
            f"✅ Modelo cambiado: **{old_model}** → **{model}**\n\n"
            f"[Configuración →](http://localhost:{port}/settings)"
        )
    except Exception as e:
        return f"Error al cambiar modelo: {e}"


@tool(
    name="update_security_mode",
    description=(
        "Change the security/execution mode for tool runs.\n"
        "- 'confirmation': ask user before each sensitive tool\n"
        "- 'auto': run all tools automatically without asking\n"
        "- 'yolo': no restrictions at all (dangerous)"
    ),
    parameters={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["confirmation", "auto", "yolo"],
                "description": "New execution mode",
            },
        },
        "required": ["mode"],
    },
    risk_level="medium",
    category="system",
)
async def update_security_mode(mode: str, _brain=None, **kwargs) -> str:
    if _config is None:
        return "Config no disponible."
    try:
        _config.security.execution_mode = mode
        port = _port()
        emoji = {"confirmation": "🔒", "auto": "⚡", "yolo": "🔥"}.get(mode, "")
        return (
            f"{emoji} Modo de seguridad cambiado a **{mode}**.\n\n"
            f"[Configuración →](http://localhost:{port}/settings)"
        )
    except Exception as e:
        return f"Error al actualizar modo: {e}"


# ─── Routine Tools ────────────────────────────────────────────────────────────

@tool(
    name="list_routines",
    description=(
        "List all detected activity routines (patterns the AI found in your OS usage). "
        "Shows name, apps involved, and schedule pattern."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    risk_level="low",
    category="system",
)
async def list_routines(_brain=None, **kwargs) -> str:
    db = _get_db(_brain)
    if not db:
        return "Base de datos no disponible."
    port = _port()
    try:
        routines = await db.get_all_routines()
        if not routines:
            return (
                f"No hay rutinas detectadas aún. Usa 'analizar mis rutinas' para detectarlas.\n\n"
                f"[Ir a Rutinas →](http://localhost:{port}/routines)"
            )
        lines = [f"**Rutinas detectadas ({len(routines)}):**\n"]
        for r in routines:
            apps = r.get("apps", [])
            if isinstance(apps, str):
                import json
                try:
                    apps = json.loads(apps)
                except Exception:
                    apps = [apps]
            apps_str = ", ".join(apps[:4]) if apps else "N/A"
            lines.append(
                f"- **[{r['id']}] {r['name']}** — {r.get('schedule_pattern', '')}\n"
                f"  Apps: {apps_str}"
            )
        lines.append(f"\n[Ver Rutinas →](http://localhost:{port}/routines)")
        return "\n".join(lines)
    except Exception as e:
        return f"Error al listar rutinas: {e}"


@tool(
    name="execute_routine",
    description=(
        "Execute a detected routine immediately — opens the configured apps "
        "and sets up the workspace for that activity."
    ),
    parameters={
        "type": "object",
        "properties": {
            "routine_id": {
                "type": "integer",
                "description": "The numeric ID of the routine to execute.",
            },
        },
        "required": ["routine_id"],
    },
    risk_level="medium",
    category="system",
)
async def execute_routine(routine_id: int, _brain=None, **kwargs) -> str:
    db = _get_db(_brain)
    if not db:
        return "Base de datos no disponible."
    try:
        routine = await db.get_routine(routine_id)
        if not routine:
            return f"Rutina {routine_id} no encontrada."
        from openacm.watchers.routine_executor import RoutineExecutor
        executor = RoutineExecutor()
        await executor.execute(routine)
        port = _port()
        return (
            f"✅ Rutina **{routine['name']}** ejecutada.\n\n"
            f"[Ver Rutinas →](http://localhost:{port}/routines)"
        )
    except Exception as e:
        return f"Error al ejecutar rutina: {e}"
