"""
SQLite database for OpenACM.

Stores conversation logs, tool execution logs, and usage statistics.
Uses aiosqlite for async operations.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

log = structlog.get_logger()


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self):
        """Create database and tables if they don't exist."""
        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tool_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                arguments TEXT,
                result TEXT,
                success INTEGER DEFAULT 1,
                elapsed_ms INTEGER DEFAULT 0,
                timestamp TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                provider TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cost REAL DEFAULT 0.0,
                elapsed_ms INTEGER DEFAULT 0,
                timestamp TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_messages_user_channel 
                ON messages(user_id, channel_id);
            CREATE INDEX IF NOT EXISTS idx_messages_timestamp 
                ON messages(timestamp);
            CREATE INDEX IF NOT EXISTS idx_tool_executions_timestamp 
                ON tool_executions(timestamp);
            CREATE INDEX IF NOT EXISTS idx_llm_usage_timestamp 
                ON llm_usage(timestamp);
        """)
        await self._db.commit()
        log.info("Database initialized", path=self.db_path)

    async def close(self):
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ─── Messages ─────────────────────────────────────────────

    async def log_message(
        self,
        user_id: str,
        channel_id: str,
        role: str,
        content: str,
        timestamp: str | None = None,
    ):
        """Log a conversation message."""
        if not self._db:
            return
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO messages (user_id, channel_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, channel_id, role, content, ts),
        )
        await self._db.commit()

    async def get_conversation(
        self, user_id: str, channel_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get conversation history."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT role, content, timestamp FROM messages "
            "WHERE user_id = ? AND channel_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, channel_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in reversed(rows)]

    # ─── Tool Executions ──────────────────────────────────────

    async def log_tool_execution(
        self,
        user_id: str,
        channel_id: str,
        tool_name: str,
        arguments: str,
        result: str,
        success: bool = True,
        elapsed_ms: int = 0,
    ):
        """Log a tool execution."""
        if not self._db:
            return
        ts = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO tool_executions "
            "(user_id, channel_id, tool_name, arguments, result, success, elapsed_ms, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, channel_id, tool_name, arguments, result, int(success), elapsed_ms, ts),
        )
        await self._db.commit()

    async def get_tool_executions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent tool executions."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM tool_executions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ─── LLM Usage ────────────────────────────────────────────

    async def log_llm_usage(
        self,
        model: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost: float = 0.0,
        elapsed_ms: int = 0,
    ):
        """Log LLM API usage."""
        if not self._db:
            return
        ts = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO llm_usage "
            "(model, provider, prompt_tokens, completion_tokens, total_tokens, cost, elapsed_ms, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (model, provider, prompt_tokens, completion_tokens, total_tokens, cost, elapsed_ms, ts),
        )
        await self._db.commit()

    # ─── Statistics ───────────────────────────────────────────

    async def get_stats(self) -> dict[str, Any]:
        """Get overall usage statistics."""
        if not self._db:
            return {}

        stats = {}

        # Total messages
        cursor = await self._db.execute("SELECT COUNT(*) as cnt FROM messages")
        row = await cursor.fetchone()
        stats["total_messages"] = row["cnt"] if row else 0

        # Total tokens
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) as total FROM llm_usage"
        )
        row = await cursor.fetchone()
        stats["total_tokens"] = row["total"] if row else 0

        # Total tool calls
        cursor = await self._db.execute("SELECT COUNT(*) as cnt FROM tool_executions")
        row = await cursor.fetchone()
        stats["total_tool_calls"] = row["cnt"] if row else 0

        # Active conversations (distinct user/channel pairs with messages in last 24h)
        cursor = await self._db.execute(
            "SELECT COUNT(DISTINCT user_id || ':' || channel_id) as cnt "
            "FROM messages WHERE timestamp > datetime('now', '-1 day')"
        )
        row = await cursor.fetchone()
        stats["active_conversations"] = row["cnt"] if row else 0

        # Messages today
        cursor = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM messages "
            "WHERE timestamp > datetime('now', 'start of day')"
        )
        row = await cursor.fetchone()
        stats["messages_today"] = row["cnt"] if row else 0

        # Tokens today
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) as total FROM llm_usage "
            "WHERE timestamp > datetime('now', 'start of day')"
        )
        row = await cursor.fetchone()
        stats["tokens_today"] = row["total"] if row else 0

        return stats

    async def get_usage_history(self, days: int = 30) -> list[dict[str, Any]]:
        """Get daily usage stats for the last N days."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT DATE(timestamp) as date, "
            "COUNT(*) as requests, "
            "SUM(total_tokens) as tokens, "
            "SUM(cost) as cost "
            "FROM llm_usage "
            "WHERE timestamp > datetime('now', ? || ' days') "
            "GROUP BY DATE(timestamp) "
            "ORDER BY date",
            (f"-{days}",),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_channel_stats(self) -> list[dict[str, Any]]:
        """Get message counts and last activity grouped by user and channel."""
        if not self._db:
            return []
        
        # We use a subquery to fetch the content of the most recent message
        query = """
            SELECT 
                user_id, 
                channel_id, 
                COUNT(*) as message_count, 
                MAX(timestamp) as last_updated,
                (SELECT content FROM messages m2 
                 WHERE m2.user_id = messages.user_id AND m2.channel_id = messages.channel_id 
                 ORDER BY timestamp DESC LIMIT 1) as last_message
            FROM messages 
            GROUP BY user_id, channel_id 
            ORDER BY last_updated DESC
        """
        cursor = await self._db.execute(query)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
