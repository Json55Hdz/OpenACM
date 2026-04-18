"""
Tests for openacm.storage.database

All tests use an in-memory SQLite database (:memory:) via the `db` fixture
from conftest.py — no files created, no cleanup needed.

Covers:
  - Schema initialization
  - Message CRUD (add, get, delete)
  - Tool execution logging
  - LLM usage logging
  - Output truncation constants applied correctly
"""

import pytest
from openacm.constants import TRUNCATE_DB_OUTPUT_CHARS, TRUNCATE_DB_ERROR_CHARS


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestDatabaseInit:
    async def test_initializes_without_error(self, db):
        """If the fixture resolved, initialization worked."""
        assert db._db is not None

    async def test_messages_table_exists(self, db):
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        row = await cursor.fetchone()
        assert row is not None, "messages table should exist after initialize()"

    async def test_tool_executions_table_exists(self, db):
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_executions'"
        )
        row = await cursor.fetchone()
        assert row is not None

    async def test_llm_usage_table_exists(self, db):
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='llm_usage'"
        )
        row = await cursor.fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class TestMessages:
    async def test_add_and_retrieve_user_message(self, db):
        await db.log_message(
            user_id="u1", channel_id="web",
            role="user", content="Hello",
            timestamp="2024-01-01T00:00:00",
        )
        msgs = await db.get_conversation("u1", "web", limit=10)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello"

    async def test_add_multiple_messages_returned_in_order(self, db):
        for i in range(3):
            await db.log_message(
                user_id="u1", channel_id="web",
                role="user", content=f"msg {i}",
                timestamp=f"2024-01-01T00:00:0{i}",
            )
        msgs = await db.get_conversation("u1", "web", limit=10)
        assert len(msgs) == 3
        assert msgs[0]["content"] == "msg 0"
        assert msgs[2]["content"] == "msg 2"

    async def test_limit_is_respected(self, db):
        for i in range(5):
            await db.log_message(
                user_id="u1", channel_id="web",
                role="user", content=f"msg {i}",
                timestamp=f"2024-01-01T00:00:0{i}",
            )
        msgs = await db.get_conversation("u1", "web", limit=3)
        assert len(msgs) == 3

    async def test_messages_are_channel_scoped(self, db):
        await db.log_message(
            user_id="u1", channel_id="web",
            role="user", content="web msg",
            timestamp="2024-01-01T00:00:00",
        )
        await db.log_message(
            user_id="u1", channel_id="telegram",
            role="user", content="telegram msg",
            timestamp="2024-01-01T00:00:01",
        )
        web_msgs = await db.get_conversation("u1", "web", limit=10)
        tg_msgs = await db.get_conversation("u1", "telegram", limit=10)
        assert len(web_msgs) == 1
        assert len(tg_msgs) == 1
        assert web_msgs[0]["content"] == "web msg"
        assert tg_msgs[0]["content"] == "telegram msg"

    async def test_delete_conversation(self, db):
        await db.log_message(
            user_id="u1", channel_id="web",
            role="user", content="to delete",
            timestamp="2024-01-01T00:00:00",
        )
        await db.delete_conversation_messages("u1", "web")
        msgs = await db.get_conversation("u1", "web", limit=10)
        assert msgs == []

    async def test_different_users_are_isolated(self, db):
        await db.log_message(
            user_id="alice", channel_id="web",
            role="user", content="alice msg",
            timestamp="2024-01-01T00:00:00",
        )
        await db.log_message(
            user_id="bob", channel_id="web",
            role="user", content="bob msg",
            timestamp="2024-01-01T00:00:01",
        )
        alice_msgs = await db.get_conversation("alice", "web", limit=10)
        bob_msgs = await db.get_conversation("bob", "web", limit=10)
        assert len(alice_msgs) == 1
        assert len(bob_msgs) == 1


# ---------------------------------------------------------------------------
# Tool execution logging
# ---------------------------------------------------------------------------

class TestToolExecutionLogging:
    async def test_log_tool_execution_success(self, db):
        await db.log_tool_execution(
            user_id="u1",
            channel_id="web",
            tool_name="run_command",
            arguments='{"cmd": "ls"}',
            result="file1.txt\nfile2.txt",
            success=True,
            elapsed_ms=42,
        )
        rows = await db.get_tool_executions(limit=10)
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "run_command"
        assert rows[0]["success"] == 1

    async def test_log_tool_execution_failure(self, db):
        await db.log_tool_execution(
            user_id="u1",
            channel_id="web",
            tool_name="run_command",
            arguments='{"cmd": "bad"}',
            result="Permission denied",
            success=False,
            elapsed_ms=5,
        )
        rows = await db.get_tool_executions(limit=10)
        assert rows[0]["success"] == 0

    async def test_output_truncation_constant_matches_db_column(self, db):
        """
        Verify that TRUNCATE_DB_OUTPUT_CHARS is the right constant for the result column
        by writing exactly that many chars and confirming it's stored intact.
        """
        exact_output = "x" * TRUNCATE_DB_OUTPUT_CHARS
        await db.log_tool_execution(
            user_id="u1", channel_id="web",
            tool_name="test_tool",
            arguments="{}",
            result=exact_output,
            success=True, elapsed_ms=1,
        )
        rows = await db.get_tool_executions(limit=1)
        assert len(rows[0]["result"]) == TRUNCATE_DB_OUTPUT_CHARS


# ---------------------------------------------------------------------------
# LLM usage logging
# ---------------------------------------------------------------------------

class TestLLMUsageLogging:
    async def test_log_llm_usage(self, db):
        await db.log_llm_usage(
            model="gpt-4o",
            provider="openai",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost=0.005,
            elapsed_ms=200,
        )
        stats = await db.get_stats()
        assert stats["total_tokens"] >= 150

    async def test_multiple_usage_logs_accumulate(self, db):
        for _ in range(3):
            await db.log_llm_usage(
                model="gpt-4o",
                provider="openai",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                cost=0.001,
                elapsed_ms=50,
            )
        stats = await db.get_stats()
        assert stats["total_tokens"] >= 45
