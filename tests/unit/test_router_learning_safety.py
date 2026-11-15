"""The router learns from what the model did and then acts without asking the model.
It must never act for outsiders, learn from failures or replay a command for a different target."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from openacm.core.brain import Brain
from openacm.core.config import AssistantConfig
from openacm.core.local_router import LocalRouter


class TestAgentsNeverGetTheFastPath:
    def test_an_agents_router_only_observes(self, mock_llm_router, event_bus_fixture=None):
        brain = Brain(
            config=AssistantConfig(is_agent=True),
            llm_router=mock_llm_router, memory=MagicMock(), event_bus=MagicMock(), tool_registry=MagicMock(),
        )
        assert brain.local_router.observation_mode is True

    def test_the_owners_brain_keeps_the_fast_path(self, mock_llm_router):
        brain = Brain(
            config=AssistantConfig(),
            llm_router=mock_llm_router, memory=MagicMock(), event_bus=MagicMock(), tool_registry=MagicMock(),
        )
        assert brain.local_router.observation_mode is False

    async def test_an_agent_never_teaches_the_router(self, mock_llm_router):
        brain = Brain(
            config=AssistantConfig(is_agent=True),
            llm_router=mock_llm_router, memory=MagicMock(), event_bus=MagicMock(), tool_registry=MagicMock(),
        )
        brain.local_router.learn = AsyncMock()
        task = asyncio.create_task(asyncio.sleep(0, result=None))
        await brain._maybe_learn_from_tools(
            "abre chrome", [{"function": {"name": "open_url", "arguments": '{"url": "https://x.com"}'}}], task)
        brain.local_router.learn.assert_not_awaited()


class TestLearnedActionsNeedTheSameTarget:
    @pytest.mark.parametrize("a,b,ok", [
        ("abre youtube", "abre youtube por favor", True),
        ("abre el proyecto alfa", "abre el proyecto beta", False),
        ("pon música de Shakira", "pon música de Metallica", False),
        ("abre chrome", "abre chrome", True),
        ("", "abre chrome", False),
    ])
    def test_phrases_compatible(self, a, b, ok):
        assert LocalRouter.phrases_compatible(a, b) is ok


class TestFastPathReplay:
    async def test_a_learned_action_that_errors_is_not_reported_as_done(self):
        from openacm.core import fast_path

        brain = SimpleNamespace(
            local_router=SimpleNamespace(lookup_action=lambda m: {"tool": "run_command", "args": {}, "response": "Abriendo X"}),
            tool_registry=SimpleNamespace(execute=AsyncMock(return_value="Error: command not found")),
        )
        out = await fast_path.dispatch("UNKNOWN_INTENT", brain, "abre x", "u", "c", "web")
        assert out is None


class TestReviewAndForget:
    @pytest.fixture
    def router(self, tmp_path, monkeypatch):
        import json
        from openacm.core import local_router as lr

        monkeypatch.setattr(lr, "LEARNED_ACTIONS_PATH", tmp_path / "actions.json")
        monkeypatch.setattr(lr, "LEARNED_EXAMPLES_PATH", tmp_path / "examples.json")
        (tmp_path / "actions.json").write_text(json.dumps([
            {"phrase": "abre youtube", "tool": "open_url", "args": {"url": "https://youtube.com"}, "intent": "OPEN_APP", "response": "x"},
            {"phrase": "abre google", "tool": "open_url", "args": {"url": "https://google.com"}, "intent": "OPEN_APP", "response": "x"},
        ]))
        (tmp_path / "examples.json").write_text(json.dumps({"OPEN_APP": ["abre eso"]}))
        r = LocalRouter.__new__(LocalRouter)
        monkeypatch.setattr(LocalRouter, "_reload_action_embeddings_sync", lambda self: None)
        monkeypatch.setattr(LocalRouter, "_reload_intent_embeddings", lambda self, i, l: None)
        return r

    async def test_what_was_learned_can_be_listed_and_forgotten(self, router):
        listed = router.list_learned()
        assert [a["phrase"] for a in listed["actions"]] == ["abre youtube", "abre google"]
        assert await router.forget_action(0) is True
        assert [a["phrase"] for a in router.list_learned()["actions"]] == ["abre google"]
        assert await router.forget_action(5) is False
        assert await router.forget_example("OPEN_APP", "abre eso") is True
        assert router.list_learned()["examples"] == {}
        assert await router.forget_example("OPEN_APP", "nunca existió") is False
