"""Unit tests for the create_or_update_agent_flow tool."""
from unittest.mock import AsyncMock, MagicMock

from openacm.tools.flow_tool import create_or_update_agent_flow, _resolve_agent_id, _auto_layout


def _valid_graph():
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"parameters": []}},
            {"id": "end", "type": "end", "config": {"template": "done"}},
        ],
        "edges": [{"from": "start", "to": "end", "fromHandle": "default", "toHandle": "default", "kind": "flow"}],
    }


def _fake_brain(db):
    brain = MagicMock()
    brain.skill_manager.database = db
    return brain


class TestResolveAgentId:
    def test_explicit_agent_id_wins(self):
        assert _resolve_agent_id(5, "agent_9") == 5

    def test_falls_back_to_channel_id(self):
        assert _resolve_agent_id(None, "agent_9") == 9

    def test_falls_back_to_channel_id_with_flow_suffix(self):
        assert _resolve_agent_id(None, "agent_5_flow_12") == 5

    def test_non_agent_channel_id_returns_none(self):
        assert _resolve_agent_id(None, "swarm_abc") is None

    def test_agent_prefix_without_separator_returns_none(self):
        # The suffix-tolerant regex must not start matching things that only
        # *look* like an agent channel.
        assert _resolve_agent_id(None, "agent_5x") is None
        assert _resolve_agent_id(None, "agentx_5") is None

    def test_no_agent_id_no_channel_id_returns_none(self):
        assert _resolve_agent_id(None, None) is None


class TestAutoLayout:
    def test_fills_in_missing_positions(self):
        nodes = [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}]
        edges = [{"from": "start", "to": "end", "fromHandle": "default", "toHandle": "default", "kind": "flow"}]
        _auto_layout(nodes, edges)
        assert "position" in nodes[0] and "position" in nodes[1]
        assert nodes[0]["position"]["y"] < nodes[1]["position"]["y"]  # start above end (vertical layout)

    def test_never_overwrites_existing_position(self):
        nodes = [{"id": "start", "type": "start", "position": {"x": 999, "y": 999}}]
        _auto_layout(nodes, [])
        assert nodes[0]["position"] == {"x": 999, "y": 999}


class TestCreateOrUpdateAgentFlow:
    async def test_no_agent_resolvable_returns_error_without_db_call(self):
        db = AsyncMock()
        result = await create_or_update_agent_flow(
            name="x", graph_json=_valid_graph(), _brain=_fake_brain(db), _channel_id=None,
        )
        assert "agent_id" in result
        db.create_flow.assert_not_awaited()

    async def test_invalid_graph_returns_errors_without_db_call(self):
        db = AsyncMock()
        bad_graph = {"nodes": [{"id": "a", "type": "bogus", "config": {}}], "edges": []}
        result = await create_or_update_agent_flow(
            name="x", graph_json=bad_graph, agent_id=1, _brain=_fake_brain(db),
        )
        assert "bogus" in result
        db.create_flow.assert_not_awaited()

    async def test_valid_graph_creates_flow_via_explicit_agent_id(self):
        db = AsyncMock()
        db.create_flow = AsyncMock(return_value=42)
        result = await create_or_update_agent_flow(
            name="Buscar productos", graph_json=_valid_graph(), agent_id=7, _brain=_fake_brain(db),
        )
        db.create_flow.assert_awaited_once()
        assert db.create_flow.await_args.kwargs["agent_id"] == 7
        assert "42" in result

    async def test_valid_graph_creates_flow_via_channel_id(self):
        db = AsyncMock()
        db.create_flow = AsyncMock(return_value=8)
        result = await create_or_update_agent_flow(
            name="x", graph_json=_valid_graph(), _brain=_fake_brain(db), _channel_id="agent_7",
        )
        assert db.create_flow.await_args.kwargs["agent_id"] == 7

    async def test_flow_id_given_updates_instead_of_creating(self):
        db = AsyncMock()
        db.get_flow = AsyncMock(return_value={"id": 5, "agent_id": 7})
        db.update_flow = AsyncMock(return_value=True)
        result = await create_or_update_agent_flow(
            name="x", graph_json=_valid_graph(), agent_id=7, flow_id=5, _brain=_fake_brain(db),
        )
        db.update_flow.assert_awaited_once()
        db.create_flow.assert_not_awaited()
        assert "5" in result

    async def test_flow_id_belonging_to_other_agent_is_rejected(self):
        db = AsyncMock()
        db.get_flow = AsyncMock(return_value={"id": 5, "agent_id": 999})
        result = await create_or_update_agent_flow(
            name="x", graph_json=_valid_graph(), agent_id=7, flow_id=5, _brain=_fake_brain(db),
        )
        assert "5" in result
        db.update_flow.assert_not_awaited()
