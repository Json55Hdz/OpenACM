"""An agent's Telegram bot talks to the public: commands must not reach the whole system."""

from types import SimpleNamespace

import pytest

from openacm.channels.agent_telegram_bot import AgentBrainAdapter, AgentTelegramChannel
from openacm.channels.telegram_channel import TelegramChannel


class _Update:
    def __init__(self, user_id=7):
        self.replies = []
        self.message = SimpleNamespace(chat_id=7, reply_text=self._reply)
        self.effective_user = SimpleNamespace(id=user_id)

    async def _reply(self, text, **kwargs):
        self.replies.append(text)


class _Commands:
    def __init__(self):
        self.calls = []

    async def handle(self, name, args, user_id, channel_id):
        self.calls.append((name, user_id, channel_id))
        return SimpleNamespace(text="ok", data=None)


def _agent_channel(allowed=None):
    brain = AgentBrainAdapter({"id": 5, "name": "Bot"}, SimpleNamespace())
    channel = AgentTelegramChannel.__new__(AgentTelegramChannel)
    channel.brain = brain
    channel.config = SimpleNamespace(allowed_users=allowed or [])
    channel._cmd = _Commands()
    return channel


async def test_model_and_stats_are_not_available_on_an_agent_bot():
    channel = _agent_channel()
    for handler in (channel._cmd_model, channel._cmd_stats):
        update = _Update()
        await handler(update, SimpleNamespace(args=["gpt-x"]))
        assert update.replies and "no está disponible" in update.replies[0]
    assert channel._cmd.calls == []


async def test_clear_uses_the_agents_scoped_user_id():
    channel = _agent_channel()
    await channel._cmd_clear(_Update(user_id=42), SimpleNamespace(args=[]))
    assert channel._cmd.calls == [("/clear", "a5_tg_42", "7")]


async def test_a_user_outside_the_allowed_list_cannot_use_any_command():
    channel = _agent_channel(allowed=["1"])
    for handler in (channel._cmd_help, channel._cmd_model, channel._cmd_stats, channel._cmd_clear):
        update = _Update(user_id=999)
        await handler(update, SimpleNamespace(args=[]))
        assert update.replies == []
    assert channel._cmd.calls == []


async def test_the_main_bot_keeps_model_and_stats_for_allowed_users():
    channel = TelegramChannel.__new__(TelegramChannel)
    channel.config = SimpleNamespace(allowed_users=["7"])
    channel._cmd = _Commands()
    update = _Update(user_id=7)
    await channel._cmd_model(update, SimpleNamespace(args=[]))
    assert channel._cmd.calls and channel._cmd.calls[0][0] == "/model"


async def test_adapter_accepts_what_the_telegram_channel_sends():
    """TelegramChannel calls brain.process_message(..., debounce=True); an agent's adapter must take it
    (it crashed every agent message with 'unexpected keyword argument debounce')."""
    from openacm.channels.agent_telegram_bot import AgentBrainAdapter

    seen = {}

    class Runner:
        async def run(self, **kwargs):
            seen.update(kwargs)
            return "ok"

    adapter = AgentBrainAdapter({"id": 5}, Runner())
    out = await adapter.process_message(
        content="hola", user_id="42", channel_id="c", channel_type="telegram", attachments=None, debounce=True,
    )
    assert out == "ok" and seen["debounce"] is True and seen["user_id"] == "a5_tg_42"
