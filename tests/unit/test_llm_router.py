"""
Tests for openacm.core.llm_router — focused on the opencode_go custom-provider
HTTP path (_custom_chat) and its x-opencode-session header requirement.
"""
import pytest

from openacm.core.config import LLMConfig
from openacm.core.llm_router import LLMRouter


def _make_router(event_bus, provider="opencode_go"):
    config = LLMConfig(
        default_provider=provider,
        providers={
            provider: {
                "base_url": "https://opencode.ai/zen/go/v1",
                "default_model": "kimi-k2.5",
            }
        },
    )
    return LLMRouter(config, event_bus)


class _FakeStreamResponse:
    status_code = 200

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}'
        yield "data: [DONE]"

    async def aread(self):
        return b""


class _FakeStreamCtx:
    async def __aenter__(self):
        return _FakeStreamResponse()

    async def __aexit__(self, *exc):
        return False


class _FakeAsyncClient:
    """Captures the headers/url/json passed to .stream() for assertions."""

    last_call: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, headers=None, json=None, timeout=None):
        _FakeAsyncClient.last_call = {
            "method": method,
            "url": url,
            "headers": headers,
            "json": json,
        }
        return _FakeStreamCtx()


class TestOpenCodeSessionHeader:
    async def test_sends_x_opencode_session_header_for_opencode_go(self, event_bus, monkeypatch):
        monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)
        router = _make_router(event_bus, provider="opencode_go")

        await router._custom_chat(messages=[{"role": "user", "content": "hi"}])

        headers = _FakeAsyncClient.last_call["headers"]
        assert "x-opencode-session" in headers
        assert headers["x-opencode-session"]  # non-empty

    async def test_session_id_stable_across_calls_without_stream_context(self, event_bus, monkeypatch):
        monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)
        router = _make_router(event_bus, provider="opencode_go")

        await router._custom_chat(messages=[{"role": "user", "content": "hi"}])
        first_session = _FakeAsyncClient.last_call["headers"]["x-opencode-session"]

        await router._custom_chat(messages=[{"role": "user", "content": "again"}])
        second_session = _FakeAsyncClient.last_call["headers"]["x-opencode-session"]

        assert first_session == second_session

    async def test_uses_active_channel_id_as_session_when_available(self, event_bus, monkeypatch):
        monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)
        router = _make_router(event_bus, provider="opencode_go")
        router._active_stream_ctx = ("user-1", "channel-42", "web")

        await router._custom_chat(messages=[{"role": "user", "content": "hi"}])

        headers = _FakeAsyncClient.last_call["headers"]
        assert headers["x-opencode-session"] == "channel-42"

    async def test_does_not_send_header_for_other_custom_providers(self, event_bus, monkeypatch):
        monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)
        router = _make_router(event_bus, provider="openrouter")

        await router._custom_chat(messages=[{"role": "user", "content": "hi"}])

        headers = _FakeAsyncClient.last_call["headers"]
        assert "x-opencode-session" not in headers
