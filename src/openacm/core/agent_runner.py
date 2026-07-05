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

from openacm.tools.base import ToolDefinition

log = structlog.get_logger()

_KNOWLEDGE_CHAR_LIMIT = 40_000


def _build_flow_tool(flow: dict, executor) -> ToolDefinition:
    """Convert one flow DB row into a dynamically-callable ToolDefinition."""
    graph = json.loads(flow["graph_json"])
    start_node = next((n for n in graph["nodes"] if n["type"] == "start"), None)
    properties: dict = {}
    required: list[str] = []
    for p in (start_node["config"].get("parameters", []) if start_node else []):
        properties[p["name"]] = {"type": p.get("type", "string"), "description": p.get("description", "")}
        if p.get("required"):
            required.append(p["name"])

    async def handler(_brain=None, **kwargs) -> str:
        call_params = {k: v for k, v in kwargs.items() if not k.startswith("_")}
        return await executor.run(graph, call_params)

    return ToolDefinition(
        name=f"flow_{flow['id']}",
        description=flow["description"] or flow["name"],
        parameters={"type": "object", "properties": properties, "required": required},
        handler=handler,
        risk_level="medium",
        category="custom_flow",
    )


class _AgentToolRegistry:
    """Wraps the shared, global tool registry for one AgentRunner.run() call:
    applies this agent's allowed_tools system-tool filter (unchanged from
    before this class existed) AND always adds this agent's active flow
    tools on top, regardless of that filter. Flow tools are agent-private
    and additive — they are never subject to the allowed_tools allowlist,
    which only ever applied to the shared static/system tool set.

    Exposes `.tools` explicitly (not via __getattr__) because Brain's
    agentic loop gates every tool call on `tool_name in tool_registry.tools`
    before calling execute() — see brain_loop.py."""

    def __init__(self, base_registry, filtered_schema: list[dict] | None, flow_tools: dict[str, "ToolDefinition"]):
        self._base = base_registry
        self._filtered_schema = filtered_schema
        self._flow_tools = flow_tools
        self.tools = {**getattr(base_registry, "tools", {}), **flow_tools}

    def get_tools_schema(self) -> list[dict]:
        base_schema = self._filtered_schema if self._filtered_schema is not None else self._base.get_tools_schema()
        return base_schema + [t.to_openai_schema() for t in self._flow_tools.values()]

    def get_tools_by_intent(self, message: str) -> list[dict]:
        base_schema = self._base.get_tools_by_intent(message)
        if self._filtered_schema is not None:
            allowed_names = {t["function"]["name"] for t in self._filtered_schema}
            base_schema = [t for t in base_schema if t["function"]["name"] in allowed_names]
        return base_schema + [t.to_openai_schema() for t in self._flow_tools.values()]

    async def execute(self, tool_name: str, arguments: dict, user_id: str = "", channel_id: str = "", channel_type: str = "web", _brain=None) -> str:
        if tool_name in self._flow_tools:
            return await self._flow_tools[tool_name].handler(_brain=_brain, **arguments)
        return await self._base.execute(tool_name, arguments, user_id, channel_id, channel_type, _brain=_brain)

    def __getattr__(self, name):
        return getattr(self._base, name)


class AgentRunner:
    """
    Executes messages through a configured agent.

    Agents share the main LLM/tool infrastructure but each one has its own:
    - system_prompt (personality + rules)
    - allowed_tools ('all', 'none', or JSON list of tool names)
    - memory namespace (isolated from the main chat)
    - knowledge base (injected from agent_knowledge table if database is set)
    """

    def __init__(self, llm_router, tool_registry, memory, event_bus, database=None, skill_manager=None):
        self.llm_router = llm_router
        self.tool_registry = tool_registry
        self.memory = memory
        self.event_bus = event_bus
        self.database = database
        self.skill_manager = skill_manager

    def _get_tools(self, allowed_tools: str) -> list[dict] | None:
        """Return the tools list for this agent based on its policy."""
        if not self.tool_registry:
            return None
        if allowed_tools == "none":
            return None
        if allowed_tools == "all":
            return self.tool_registry.get_tools_schema()
        try:
            names = json.loads(allowed_tools)
            all_tools = self.tool_registry.get_tools_schema()
            return [t for t in all_tools if t["function"]["name"] in names]
        except Exception:
            return self.tool_registry.get_tools_schema()

    def _build_system_prompt(self, base_prompt: str, knowledge_items: list[dict]) -> str:
        """Prepend knowledge block to base system prompt, truncating if needed."""
        if not knowledge_items:
            return base_prompt

        sections = "\n\n".join(
            f"### {item['title']}\n{item['content']}" for item in knowledge_items
        )
        block = f"## Base de conocimiento\n\n{sections}"

        if len(block) > _KNOWLEDGE_CHAR_LIMIT:
            block = block[:_KNOWLEDGE_CHAR_LIMIT] + "\n\n[Conocimiento truncado por límite de contexto]"

        return f"{block}\n\n{base_prompt}"

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

        # Fetch knowledge and build enriched system prompt
        knowledge_items: list[dict] = []
        if self.database:
            try:
                knowledge_items = await self.database.get_agent_knowledge(agent["id"])
            except Exception as exc:
                log.warning("AgentRunner: failed to fetch knowledge", agent_id=agent["id"], error=str(exc))

        system_prompt = self._build_system_prompt(agent["system_prompt"], knowledge_items)

        if self.skill_manager:
            skills_prompt = await self.skill_manager.get_active_skills_prompt_for_agent(agent["id"])
            if skills_prompt:
                system_prompt = f"{system_prompt}\n\n{skills_prompt}"

        config = AssistantConfig(
            name=agent["name"],
            system_prompt=system_prompt,
            max_tool_iterations=10,
            onboarding_completed=True,
            is_agent=True,
        )

        if channel_id is None:
            channel_id = f"agent_{agent['id']}"

        allowed = agent.get("allowed_tools", "all")

        flow_tools: dict[str, ToolDefinition] = {}
        if self.database and allowed != "none":
            try:
                active_flows = await self.database.get_agent_flows(agent["id"], active_only=True)
            except Exception as exc:
                log.warning("AgentRunner: failed to fetch flows", agent_id=agent["id"], error=str(exc))
                active_flows = []
            if active_flows:
                from openacm.core.flow_executor import FlowExecutor

                async def get_connection(connection_id: int):
                    return await self.database.get_connection(connection_id)

                executor = FlowExecutor(get_connection=get_connection)
                flow_tools = {f"flow_{f['id']}": _build_flow_tool(f, executor) for f in active_flows}

        agent_tool_registry = self.tool_registry if allowed != "none" else None
        if allowed != "none" and (allowed not in ("all",) or flow_tools):
            filtered_schema = self._get_tools(allowed) if allowed not in ("all", "none") else None
            agent_tool_registry = _AgentToolRegistry(self.tool_registry, filtered_schema, flow_tools)

        brain = Brain(
            config=config,
            llm_router=self.llm_router,
            memory=self.memory,
            event_bus=self.event_bus,
            tool_registry=agent_tool_registry,
        )

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
