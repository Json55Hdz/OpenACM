"""WhatsApp BSUID support: users with a username arrive without `from`."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from openacm.channels.whatsapp_cloud_channel import recipient_fields
from tests.unit.test_agent_whatsapp_channel import _make_channel


class TestRecipientFields:
    @pytest.mark.parametrize("target", ["CO.1640468054141646", "US.13491208655302741918"])
    def test_bsuid_uses_recipient(self, target):
        assert recipient_fields(target) == {"recipient": target}

    @pytest.mark.parametrize("target", ["573234677424", "+573234677424", "14083723448"])
    def test_phone_uses_to(self, target):
        assert recipient_fields(target) == {"to": target}


class TestBsuidFlow:
    async def test_message_without_from_is_handled(self):
        ch, runner = _make_channel()
        value = {"messages": [{
            "from_user_id": "CO.1640468054141646", "id": "wamid.1",
            "timestamp": "1", "type": "text", "text": {"body": "hola"},
        }]}
        ch._deliver = AsyncMock()

        await ch.handle_incoming(value)

        assert runner.run.call_args.kwargs["user_id"] == "a7_wa_CO.1640468054141646"
        ch._deliver.assert_awaited_once_with("CO.1640468054141646", "Hola respuesta")

    async def test_phone_from_takes_precedence(self):
        ch, runner = _make_channel()
        value = {"messages": [{
            "from": "573234677424", "from_user_id": "CO.1", "id": "wamid.2",
            "type": "text", "text": {"body": "hola"},
        }]}
        ch._deliver = AsyncMock()

        await ch.handle_incoming(value)

        ch._deliver.assert_awaited_once_with("573234677424", "Hola respuesta")

    async def test_send_message_to_bsuid_uses_recipient(self):
        ch, _ = _make_channel()
        ch._http = MagicMock()
        ch._http.post = AsyncMock(return_value=MagicMock(status_code=200))

        assert await ch.send_message("CO.1640468054141646", "hola") is True

        payload = ch._http.post.call_args.kwargs["json"]
        assert payload["recipient"] == "CO.1640468054141646"
        assert "to" not in payload

    async def test_send_message_to_phone_uses_to(self):
        ch, _ = _make_channel()
        ch._http = MagicMock()
        ch._http.post = AsyncMock(return_value=MagicMock(status_code=200))

        await ch.send_message("573234677424", "hola")

        payload = ch._http.post.call_args.kwargs["json"]
        assert payload["to"] == "573234677424"
        assert "recipient" not in payload
