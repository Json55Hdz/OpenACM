"""
Tests for openacm.core.llm_router — focused on the opencode_go custom-provider
HTTP path (_custom_chat) and its x-opencode-session header requirement.
"""
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


class TestNormalizeMessages:
    def test_strips_top_level_name_from_all_messages(self, event_bus):
        router = _make_router(event_bus, provider="opencode_go")
        raw_messages = [
            {"role": "system", "content": "You are Celubot", "name": "system_prompt"},
            {"role": "user", "content": "Hola", "name": "Customer_57322"},
            {
                "role": "assistant",
                "content": "Consultando...",
                "name": "assistant_bot",
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {"name": "check_catalog", "arguments": '{"query": "iphone"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_abc123",
                "content": '{"items": ["iPhone 13", "iPhone 14"]}',
                "name": "check_catalog",
            },
        ]

        normalized = router._normalize_messages(raw_messages)

        # Ensure no message contains a top-level "name" key
        for msg in normalized:
            assert "name" not in msg, f"Message with role '{msg.get('role')}' still has top-level 'name'"

        # Verify tool message is retained with tool_call_id and content
        tool_msgs = [m for m in normalized if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "call_abc123"
        assert 'iPhone 13' in tool_msgs[0]["content"]

        # Verify assistant tool_calls function name is intact
        assistant_msgs = [m for m in normalized if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["tool_calls"][0]["function"]["name"] == "check_catalog"


class TestRetryLogic:
    async def test_retries_on_429_rate_limit(self, event_bus, monkeypatch):
        router = _make_router(event_bus, provider="opencode_go")

        attempts = 0

        async def fake_chat_attempt(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                import httpx
                resp = httpx.Response(429, headers={"retry-after": "0.01"})
                req = httpx.Request("POST", "https://opencode.ai/zen/go/v1/chat/completions")
                raise httpx.HTTPStatusError("Server error '429' for url", request=req, response=resp)
            return {"content": "recovered from rate limit", "tool_calls": []}

        monkeypatch.setattr(router, "_chat_attempt", fake_chat_attempt)

        res = await router.chat(messages=[{"role": "user", "content": "hi"}], max_retries=3)
        assert attempts == 2
        assert res["content"] == "recovered from rate limit"

    async def test_does_not_retry_on_400_bad_request(self, event_bus, monkeypatch):
        import pytest
        router = _make_router(event_bus, provider="opencode_go")

        attempts = 0

        async def fake_chat_attempt(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            import httpx
            resp = httpx.Response(400)
            req = httpx.Request("POST", "https://opencode.ai/zen/go/v1/chat/completions")
            raise httpx.HTTPStatusError("Server error '400' for url", request=req, response=resp)

        monkeypatch.setattr(router, "_chat_attempt", fake_chat_attempt)

        with pytest.raises(Exception) as exc_info:
            await router.chat(messages=[{"role": "user", "content": "hi"}], max_retries=3)
        assert attempts == 1
        assert "400" in str(exc_info.value)


