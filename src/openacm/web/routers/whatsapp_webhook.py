"""
WhatsApp Cloud API webhook routes.

Meta delivers incoming messages by POSTing to a public HTTPS URL. These two
routes implement that contract:

  GET  /webhooks/whatsapp  → verification handshake (Meta calls this once)
  POST /webhooks/whatsapp  → incoming messages / status events

The POST body is HMAC-validated against the app secret of the channel the message is
addressed to (an agent channel has its own Meta app, so its own secret), then each message
is handled in the background so Meta gets its answer at once instead of retrying a slow one.
"""
from __future__ import annotations

import asyncio
import os

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse, JSONResponse

from openacm.web.state import _state

log = structlog.get_logger()

# Messages being handled. A task nobody references can be garbage collected before it finishes.
_in_flight: set[asyncio.Task] = set()

# Set to "true" to reject webhooks when no app secret is configured (the default only warns,
# so a deployment that never set a secret keeps working).
REQUIRE_SIGNATURE_ENV = "OPENACM_WHATSAPP_REQUIRE_SIGNATURE"


def _wa_config():
    cfg = getattr(_state, "config", None)
    if cfg is None:
        return None
    return cfg.channels.whatsapp


def _channel_for(phone_id: str):
    """The agent channel that owns this phone number, else the main WhatsApp channel."""
    from openacm.channels.whatsapp_cloud_channel import get_active_channel

    channel = None
    if phone_id and getattr(_state, "agent_channel_manager", None):
        channel = _state.agent_channel_manager.get_channel_by_phone(phone_id)
    return channel or get_active_channel()


def _phone_ids(payload: dict) -> list[str]:
    return [
        change.get("value", {}).get("metadata", {}).get("phone_number_id", "")
        for entry in payload.get("entry", [])
        for change in entry.get("changes", [])
    ]


def _secret_for(phone_id: str) -> str:
    """The app secret that must have signed a message addressed to this phone number: the
    channel's own, or the global one for a channel that has none."""
    wa = _wa_config()
    global_secret = (wa.app_secret if wa else "") or ""
    channel = _channel_for(phone_id)
    own = getattr(getattr(channel, "config", None), "app_secret", "") or ""
    return own or global_secret


def _signature_ok(payload: dict, raw: bytes, header: str) -> bool:
    """Every addressed channel must be satisfied by the signature using ITS OWN secret, so a
    payload signed for one channel cannot carry a change addressed to another."""
    from openacm.channels.whatsapp_cloud_channel import verify_signature

    secrets = [_secret_for(pid) for pid in (_phone_ids(payload) or [""])]
    if all(secrets):
        return all(verify_signature(secret, raw, header) for secret in secrets)
    if any(secrets):
        log.warning("WhatsApp webhook mixes channels with and without an app secret — rejected")
        return False
    if os.environ.get(REQUIRE_SIGNATURE_ENV, "").lower() == "true":
        log.warning("WhatsApp webhook rejected: no app secret configured and a signature is required")
        return False
    log.warning(
        "WhatsApp webhook accepted WITHOUT a signature check: no app secret is configured, so "
        "anyone who knows the URL can send messages as any user. Set the app secret."
    )
    return True


async def _handle(channel, value: dict) -> None:
    try:
        await channel.handle_incoming(value)
    except Exception as exc:
        log.error("WhatsApp message handling failed", error=str(exc), exc_info=True)


def register_routes(app: FastAPI) -> None:
    @app.get("/webhooks/whatsapp")
    async def whatsapp_verify(request: Request):
        """Meta's one-time verification: echo hub.challenge if the token matches."""
        wa = _wa_config()
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge", "")

        if mode == "subscribe" and token:
            # Check global config first
            if wa and wa.verify_token and token == wa.verify_token:
                return PlainTextResponse(challenge)
            # Fall back to any active agent WhatsApp channel
            mgr = getattr(_state, "agent_channel_manager", None)
            if mgr and mgr.get_whatsapp_channel_by_verify_token(token):
                return PlainTextResponse(challenge)

        log.warning("WhatsApp webhook verification rejected", mode=mode)
        return PlainTextResponse("forbidden", status_code=403)

    @app.post("/webhooks/whatsapp")
    async def whatsapp_incoming(request: Request):
        """Receive message/status events from Meta."""
        raw = await request.body()
        try:
            payload = await request.json()
        except Exception:
            log.warning("WhatsApp webhook body is not JSON", size=len(raw))
            return Response(status_code=400)

        if not _signature_ok(payload, raw, request.headers.get("X-Hub-Signature-256", "")):
            log.warning("WhatsApp webhook signature invalid — dropping")
            return Response(status_code=403)

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_id = value.get("metadata", {}).get("phone_number_id", "")
                channel = _channel_for(phone_id)
                messages = value.get("messages") or []

                for m in messages:
                    log.info(
                        "WhatsApp inbound message",
                        msg_id=m.get("id"),
                        sender=m.get("from") or m.get("from_user_id"),
                        mtype=m.get("type"),
                        phone_id=phone_id,
                        routed=type(channel).__name__ if channel else None,
                    )

                if channel is None:
                    if messages:
                        log.warning("WhatsApp message dropped — no channel for phone_id", phone_id=phone_id)
                    continue

                # Answer Meta now: an agent run can outlast Meta's timeout, and Meta would
                # then send the same message again.
                task = asyncio.create_task(_handle(channel, value))
                _in_flight.add(task)
                task.add_done_callback(_in_flight.discard)

        return JSONResponse({"status": "ok"})
