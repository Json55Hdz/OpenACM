"""
WhatsApp Cloud API webhook routes.

Meta delivers incoming messages by POSTing to a public HTTPS URL. These two
routes implement that contract:

  GET  /webhooks/whatsapp  → verification handshake (Meta calls this once)
  POST /webhooks/whatsapp  → incoming messages / status events

The POST body is HMAC-validated against the app secret, then each message is
dispatched to the active WhatsAppCloudChannel.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse, JSONResponse

from openacm.web.state import _state

log = structlog.get_logger()


def _wa_config():
    cfg = getattr(_state, "config", None)
    if cfg is None:
        return None
    return cfg.channels.whatsapp


def register_routes(app: FastAPI) -> None:
    @app.get("/webhooks/whatsapp")
    async def whatsapp_verify(request: Request):
        """Meta's one-time verification: echo hub.challenge if the token matches."""
        wa = _wa_config()
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge", "")
        if wa and mode == "subscribe" and token and token == wa.verify_token:
            return PlainTextResponse(challenge)
        log.warning("WhatsApp webhook verification rejected", mode=mode)
        return PlainTextResponse("forbidden", status_code=403)

    @app.post("/webhooks/whatsapp")
    async def whatsapp_incoming(request: Request):
        """Receive message/status events from Meta."""
        from openacm.channels.whatsapp_cloud_channel import get_active_channel, verify_signature

        wa = _wa_config()
        raw = await request.body()

        if wa and not verify_signature(wa.app_secret, raw, request.headers.get("X-Hub-Signature-256", "")):
            log.warning("WhatsApp webhook signature invalid — dropping")
            return Response(status_code=403)

        try:
            payload = await request.json()
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    phone_id = value.get("metadata", {}).get("phone_number_id", "")

                    # Route to agent channel first, fall back to global Brain channel
                    channel = None
                    if phone_id and getattr(_state, "agent_channel_manager", None):
                        channel = _state.agent_channel_manager.get_channel_by_phone(phone_id)
                    if channel is None:
                        channel = get_active_channel()

                    if channel is None:
                        continue

                    await channel.handle_incoming(value)
        except Exception as exc:
            log.error("WhatsApp webhook processing failed", error=str(exc))

        return JSONResponse({"status": "ok"})
