"""Tests for SkillManager's per-flow skill scoping — in particular the real
body of generate_flow_skill(), which is normally hidden behind a mock in
tests/unit/test_agents_flow_skill_api.py (that file only verifies the
endpoint calls the skill manager, never exercises the prompt-building logic
itself)."""
import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from openacm.core.skill_manager import SkillManager
from openacm.storage.database import Database


async def _make_manager():
    db = Database(":memory:")
    await db.initialize()
    manager = SkillManager(db)
    return manager, db


async def _make_agent(db, name="a1"):
    return await db.create_agent(name=name, description="", system_prompt="test")


MULTI_NODE_GRAPH = json.dumps({
    "nodes": [
        {"id": "start", "type": "start", "config": {"parameters": [
            {"name": "url", "type": "string", "description": "Target URL to check"},
            {"name": "timeout", "type": "number", "description": "Request timeout in seconds"},
        ]}},
        {"id": "http1", "type": "http_request", "config": {"url": "{{url}}"}},
        {"id": "cond1", "type": "conditional", "config": {"expression": "status == 200"}},
        {"id": "end", "type": "end", "config": {"template": "done"}},
    ],
    "edges": [
        {"from": "start", "to": "http1", "fromHandle": "default"},
        {"from": "http1", "to": "cond1", "fromHandle": "default"},
        {"from": "cond1", "to": "end", "fromHandle": "default"},
    ],
})


async def _make_flow(db, agent_id, graph_json=MULTI_NODE_GRAPH, name="check-website"):
    return await db.create_flow(agent_id=agent_id, name=name, description="Checks a URL", graph_json=graph_json)


class TestCreateFlowSkill:
    async def test_creates_a_flow_private_skill_without_writing_a_file(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)  # SKILLS_BASE_DIR is relative ("./skills")
        agent_id = await _make_agent(db)
        flow_id = await _make_flow(db, agent_id)

        skill = await manager.create_flow_skill(
            flow_id=flow_id, name="cuando-usar", description="d", content="c",
        )

        assert skill["name"] == "cuando-usar"
        assert skill["flow_id"] == flow_id
        assert not (tmp_path / "skills" / "custom" / "cuando-usar.md").exists()
        await db.close()


class TestGenerateFlowSkill:
    async def test_raises_without_llm_router(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        flow_id = await _make_flow(db, agent_id)

        with pytest.raises(ValueError):
            await manager.generate_flow_skill(
                flow_id=flow_id, name="check-website", description="d", llm_router=None,
            )
        await db.close()

    async def test_prompt_includes_start_params_and_node_types(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        flow_id = await _make_flow(db, agent_id)
        fake_router = MagicMock()
        fake_router.chat = AsyncMock(return_value={"content": "# Generated flow skill"})

        await manager.generate_flow_skill(
            flow_id=flow_id, name="check-website", description="Checks a URL",
            llm_router=fake_router,
        )

        fake_router.chat.assert_awaited_once()
        _, call_kwargs = fake_router.chat.call_args
        prompt = call_kwargs["messages"][0]["content"]
        # Start-node parameters (name, type, description) must be extracted
        # into the prompt.
        assert "url (string): Target URL to check" in prompt
        assert "timeout (number): Request timeout in seconds" in prompt
        # Node types other than start/end must be listed, in order, and
        # start/end themselves must be excluded from that list.
        assert "http_request, conditional" in prompt
        assert "start" not in prompt.split("Flow's internal steps")[1].split("\n")[0]
        await db.close()

    async def test_no_parameters_and_no_middle_nodes_use_placeholders(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        empty_graph = json.dumps({
            "nodes": [
                {"id": "start", "type": "start", "config": {"parameters": []}},
                {"id": "end", "type": "end", "config": {"template": "done"}},
            ],
            "edges": [{"from": "start", "to": "end", "fromHandle": "default"}],
        })
        flow_id = await _make_flow(db, agent_id, graph_json=empty_graph, name="no-op-flow")
        fake_router = MagicMock()
        fake_router.chat = AsyncMock(return_value={"content": "# Generated"})

        await manager.generate_flow_skill(
            flow_id=flow_id, name="no-op-flow", description="d", llm_router=fake_router,
        )

        _, call_kwargs = fake_router.chat.call_args
        prompt = call_kwargs["messages"][0]["content"]
        assert "(sin parámetros)" in prompt
        assert "(ninguno)" in prompt
        await db.close()

    async def test_returns_llm_content_saved_as_the_flows_skill(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        flow_id = await _make_flow(db, agent_id)
        fake_router = MagicMock()
        fake_router.chat = AsyncMock(return_value={"content": "# Generated flow skill content"})

        skill = await manager.generate_flow_skill(
            flow_id=flow_id, name="check-website", description="Checks a URL",
            llm_router=fake_router,
        )

        assert skill["content"] == "# Generated flow skill content"
        assert skill["flow_id"] == flow_id
        assert skill["name"] == "check-website"
        # It must actually have been persisted (get_flow_skill sees it).
        assert (await manager.get_flow_skill(flow_id))["id"] == skill["id"]
        await db.close()
