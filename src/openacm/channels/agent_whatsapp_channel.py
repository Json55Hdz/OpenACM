"""
AgentWhatsAppChannel — routes WhatsApp messages to a specific agent's AgentRunner.

Subclasses WhatsAppCloudChannel and overrides:
  - start(): same credential check but does NOT set the _active_channel singleton
  - _respond(): routes to AgentRunner instead of Brain
"""
from __future__ import annotations

import structlog
import httpx

from openacm.channels.whatsapp_cloud_channel import WhatsAppCloudChannel
from openacm.core.config import WhatsAppConfig
from openacm.core.events import EventBus, EVENT_CHANNEL_CONNECTED, EVENT_CHANNEL_DISCONNECTED
from openacm.core.agent_runner import AgentRunner

log = structlog.get_logger()


class AgentWhatsAppChannel(WhatsAppCloudChannel):
    """WhatsApp channel for a single agent (does not touch the global _active_channel)."""

    def __init__(
        self,
        config: WhatsAppConfig,
        agent_runner: AgentRunner,
        agent: dict,
        event_bus: EventBus,
    ):
        # Pass brain=None — we override _respond so brain is never called
        super().__init__(config=config, brain=None, event_bus=event_bus)
        self.agent_runner = agent_runner
        self.agent = agent

    async def start(self):
        """Connect without setting the module-level _active_channel singleton."""
        if not self.config.access_token or not self.config.phone_number_id:
            log.warning(
                "AgentWhatsAppChannel not configured",
                agent_id=self.agent["id"],
            )
            self.ready_event.set()
            return

        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self.config.access_token}"},
            timeout=30,
        )

        try:
            resp = await self._http.get(f"/{self.config.phone_number_id}")
            if resp.status_code == 200:
                self._connected = True
                log.info(
                    "AgentWhatsAppChannel connected",
                    agent=self.agent["name"],
                    number=resp.json().get("display_phone_number"),
                )
            else:
                log.warning(
                    "AgentWhatsAppChannel credential check failed",
                    agent=self.agent["name"],
                    status=resp.status_code,
                )
        except Exception as exc:
            log.warning("AgentWhatsAppChannel could not reach Graph API", error=str(exc))

        self.ready_event.set()
        if self._connected:
            await self.event_bus.emit(
                EVENT_CHANNEL_CONNECTED,
                {"channel": "whatsapp", "agent_id": self.agent["id"]},
            )

    async def stop(self):
        if self._http:
            await self._http.aclose()
        self._connected = False
        await self.event_bus.emit(
            EVENT_CHANNEL_DISCONNECTED,
            {"channel": "whatsapp", "agent_id": self.agent["id"]},
        )

    async def _respond(self, sender: str, content: str):
        """Route to AgentRunner with scoped user_id for memory isolation."""
        scoped_uid = f"a{self.agent['id']}_wa_{sender}"
        response = await self.agent_runner.run(
            agent=self.agent,
            message=content,
            user_id=scoped_uid,
            channel_id=sender,
            channel_type=f"whatsapp_a{self.agent['id']}",
        )
        await self._deliver(sender, response)
