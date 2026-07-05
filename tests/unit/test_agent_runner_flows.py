"""Test that AgentRunner.run() exposes the agent's active flows as callable
tools, dispatches flow-tool calls through FlowExecutor, and leaves an
agent with no flows completely unaffected (byte-identical to before this
change)."""
from unittest.mock import AsyncMock, MagicMock, patch
import json
import pytest
from openacm.core.agent_runner import AgentRunner

AGENT = {
    "id": 42, "name": "TestAgent", "description": "d",
    "system_prompt": "Base agent prompt.", "allowed_tools": "all",
}

FLOW_ROW = {
    "id": 7, "name": "check-availability", "description": "Checks product availability",
    "graph_json": json.dumps({
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": [{"name": "producto", "type": "string", "description": "product name", "required": True}]}},
            {"id": "end", "type": "end", "config": {"template": "Checked: {{producto}}"}},
        ],
        "edges": [{"from": "start", "to": "end", "fromHandle": "default"}],
    }),
}


def _make_runner(database=None):
    return AgentRunner(
        llm_router=MagicMock(), tool_registry=MagicMock(), memory=MagicMock(),
        event_bus=MagicMock(), database=database, skill_manager=None,
    )


class _FakeToolRegistry:
    def __init__(self):
        self.tools = {"some_static_tool": MagicMock(), "other_static_tool": MagicMock()}

    def get_tools_schema(self):
        return [
            {"type": "function", "function": {"name": "some_static_tool"}},
            {"type": "function", "function": {"name": "other_static_tool"}},
        ]

    def get_tools_by_intent(self, msg):
        return self.get_tools_schema()


class TestFlowToolsExposedToAgent:
    async def test_agents_active_flow_appears_in_the_tool_schema(self):
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        schema_names = {t["function"]["name"] for t in captured["tool_registry"].get_tools_schema()}
        assert "flow_7" in schema_names
        assert "some_static_tool" in schema_names  # existing static tools still present

    async def test_flow_tool_is_in_the_tools_membership_dict(self):
        """brain_loop.py gates on `tool_name in tool_registry.tools` before
        calling execute() — flow_7 must be a real key there, not just in
        the schema list."""
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        assert "flow_7" in captured["tool_registry"].tools
        assert "some_static_tool" in captured["tool_registry"].tools

    async def test_calling_the_flow_tool_runs_it_via_flow_executor(self):
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
        db.get_connection = AsyncMock(return_value=None)
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        result = await captured["tool_registry"].execute("flow_7", {"producto": "zapatos"})
        assert result == "Checked: zapatos"

    async def test_agent_with_no_flows_is_unaffected(self):
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[])
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        schema_names = {t["function"]["name"] for t in captured["tool_registry"].get_tools_schema()}
        assert schema_names == {"some_static_tool", "other_static_tool"}

    async def test_no_database_means_no_flow_tools_but_static_tools_still_work(self):
        runner = _make_runner(database=None)
        runner.tool_registry = _FakeToolRegistry()

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=AGENT, message="hi")

        schema_names = {t["function"]["name"] for t in captured["tool_registry"].get_tools_schema()}
        assert schema_names == {"some_static_tool", "other_static_tool"}

    async def test_allowed_tools_none_still_gets_no_tool_registry_at_all(self):
        """Existing behavior (from before this task) must be preserved:
        allowed_tools == 'none' passes tool_registry=None to Brain entirely."""
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()
        agent_none = {**AGENT, "allowed_tools": "none"}

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=agent_none, message="hi")

        assert captured["tool_registry"] is None

    async def test_json_list_allowed_tools_combined_with_active_flows(self):
        """allowed_tools as a JSON list of system tool names must still
        filter the static tool schema (existing sub-project-1 behavior),
        AND active flow tools must still be added on top of that filtered
        set — the two features compose rather than one overriding the other."""
        db = MagicMock()
        db.get_agent_knowledge = AsyncMock(return_value=[])
        db.get_agent_flows = AsyncMock(return_value=[FLOW_ROW])
        runner = _make_runner(database=db)
        runner.tool_registry = _FakeToolRegistry()
        agent_filtered = {**AGENT, "allowed_tools": json.dumps(["some_static_tool"])}

        captured = {}

        class _FakeBrain:
            def __init__(self, config, tool_registry=None, **kwargs):
                captured["tool_registry"] = tool_registry

            async def process_message(self, **kwargs):
                return "ok"

        with patch("openacm.core.brain.Brain", _FakeBrain):
            await runner.run(agent=agent_filtered, message="hi")

        schema_names = {t["function"]["name"] for t in captured["tool_registry"].get_tools_schema()}
        assert schema_names == {"some_static_tool", "flow_7"}
        assert "other_static_tool" not in schema_names
        assert "flow_7" in captured["tool_registry"].tools
