"""Tests for AgentRunner's customer-name injection (survives memory_ttl resets)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_runner(customer_name=None):
    from openacm.core.agent_runner import AgentRunner

    mock_db = MagicMock()
    mock_db.get_agent_knowledge = AsyncMock(return_value=[])
    mock_db.get_customer_name = AsyncMock(return_value=customer_name)

    mock_llm = MagicMock()
    mock_memory = MagicMock()
    mock_memory.get_history = AsyncMock(return_value=[])
    mock_memory.add_message = AsyncMock()
    mock_event_bus = MagicMock()
    mock_event_bus.emit = AsyncMock()

    runner = AgentRunner(
        llm_router=mock_llm,
        tool_registry=None,
        memory=mock_memory,
        event_bus=mock_event_bus,
        database=mock_db,
    )
    return runner, mock_db


class TestApplyCustomerName:
    def test_no_name_returns_prompt_unchanged(self):
        from openacm.core.agent_runner import AgentRunner
        runner = AgentRunner(llm_router=None, tool_registry=None, memory=None, event_bus=None)
        assert runner._apply_customer_name("Be helpful.", None) == "Be helpful."

    def test_name_appended_to_prompt(self):
        from openacm.core.agent_runner import AgentRunner
        runner = AgentRunner(llm_router=None, tool_registry=None, memory=None, event_bus=None)
        result = runner._apply_customer_name("Be helpful.", "Juan")
        assert result.startswith("Be helpful.")
        assert "Juan" in result


class TestAgentRunnerCustomerNameLookup:
    async def test_looks_up_customer_name_by_user_and_channel(self):
        runner, mock_db = _make_runner(customer_name="Juan")
        agent = {"id": 1, "name": "Bot", "system_prompt": "Be helpful.", "allowed_tools": "none"}

        with patch("openacm.core.brain.Brain.process_message", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = "ok"
            await runner.run(agent=agent, message="Hi", user_id="u1", channel_id="c1")

        mock_db.get_customer_name.assert_awaited_once_with("u1", "c1")

    async def test_no_database_skips_lookup(self):
        from openacm.core.agent_runner import AgentRunner

        mock_llm = MagicMock()
        mock_memory = MagicMock()
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.add_message = AsyncMock()
        mock_event_bus = MagicMock()
        mock_event_bus.emit = AsyncMock()

        runner = AgentRunner(
            llm_router=mock_llm, tool_registry=None, memory=mock_memory,
            event_bus=mock_event_bus, database=None,
        )
        agent = {"id": 1, "name": "Bot", "system_prompt": "Be helpful.", "allowed_tools": "none"}

        with patch("openacm.core.brain.Brain.process_message", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = "ok"
            await runner.run(agent=agent, message="Hi")
        # Should not raise


class TestWhatTheAgentActuallyReceives:
    """The lookup alone proves nothing: the name has to end up in the prompt the brain runs with."""

    async def test_the_customer_name_reaches_the_brain_system_prompt(self):
        runner, _ = _make_runner(customer_name="Juan")
        agent = {"id": 1, "name": "Bot", "system_prompt": "Be helpful.", "allowed_tools": "none"}
        seen = {}

        class SpyBrain:
            def __init__(self, config, **kwargs):
                seen["prompt"] = config.system_prompt

            async def process_message(self, **kwargs):
                seen["kwargs"] = kwargs
                return "ok"

        with patch("openacm.core.brain.Brain", SpyBrain):
            await runner.run(agent=agent, message="Hi", user_id="u1", channel_id="c1", attachments=["f.jpg"])

        assert "Juan" in seen["prompt"]
        assert seen["kwargs"]["attachments"] == ["f.jpg"]


class TestOneMessageAtATimePerConversation:
    @staticmethod
    def _spy_brain(log):
        import asyncio

        class SpyBrain:
            def __init__(self, config, **kwargs):
                pass

            async def process_message(self, content, **kwargs):
                log.append(("start", content))
                await asyncio.sleep(0.05)
                log.append(("end", content))
                return content

        return SpyBrain

    async def test_two_messages_to_the_same_conversation_do_not_overlap(self):
        import asyncio

        runner, _ = _make_runner()
        agent = {"id": 1, "name": "Bot", "system_prompt": "x", "allowed_tools": "none"}
        log: list = []
        with patch("openacm.core.brain.Brain", self._spy_brain(log)):
            await asyncio.gather(
                runner.run(agent=agent, message="first", user_id="u1", channel_id="c1"),
                runner.run(agent=agent, message="second", user_id="u1", channel_id="c1"),
            )
        assert [e[0] for e in log] == ["start", "end", "start", "end"]

    async def test_different_conversations_still_run_in_parallel(self):
        import asyncio

        runner, _ = _make_runner()
        agent = {"id": 1, "name": "Bot", "system_prompt": "x", "allowed_tools": "none"}
        log: list = []
        with patch("openacm.core.brain.Brain", self._spy_brain(log)):
            await asyncio.gather(
                runner.run(agent=agent, message="a", user_id="u1", channel_id="c1"),
                runner.run(agent=agent, message="b", user_id="u2", channel_id="c2"),
            )
        assert [e[0] for e in log][:2] == ["start", "start"]

    async def test_idle_locks_are_not_kept(self):
        runner, _ = _make_runner()
        agent = {"id": 1, "name": "Bot", "system_prompt": "x", "allowed_tools": "none"}
        with patch("openacm.core.brain.Brain", self._spy_brain([])):
            await runner.run(agent=agent, message="a", user_id="u1", channel_id="c1")
        assert runner._conversation_locks == {}
