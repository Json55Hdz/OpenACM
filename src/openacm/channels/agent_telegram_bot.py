"""
Agent Telegram Bot — connects individual agents to their own Telegram bots.

Each agent with a telegram_token in the DB gets its own bot.
Uses AgentBrainAdapter to make AgentRunner look like a Brain,
so TelegramChannel handles all the Telegram plumbing as normal.
"""

import asyncio
import structlog

from openacm.channels.telegram_channel import TelegramChannel
from openacm.core.agent_runner import AgentRunner
from openacm.core.config import TelegramConfig

log = structlog.get_logger()


class AgentBrainAdapter:
    """
    Wraps AgentRunner + agent config to look like a Brain.

    TelegramChannel only calls process_message() — this adapter
    satisfies that interface and routes to the AgentRunner.

    Memory is isolated per (agent, telegram_user) pair so different
    users talking to the same agent bot don't share conversation history.
    """

    def __init__(self, agent: dict, agent_runner: AgentRunner):
        self.agent = agent
        self.agent_runner = agent_runner

    @property
    def memory(self):
        """Expone la memoria del AgentRunner para que CommandProcessor funcione."""
        return self.agent_runner.memory

    @property
    def llm_router(self):
        """Expone el LLM router para que CommandProcessor funcione."""
        return self.agent_runner.llm_router

    @property
    def channel_type(self) -> str:
        """Unique channel_type for this agent's bot — prevents cross-bot event handling."""
        return f"telegram_a{self.agent['id']}"

    async def process_message(
        self,
        content: str,
        user_id: str,
        channel_id: str,
        channel_type: str,
        attachments: list | None = None,
    ) -> str:
        # Prefix user_id to avoid collision with main brain memory namespaces
        scoped_user_id = f"tg_{user_id}"
        return await self.agent_runner.run(
            agent=self.agent,
            message=content,
            user_id=scoped_user_id,
            channel_id=channel_id,
            channel_type=self.channel_type,  # ej: "telegram_a5" — único por agente
        )


class AgentTelegramChannel(TelegramChannel):
    """
    TelegramChannel que solo responde a eventos de su agente específico.

    Sobreescribe _on_message_sent para filtrar por channel_type único
    en lugar de "telegram" genérico — evita que múltiples bots intenten
    responder al mismo chat.
    """

    def __init__(self, config, brain: AgentBrainAdapter, event_bus, database=None):
        super().__init__(config, brain, event_bus, database)
        self._agent_channel_type = brain.channel_type  # ej: "telegram_a5"

    async def _on_message_sent(self, event_type: str, data: dict):
        # Solo procesar eventos de ESTE agente, no de otros bots
        if data.get("channel_type") != self._agent_channel_type:
            return
        # Delegate con channel_type reemplazado a "telegram" para que el
        # resto de la lógica (envío de archivos, split de mensajes) funcione igual
        data = dict(data)
        data["channel_type"] = "telegram"
        await super()._on_message_sent(event_type, data)


class AgentBotManager:
    """
    Manages one TelegramChannel per agent that has a telegram_token.

    Handles start, stop, and restart of individual agent bots.
    Called at startup and whenever an agent's token changes.
    """

    def __init__(self, agent_runner: AgentRunner, event_bus, database):
        self.agent_runner = agent_runner
        self.event_bus = event_bus
        self.database = database
        # agent_id → TelegramChannel
        self._bots: dict[int, TelegramChannel] = {}

    async def start_all(self):
        """Start a bot for every agent with a telegram_token."""
        agents = await self.database.get_all_agents()
        active = [a for a in agents if a.get("is_active") and a.get("telegram_token", "").strip()]
        if not active:
            log.info("No agent Telegram bots configured")
            return

        for agent in active:
            await self.start_bot(agent)

        log.info("Agent Telegram bots started", count=len(active))

    async def start_bot(self, agent: dict):
        """Start a Telegram bot for a single agent."""
        agent_id = agent["id"]
        token = agent.get("telegram_token", "").strip()
        if not token:
            return

        # Stop existing bot if running
        await self.stop_bot(agent_id)

        brain_adapter = AgentBrainAdapter(agent, self.agent_runner)
        config = TelegramConfig(token=token, enabled=True)

        bot = AgentTelegramChannel(
            config=config,
            brain=brain_adapter,
            event_bus=self.event_bus,
            database=self.database,
        )
        self._bots[agent_id] = bot

        asyncio.create_task(bot.start())
        await asyncio.wait_for(bot.ready_event.wait(), timeout=15)

        if bot.is_connected:
            log.info("Agent bot started", agent=agent["name"], agent_id=agent_id)
        else:
            log.warning("Agent bot failed to start", agent=agent["name"], agent_id=agent_id)
            self._bots.pop(agent_id, None)

    async def stop_bot(self, agent_id: int):
        """Stop the bot for a given agent."""
        bot = self._bots.pop(agent_id, None)
        if bot:
            await bot.stop()
            log.info("Agent bot stopped", agent_id=agent_id)

    async def restart_bot(self, agent_id: int):
        """Reload agent from DB and restart its bot."""
        agent = await self.database.get_agent(agent_id)
        if not agent:
            await self.stop_bot(agent_id)
            return
        if not agent.get("telegram_token", "").strip() or not agent.get("is_active"):
            await self.stop_bot(agent_id)
            return
        await self.start_bot(agent)

    async def stop_all(self):
        """Stop all running agent bots."""
        for agent_id in list(self._bots.keys()):
            await self.stop_bot(agent_id)

    def get_status(self) -> list[dict]:
        """Return status of all agent bots."""
        return [
            {"agent_id": agent_id, "connected": bot.is_connected}
            for agent_id, bot in self._bots.items()
        ]
