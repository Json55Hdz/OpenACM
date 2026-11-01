"""Agents can split one reply into several WhatsApp messages with <<MSG>>."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openacm.utils.text import MESSAGE_SPLIT_MARKER, join_message_parts, split_message_parts


class TestHelpers:
    def test_split_drops_empty_parts_and_trims(self):
        assert split_message_parts(f" uno \n{MESSAGE_SPLIT_MARKER}\n\n{MESSAGE_SPLIT_MARKER} dos ") == ["uno", "dos"]

    def test_text_without_marker_is_a_single_part(self):
        assert split_message_parts("hola") == ["hola"]

    def test_join_replaces_marker_with_blank_line(self):
        assert join_message_parts(f"uno {MESSAGE_SPLIT_MARKER} dos") == "uno\n\ndos"

    def test_join_leaves_plain_text_untouched(self):
        assert join_message_parts("  hola\n") == "  hola\n"


def _channel(monkeypatch):
    from openacm.channels import whatsapp_cloud_channel as mod

    monkeypatch.setattr(mod, "_MESSAGE_GAP_SECONDS", 0)
    ch = mod.WhatsAppCloudChannel.__new__(mod.WhatsAppCloudChannel)
    ch.calls = []
    ch.send_message = AsyncMock(side_effect=lambda to, text, **kw: ch.calls.append(("text", text)) or True)

    async def fake_media(to, fpath, caption):
        ch.calls.append(("file", caption))
        return True

    ch._send_media = fake_media
    return ch


class TestDeliverSplit:
    async def test_parts_are_sent_as_separate_messages_in_order(self, monkeypatch):
        ch = _channel(monkeypatch)
        await ch._deliver("573001112233", f"aviso legal {MESSAGE_SPLIT_MARKER} saludo y respuesta")
        assert ch.calls == [("text", "aviso legal"), ("text", "saludo y respuesta")]

    async def test_reply_without_marker_is_one_message(self, monkeypatch):
        ch = _channel(monkeypatch)
        await ch._deliver("573001112233", "hola")
        assert ch.calls == [("text", "hola")]

    async def test_file_goes_after_first_part_and_before_the_rest(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENACM_PROJECT_ROOT", str(tmp_path))
        (tmp_path / "data" / "media").mkdir(parents=True)
        (tmp_path / "data" / "media" / "upload_x.pdf").write_bytes(b"%PDF")
        ch = _channel(monkeypatch)

        await ch._deliver("573001112233", f"ATTACHMENT:upload_x.pdf\nentrega {MESSAGE_SPLIT_MARKER} flete")
        assert ch.calls == [("file", "entrega"), ("text", "flete")]

    async def test_long_first_part_still_goes_as_text_before_the_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENACM_PROJECT_ROOT", str(tmp_path))
        (tmp_path / "data" / "media").mkdir(parents=True)
        (tmp_path / "data" / "media" / "upload_x.pdf").write_bytes(b"%PDF")
        ch = _channel(monkeypatch)

        await ch._deliver("573001112233", f"ATTACHMENT:upload_x.pdf\n{'x' * 1500} {MESSAGE_SPLIT_MARKER} flete")
        assert [c[0] for c in ch.calls] == ["text", "file", "text"]
        assert ch.calls[1][1] == ""


class TestAgentRunnerMarker:
    async def _run(self, channel_type, reply):
        from openacm.core.agent_runner import AgentRunner

        memory = MagicMock()
        memory.get_history = AsyncMock(return_value=[])
        memory.add_message = AsyncMock()
        bus = MagicMock()
        bus.emit = AsyncMock()
        runner = AgentRunner(llm_router=MagicMock(), tool_registry=None, memory=memory, event_bus=bus, database=None)
        agent = {"id": 2, "name": "Bot", "system_prompt": "x", "allowed_tools": "none"}
        with patch("openacm.core.brain.Brain.process_message", new_callable=AsyncMock, return_value=reply):
            return await runner.run(agent=agent, message="hi", user_id="u", channel_id="c", channel_type=channel_type)

    @pytest.mark.parametrize("channel", ["whatsapp_a2", "telegram_a5", "whatsapp_web_a2", "discord"])
    async def test_messaging_channels_keep_the_marker_for_the_channel(self, channel):
        out = await self._run(channel, f"uno {MESSAGE_SPLIT_MARKER} dos")
        assert MESSAGE_SPLIT_MARKER in out

    @pytest.mark.parametrize("channel", ["web", "console"])
    async def test_non_messaging_channels_never_see_the_marker(self, channel):
        out = await self._run(channel, f"uno {MESSAGE_SPLIT_MARKER} dos")
        assert MESSAGE_SPLIT_MARKER not in out and out == "uno\n\ndos"


class TestEveryChannelSplits:
    """send_message of ANY BaseChannel subclass delivers marker-separated parts one by one."""

    async def test_send_message_is_split_for_any_subclass(self, monkeypatch):
        from openacm.channels import base
        from openacm.channels.base import BaseChannel

        monkeypatch.setattr(base, "MESSAGE_GAP_SECONDS", 0)
        sent = []

        class Fake(BaseChannel):
            name = "fake"
            is_connected = True

            async def start(self): ...
            async def stop(self): ...

            async def send_message(self, target_id, content, **kwargs):
                sent.append((target_id, content))
                return True

        ok = await Fake().send_message("c1", f"uno {MESSAGE_SPLIT_MARKER} dos {MESSAGE_SPLIT_MARKER} tres")
        assert ok is True
        assert sent == [("c1", "uno"), ("c1", "dos"), ("c1", "tres")]

    async def test_plain_text_goes_through_untouched(self):
        from openacm.channels.base import BaseChannel

        sent = []

        class Fake(BaseChannel):
            name = "fake"
            is_connected = True

            async def start(self): ...
            async def stop(self): ...

            async def send_message(self, target_id, content, **kwargs):
                sent.append(content)
                return True

        await Fake().send_message("c1", "hola")
        assert sent == ["hola"]

    async def test_telegram_event_reply_sends_each_part_as_its_own_message(self, monkeypatch):
        from openacm.channels import telegram_channel as mod

        monkeypatch.setattr(mod, "MESSAGE_GAP_SECONDS", 0)
        ch = mod.TelegramChannel.__new__(mod.TelegramChannel)
        ch._connected = True
        ch._app = MagicMock()
        ch._app.bot.send_message = AsyncMock()

        await ch._on_message_sent(
            "message_sent",
            {"channel_type": "telegram", "channel_id": "123", "content": f"uno {MESSAGE_SPLIT_MARKER} dos"},
        )

        texts = [c.kwargs["text"] for c in ch._app.bot.send_message.call_args_list]
        assert texts == ["uno", "dos"]


class TestTelegramIncoming:
    async def test_typing_indicator_timeout_does_not_drop_the_message(self):
        from openacm.channels import telegram_channel as mod

        ch = mod.TelegramChannel.__new__(mod.TelegramChannel)
        ch.config = MagicMock(allowed_users=[])
        ch.brain = MagicMock()
        ch.brain.process_message = AsyncMock(return_value="ok")
        ch._app = MagicMock()

        update = MagicMock()
        update.effective_user.id = 1
        update.message.chat_id = 5
        update.message.text = "hola"
        update.message.photo = None
        update.message.voice = None
        update.message.audio = None
        update.message.document = None
        update.message.chat.send_action = AsyncMock(side_effect=TimeoutError("Timed out"))

        await ch._handle_message(update, MagicMock())
        import asyncio
        await asyncio.sleep(0.05)

        ch.brain.process_message.assert_awaited()


class TestTelegramRetry:
    async def test_timed_out_send_is_retried_so_the_reply_still_arrives(self, monkeypatch):
        from telegram.error import TimedOut

        from openacm.channels import telegram_channel as mod

        monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())
        ch = mod.TelegramChannel.__new__(mod.TelegramChannel)
        ch._connected = True
        ch._app = MagicMock()
        ch._app.bot.send_message = AsyncMock(side_effect=[TimedOut("Timed out"), None])

        await ch._on_message_sent("message_sent", {"channel_type": "telegram", "channel_id": "123", "content": "hola"})

        assert ch._app.bot.send_message.await_count == 2
