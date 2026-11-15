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
