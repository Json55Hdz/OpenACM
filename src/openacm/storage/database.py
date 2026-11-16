"""
SQLite database for OpenACM.

Stores conversation logs, tool execution logs, and usage statistics.
Uses aiosqlite for async operations.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from openacm.constants import TRUNCATE_DB_OUTPUT_CHARS, TRUNCATE_DB_ERROR_CHARS
from openacm.utils.text import truncate
from openacm.storage.database_agents import AgentsMixin
from openacm.storage.database_migrations import MigrationsMixin
from openacm.storage.database_skills_stats import SkillsStatsMixin
from openacm.storage.database_llm_monitor import LlmMonitorMixin
from openacm.storage.database_swarms import SwarmsMixin
from openacm.storage.database_watchers import WatchersMixin

log = structlog.get_logger()


class Database(MigrationsMixin, SwarmsMixin, AgentsMixin, WatchersMixin, SkillsStatsMixin, LlmMonitorMixin):
    """Async SQLite database wrapper."""

    def __init__(self, db_path: str, encryptor: Any = None):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._enc = encryptor  # ActivityEncryptor | None

    # ─── Encryption helpers ───────────────────────────────────

    def _e(self, value: str) -> str:
        """Encrypt value if encryptor is configured, else return as-is."""
        return self._enc.encrypt(value) if self._enc else value

    def _d(self, value: str) -> str:
        """Decrypt value if encryptor is configured, else return as-is."""
        return self._enc.decrypt(value) if self._enc else value

    def _decrypt_activity(self, row: dict) -> dict:
        """Decrypt sensitive fields in an app_activity row."""
        if not self._enc:
            return row
        return {
            **row,
            "app_name":     self._d(row.get("app_name", "")),
            "window_title": self._d(row.get("window_title", "")),
            "process_name": self._d(row.get("process_name", "")),
            "project_name": self._d(row.get("project_name", "")) if row.get("project_name") else "",
        }

    def _decrypt_routine(self, row: dict) -> dict:
        """Decrypt sensitive fields in a detected_routine row."""
        if not self._enc:
            return row
        return {
            **row,
            "name":         self._d(row.get("name", "")),
            "description":  self._d(row.get("description", "")),
            "apps":         self._d(row.get("apps", "[]")),
            "trigger_data": self._d(row.get("trigger_data", "{}")),
        }

    async def initialize(self):
        """Create database and tables if they don't exist."""
        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        # WAL mode allows concurrent readers + 1 writer without blocking.
        # busy_timeout makes SQLite retry for up to 10s instead of failing instantly.
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=10000")
        await self._db.execute("PRAGMA foreign_keys = ON")

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

            CREATE TABLE IF NOT EXISTS llm_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT,
                role TEXT,
                error_class TEXT,
                message TEXT,
                failover_to TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_llm_errors_timestamp
                ON llm_errors(timestamp);

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

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                system_prompt TEXT NOT NULL,
                allowed_tools TEXT DEFAULT 'all',
                is_active INTEGER DEFAULT 1,
                webhook_secret TEXT NOT NULL,
                telegram_token TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_agents_active ON agents(is_active);
        """)
        await self._db.commit()

        await self._run_migrations()
        log.info("Database initialized", path=self.db_path)

    # ─── Messages ─────────────────────────────────────────────

    async def log_message(
        self,
        user_id: str,
        channel_id: str,
        role: str,
        content: str,
        timestamp: str | None = None,
        extra: dict | None = None,
    ):
        """Log a conversation message (content encrypted at rest if encryptor configured).

        `extra` holds what the text alone cannot: the tool calls an assistant message made, or
        which call a tool result answers. It is stored encrypted like the content.
        """
        if not self._db:
            return
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        extra_data = self._e(json.dumps(extra)) if extra else None
        await self._db.execute(
            "INSERT INTO messages (user_id, channel_id, role, content, timestamp, extra_data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, channel_id, role, self._e(content), ts, extra_data),
        )
        await self._db.commit()

    async def get_conversation(
        self, user_id: str, channel_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get conversation history (content decrypted on read)."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT role, content, timestamp, extra_data FROM messages "
            "WHERE user_id = ? AND channel_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, channel_id, limit),
        )
        rows = await cursor.fetchall()
        result = []
        for row in reversed(rows):
            r = dict(row)
            try:
                r["content"] = self._d(r["content"])
            except Exception:
                pass  # leave as-is if decryption fails (e.g. pre-encryption rows)
            raw_extra = r.pop("extra_data", None)
            if raw_extra:
                try:
                    r["extra"] = json.loads(self._d(raw_extra))
                except Exception:
                    pass  # unreadable structure: the message is still usable as plain text
            result.append(r)
        return result

    async def get_last_message_timestamp(self, user_id: str, channel_id: str) -> str | None:
        """Timestamp (ISO string) of the most recent message in this conversation, if any."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT timestamp FROM messages WHERE user_id = ? AND channel_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (user_id, channel_id),
        )
        row = await cursor.fetchone()
        return row["timestamp"] if row else None

    async def get_customer_name(self, user_id: str, channel_id: str) -> str | None:
        """The customer's name for this conversation, if one has been saved."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT name FROM customer_names WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )
        row = await cursor.fetchone()
        return row["name"] if row else None

    async def set_customer_name(self, user_id: str, channel_id: str, name: str) -> None:
        """Save (or overwrite) the customer's name for this conversation."""
        if not self._db:
            return
        await self._db.execute(
            "INSERT INTO customer_names (user_id, channel_id, name, updated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id, channel_id) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at",
            (user_id, channel_id, name),
        )
        await self._db.commit()

    @property
    def messages_encrypted(self) -> bool:
        """True if message content is being encrypted at rest."""
        return self._enc is not None

    async def delete_conversation_messages(self, user_id: str, channel_id: str) -> int:
        """Delete all messages for a user/channel pair from the database.
        Returns the number of rows deleted."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "DELETE FROM messages WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )
        await self._db.commit()
        return cursor.rowcount or 0

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

    # ─── Settings ─────────────────────────────────────────────

    async def get_setting(self, key: str) -> str | None:
        """Get a setting value by key."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        """Set a setting value (upsert)."""
        if not self._db:
            return
        await self._db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (key, value),
        )
        await self._db.commit()

    async def get_all_settings(self) -> dict[str, str]:
        """Get all settings as a dict."""
        if not self._db:
            return {}
        cursor = await self._db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}

    # ─── Plugin state (Phase 1 plugin dashboard) ───────────────

    async def is_plugin_enabled(self, name: str) -> bool:
        """A plugin with no row is enabled by default."""
        if not self._db:
            return True
        cursor = await self._db.execute(
            "SELECT enabled FROM plugin_state WHERE plugin_name = ?", (name,)
        )
        row = await cursor.fetchone()
        return bool(row["enabled"]) if row else True

    async def set_plugin_enabled(self, name: str, enabled: bool) -> None:
        if not self._db:
            return
        await self._db.execute(
            "INSERT INTO plugin_state (plugin_name, enabled) VALUES (?, ?) "
            "ON CONFLICT(plugin_name) DO UPDATE SET enabled = excluded.enabled",
            (name, int(enabled)),
        )
        await self._db.commit()

    async def get_plugin_config(self, name: str) -> dict:
        if not self._db:
            return {}
        cursor = await self._db.execute(
            "SELECT config_json FROM plugin_state WHERE plugin_name = ?", (name,)
        )
        row = await cursor.fetchone()
        if not row:
            return {}
        import json
        return json.loads(row["config_json"])

    async def set_plugin_config(self, name: str, config: dict) -> None:
        if not self._db:
            return
        import json
        await self._db.execute(
            "INSERT INTO plugin_state (plugin_name, config_json) VALUES (?, ?) "
            "ON CONFLICT(plugin_name) DO UPDATE SET config_json = excluded.config_json",
            (name, json.dumps(config)),
        )
        await self._db.commit()

    async def get_all_plugin_states(self) -> dict[str, dict]:
        if not self._db:
            return {}
        import json
        cursor = await self._db.execute(
            "SELECT plugin_name, enabled, config_json FROM plugin_state"
        )
        rows = await cursor.fetchall()
        return {
            row["plugin_name"]: {
                "enabled": bool(row["enabled"]),
                "config": json.loads(row["config_json"]),
            }
            for row in rows
        }

    # ─── Workflow Tracking ────────────────────────────────────────────────────

    async def insert_workflow_execution(
        self,
        user_id: str,
        channel_id: str,
        user_message: str,
        tool_sequence_raw: str,
        tool_sequence_clean: str,
        tool_args_hash: str,
        turn_timestamp: str,
    ) -> int:
        """Insert a workflow execution record and return its id."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO workflow_executions "
            "(user_id, channel_id, user_message, tool_sequence_raw, tool_sequence_clean, tool_args_hash, turn_timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, channel_id, user_message, tool_sequence_raw, tool_sequence_clean, tool_args_hash, turn_timestamp),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def update_workflow_intent_summary(self, execution_id: int, intent_summary: str) -> None:
        """Update the intent_summary field of a workflow_execution row."""
        if not self._db:
            return
        await self._db.execute(
            "UPDATE workflow_executions SET intent_summary = ? WHERE id = ?",
            (intent_summary, execution_id),
        )
        await self._db.commit()

    async def get_recent_workflow_executions(
        self, user_id: str, channel_id: str, limit: int = 30
    ) -> list[dict[str, Any]]:
        """Get the most recent workflow executions for a user/channel."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM workflow_executions "
            "WHERE user_id = ? AND channel_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, channel_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def count_workflow_hash(self, user_id: str, tool_args_hash: str) -> int:
        """Count how many times a specific tool sequence hash appears for a user."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM workflow_executions "
            "WHERE user_id = ? AND tool_args_hash = ?",
            (user_id, tool_args_hash),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def get_workflow_executions_by_hash(
        self, user_id: str, tool_args_hash: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get workflow executions matching a specific hash."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM workflow_executions "
            "WHERE user_id = ? AND tool_args_hash = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, tool_args_hash, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def count_user_workflow_turns(self, user_id: str) -> int:
        """Count total workflow execution records for a user."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM workflow_executions WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def insert_workflow_suggestion(
        self,
        user_id: str,
        channel_id: str,
        trigger_count: int,
        representative_ids_json: str,
        suggested_at: str,
    ) -> int:
        """Insert a workflow suggestion record and return its id."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO workflow_suggestions "
            "(user_id, channel_id, trigger_count, representative_ids, suggested_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, channel_id, trigger_count, representative_ids_json, suggested_at),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_pending_suggestion(self, user_id: str, channel_id: str) -> dict[str, Any] | None:
        """Get the latest pending suggestion for a user/channel."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM workflow_suggestions "
            "WHERE user_id = ? AND channel_id = ? AND status = 'pending' "
            "ORDER BY id DESC LIMIT 1",
            (user_id, channel_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_pending_suggestion_by_id(self, suggestion_id: int) -> dict[str, Any] | None:
        """Get a workflow suggestion by its id."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM workflow_suggestions WHERE id = ? LIMIT 1",
            (suggestion_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_suggestion_status(
        self,
        suggestion_id: int,
        status: str,
        responded_at: str | None = None,
        created_tool_name: str | None = None,
    ) -> None:
        """Update the status (and optional fields) of a workflow suggestion."""
        if not self._db:
            return
        await self._db.execute(
            "UPDATE workflow_suggestions "
            "SET status = ?, responded_at = ?, created_tool_name = ? "
            "WHERE id = ?",
            (status, responded_at, created_tool_name, suggestion_id),
        )
        await self._db.commit()

    async def get_last_suggestion(self, user_id: str, channel_id: str) -> dict[str, Any] | None:
        """Get the most recent suggestion for a user/channel (any status) for cooldown checks."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM workflow_suggestions "
            "WHERE user_id = ? AND channel_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (user_id, channel_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_dismissed_workflow_hashes(self, user_id: str, since_iso: str) -> set[str]:
        """Workflow patterns this user answered 'no' to since the given moment."""
        if not self._db:
            return set()
        cursor = await self._db.execute(
            "SELECT DISTINCT e.tool_args_hash FROM workflow_suggestions s "
            "JOIN json_each(s.representative_ids) r "
            "JOIN workflow_executions e ON e.id = r.value "
            "WHERE s.user_id = ? AND s.status = 'dismissed' AND s.responded_at >= ?",
            (user_id, since_iso),
        )
        return {row[0] for row in await cursor.fetchall()}

    async def get_workflow_executions_by_ids(self, ids: list[int]) -> list[dict[str, Any]]:
        """Fetch workflow executions by a list of ids."""
        if not self._db or not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        cursor = await self._db.execute(
            f"SELECT * FROM workflow_executions WHERE id IN ({placeholders})",
            ids,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def count_turns_since_execution_id(
        self, user_id: str, channel_id: str, since_id: int
    ) -> int:
        """Count workflow executions for a user/channel with id > since_id."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM workflow_executions "
            "WHERE user_id = ? AND channel_id = ? AND id > ?",
            (user_id, channel_id, since_id),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    # ─── Content Queue ────────────────────────────────────────

    async def create_content_item(
        self,
        platform: str,
        content_type: str,
        title: str,
        body: str,
        media_paths: str = "[]",
        metadata: str = "{}",
        swarm_id: int | None = None,
    ) -> int:
        if not self._db:
            return 0
        ts = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "INSERT INTO content_queue "
            "(platform, content_type, title, body, media_paths, metadata, status, swarm_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (platform, content_type, title, body, media_paths, metadata, swarm_id, ts, ts),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_content_queue(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if not self._db:
            return []
        if status:
            cursor = await self._db.execute(
                "SELECT * FROM content_queue WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM content_queue ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_content_item(self, item_id: int) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM content_queue WHERE id = ?", (item_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_content_status(self, item_id: int, status: str, extra: dict | None = None) -> bool:
        if not self._db:
            return False
        ts = datetime.now(timezone.utc).isoformat()
        field_map = {
            "approved": "approved_at",
            "rejected": "rejected_at",
            "published": "published_at",
        }
        updates = ["status = ?", "updated_at = ?"]
        params: list = [status, ts]
        if status in field_map:
            updates.append(f"{field_map[status]} = ?")
            params.append(ts)
        if extra and "publish_error" in extra:
            updates.append("publish_error = ?")
            params.append(extra["publish_error"])
        params.append(item_id)
        await self._db.execute(
            f"UPDATE content_queue SET {', '.join(updates)} WHERE id = ?", params
        )
        await self._db.commit()
        return True

    async def delete_content_item(self, item_id: int) -> bool:
        if not self._db:
            return False
        cursor = await self._db.execute("DELETE FROM content_queue WHERE id = ?", (item_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def count_pending_content(self) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM content_queue WHERE status = 'pending'"
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    # ─── Social Credentials ───────────────────────────────────

    async def get_social_credentials(self, platform: str) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM social_credentials WHERE platform = ? AND is_active = 1",
            (platform,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_social_credentials(self) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT id, platform, is_active, verified_at, created_at, updated_at "
            "FROM social_credentials ORDER BY platform"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def save_social_credentials(self, platform: str, credentials: str, verified: bool = False) -> bool:
        if not self._db:
            return False
        ts = datetime.now(timezone.utc).isoformat()
        verified_at = ts if verified else None
        await self._db.execute(
            "INSERT INTO social_credentials (platform, credentials, is_active, verified_at, created_at, updated_at) "
            "VALUES (?, ?, 1, ?, ?, ?) "
            "ON CONFLICT(platform) DO UPDATE SET credentials = excluded.credentials, "
            "is_active = 1, verified_at = excluded.verified_at, updated_at = excluded.updated_at",
            (platform, credentials, verified_at, ts, ts),
        )
        await self._db.commit()
        return True

    async def delete_social_credentials(self, platform: str) -> bool:
        if not self._db:
            return False
        cursor = await self._db.execute(
            "DELETE FROM social_credentials WHERE platform = ?", (platform,)
        )
        await self._db.commit()
        return cursor.rowcount > 0
