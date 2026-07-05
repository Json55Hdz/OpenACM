"""Tests for SkillManager's per-agent skill scoping — private skills must
never leak into the global active-skills cache used by every conversation."""
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


class TestCreateAgentSkill:
    async def test_creates_a_private_skill_without_writing_a_file(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)  # SKILLS_BASE_DIR is relative ("./skills")
        agent_id = await _make_agent(db)

        skill = await manager.create_agent_skill(
            agent_id=agent_id, name="faq-answers", description="d", content="c",
        )

        assert skill["name"] == "faq-answers"
        assert skill["agent_id"] == agent_id
        assert not (tmp_path / "skills" / "custom" / "faq-answers.md").exists()
        await db.close()

    async def test_private_skill_is_excluded_from_global_get_all_skills(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)

        await manager.create_agent_skill(agent_id=agent_id, name="faq-answers", description="d", content="c")

        assert await db.get_all_skills() == []
        await db.close()


class TestGenerateAgentSkill:
    async def test_generates_content_via_llm_and_saves_it_privately(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        fake_router = MagicMock()
        fake_router.chat = AsyncMock(return_value={"content": "# Generated content"})

        skill = await manager.generate_agent_skill(
            agent_id=agent_id, name="closing-deals", description="d", use_cases="u",
            llm_router=fake_router,
        )

        assert skill["content"] == "# Generated content"
        assert skill["agent_id"] == agent_id
        fake_router.chat.assert_awaited_once()
        await db.close()


class TestActiveSkillsPromptForAgent:
    async def test_includes_agents_own_active_private_skill(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        await manager.create_agent_skill(agent_id=agent_id, name="s1", description="d", content="agent-only content")

        prompt = await manager.get_active_skills_prompt_for_agent(agent_id)

        assert "agent-only content" in prompt
        await db.close()

    async def test_includes_enabled_global_skill(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        global_id = await db.create_skill(name="g1", description="d", content="global content")
        await db.enable_agent_skill(agent_id, global_id)

        prompt = await manager.get_active_skills_prompt_for_agent(agent_id)

        assert "global content" in prompt
        await db.close()

    async def test_excludes_global_skill_not_enabled_for_this_agent(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        await db.create_skill(name="g1", description="d", content="not enabled content")

        prompt = await manager.get_active_skills_prompt_for_agent(agent_id)

        assert "not enabled content" not in prompt
        await db.close()

    async def test_excludes_inactive_private_skill(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)
        skill = await manager.create_agent_skill(agent_id=agent_id, name="s1", description="d", content="inactive content")
        await db.toggle_skill(skill["id"])  # is_active 1 -> 0

        prompt = await manager.get_active_skills_prompt_for_agent(agent_id)

        assert "inactive content" not in prompt
        await db.close()

    async def test_empty_when_agent_has_no_skills(self, tmp_path, monkeypatch):
        manager, db = await _make_manager()
        monkeypatch.chdir(tmp_path)
        agent_id = await _make_agent(db)

        prompt = await manager.get_active_skills_prompt_for_agent(agent_id)

        assert prompt == ""
        await db.close()
