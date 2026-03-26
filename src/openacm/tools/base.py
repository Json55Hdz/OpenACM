"""
Tool base class and decorator for defining tools.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


@dataclass
class ToolDefinition:
    """Describes a tool that the AI can call."""
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Coroutine]
    risk_level: str = "low"  # low, medium, high
    needs_sandbox: bool = False

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# Global list to collect tool definitions from modules
_registered_tools: list[ToolDefinition] = []


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    risk_level: str = "low",
    needs_sandbox: bool = False,
):
    """
    Decorator to register an async function as a tool.
    
    Usage:
        @tool(
            name="my_tool",
            description="Does something useful",
            parameters={
                "type": "object",
                "properties": {
                    "arg1": {"type": "string", "description": "First argument"}
                },
                "required": ["arg1"]
            },
            risk_level="low"
        )
        async def my_tool(arg1: str, **ctx) -> str:
            return f"Result for {arg1}"
    """
    def decorator(func: Callable[..., Coroutine]) -> Callable[..., Coroutine]:
        tool_def = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=func,
            risk_level=risk_level,
            needs_sandbox=needs_sandbox,
        )
        _registered_tools.append(tool_def)
        func._tool_definition = tool_def
        return func
    return decorator


def get_registered_tools() -> list[ToolDefinition]:
    """Get all tools registered via the @tool decorator."""
    return list(_registered_tools)
