"""
AgentRunner — runs an autonomous agent with its own system prompt and rules.

Each agent is an independent "mini-brain" that shares the main LLM router,
tool registry, and memory manager — but uses a custom system prompt and can
have its own tool restrictions.
"""

import asyncio
import json
from typing import Any

import structlog

log = structlog.get_logger()


class AgentRunner:
    """
    Executes messages through a configured agent.

    Agents share the main LLM/tool infrastructure but each one has its own:
    - system_prompt (personality + rules)
    - allowed_tools ('all', 'none', or JSON list of tool names)
    - memory namespace (isolated from the main chat)
    """

    def __init__(self, llm_router, tool_registry, memory, event_bus):
        self.llm_router = llm_router
        self.tool_registry = tool_registry
        self.memory = memory
        self.event_bus = event_bus

    def _get_tools(self, allowed_tools: str) -> list[dict] | None:
        """Return the tools list for this agent based on its policy."""
        if not self.tool_registry:
            return None
        if allowed_tools == "none":
            return None
        if allowed_tools == "all":
            return self.tool_registry.get_tools_schema()
        # JSON list of tool names
        try:
            names = json.loads(allowed_tools)
            all_tools = self.tool_registry.get_tools_schema()
            return [t for t in all_tools if t["function"]["name"] in names]
        except Exception:
            return self.tool_registry.get_tools_schema()

    async def run(
        self,
        agent: dict[str, Any],
        message: str,
        user_id: str = "user",
        channel_id: str | None = None,
        channel_type: str = "agent",
    ) -> str:
        """
        Process a message through the given agent config.

        Uses a dedicated channel namespace so each agent's memory is isolated
        from the main chat and from other agents.

        channel_id / channel_type can be overridden by callers (e.g. Telegram)
        so that EVENT_MESSAGE_SENT is emitted with the correct routing info.
        """
        from openacm.core.config import AssistantConfig
        from openacm.core.brain import Brain

        config = AssistantConfig(
            name=agent["name"],
            system_prompt=agent["system_prompt"],
            max_tool_iterations=10,
        )

        # Use caller-provided channel_id or fall back to isolated namespace
        if channel_id is None:
            channel_id = f"agent_{agent['id']}"

        brain = Brain(
            config=config,
            llm_router=self.llm_router,
            memory=self.memory,
            event_bus=self.event_bus,
            tool_registry=self.tool_registry if agent.get("allowed_tools", "all") != "none" else None,
        )

        # Monkey-patch tool selection to respect allowed_tools
        allowed = agent.get("allowed_tools", "all")
        if allowed not in ("all", "none"):
            _tools = self._get_tools(allowed)

            original_get = brain.tool_registry.get_all_tools if brain.tool_registry else None

            class _FilteredRegistry:
                def get_tools_schema(self_inner):
                    return _tools or []

                def get_tools_by_intent(self_inner, msg):
                    return _tools or []

                def __getattr__(self_inner, name):
                    return getattr(self.tool_registry, name)

            brain.tool_registry = _FilteredRegistry()

        try:
            response = await brain.process_message(
                content=message,
                user_id=user_id,
                channel_id=channel_id,
                channel_type=channel_type,
            )
            return response
        except Exception as e:
            log.error("AgentRunner error", agent_id=agent["id"], error=str(e))
            return f"Error processing message: {e}"
