"""
Tool Registry — manages all available tools.

Handles tool registration, schema generation, and execution
with security policy enforcement.
"""

import json
import time
import types
from typing import Any

import structlog

from openacm.core.events import EventBus
from openacm.security.sandbox import Sandbox
from openacm.storage.database import Database
from openacm.tools.base import ToolDefinition, get_registered_tools

log = structlog.get_logger()


class ToolRegistry:
    """Central registry for all tools."""

    def __init__(self, sandbox: Sandbox, event_bus: EventBus, database: Database):
        self.sandbox = sandbox
        self.event_bus = event_bus
        self.database = database
        self.tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        """Register a single tool."""
        self.tools[tool.name] = tool
        log.debug("Tool registered", name=tool.name, risk=tool.risk_level)

    def register_module(self, module: types.ModuleType):
        """
        Register all @tool-decorated functions from a module.
        Imports the module to trigger decorator registration, then
        collects tools that have _tool_definition attributes.
        """
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if callable(attr) and hasattr(attr, "_tool_definition"):
                tool_def: ToolDefinition = attr._tool_definition
                self.register(tool_def)

    # Keyword-to-category mapping for intent-based tool filtering
    INTENT_KEYWORDS: dict[str, list[str]] = {
        "system": [
            "run", "execute", "command", "terminal", "bash", "shell", "install",
            "system", "proceso", "ejecuta", "ejecutar", "pip", "npm",
        ],
        "file": [
            "file", "read", "write", "save", "directory", "folder",
            "archivo", "carpeta", "leer", "escribir", "guardar", "lista",
            "pdf", "excel", "word", "pptx", "powerpoint", "xlsx", "docx",
            "csv", "zip", "download", "descargar", "adjunto", "adjuntar",
        ],
        "web": [
            "search", "browse", "url", "website", "navigate", "click",
            "busca", "buscar", "web", "página", "página web",
        ],
        "ai": [
            "remember", "memory", "recall", "search_memory",
            "recuerda", "memoria", "olvida", "recordar",
        ],
        "media": [
            "screenshot", "image", "photo", "capture", "pdf", "send_file",
            "captura", "pantalla", "foto", "imagen", "enviar archivo",
        ],
        "blender": [
            "blender", "3d", "model", "modelar", "modela", "mesh", "malla",
            "bpy", "glb", "gltf", "stl", "obj", "blend",
            "chess", "ajedrez", "pieza", "esfera", "cubo", "cilindro",
            "render", "renderizar", "three-dimensional", "sculpt", "esculp",
            "animate", "animacion", "rig", "skeleton", "esqueleto",
            "three dimensional", "tridimensional",
        ],
        "google": [
            "gmail", "email", "correo", "calendar", "calendario",
            "event", "evento", "drive", "youtube", "google",
        ],
        "meta": [
            "skill", "tool", "herramienta", "habilidad",
            "create_skill", "create_tool",
        ],
    }

    def get_tools_schema(self) -> list[dict[str, Any]]:
        """Get all tools in OpenAI function calling format."""
        return [tool.to_openai_schema() for tool in self.tools.values()]

    def get_tools_by_intent(self, message: str) -> list[dict[str, Any]]:
        """Return only tools relevant to the user's message + always-available core tools.

        Category 'general' tools are always included when filtering is active.
        If no specific intent is detected, all tools are sent as a safety fallback.
        """
        msg_lower = message.lower()
        matched_categories: set[str] = {"general"}  # always include general

        for cat, keywords in self.INTENT_KEYWORDS.items():
            if any(kw in msg_lower for kw in keywords):
                matched_categories.add(cat)

        # No specific intent detected → send only general-category tools.
        # Specialized tools (google, blender, etc.) are expensive and should
        # only appear when the user's message explicitly asks for them.
        if matched_categories == {"general"}:
            return [t.to_openai_schema() for t in self.tools.values() if t.category == "general"]

        filtered = [
            t.to_openai_schema()
            for t in self.tools.values()
            if t.category in matched_categories or t.category == "general"
        ]

        log.debug(
            "Tool filtering applied",
            categories=sorted(matched_categories),
            total_tools=len(self.tools),
            filtered_tools=len(filtered),
        )

        return filtered

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str = "",
        channel_id: str = "",
        _brain=None,
    ) -> str:
        """
        Execute a tool by name with the given arguments.

        Injects sandbox, brain, and other context into the tool handler.
        Logs execution to database.
        """
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found"

        tool = self.tools[tool_name]
        start_time = time.time()
        success = True

        try:
            # Inject context into tool call
            result = await tool.handler(
                **arguments,
                _sandbox=self.sandbox,
                _event_bus=self.event_bus,
                _brain=_brain,
            )
            result_str = str(result)
        except Exception as e:
            result_str = f"Error: {str(e)}"
            success = False
            log.error("Tool execution failed", tool=tool_name, error=str(e))

        elapsed_ms = int((time.time() - start_time) * 1000)

        # Log to database
        try:
            await self.database.log_tool_execution(
                user_id=user_id,
                channel_id=channel_id,
                tool_name=tool_name,
                arguments=json.dumps(arguments, default=str),
                result=result_str[:5000],  # truncate for storage
                success=success,
                elapsed_ms=elapsed_ms,
            )
        except Exception as e:
            log.error("Failed to log tool execution", error=str(e))

        return result_str
