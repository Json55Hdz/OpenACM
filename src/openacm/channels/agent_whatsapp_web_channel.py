"""
AgentWhatsAppWebChannel — routes WhatsApp bridge messages to a specific agent's AgentRunner.

Uses the Node.js whatsapp-web.js bridge (unofficial API).
Each agent needs its own bridge instance at a unique bridge_url.
"""
from __future__ import annotations

import structlog

from openacm.channels.whatsapp_channel import WhatsAppChannel
from openacm.core.config import WhatsAppConfig
from openacm.core.events import EventBus, EVENT_CHANNEL_CONNECTED, EVENT_CHANNEL_DISCONNECTED
from openacm.core.agent_runner import AgentRunner

log = structlog.get_logger()


class AgentWhatsAppWebChannel(WhatsAppChannel):
    """WhatsApp bridge channel for a single agent (does not affect the global channel)."""

    def __init__(
        self,
        config: WhatsAppConfig,
        agent_runner: AgentRunner,
        agent: dict,
        event_bus: EventBus,
    ):
        # Pass brain=None — we override _handle_incoming so brain is never called
        super().__init__(config=config, brain=None, event_bus=event_bus)
        self.agent_runner = agent_runner
        self.agent = agent

    async def _handle_incoming(self, data: dict):
        """Route to AgentRunner with scoped user_id for memory isolation."""
        content = data.get("body", "")
        sender = data.get("from", "")
        chat_id = data.get("chatId", sender)

        if not content or not sender:
            return

        try:
            scoped_uid = f"a{self.agent['id']}_ww_{sender}"
            response = await self.agent_runner.run(
                agent=self.agent,
                message=content,
                user_id=scoped_uid,
                channel_id=chat_id,
                channel_type=f"whatsapp_web_a{self.agent['id']}",
            )
            if response:
                await self.send_message(chat_id, response)
        except Exception as exc:
            log.error(
                "AgentWhatsAppWebChannel processing error",
                agent=self.agent.get("name"),
                error=str(exc),
            )
