"""A message sent to the user outside a reply is remembered in their conversation."""
import asyncio
from types import SimpleNamespace

from openacm.channels.base import BaseChannel
from openacm.core.memory import MemoryManager


class _Channel(BaseChannel):
    def __init__(self, memory, delivers=True, knows_conversation=True):
        self.brain = SimpleNamespace(memory=memory)
        self.ready_event = asyncio.Event()
        self.delivers, self.knows_conversation, self.sent = delivers, knows_conversation, []

    name = "fake"
    is_connected = True

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_message(self, target_id, content, **kwargs):
        self.sent.append((target_id, content))
        return self.delivers

    def conversation_ids(self, target_id):
        return (target_id, target_id) if self.knows_conversation else None


async def _history(mem):
    return [m["content"] for m in await mem.get_or_create("42", "42", "system prompt")]


async def test_notice_is_sent_and_remembered(db, app_config):
    mem = MemoryManager(database=db, config=app_config.assistant)
    channel = _Channel(mem)
    assert await channel.notify("42", "Job 5 has a question") is True
    assert channel.sent == [("42", "Job 5 has a question")]
    assert await _history(mem) == ["system prompt", "Job 5 has a question"]


async def test_undelivered_notice_is_not_remembered(db, app_config):
    mem = MemoryManager(database=db, config=app_config.assistant)
    assert await _Channel(mem, delivers=False).notify("42", "lost") is False
    assert await _history(mem) == ["system prompt"]


async def test_channel_that_cannot_name_the_conversation_only_sends(db, app_config):
    mem = MemoryManager(database=db, config=app_config.assistant)
    assert await _Channel(mem, knows_conversation=False).notify("42", "hello") is True
    assert await _history(mem) == ["system prompt"]


class TestTelegramPlainText:
    async def test_plain_messages_are_not_parsed_as_markdown(self):
        from openacm.channels.telegram_channel import TelegramChannel

        calls = []

        async def send_message(**kwargs):
            calls.append(kwargs)

        channel = TelegramChannel.__new__(TelegramChannel)
        channel._app = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
        assert await channel.send_message("42", "a_b", plain=True)
        assert await channel.send_message("42", "a_b")
        assert calls[0]["parse_mode"] is None and calls[1]["parse_mode"] == "Markdown"


class TestLongAndAwkwardMessages:
    """A reply must arrive: split when too long, plain text when Markdown is refused."""

    @staticmethod
    def _telegram(send):
        from openacm.channels.telegram_channel import TelegramChannel

        channel = TelegramChannel.__new__(TelegramChannel)
        channel._app = SimpleNamespace(bot=SimpleNamespace(send_message=send))
        return channel

    async def test_a_long_telegram_message_is_split_not_cut(self):
        sent = []

        async def send_message(**kwargs):
            sent.append(kwargs["text"])

        text = " ".join(f"palabra{i}" for i in range(2500))
        assert await self._telegram(send_message).send_message("42", text)
        assert len(sent) > 1 and all(len(t) <= 4096 for t in sent)
        assert " ".join(sent).split() == text.split()

    async def test_a_refused_markdown_message_is_sent_again_as_plain_text(self):
        attempts = []

        async def send_message(**kwargs):
            attempts.append(kwargs["parse_mode"])
            if kwargs["parse_mode"] == "Markdown":
                raise RuntimeError("Can't parse entities")

        assert await self._telegram(send_message).send_message("42", "snake_case y *roto")
        assert attempts == ["Markdown", None]

    async def test_a_telegram_failure_is_reported_not_hidden(self):
        async def send_message(**kwargs):
            raise RuntimeError("chat not found")

        assert await self._telegram(send_message).send_message("42", "hola") is False

    async def test_a_long_whatsapp_message_goes_out_in_pieces(self):
        from openacm.channels.whatsapp_cloud_channel import WhatsAppCloudChannel

        bodies = []

        class Http:
            async def post(self, url, json):
                bodies.append(json["text"]["body"])
                return SimpleNamespace(status_code=200, text="")

        channel = WhatsAppCloudChannel.__new__(WhatsAppCloudChannel)
        channel._http = Http()
        channel.config = SimpleNamespace(phone_number_id="1")
        text = " ".join(f"palabra{i}" for i in range(2500))
        assert await channel.send_message("573000000000", text)
        assert len(bodies) > 1 and all(len(b) <= 4096 for b in bodies)
        assert " ".join(bodies).split() == text.split()
