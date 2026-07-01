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

_KNOWLEDGE_CHAR_LIMIT = 40_000


class AgentRunner:
    """
    Executes messages through a configured agent.

    Agents share the main LLM/tool infrastructure but each one has its own:
    - system_prompt (personality + rules)
    - allowed_tools ('all', 'none', or JSON list of tool names)
    - memory namespace (isolated from the main chat)
    - knowledge base (injected from agent_knowledge table if database is set)
    """

    def __init__(self, llm_router, tool_registry, memory, event_bus, database=None):
        self.llm_router = llm_router
        self.tool_registry = tool_registry
        self.memory = memory
        self.event_bus = event_bus
        self.database = database

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
        """Prepend knowledge block and current date to base system prompt, truncating if needed."""
        import datetime
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_block = f"[System Context: The current date and time is {now_str}. You must take this into account when answering time-sensitive questions or searching the web.]\n\n"

        if not knowledge_items:
            return date_block + base_prompt

        sections = "\n\n".join(
            f"### {item['title']}\n{item['content']}" for item in knowledge_items
        )
        block = f"## Base de conocimiento\n\n{sections}"

        if len(block) > _KNOWLEDGE_CHAR_LIMIT:
            block = block[:_KNOWLEDGE_CHAR_LIMIT] + "\n\n[Conocimiento truncado por límite de contexto]"

        return f"{date_block}{block}\n\n{base_prompt}"

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

        # Inject channel-specific formatting instructions
        if channel_type and "whatsapp" in channel_type.lower():
            system_prompt += (
                "\n\n[FORMATTING INSTRUCTIONS: You are replying on WhatsApp. "
                "CRITICAL: DO NOT use Markdown tables, they are unreadable on WhatsApp! Use short bulleted lists instead. "
                "Keep paragraphs very short. Use WhatsApp bold formatting (*text*) instead of standard markdown (**text**).]"
            )

        config = AssistantConfig(
            name=agent["name"],
            system_prompt=system_prompt,
            max_tool_iterations=10,
            onboarding_completed=True,
            is_agent=True,
        )

        if channel_id is None:
            channel_id = f"agent_{agent['id']}"

        brain = Brain(
            config=config,
            llm_router=self.llm_router,
            memory=self.memory,
            event_bus=self.event_bus,
            tool_registry=self.tool_registry if agent.get("allowed_tools", "all") != "none" else None,
        )
        brain.agent_id = agent["id"]

        allowed = agent.get("allowed_tools", "all")
        if allowed not in ("all", "none"):
            _tools = self._get_tools(allowed)

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
