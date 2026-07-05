"""Test that _build_worker_system_prompt includes a worker's skills prompt
when one is provided, and is unaffected when it isn't (existing behavior)."""
from unittest.mock import MagicMock
from openacm.core.swarm_manager import SwarmManager


def _make_manager():
    return SwarmManager(
        database=MagicMock(), llm_router=MagicMock(), tool_registry=MagicMock(),
        memory=MagicMock(), event_bus=MagicMock(), skill_manager=MagicMock(),
    )


WORKER = {"id": 1, "name": "w1", "role": "worker", "description": "d",
          "system_prompt": "Base prompt.", "workspace_path": "/tmp/ws"}
SWARM = {"goal": "test goal", "working_path": None}


class TestBuildWorkerSystemPromptWithSkills:
    def test_appends_skills_prompt_when_provided(self):
        manager = _make_manager()

        result = manager._build_worker_system_prompt(WORKER, SWARM, [WORKER], skills_prompt="## my-skill\n\ndo the thing")

        assert "## my-skill" in result
        assert "do the thing" in result

    def test_no_skills_prompt_leaves_output_unchanged_from_before(self):
        manager = _make_manager()

        with_empty = manager._build_worker_system_prompt(WORKER, SWARM, [WORKER], skills_prompt="")
        with_default = manager._build_worker_system_prompt(WORKER, SWARM, [WORKER])

        assert with_empty == with_default
        assert "Base prompt." in with_empty
