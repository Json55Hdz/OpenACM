"""
WhatsApp Cloud API channel — official Meta WhatsApp Business Platform.

Outbound messages go straight to the Graph API over HTTPS (no public URL
needed). Inbound messages arrive via a webhook that Meta POSTs to the OpenACM
web server; the webhook route (web/routers/whatsapp_webhook.py) hands each
message to `handle_incoming` here. This module keeps a reference to the active
channel so the webhook route can reach it.
"""

import asyncio
import hashlib
import hmac
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

import httpx
import structlog

from openacm.channels.base import BaseChannel
from openacm.core.brain import Brain
from openacm.core.config import WhatsAppConfig
from openacm.core.events import EventBus, EVENT_CHANNEL_CONNECTED, EVENT_CHANNEL_DISCONNECTED
from openacm.core.messages import (
    MSG_WHATSAPP_AUDIO_DEFAULT,
    MSG_WHATSAPP_DOCUMENT_DEFAULT,
    MSG_WHATSAPP_IMAGE_DEFAULT,
)
from openacm.utils.text import chunk_text, extract_and_strip_thinking, split_message_parts

log = structlog.get_logger()

# WhatsApp Cloud refuses a text message longer than this
WHATSAPP_MESSAGE_LIMIT = 4096

_MEDIA_CAPTION_LIMIT = 1024  # WhatsApp Cloud API max caption length for documents/images
_MESSAGE_GAP_SECONDS = 0.7  # pause between the parts of a split reply

# Inbound media we download and hand to the agent (like the Telegram channel does).
_INBOUND_MEDIA_TYPES = ("image", "audio", "document")
_DEFAULT_MEDIA_TEXT = {
    "image": MSG_WHATSAPP_IMAGE_DEFAULT,
    "audio": MSG_WHATSAPP_AUDIO_DEFAULT,
    "document": MSG_WHATSAPP_DOCUMENT_DEFAULT,
}
_MAX_INBOUND_MEDIA_BYTES = 20 * 1024 * 1024
_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/amr": ".amr", "audio/aac": ".aac",
    "application/pdf": ".pdf",
}

# Set by start() so the webhook route can dispatch incoming messages to us.
_active_channel: "WhatsAppCloudChannel | None" = None


def get_active_channel() -> "WhatsAppCloudChannel | None":
    return _active_channel


# Business-scoped user ID, e.g. "CO.1640468054141646". Meta sends it instead of a
# phone number for users who enabled a WhatsApp username.
_BSUID_RE = re.compile(r"^[A-Z]{2}(\.[A-Za-z0-9]+)+$")


def recipient_fields(target_id: str) -> dict[str, str]:
    """Outbound addressing: `recipient` for a BSUID, `to` for a phone number."""
    return {"recipient": target_id} if _BSUID_RE.match(target_id) else {"to": target_id}


def is_bsuid(target_id: str) -> bool:
    return bool(_BSUID_RE.match(target_id))


