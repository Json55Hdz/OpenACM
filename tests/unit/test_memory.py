"""
Tests for openacm.core.memory.MemoryManager

Covers:
  - _content_for_db: string, multimodal list, non-string passthrough
  - _estimate_tokens: empty list, string content, tool_calls overhead
  - add_message + get_messages: cache population and retrieval
  - clear: removes entry from in-memory cache
  - get_or_create: inserts system prompt and restores from DB
"""

import json
import pytest
import pytest_asyncio

from openacm.core.memory import MemoryManager


# ---------------------------------------------------------------------------
# Static helpers — no DB needed
# ---------------------------------------------------------------------------

class TestContentForDb:
    def test_plain_string_returned_as_is(self):
        assert MemoryManager._content_for_db("hello") == "hello"

    def test_text_parts_joined(self):
        content = [{"type": "text", "text": "foo"}, {"type": "text", "text": "bar"}]
        result = MemoryManager._content_for_db(content)
        assert "foo" in result
        assert "bar" in result

    def test_image_with_file_id_replaced(self):
        content = [{"type": "image_url", "_file_id": "shot.png"}]
        result = MemoryManager._content_for_db(content)
        assert "[IMAGE:shot.png]" in result
        assert "data:" not in result

    def test_image_without_file_id_uses_fallback(self):
        content = [{"type": "image_url"}]
        result = MemoryManager._content_for_db(content)
        assert "[📎 image]" in result

    def test_empty_text_parts_skipped(self):
        content = [{"type": "text", "text": "  "}, {"type": "text", "text": "kept"}]
        result = MemoryManager._content_for_db(content)
        assert "kept" in result

    def test_non_string_non_list_converted(self):
        assert MemoryManager._content_for_db(42) == "42"

    def test_empty_list_returns_empty_string(self):
        assert MemoryManager._content_for_db([]) == ""


class TestEstimateTokens:
    def test_empty_list(self):
        assert MemoryManager._estimate_tokens([]) == 0

    def test_string_content(self):
        msgs = [{"role": "user", "content": "a" * 300}]
        assert MemoryManager._estimate_tokens(msgs) == 100  # 300 // 3

    def test_list_content_text_parts(self):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "a" * 300}]}]
        assert MemoryManager._estimate_tokens(msgs) == 100

    def test_tool_calls_add_tokens(self):
        tool_calls = [{"id": "c1", "function": {"name": "run", "arguments": "{}"}}]
        msgs = [{"role": "assistant", "content": "", "tool_calls": tool_calls}]
        tokens = MemoryManager._estimate_tokens(msgs)
        expected = len(json.dumps(tool_calls)) // 3
        assert tokens >= expected

    def test_multiple_messages_summed(self):
        msgs = [
            {"role": "user", "content": "a" * 60},
            {"role": "assistant", "content": "b" * 60},
        ]
        assert MemoryManager._estimate_tokens(msgs) == 40  # (60+60) // 3


# ---------------------------------------------------------------------------
# Instance methods — requires db fixture
# ---------------------------------------------------------------------------

class TestAddAndGet:
    async def test_add_and_retrieve_single_message(self, db, app_config):
        mem = MemoryManager(database=db, config=app_config.assistant)
        await mem.add_message("u1", "web", "user", "Hello")
        msgs = await mem.get_messages("u1", "web")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Hello"

    async def test_multiple_messages_in_order(self, db, app_config):
        mem = MemoryManager(database=db, config=app_config.assistant)
        for text in ("first", "second", "third"):
            await mem.add_message("u1", "web", "user", text)
        msgs = await mem.get_messages("u1", "web")
        assert [m["content"] for m in msgs] == ["first", "second", "third"]

    async def test_role_preserved(self, db, app_config):
        mem = MemoryManager(database=db, config=app_config.assistant)
        await mem.add_message("u1", "web", "assistant", "Hi there")
        msgs = await mem.get_messages("u1", "web")
        assert msgs[0]["role"] == "assistant"

    async def test_tool_calls_attached(self, db, app_config):
        mem = MemoryManager(database=db, config=app_config.assistant)
        tc = [{"id": "c1", "function": {"name": "run", "arguments": "{}"}}]
        await mem.add_message("u1", "web", "assistant", "", tool_calls=tc)
        msgs = await mem.get_messages("u1", "web")
        assert msgs[0]["tool_calls"] == tc

    async def test_empty_channel_returns_empty_list(self, db, app_config):
        mem = MemoryManager(database=db, config=app_config.assistant)
        msgs = await mem.get_messages("nobody", "nowhere")
        assert msgs == []

    async def test_channels_isolated(self, db, app_config):
        mem = MemoryManager(database=db, config=app_config.assistant)
        await mem.add_message("u1", "web", "user", "web msg")
        await mem.add_message("u1", "telegram", "user", "tg msg")
        assert len(await mem.get_messages("u1", "web")) == 1
        assert len(await mem.get_messages("u1", "telegram")) == 1

    async def test_users_isolated(self, db, app_config):
        mem = MemoryManager(database=db, config=app_config.assistant)
        await mem.add_message("alice", "web", "user", "alice")
        await mem.add_message("bob", "web", "user", "bob")
        assert (await mem.get_messages("alice", "web"))[0]["content"] == "alice"
        assert (await mem.get_messages("bob", "web"))[0]["content"] == "bob"


class TestClear:
    async def test_clear_removes_cache_entry(self, db, app_config):
        mem = MemoryManager(database=db, config=app_config.assistant)
        await mem.add_message("u1", "web", "user", "Hello")
        await mem.clear("u1", "web")
        key = mem._key("u1", "web")
        assert key not in mem._cache

    async def test_clear_nonexistent_is_safe(self, db, app_config):
        mem = MemoryManager(database=db, config=app_config.assistant)
        await mem.clear("ghost", "void")  # must not raise


class TestGetOrCreate:
    async def test_creates_with_system_prompt(self, db, app_config):
        mem = MemoryManager(database=db, config=app_config.assistant)
        msgs = await mem.get_or_create("u1", "web", "You are a test bot.")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are a test bot."

    async def test_refreshes_system_prompt_on_second_call(self, db, app_config):
        mem = MemoryManager(database=db, config=app_config.assistant)
        await mem.get_or_create("u1", "web", "old prompt")
        msgs = await mem.get_or_create("u1", "web", "new prompt")
        assert msgs[0]["content"] == "new prompt"
