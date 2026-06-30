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
        # Scope user_id to agent to isolate each agent's conversation history —
        # without this, two agents serving the same Telegram user share the same
        # memory key (channel_id:user_id) and their histories bleed into each other.
        scoped_user_id = f"a{self.agent['id']}_tg_{user_id}"
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

    def _owns_event(self, data: dict) -> bool:
        return data.get("channel_type") == self._agent_channel_type

    async def _on_message_sent(self, event_type: str, data: dict):
        # Solo procesar eventos de ESTE agente, no de otros bots
        if data.get("channel_type") != self._agent_channel_type:
            return
        # Delegate con channel_type reemplazado a "telegram" para que el
        # resto de la lógica (envío de archivos, split de mensajes) funcione igual
        data = dict(data)
        data["channel_type"] = "telegram"
        await super()._on_message_sent(event_type, data)

    async def start(self):
        await super().start()
        self.event_bus.on("channel:send", self._handle_channel_send)

    async def stop(self):
        try:
            self.event_bus.off("channel:send", self._handle_channel_send)
        except Exception:
            pass
        await super().stop()

    async def _handle_channel_send(self, event_type: str, data: dict):
        """Deliver a proactive message to the configured chat if this agent owns it."""
        if data.get("agent_id") != self.brain.agent["id"]:
            return
        target_id = str(data.get("target_id", ""))
        text = str(data.get("text", ""))
        if target_id and text:
            await self.send_message(target_id, text)


