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


def _bsuid_value(name="Maria", user_id="CO.1640468054141646"):
    return {
        "contacts": [{"user_id": user_id, "profile": {"name": name, "username": "maria_x"}}],
        "messages": [{"from_user_id": user_id, "id": "wamid.n", "type": "text", "text": {"body": "hola"}}],
    }


class TestContactName:
    def test_display_name_prefers_profile_name_then_username(self):
        from openacm.channels.whatsapp_cloud_channel import contact_display_name
        assert contact_display_name(_bsuid_value(), "CO.1640468054141646") == "Maria"
        assert contact_display_name(_bsuid_value(name=""), "CO.1640468054141646") == "maria_x"
        assert contact_display_name(_bsuid_value(), "CO.other") == ""

    async def test_bsuid_sender_seeds_name_when_none_saved(self):
        ch, runner = _make_channel()
        db = MagicMock()
        db.get_customer_name = AsyncMock(return_value=None)
        db.set_customer_name = AsyncMock()
        runner.database = db
        ch._deliver = AsyncMock()

        await ch.handle_incoming(_bsuid_value())

        db.set_customer_name.assert_awaited_once_with(
            "a7_wa_CO.1640468054141646", "CO.1640468054141646", "Maria"
        )

    async def test_existing_saved_name_is_not_overwritten(self):
        ch, runner = _make_channel()
        db = MagicMock()
        db.get_customer_name = AsyncMock(return_value="Mariana")
        db.set_customer_name = AsyncMock()
        runner.database = db
        ch._deliver = AsyncMock()

        await ch.handle_incoming(_bsuid_value())

        db.set_customer_name.assert_not_awaited()

    async def test_phone_sender_does_not_touch_names(self):
        ch, runner = _make_channel()
        db = MagicMock()
        db.get_customer_name = AsyncMock(return_value=None)
        db.set_customer_name = AsyncMock()
        runner.database = db
        ch._deliver = AsyncMock()
        value = {
            "contacts": [{"wa_id": "573234677424", "profile": {"name": "Pedro"}}],
            "messages": [{"from": "573234677424", "id": "wamid.p", "type": "text", "text": {"body": "hola"}}],
        }

        await ch.handle_incoming(value)

        db.set_customer_name.assert_not_awaited()

    async def test_name_save_failure_does_not_block_reply(self):
        ch, runner = _make_channel()
        db = MagicMock()
        db.get_customer_name = AsyncMock(side_effect=RuntimeError("db down"))
        runner.database = db
        ch._deliver = AsyncMock()

        await ch.handle_incoming(_bsuid_value())

        ch._deliver.assert_awaited_once()
