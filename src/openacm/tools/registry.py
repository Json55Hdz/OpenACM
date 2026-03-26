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

    def get_tools_schema(self) -> list[dict[str, Any]]:
        """Get all tools in OpenAI function calling format."""
        return [tool.to_openai_schema() for tool in self.tools.values()]

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str = "",
        channel_id: str = "",
    ) -> str:
        """
        Execute a tool by name with the given arguments.
        
        Injects sandbox and other context into the tool handler.
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
