"""Tests for AgentRunner.run()'s optional extra_system_context parameter."""
from unittest.mock import MagicMock, patch

from openacm.core.agent_runner import AgentRunner

AGENT = {
    "id": 42, "name": "TestAgent", "description": "d",
    "system_prompt": "Base agent prompt.", "allowed_tools": "all",
}


def _make_runner():
    return AgentRunner(
        llm_router=MagicMock(), tool_registry=MagicMock(), memory=MagicMock(),
        event_bus=MagicMock(), database=None, skill_manager=None,
    )


class TestExtraSystemContext:
    async def test_appended_to_system_prompt_when_provided(self):
        captured = {}

        class _FakeBrain:
            def __init__(self, config, **kwargs):
                captured["system_prompt"] = config.system_prompt

            async def process_message(self, **kwargs):
                return "ok"

        runner = _make_runner()
        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi", extra_system_context="Estás editando el flujo X.")

        assert "Base agent prompt." in captured["system_prompt"]
        assert "Estás editando el flujo X." in captured["system_prompt"]

    async def test_not_appended_when_omitted(self):
        captured = {}

        class _FakeBrain:
            def __init__(self, config, **kwargs):
                captured["system_prompt"] = config.system_prompt

            async def process_message(self, **kwargs):
                return "ok"

        runner = _make_runner()
        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        assert captured["system_prompt"] == "Base agent prompt."