def contact_display_name(value: dict[str, Any], user_id: str) -> str:
    """Profile name (or username) Meta sent for `user_id` in this webhook value."""
    for contact in value.get("contacts") or []:
        if user_id in (contact.get("user_id"), contact.get("wa_id")):
            profile = contact.get("profile") or {}
            return (profile.get("name") or profile.get("username") or "").strip()
    return ""


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
        sent_all = True
        # WhatsApp refuses a text over its limit: a long reply goes out as several messages
        for piece in chunk_text(content, WHATSAPP_MESSAGE_LIMIT):
            try:
                resp = await self._http.post(
                    f"/{self.config.phone_number_id}/messages",
                    json={
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        **recipient_fields(target_id),
                        "type": "text",
                        "text": {"preview_url": True, "body": piece},
                    },
                )
                if resp.status_code >= 400:
                    log.error("WhatsApp send failed", status=resp.status_code, body=resp.text[:300])
                    sent_all = False
            except Exception as exc:
                log.error("WhatsApp send error", error=str(exc))
                sent_all = False
        return sent_all

    async def _send_media(self, target_id: str, fpath: Path, caption: str) -> bool:
        """Upload a local file to Meta and send it as a document/image."""
        if not self._http:
            return False
        try:
            from openacm.security.crypto import decrypt_file
            raw = decrypt_file(fpath)
            # Friendly name set by send_file_to_chat: upload_<hex>__<name>.<ext> → <name>.<ext>
            shown_name = fpath.name.split("__", 1)[1] if re.match(r"upload_[0-9a-f]{32}__", fpath.name) else fpath.name
            mime = mimetypes.guess_type(shown_name)[0] or "application/octet-stream"
            # 1. Upload media → media_id
            files = {
                "file": (shown_name, raw, mime),
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
                "messaging_product": "whatsapp", **recipient_fields(target_id),
                "type": "image" if is_image else "document",
            }
            payload["image" if is_image else "document"] = {
                "id": media_id, **({"caption": caption} if caption else {}),
                **({} if is_image else {"filename": shown_name}),
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
                log.info("WhatsApp message skipped — duplicate id", msg_id=msg_id)
                continue  # Meta retried a webhook we already handled
            if msg_id:
                self._seen_ids.add(msg_id)
                if len(self._seen_ids) > 1000:
                    self._seen_ids = set(list(self._seen_ids)[-500:])

            # `from` is omitted for username users without a visible phone number
            sender = msg.get("from") or msg.get("from_user_id", "")
            mtype = msg.get("type", "")
            attachments: list[str] = []
            if mtype == "text":
                content = msg.get("text", {}).get("body", "")
            elif mtype in ("button", "interactive"):
                content = (
                    msg.get("button", {}).get("text")
                    or msg.get("interactive", {}).get("button_reply", {}).get("title")
                    or msg.get("interactive", {}).get("list_reply", {}).get("title")
                    or ""
                )
            elif mtype in _INBOUND_MEDIA_TYPES:
                media = msg.get(mtype) or {}
                caption = media.get("caption") or ""
                file_id = None
                try:
                    file_id = await self._download_media(media.get("id", ""))
                except Exception as exc:
                    log.warning("WhatsApp media download failed", msg_id=msg_id, mtype=mtype, error=str(exc))
                if file_id:
                    attachments.append(file_id)
                    content = caption or _DEFAULT_MEDIA_TEXT[mtype]
                else:
                    content = f"{caption}\n[{mtype} recibido, no se pudo descargar]".strip()
            else:
                content = f"[{mtype} recibido]"

            if not sender or not content:
                log.warning(
                    "WhatsApp message dropped — empty sender or content",
                    msg_id=msg_id, sender=sender, mtype=mtype, keys=list(msg.keys()),
                )
                continue

            if is_bsuid(sender):
                # No phone number to show in the UI: use the WhatsApp profile name.
                name = contact_display_name(value, sender)
                if name:
                    try:
                        await self._remember_contact_name(sender, name)
                    except Exception as exc:
                        log.warning("WhatsApp contact name save failed", error=str(exc))

            try:
                await self._respond(sender, content, attachments or None)
            except Exception as exc:
                log.error("WhatsApp message processing error", error=str(exc))

    async def _download_media(self, media_id: str) -> str | None:
        """Fetch an inbound image/audio/document from Meta and save it like Telegram does.

        Meta sends only a media id: a first call returns a short-lived URL, a second (with the
        access token) returns the bytes. Returns the saved file id, or None when there is nothing
        usable (no id, too big, unsupported).
        """
        if not media_id:
            return None
        meta = await self._http.get(f"/{media_id}")
        meta.raise_for_status()
        info = meta.json()
        url = info.get("url")
        if not url:
            return None
        mime = (info.get("mime_type") or "").split(";")[0].strip().lower()
        size = int(info.get("file_size") or 0)
        if size > _MAX_INBOUND_MEDIA_BYTES:
            log.warning("WhatsApp media too big, skipped", media_id=media_id, size=size)
            return None
        blob = await self._http.get(url)
        blob.raise_for_status()
        if len(blob.content) > _MAX_INBOUND_MEDIA_BYTES:
            return None
        ext = _MIME_EXTENSIONS.get(mime) or mimetypes.guess_extension(mime) or ".bin"

        import secrets
        from openacm.security.crypto import get_media_dir

        file_id = f"{secrets.token_hex(12)}{ext}"
        dest = get_media_dir() / file_id
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob.content)
        return file_id

    async def _remember_contact_name(self, sender: str, name: str):
        """Hook: persist a display name for a sender. No-op for the Brain channel."""

    async def _deliver(self, sender: str, response: str):
        """Parse ATTACHMENT: lines and send text + media to sender."""
        project_root = os.environ.get("OPENACM_PROJECT_ROOT", ".")
        media_dir = Path(project_root) / "data" / "media"

        lines = response.splitlines()
        attachment_names = [line[len("ATTACHMENT:"):].strip() for line in lines if line.startswith("ATTACHMENT:")]
        clean_text = "\n".join(line for line in lines if not line.startswith("ATTACHMENT:")).strip()
        clean_text, _ = extract_and_strip_thinking(clean_text)

        # The agent can split its reply into several messages with MESSAGE_SPLIT_MARKER;
        # the first part keeps the attachment logic below, the rest go out afterwards.
        clean_text, *later_parts = split_message_parts(clean_text) or [""]

        # Meta rejects media captions over 1024 chars (the upload would fail and the file would
        # be silently lost), so long replies go out as a normal text message before the file.
        if attachment_names and len(clean_text) > _MEDIA_CAPTION_LIMIT:
            await self.send_message(sender, clean_text)
            clean_text = ""

        for fname in attachment_names:
            fpath = media_dir / fname
            if fpath.exists():
                if await self._send_media(sender, fpath, clean_text):
                    clean_text = ""  # caption already delivered with the file

        if clean_text:
            await self.send_message(sender, clean_text)

        for part in later_parts:
            await asyncio.sleep(_MESSAGE_GAP_SECONDS)  # keep WhatsApp delivery order
            await self.send_message(sender, part)

    async def _respond(self, sender: str, content: str, attachments: list[str] | None = None):
        """Run the brain and deliver the reply."""
        response = await self.brain.process_message(
            content=content,
            user_id=sender,
            channel_id=sender,
            channel_type="whatsapp",
            attachments=attachments,
            debounce=True,
        )
        if response:  # "" = folded into an earlier message of the same burst
            await self._deliver(sender, response)
