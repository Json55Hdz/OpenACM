"""Failover: a failing model hands the request to the next one; dead providers cool down."""
import asyncio
import time

import pytest

from openacm.core.config import LLMConfig
from openacm.core.events import EventBus
from openacm.core.llm_failover import scrub_error
from openacm.core.llm_router import LLMRouter


@pytest.fixture
def router():
    cfg = LLMConfig(default_provider="openai", providers={
        "openai": {"default_model": "gpt-main"},
        "anthropic": {"default_model": "claude-b"},
        "ollama": {"default_model": "llama-c", "base_url": "http://localhost:11434/v1"},
    })
    r = LLMRouter(cfg, EventBus())
    r.set_model("gpt-main", provider="openai")
    return r


def scripted(router, failing: set[str]):
    """_chat that raises for the providers in `failing`; records every attempt."""
    attempts = []

    async def fake(*a, **k):
        attempts.append((router._current_provider, router.current_model, k.get("max_retries")))
        if router._current_provider in failing:
            raise RuntimeError(f"{router._current_provider} is down; api_key=sk-secret123456789")
        return {"content": "ok", "tool_calls": [], "usage": {}, "model": router.current_model}

    router._chat = fake
    return attempts


async def test_no_fallbacks_means_the_error_surfaces(router):
    scripted(router, {"openai"})
    with pytest.raises(RuntimeError, match="openai is down"):
        await router.chat([])


async def test_a_failing_model_falls_over_to_the_next(router):
    attempts = scripted(router, {"openai"})
    await router.routes.set_fallbacks([{"provider": "anthropic", "model": "claude-b"}])
    result = await router.chat([])
    assert result["content"] == "ok"
    assert [a[0] for a in attempts] == ["openai", "anthropic"]
    assert attempts[0][2] == 2  # fewer retries on a model that has a fallback behind it
    assert router._current_provider == "openai"  # override restored


async def test_the_whole_chain_is_tried_in_order_then_the_last_error_surfaces(router):
    attempts = scripted(router, {"openai", "anthropic", "ollama"})
    await router.routes.set_fallbacks([{"provider": "anthropic", "model": ""}, {"provider": "ollama", "model": ""}])
    with pytest.raises(RuntimeError, match="ollama is down"):
        await router.chat([])
    assert [a[0] for a in attempts] == ["openai", "anthropic", "ollama"]


async def test_a_failed_provider_cools_down_and_is_skipped_next_time(router):
    attempts = scripted(router, {"openai"})
    await router.routes.set_fallbacks([{"provider": "anthropic", "model": ""}])
    await router.chat([])
    attempts.clear()
    await router.chat([])
    assert [a[0] for a in attempts] == ["anthropic"]  # openai not even tried
    assert router.provider_health()["openai"]["cooling_for_s"] > 0


async def test_the_last_resort_is_tried_even_while_cooling(router):
    attempts = scripted(router, {"openai"})
    router._mark_failed("openai", RuntimeError("x"))  # cooling, no fallbacks
    with pytest.raises(RuntimeError):
        await router.chat([])
    assert [a[0] for a in attempts] == ["openai"]


async def test_success_clears_the_cooldown(router):
    scripted(router, set())
    router._mark_failed("openai", RuntimeError("x"))
    router._health_state()["openai"]["until"] = time.time() - 1  # cooldown over
    await router.chat([])
    assert "openai" not in router.provider_health()


async def test_a_named_model_never_fails_over(router):
    seen = []

    async def fake(*a, **k):
        seen.append(k.get("model_override"))
        raise RuntimeError("boom")

    router._chat = fake
    await router.routes.set_fallbacks([{"provider": "anthropic", "model": ""}])
    with pytest.raises(RuntimeError):
        await router.chat([], model_override="anthropic/claude-x")
    assert seen == ["anthropic/claude-x"]


async def test_a_route_that_fails_falls_back_too(router):
    attempts = scripted(router, {"ollama"})
    await router.routes.set_routes("global", "", {"tools": {"provider": "ollama", "model": "llama-c"}})
    await router.routes.set_fallbacks([{"provider": "anthropic", "model": ""}])
    await router.chat([], role="tools")
    assert [a[0] for a in attempts] == ["ollama", "anthropic"]


async def test_cancellation_is_not_a_failure(router):
    async def fake(*a, **k):
        raise asyncio.CancelledError

    router._chat = fake
    await router.routes.set_fallbacks([{"provider": "anthropic", "model": ""}])
    with pytest.raises(asyncio.CancelledError):
        await router.chat([])
    assert router.provider_health() == {}


async def test_errors_are_recorded_without_secrets(router, db):
    router._database = db
    scripted(router, {"openai"})
    await router.routes.set_fallbacks([{"provider": "anthropic", "model": ""}])
    await router.chat([])
    errors = await db.get_llm_errors(days=1)
    assert len(errors) == 1 and errors[0]["provider"] == "openai"
    assert "sk-secret" not in errors[0]["message"] and errors[0]["failover_to"].startswith("anthropic")
    report = await db.get_llm_monitor(days=1)
    assert report["totals"]["errors"] == 1 and report["totals"]["failovers"] == 1


def test_scrub_hides_keys_and_bearer_tokens():
    out = scrub_error("401 Bearer abc123def456 and sk-ant-REALKEY12345 and api_key=zzzzzzzzzzzz")
    assert "abc123def456" not in out and "REALKEY" not in out and "zzzzzzzz" not in out


async def test_fallback_validation(router):
    from openacm.core.model_routes import RouteError

    with pytest.raises(RouteError):
        await router.routes.set_fallbacks([{"provider": "nope", "model": "x"}])
    with pytest.raises(RouteError):
        await router.routes.set_fallbacks([{"provider": "openai", "model": ""}] * 0 + [{"provider": "openai", "model": str(i)} for i in range(6)])
    assert await router.routes.set_fallbacks([]) == []


@pytest.mark.parametrize("raw,leak", [
    ("Incorrect API key provided: gsk_abcdefgh12345678", "gsk_abcdefgh12345678"),
    ("bad key AIzaSyA1234567890abcdefghijkl", "AIzaSyA1234567890"),
    ("GET https://api.x.com/v1?key=SUPERSECRETVALUE&alt=json failed", "SUPERSECRETVALUE"),
    ("POST https://user:hunter2pass@host/v1 failed", "hunter2pass"),
    ("x-api-key: abcd1234efgh5678", "abcd1234efgh5678"),
    ("token=abcdefghijklmnopqrstuvwxyz0123456789ABCD", "abcdefghijklmnop"),
])
def test_scrub_covers_common_key_formats(raw, leak):
    assert leak not in scrub_error(raw)


def test_scrub_removes_the_real_configured_keys(monkeypatch):
    monkeypatch.setenv("MYPROVIDER_API_KEY", "plainlooking-value-9")
    assert "plainlooking-value-9" not in scrub_error("auth failed for plainlooking-value-9 on host")
