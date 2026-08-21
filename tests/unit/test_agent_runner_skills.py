"""Test that AgentRunner.run() includes the agent's active skills prompt
in the system prompt handed to Brain, and is unaffected when the agent has
no skill_manager or no active skills (existing behavior preserved)."""
from unittest.mock import AsyncMock, MagicMock, patch

from openacm.core.agent_runner import AgentRunner

AGENT = {
    "id": 42, "name": "TestAgent", "description": "d",
    "system_prompt": "Base agent prompt.", "allowed_tools": "all",
}


def _make_runner(skill_manager=None):
    return AgentRunner(
        llm_router=MagicMock(), tool_registry=MagicMock(), memory=MagicMock(),
        event_bus=MagicMock(), database=None, skill_manager=skill_manager,
    )


class TestRunIncludesAgentSkillsPrompt:
    async def test_appends_skills_prompt_when_skill_manager_returns_one(self):
        skill_manager = MagicMock()
        skill_manager.get_active_skills_prompt_for_agent = AsyncMock(return_value="## my-skill\n\ndo the thing")
        runner = _make_runner(skill_manager=skill_manager)

        captured = {}

        class _FakeBrain:
            def __init__(self, config, **kwargs):
                captured["system_prompt"] = config.system_prompt

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        assert "## my-skill" in captured["system_prompt"]
        assert "do the thing" in captured["system_prompt"]
        skill_manager.get_active_skills_prompt_for_agent.assert_awaited_once_with(42)

    async def test_no_skill_manager_leaves_prompt_unchanged(self):
        runner = _make_runner(skill_manager=None)

        captured = {}

        class _FakeBrain:
            def __init__(self, config, **kwargs):
                captured["system_prompt"] = config.system_prompt

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        assert captured["system_prompt"] == "Base agent prompt."


class TestRunPassesSkillManagerToBrain:
    """The agentic-loop Brain that AgentRunner.run() builds for the agent's
    own tool calls must receive the SAME skill_manager AgentRunner was
    constructed with — tools like create_or_update_agent_flow and cron_tool
    reach the database via _brain.skill_manager.database, so a Brain built
    without it silently has no database for the agent's own tool calls."""

    async def test_brain_receives_the_runners_skill_manager(self):
        skill_manager = MagicMock()
        skill_manager.get_active_skills_prompt_for_agent = AsyncMock(return_value="")
        runner = _make_runner(skill_manager=skill_manager)

        captured = {}

        class _FakeBrain:
            def __init__(self, config, **kwargs):
                captured["kwargs"] = kwargs

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        assert captured["kwargs"]["skill_manager"] is skill_manager

    async def test_brain_receives_none_when_runner_has_no_skill_manager(self):
        runner = _make_runner(skill_manager=None)

        captured = {}

        class _FakeBrain:
            def __init__(self, config, **kwargs):
                captured["kwargs"] = kwargs

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        assert captured["kwargs"]["skill_manager"] is None
