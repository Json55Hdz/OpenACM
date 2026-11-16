"""Model routes: a different model per kind of work, per chat / workspace / globally."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from openacm.core.config import LLMConfig
from openacm.core.events import EventBus
from openacm.core.llm_router import LLMRouter
from openacm.core.model_routes import RouteError, route_scope


@pytest.fixture
def router():
    cfg = LLMConfig(default_provider="openai", providers={
        "openai": {"default_model": "gpt-main"},
        "anthropic": {"default_model": "claude-big"},
        "ollama": {"default_model": "llama-small", "base_url": "http://localhost:11434/v1"},
    })
    r = LLMRouter(cfg, EventBus())
    r.set_model("gpt-main", provider="openai")
    return r


def spy(router):
    """Replace the real call with one that records which model the call would have used."""
    seen = []

    async def fake(*a, **k):
        seen.append((router._current_provider, router.current_model))
        return {"content": "ok", "tool_calls": [], "usage": {}, "model": router.current_model}

    router._chat = fake
    return seen


async def test_without_routes_everything_uses_the_main_model(router):
    seen = spy(router)
    await router.chat([], role="orchestrator")
    await router.chat([], role="tools")
    await router.chat([])
    assert seen == [("openai", "gpt-main")] * 3


async def test_a_global_route_applies_only_to_its_role(router):
    seen = spy(router)
    await router.routes.set_routes("global", "", {"tools": {"provider": "ollama", "model": "llama-small"}})
    await router.chat([], role="orchestrator")
    await router.chat([], role="tools")
    assert seen == [("openai", "gpt-main"), ("ollama", "llama-small")]
    assert (router._current_provider, router.current_model) == ("openai", "gpt-main")  # restored


async def test_chat_beats_workspace_beats_global(router):
    seen = spy(router)
    await router.routes.set_routes("global", "", {"orchestrator": {"provider": "ollama", "model": "g"}})
    await router.routes.set_routes("workspace", "/proj", {"orchestrator": {"provider": "anthropic", "model": "w"}})
    await router.routes.set_routes("chat", "web:u1", {"orchestrator": {"provider": "openai", "model": "c"}})
    ws = str(__import__("pathlib").Path("/proj").resolve())

    async def run(scope):
        route_scope.set(scope)
        await router.chat([], role="orchestrator")

    await asyncio.create_task(run(("web:u1", ws)))      # chat wins
    await asyncio.create_task(run(("web:other", ws)))   # workspace wins
    await asyncio.create_task(run(("web:other", "")))   # global
    assert [m for _, m in seen] == ["c", "w", "g"]


async def test_two_conversations_at_once_do_not_see_each_others_model(router):
    await router.routes.set_routes("chat", "web:a", {"orchestrator": {"provider": "anthropic", "model": "A"}})
    await router.routes.set_routes("chat", "web:b", {"orchestrator": {"provider": "ollama", "model": "B"}})
    seen = {}

    async def fake(*a, **k):
        await asyncio.sleep(0.01)  # let the other task run in between
        seen[route_scope.get()[0]] = router.current_model
        return {"content": "", "tool_calls": [], "usage": {}}

    router._chat = fake

    async def run(key):
        route_scope.set((key, ""))
        await router.chat([], role="orchestrator")

    await asyncio.gather(asyncio.create_task(run("web:a")), asyncio.create_task(run("web:b")))
    assert seen == {"web:a": "A", "web:b": "B"}


async def test_an_explicit_model_override_wins_over_routes(router):
    seen = []

    async def fake(*a, **k):
        seen.append(k.get("model_override"))
        return {}

    router._chat = fake
    await router.routes.set_routes("global", "", {"orchestrator": {"provider": "ollama", "model": "x"}})
    await router.chat([], role="orchestrator", model_override="anthropic/claude-x")
    assert seen == ["anthropic/claude-x"]


async def test_validation(router):
    with pytest.raises(RouteError, match="no está configurado"):
        await router.routes.set_routes("global", "", {"tools": {"provider": "nope", "model": "m"}})
    with pytest.raises(RouteError, match="Rol desconocido"):
        await router.routes.set_routes("global", "", {"thinking": {"provider": "openai", "model": "m"}})
    with pytest.raises(RouteError):
        await router.routes.set_routes("chat", "", {"tools": None})
    with pytest.raises(RouteError):
        await router.routes.set_routes("galaxy", "x", {})


async def test_clearing_a_role_and_persistence(router, db):
    await router.routes.load(db)
    await router.routes.set_routes("global", "", {"tools": {"provider": "ollama", "model": "m"}})
    fresh = LLMRouter(router.config, EventBus())
    await fresh.routes.load(db)
    assert fresh.routes.data["global"]["tools"]["model"] == "m"
    await fresh.routes.set_routes("global", "", {"tools": None})
    assert fresh.routes.data["global"] == {}