class AgentChannelManager:
    """
    Manages one channel per agent per type (telegram, whatsapp).

    Replaces AgentBotManager. Reads from the agent_channels table instead
    of the agents.telegram_token field.
    """

    def __init__(self, agent_runner: AgentRunner, event_bus, database):
        self.agent_runner = agent_runner
        self.event_bus = event_bus
        self.database = database
        # agent_id → {type → channel_instance}
        self._channels: dict[int, dict[str, object]] = {}
        # phone_number_id → AgentWhatsAppChannel (for webhook routing)
        self._whatsapp_by_phone: dict[str, object] = {}

    async def start_all(self):
        """Start channels for all active agents."""
        agents = await self.database.get_all_agents()
        active = [a for a in agents if a.get("is_active")]
        if not active:
            log.info("No active agents with channels configured")
            return

        started = 0
        for agent in active:
            channel_rows = await self.database.get_agent_channels(agent["id"])
            for row in channel_rows:
                if row.get("is_active"):
                    try:
                        await self.start_channel(agent, row)
                        started += 1
                    except Exception as exc:
                        log.warning(
                            "AgentChannelManager: failed to start channel",
                            agent=agent["name"],
                            type=row["type"],
                            error=str(exc),
                        )

        if started:
            log.info("Agent channels started", count=started)

    async def start_channel(self, agent: dict, channel_row: dict):
        """Start a single channel for an agent based on channel_row type."""
        channel_type = channel_row["type"]
        agent_id = agent["id"]
        import json as _json
        config_data = _json.loads(channel_row.get("config", "{}"))

        # Stop existing channel of this type if running
        await self.stop_channel(agent_id, channel_type)

        if channel_type == "telegram":
            channel = self._make_telegram_channel(agent, config_data)
        elif channel_type == "whatsapp":
            channel = self._make_whatsapp_channel(agent, config_data)
        elif channel_type == "whatsapp_web":
            channel = self._make_whatsapp_web_channel(agent, config_data)
        else:
            log.warning("Unknown channel type", type=channel_type)
            return

        # Register in _channels dict
        if agent_id not in self._channels:
            self._channels[agent_id] = {}
        self._channels[agent_id][channel_type] = channel

        # Register WhatsApp in phone lookup
        if channel_type == "whatsapp":
            phone_id = config_data.get("phone_number_id", "")
            if phone_id:
                self._whatsapp_by_phone[phone_id] = channel

        asyncio.create_task(channel.start())
        await asyncio.wait_for(channel.ready_event.wait(), timeout=15)

        if channel.is_connected:
            log.info("Agent channel started", agent=agent["name"], type=channel_type)
        else:
            log.warning("Agent channel failed to connect", agent=agent["name"], type=channel_type)

    def _make_telegram_channel(self, agent: dict, config_data: dict):
        token = config_data.get("token", "")
        brain_adapter = AgentBrainAdapter(agent, self.agent_runner)
        tg_config = TelegramConfig(token=token, enabled=True)
        return AgentTelegramChannel(
            config=tg_config,
            brain=brain_adapter,
            event_bus=self.event_bus,
            database=self.database,
        )

    def _make_whatsapp_web_channel(self, agent: dict, config_data: dict):
        from openacm.channels.agent_whatsapp_web_channel import AgentWhatsAppWebChannel
        from openacm.core.config import WhatsAppConfig
        wa_config = WhatsAppConfig(
            enabled=True,
            mode="bridge",
            bridge_url=config_data.get("bridge_url", "http://localhost:3000"),
        )
        return AgentWhatsAppWebChannel(
            config=wa_config,
            agent_runner=self.agent_runner,
            agent=agent,
            event_bus=self.event_bus,
        )

    def _make_whatsapp_channel(self, agent: dict, config_data: dict):
        from openacm.channels.agent_whatsapp_channel import AgentWhatsAppChannel
        from openacm.core.config import WhatsAppConfig
        wa_config = WhatsAppConfig(
            enabled=True,
            access_token=config_data.get("access_token", ""),
            phone_number_id=config_data.get("phone_number_id", ""),
            verify_token=config_data.get("verify_token", ""),
            app_secret=config_data.get("app_secret", ""),
        )
        return AgentWhatsAppChannel(
            config=wa_config,
            agent_runner=self.agent_runner,
            agent=agent,
            event_bus=self.event_bus,
        )

    async def stop_channel(self, agent_id: int, channel_type: str):
        """Stop a specific channel type for an agent."""
        agent_channels = self._channels.get(agent_id, {})
        ch = agent_channels.pop(channel_type, None)
        if not agent_channels:
            self._channels.pop(agent_id, None)
        if ch is None:
            return
        # Remove from whatsapp phone lookup
        if channel_type == "whatsapp":
            dead_phones = [k for k, v in self._whatsapp_by_phone.items() if v is ch]
            for k in dead_phones:
                del self._whatsapp_by_phone[k]
        try:
            await ch.stop()
        except Exception:
            pass
        log.info("Agent channel stopped", agent_id=agent_id, type=channel_type)

    async def restart_channel(self, agent_id: int, channel_type: str):
        """Reload channel config from DB and restart."""
        agent = await self.database.get_agent(agent_id)
        if not agent or not agent.get("is_active"):
            await self.stop_channel(agent_id, channel_type)
            return
        channel_rows = await self.database.get_agent_channels(agent_id)
        row = next((r for r in channel_rows if r["type"] == channel_type), None)
        if not row or not row.get("is_active"):
            await self.stop_channel(agent_id, channel_type)
            return
        await self.start_channel(agent, row)

    async def stop_all(self):
        """Stop all running channels."""
        for agent_id, type_map in list(self._channels.items()):
            for channel_type in list(type_map.keys()):
                await self.stop_channel(agent_id, channel_type)

    def get_channel_by_phone(self, phone_number_id: str):
        """Return the AgentWhatsAppChannel for this phone_number_id, or None."""
        return self._whatsapp_by_phone.get(phone_number_id)

    def get_whatsapp_channel_by_verify_token(self, token: str):
        """Return any active WhatsApp agent channel whose verify_token matches."""
        if not token:
            return None
        for ch in self._whatsapp_by_phone.values():
            cfg = getattr(ch, "config", None)
            if cfg and getattr(cfg, "verify_token", "") == token:
                return ch
        return None

    def get_status(self) -> list[dict]:
        """Return live connection status for all managed channels."""
        result = []
        for agent_id, type_map in self._channels.items():
            for channel_type, ch in type_map.items():
                result.append({
                    "agent_id": agent_id,
                    "type": channel_type,
                    "connected": ch.is_connected,
                })
        return result


# Keep old name as alias so existing code referencing AgentBotManager still imports
AgentBotManager = AgentChannelManager
