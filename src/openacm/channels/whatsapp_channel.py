"""
WhatsApp Channel — connects to the Node.js whatsapp-web.js bridge.

Communicates with a separate Node.js microservice that handles
the WhatsApp Web protocol via REST API + WebSocket.
"""

import asyncio
import json
from typing import Any

import httpx
import structlog

from openacm.channels.base import BaseChannel
from openacm.core.brain import Brain
from openacm.core.config import WhatsAppConfig
from openacm.core.events import EventBus, EVENT_CHANNEL_CONNECTED, EVENT_CHANNEL_DISCONNECTED

log = structlog.get_logger()


class WhatsAppChannel(BaseChannel):
    """WhatsApp channel via Node.js bridge."""

    def __init__(self, config: WhatsAppConfig, brain: Brain, event_bus: EventBus):
        self.config = config
        self.brain = brain
        self.event_bus = event_bus
        self._connected = False
        self._ws = None
        self._http_client: httpx.AsyncClient | None = None
        self._listen_task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return "whatsapp"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def start(self):
        """Connect to the WhatsApp bridge."""
        # SECURITY: POR DISEÑO - HTTP client para WhatsApp Business API
        self._http_client = httpx.AsyncClient(
            base_url=self.config.bridge_url,
            timeout=30,
        )

        # Check if bridge is running
        try:
            resp = await self._http_client.get("/status")
            if resp.status_code == 200:
                status = resp.json()
                self._connected = status.get("connected", False)
                log.info("WhatsApp bridge status", status=status)
            else:
                log.warning("WhatsApp bridge not responding")
                return
        except httpx.ConnectError:
            log.warning(
                "WhatsApp bridge not running",
                url=self.config.bridge_url,
                hint="Start the bridge with: cd bridges/whatsapp && npm start",
            )
            return

        # Start listening for incoming messages via WebSocket
        self._listen_task = asyncio.create_task(self._listen_loop())

        if self._connected:
            await self.event_bus.emit(EVENT_CHANNEL_CONNECTED, {"channel": "whatsapp"})

    async def stop(self):
        """Disconnect from the WhatsApp bridge."""
        if self._listen_task:
            self._listen_task.cancel()
        if self._http_client:
            await self._http_client.aclose()
        self._connected = False

    async def send_message(self, target_id: str, content: str, **kwargs) -> bool:
        """Send a message via WhatsApp."""
        if not self._http_client:
            return False
        try:
            resp = await self._http_client.post(
                "/send",
                json={
                    "to": target_id,
                    "message": content,
                },
            )
            return resp.status_code == 200
        except Exception as e:
            log.error("WhatsApp send failed", error=str(e))
            return False

    async def _listen_loop(self):
        """Listen for incoming messages from the bridge via polling."""
        import websockets

        ws_url = self.config.bridge_url.replace("http://", "ws://") + "/events"

        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    log.info("WhatsApp WebSocket connected")
                    async for raw_msg in ws:
                        try:
                            data = json.loads(raw_msg)
                            if data.get("type") == "message":
                                await self._handle_incoming(data)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                log.warning("WhatsApp WebSocket error, retrying...", error=str(e))
                await asyncio.sleep(5)

    async def _handle_incoming(self, data: dict[str, Any]):
        """Handle an incoming WhatsApp message."""
        content = data.get("body", "")
        sender = data.get("from", "")
        chat_id = data.get("chatId", sender)

        if not content or not sender:
            return

        try:
            response = await self.brain.process_message(
                content=content,
                user_id=sender,
                channel_id=chat_id,
                channel_type="whatsapp",
            )
            await self.send_message(chat_id, response)
        except Exception as e:
            log.error("WhatsApp message processing error", error=str(e))
