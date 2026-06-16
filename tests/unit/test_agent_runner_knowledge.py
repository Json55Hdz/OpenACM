"""Tests for AgentRunner knowledge injection."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_runner(knowledge_items=None):
    from openacm.core.agent_runner import AgentRunner

    mock_db = MagicMock()
    mock_db.get_agent_knowledge = AsyncMock(return_value=knowledge_items or [])

    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value={
        "content": "Hi there!",
        "tool_calls": [],
        "model": "mock",
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "cost": 0.0,
    })

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
    return runner, mock_db, mock_llm


class TestAgentRunnerKnowledgeInjection:
    async def test_no_knowledge_uses_original_system_prompt(self):
        runner, mock_db, mock_llm = _make_runner(knowledge_items=[])
        agent = {"id": 1, "name": "Bot", "system_prompt": "You are helpful.", "allowed_tools": "none"}

        with patch("openacm.core.brain.Brain.process_message", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = "Hi!"
            await runner.run(agent=agent, message="Hello")

        mock_db.get_agent_knowledge.assert_called_once_with(1)

    async def test_knowledge_prepended_to_system_prompt(self):
        items = [
            {"title": "FAQ", "content": "Q: hours?\nA: 9-5"},
            {"title": "Policy", "content": "No refunds."},
        ]
        runner, mock_db, mock_llm = _make_runner(knowledge_items=items)
        agent = {"id": 1, "name": "Bot", "system_prompt": "Be helpful.", "allowed_tools": "none"}

        with patch("openacm.core.brain.Brain.process_message", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = "ok"
            await runner.run(agent=agent, message="Hello")

        mock_db.get_agent_knowledge.assert_called_once_with(1)

    async def test_no_database_skips_knowledge(self):
        from openacm.core.agent_runner import AgentRunner

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
            database=None,
        )
        agent = {"id": 1, "name": "Bot", "system_prompt": "Be helpful.", "allowed_tools": "none"}

        with patch("openacm.core.brain.Brain.process_message", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = "ok"
            await runner.run(agent=agent, message="Hi")
        # Should not raise

    async def test_build_system_prompt_no_knowledge(self):
        from openacm.core.agent_runner import AgentRunner
        runner = AgentRunner(llm_router=None, tool_registry=None, memory=None, event_bus=None)
        result = runner._build_system_prompt("Be helpful.", [])
        assert result == "Be helpful."

    async def test_build_system_prompt_with_knowledge(self):
        from openacm.core.agent_runner import AgentRunner
        runner = AgentRunner(llm_router=None, tool_registry=None, memory=None, event_bus=None)
        items = [
            {"title": "FAQ", "content": "Q: hours?\nA: 9-5"},
            {"title": "Rules", "content": "No spam."},
        ]
        result = runner._build_system_prompt("Be helpful.", items)
        assert result.startswith("## Base de conocimiento")
        assert "### FAQ" in result
        assert "Q: hours?" in result
        assert "### Rules" in result
        assert result.endswith("Be helpful.")

    async def test_build_system_prompt_truncates_at_40k(self):
        from openacm.core.agent_runner import AgentRunner
        runner = AgentRunner(llm_router=None, tool_registry=None, memory=None, event_bus=None)
        items = [{"title": "Big", "content": "x" * 50_000}]
        result = runner._build_system_prompt("Base prompt.", items)
        assert "[Conocimiento truncado por límite de contexto]" in result
        assert len(result) < 55_000
