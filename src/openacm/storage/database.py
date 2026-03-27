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

            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                is_active INTEGER DEFAULT 1,
                is_builtin INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_skills_category 
                ON skills(category);
            CREATE INDEX IF NOT EXISTS idx_skills_active 
                ON skills(is_active);
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
            "SELECT COUNT(*) as cnt FROM messages WHERE timestamp > datetime('now', 'start of day')"
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

    # ─── Skills ───────────────────────────────────────────────

    async def create_skill(
        self,
        name: str,
        description: str,
        content: str,
        category: str = "general",
        is_builtin: bool = False,
    ) -> int:
        """Create a new skill."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO skills (name, description, content, category, is_builtin) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, description, content, category, int(is_builtin)),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_skill(self, skill_id: int) -> dict[str, Any] | None:
        """Get a skill by ID."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM skills WHERE id = ?",
            (skill_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_skill_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a skill by name."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM skills WHERE name = ?",
            (name,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_skills(self, active_only: bool = False) -> list[dict[str, Any]]:
        """Get all skills."""
        if not self._db:
            return []
        query = "SELECT * FROM skills"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY category, name"
        cursor = await self._db.execute(query)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_skill(
        self,
        skill_id: int,
        description: str | None = None,
        content: str | None = None,
        category: str | None = None,
        is_active: bool | None = None,
    ) -> bool:
        """Update a skill."""
        if not self._db:
            return False
        updates = []
        params = []
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if category is not None:
            updates.append("category = ?")
            params.append(category)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(int(is_active))
        if not updates:
            return False
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(skill_id)
        await self._db.execute(
            f"UPDATE skills SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await self._db.commit()
        return True

    async def delete_skill(self, skill_id: int) -> bool:
        """Delete a skill (only non-built-in)."""
        if not self._db:
            return False
        cursor = await self._db.execute(
            "DELETE FROM skills WHERE id = ? AND is_builtin = 0",
            (skill_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def toggle_skill(self, skill_id: int) -> bool:
        """Toggle skill active status."""
        if not self._db:
            return False
        await self._db.execute(
            "UPDATE skills SET is_active = NOT is_active, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (skill_id,),
        )
        await self._db.commit()
        return True
