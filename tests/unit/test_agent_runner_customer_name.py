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
