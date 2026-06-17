"""Tests for AgentWhatsAppChannel."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_wa_config(phone_id="12345"):
    from openacm.core.config import WhatsAppConfig
    return WhatsAppConfig(
        enabled=True,
        access_token="token123",
        phone_number_id=phone_id,
        verify_token="vt",
        app_secret="",
        graph_api_version="v21.0",
    )


def _make_channel(phone_id="12345"):
    from openacm.channels.agent_whatsapp_channel import AgentWhatsAppChannel
    agent = {"id": 7, "name": "TestAgent", "system_prompt": "hi", "allowed_tools": "none"}
    runner = MagicMock()
    runner.run = AsyncMock(return_value="Hola respuesta")
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    return AgentWhatsAppChannel(
        config=_make_wa_config(phone_id),
        agent_runner=runner,
        agent=agent,
        event_bus=event_bus,
    ), runner


class TestAgentWhatsAppChannel:
    async def test_respond_scopes_user_id(self):
        ch, runner = _make_channel()
        ch._http = MagicMock()
        ch._connected = True

        with patch.object(ch, "_deliver", new=AsyncMock()) as mock_deliver:
            await ch._respond("5214155552671", "Hola")

        runner.run.assert_awaited_once()
        call_kwargs = runner.run.call_args.kwargs
        assert call_kwargs["user_id"] == "a7_wa_5214155552671"
        assert call_kwargs["channel_type"] == "whatsapp_a7"
        assert call_kwargs["message"] == "Hola"

    async def test_respond_calls_deliver_with_response(self):
        ch, runner = _make_channel()
        ch._http = MagicMock()
        runner.run = AsyncMock(return_value="Mi respuesta")

        with patch.object(ch, "_deliver", new=AsyncMock()) as mock_deliver:
            await ch._respond("521111", "Test")

        mock_deliver.assert_awaited_once_with("521111", "Mi respuesta")

    async def test_start_does_not_set_active_channel_singleton(self):
        from openacm.channels import whatsapp_cloud_channel as wcc
        ch, _ = _make_channel()

        original = wcc._active_channel

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"display_phone_number": "+1 415 555 0001"}
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client
            await ch.start()

        assert wcc._active_channel is original, "AgentWhatsAppChannel must not overwrite _active_channel"

    async def test_deliver_sends_plain_text(self):
        ch, _ = _make_channel()
        ch._http = MagicMock()

        with patch.object(ch, "send_message", new=AsyncMock()) as mock_send:
            await ch._deliver("521111", "Hola mundo")

        mock_send.assert_awaited_once_with("521111", "Hola mundo")

    async def test_deliver_strips_attachment_lines(self):
        ch, _ = _make_channel()
        ch._http = MagicMock()

        with patch.object(ch, "send_message", new=AsyncMock()) as mock_send, \
             patch.object(ch, "_send_media", new=AsyncMock(return_value=False)):
            await ch._deliver("521111", "Texto\nATTACHMENT: noexists.pdf")

        mock_send.assert_awaited_once_with("521111", "Texto")
