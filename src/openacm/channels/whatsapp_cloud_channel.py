"""
WhatsApp Cloud API channel — official Meta WhatsApp Business Platform.

Outbound messages go straight to the Graph API over HTTPS (no public URL
needed). Inbound messages arrive via a webhook that Meta POSTs to the OpenACM
web server; the webhook route (web/routers/whatsapp_webhook.py) hands each
message to `handle_incoming` here. This module keeps a reference to the active
channel so the webhook route can reach it.
"""

import asyncio
import base64
import hashlib
import hmac
import os
from pathlib import Path
from typing import Any

import httpx
import structlog

from openacm.channels.base import BaseChannel
from openacm.core.brain import Brain
from openacm.core.config import WhatsAppConfig
from openacm.core.events import EventBus, EVENT_CHANNEL_CONNECTED, EVENT_CHANNEL_DISCONNECTED

log = structlog.get_logger()

# Set by start() so the webhook route can dispatch incoming messages to us.
_active_channel: "WhatsAppCloudChannel | None" = None


def get_active_channel() -> "WhatsAppCloudChannel | None":
    return _active_channel


def verify_signature(app_secret: str, raw_body: bytes, header: str) -> bool:
    """Validate Meta's X-Hub-Signature-256 header against the raw request body.

    If no app_secret is configured we skip verification (and say so via the
    caller's logs) rather than reject everything during early setup.
    """
    if not app_secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


class WhatsAppCloudChannel(BaseChannel):
    """WhatsApp channel via the official Meta Cloud API."""

    def __init__(self, config: WhatsAppConfig, brain: Brain, event_bus: EventBus):
        self.config = config
        self.brain = brain
        self.event_bus = event_bus
        self._connected = False
        self._http: httpx.AsyncClient | None = None
        self._seen_ids: set[str] = set()   # de-dupe Meta's webhook retries
        self.ready_event = asyncio.Event()

    @property
    def name(self) -> str:
        return "whatsapp"

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def _base_url(self) -> str:
        ver = self.config.graph_api_version or "v21.0"
        return f"https://graph.facebook.com/{ver}"

    async def start(self):
        global _active_channel
        if not self.config.access_token or not self.config.phone_number_id:
            log.warning(
                "WhatsApp Cloud API not configured",
                hint="Set access_token + phone_number_id (config/.env or default.yaml)",
            )
            self.ready_event.set()
            return

        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self.config.access_token}"},
            timeout=30,
        )
        _active_channel = self

        # Sanity-check credentials by reading the sender phone number.
        try:
            resp = await self._http.get(f"/{self.config.phone_number_id}")
            if resp.status_code == 200:
                self._connected = True
                log.info("WhatsApp Cloud API connected", number=resp.json().get("display_phone_number"))
            else:
                log.warning("WhatsApp Cloud API credential check failed", status=resp.status_code, body=resp.text[:300])
        except Exception as exc:
            log.warning("WhatsApp Cloud API could not reach Graph API", error=str(exc))

        self.ready_event.set()
        if self._connected:
            await self.event_bus.emit(EVENT_CHANNEL_CONNECTED, {"channel": "whatsapp"})

    async def stop(self):
        global _active_channel
        if self._http:
            await self._http.aclose()
        self._connected = False
        if _active_channel is self:
            _active_channel = None
        await self.event_bus.emit(EVENT_CHANNEL_DISCONNECTED, {"channel": "whatsapp"})

    async def send_message(self, target_id: str, content: str, **kwargs) -> bool:
        """Send a text message to a WhatsApp user (target_id = their wa_id / phone)."""
        if not self._http or not content.strip():
            return False
        try:
            resp = await self._http.post(
                f"/{self.config.phone_number_id}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": target_id,
                    "type": "text",
                    "text": {"preview_url": True, "body": content[:4096]},
                },
            )
            if resp.status_code >= 400:
                log.error("WhatsApp send failed", status=resp.status_code, body=resp.text[:300])
                return False
            return True
        except Exception as exc:
            log.error("WhatsApp send error", error=str(exc))
            return False

    async def _send_media(self, target_id: str, fpath: Path, caption: str) -> bool:
        """Upload a local file to Meta and send it as a document/image."""
        if not self._http:
            return False
        try:
            from openacm.security.crypto import decrypt_file
            raw = decrypt_file(fpath)
            # 1. Upload media → media_id
            files = {
                "file": (fpath.name, raw, "application/octet-stream"),
                "messaging_product": (None, "whatsapp"),
            }
            up = await self._http.post(f"/{self.config.phone_number_id}/media", files=files)
            if up.status_code >= 400:
                log.error("WhatsApp media upload failed", status=up.status_code, body=up.text[:300])
                return False
            media_id = up.json().get("id")
            # 2. Send by media_id (image if it looks like one, else document)
            is_image = fpath.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp", "to": target_id,
                "type": "image" if is_image else "document",
            }
            payload["image" if is_image else "document"] = {
                "id": media_id, **({"caption": caption} if caption else {}),
                **({} if is_image else {"filename": fpath.name}),
            }
            sent = await self._http.post(f"/{self.config.phone_number_id}/messages", json=payload)
            return sent.status_code < 400
        except Exception as exc:
            log.error("WhatsApp media send error", error=str(exc))
            return False

    async def handle_incoming(self, value: dict[str, Any]):
        """Process one webhook `value` object (entry[].changes[].value)."""
        messages = value.get("messages") or []
        if not messages:
            return  # statuses (delivery/read receipts) — nothing to do

        for msg in messages:
            msg_id = msg.get("id", "")
            if msg_id and msg_id in self._seen_ids:
                continue  # Meta retried a webhook we already handled
            if msg_id:
                self._seen_ids.add(msg_id)
                if len(self._seen_ids) > 1000:
                    self._seen_ids = set(list(self._seen_ids)[-500:])

            sender = msg.get("from", "")
            mtype = msg.get("type", "")
            if mtype == "text":
                content = msg.get("text", {}).get("body", "")
            elif mtype in ("button", "interactive"):
                content = (
                    msg.get("button", {}).get("text")
                    or msg.get("interactive", {}).get("button_reply", {}).get("title")
                    or msg.get("interactive", {}).get("list_reply", {}).get("title")
                    or ""
                )
            else:
                content = f"[{mtype} recibido]"

            if not sender or not content:
                continue

            try:
                await self._respond(sender, content)
            except Exception as exc:
                log.error("WhatsApp message processing error", error=str(exc))

    async def _deliver(self, sender: str, response: str):
        """Parse ATTACHMENT: lines and send text + media to sender."""
        project_root = os.environ.get("OPENACM_PROJECT_ROOT", ".")
        media_dir = Path(project_root) / "data" / "media"

        lines = response.splitlines()
        attachment_names = [l[len("ATTACHMENT:"):].strip() for l in lines if l.startswith("ATTACHMENT:")]
        clean_text = "\n".join(l for l in lines if not l.startswith("ATTACHMENT:")).strip()

        for fname in attachment_names:
            fpath = media_dir / fname
            if fpath.exists():
                if await self._send_media(sender, fpath, clean_text):
                    clean_text = ""  # caption already delivered with the file

        if clean_text:
            await self.send_message(sender, clean_text)

    async def _respond(self, sender: str, content: str):
        """Run the brain and deliver the reply."""
        response = await self.brain.process_message(
            content=content,
            user_id=sender,
            channel_id=sender,
            channel_type="whatsapp",
        )
        await self._deliver(sender, response)
