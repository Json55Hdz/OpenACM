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

from openacm.constants import TRUNCATE_DB_OUTPUT_CHARS, TRUNCATE_DB_ERROR_CHARS

log = structlog.get_logger()


class Database:
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

    # ─── Migrations ───────────────────────────────────────────

    # Bump this number every time you add a new migration below.
    _SCHEMA_VERSION = 12

    async def _run_migrations(self):
        """Apply incremental schema/data migrations on startup.

        Each migration is identified by a version number stored in the
        settings table.  Migrations run in order and are idempotent —
        safe to apply multiple times even though they're guarded by the
        version check.

        HOW TO ADD A NEW MIGRATION
        ─────────────────────────
        1. Increment _SCHEMA_VERSION above.
        2. Add an `if current < N:` block at the end of this method.
        3. Put your ALTER TABLE / UPDATE / cleanup logic inside.
        """
        # Read current version (0 = brand new DB or pre-migration install)
        row = await self._db.execute(
            "SELECT value FROM settings WHERE key = 'schema_version'"
        )
        rec = await row.fetchone()
        current = int(rec["value"]) if rec else 0

        if current >= self._SCHEMA_VERSION:
            return

        log.info("Running database migrations", from_version=current, to_version=self._SCHEMA_VERSION)

        # ── Migration 1: add tool_calls / extra_data column to messages ──
        # Previously tool_calls were serialised *inside* content as JSON.
        # Now we keep them there but add an extra_data column for future use.
        if current < 1:
            try:
                await self._db.execute(
                    "ALTER TABLE messages ADD COLUMN extra_data TEXT DEFAULT NULL"
                )
            except Exception:
                pass  # column already exists on some installs

        # ── Migration 2: strip orphaned reasoning_content from messages ──
        # Kimi K2 stores reasoning_content inside the JSON content of
        # assistant messages.  When switching providers (e.g. Gemini),
        # those messages were sent as-is and caused 400 errors.
        # _normalize_messages() now strips it at runtime, but old rows can
        # also hold malformed tool_call JSON — clean them up here so
        # historical views don't show garbage.
        if current < 2:
            import json as _json
            cursor = await self._db.execute(
                "SELECT id, content FROM messages WHERE role = 'assistant'"
            )
            rows = await cursor.fetchall()
            updates = []
            for row in rows:
                try:
                    data = _json.loads(row["content"])
                    changed = False
                    # Ensure tool_calls list items have an 'id' field
                    for tc in data.get("tool_calls") or []:
                        if not tc.get("id"):
                            import uuid as _uuid
                            tc["id"] = f"call_{_uuid.uuid4().hex[:12]}"
                            changed = True
                    if changed:
                        updates.append((row["id"], _json.dumps(data)))
                except Exception:
                    pass
            for row_id, new_content in updates:
                await self._db.execute(
                    "UPDATE messages SET content = ? WHERE id = ?",
                    (new_content, row_id),
                )
            if updates:
                log.info("Migration 2: fixed tool_call ids", count=len(updates))

        # ── Migration 3: add workflow tracking tables ──────────────────────────
        if current < 3:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS workflow_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    intent_summary TEXT NOT NULL DEFAULT '',
                    tool_sequence_raw TEXT NOT NULL DEFAULT '[]',
                    tool_sequence_clean TEXT NOT NULL DEFAULT '[]',
                    tool_args_hash TEXT NOT NULL DEFAULT '',
                    turn_timestamp TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_wf_user_channel ON workflow_executions(user_id, channel_id);
                CREATE INDEX IF NOT EXISTS idx_wf_hash ON workflow_executions(user_id, tool_args_hash);
                CREATE INDEX IF NOT EXISTS idx_wf_timestamp ON workflow_executions(turn_timestamp);

                CREATE TABLE IF NOT EXISTS workflow_suggestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    trigger_count INTEGER NOT NULL DEFAULT 0,
                    representative_ids TEXT NOT NULL DEFAULT '[]',
                    suggested_at TEXT NOT NULL,
                    responded_at TEXT,
                    created_tool_name TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_ws_user_channel ON workflow_suggestions(user_id, channel_id, status);
            """)
            log.info("Migration 3: created workflow_executions and workflow_suggestions tables")

        # ── Migration 4: OS activity watcher + detected routines ──────────────
        if current < 4:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS app_activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT NOT NULL,
                    window_title TEXT NOT NULL DEFAULT '',
                    process_name TEXT NOT NULL DEFAULT '',
                    focus_seconds REAL NOT NULL DEFAULT 0,
                    session_start TEXT NOT NULL,
                    session_end TEXT NOT NULL,
                    day_of_week INTEGER NOT NULL DEFAULT 0,
                    hour_of_day INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_app_activities_app
                    ON app_activities(app_name);
                CREATE INDEX IF NOT EXISTS idx_app_activities_start
                    ON app_activities(session_start);

                CREATE TABLE IF NOT EXISTS detected_routines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    trigger_type TEXT NOT NULL DEFAULT 'manual',
                    trigger_data TEXT NOT NULL DEFAULT '{}',
                    apps TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_run TEXT,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    occurrence_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            log.info("Migration 4: created app_activities and detected_routines tables")

        # ── Migration 5: add description + chat_mentioned to detected_routines ─
        if current < 5:
            try:
                await self._db.execute(
                    "ALTER TABLE detected_routines ADD COLUMN description TEXT DEFAULT ''"
                )
            except Exception:
                pass
            try:
                await self._db.execute(
                    "ALTER TABLE detected_routines ADD COLUMN chat_mentioned INTEGER DEFAULT 0"
                )
            except Exception:
                pass
            log.info("Migration 5: added description and chat_mentioned to detected_routines")

        # ── Migration 6: cron_jobs + cron_job_runs tables ─────────────────────
        if current < 6:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS cron_jobs (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    name           TEXT    NOT NULL,
                    description    TEXT    NOT NULL DEFAULT '',
                    cron_expr      TEXT    NOT NULL,
                    action_type    TEXT    NOT NULL,
                    action_payload TEXT    NOT NULL DEFAULT '{}',
                    is_enabled     INTEGER NOT NULL DEFAULT 1,
                    last_run       TEXT,
                    next_run       TEXT,
                    run_count      INTEGER NOT NULL DEFAULT 0,
                    last_status    TEXT    NOT NULL DEFAULT 'pending',
                    last_output    TEXT,
                    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_cron_jobs_enabled  ON cron_jobs(is_enabled);
                CREATE INDEX IF NOT EXISTS idx_cron_jobs_next_run ON cron_jobs(next_run);

                CREATE TABLE IF NOT EXISTS cron_job_runs (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id       INTEGER NOT NULL REFERENCES cron_jobs(id) ON DELETE CASCADE,
                    started_at   TEXT    NOT NULL,
                    finished_at  TEXT,
                    status       TEXT    NOT NULL DEFAULT 'running',
                    output       TEXT,
                    error        TEXT,
                    triggered_by TEXT    NOT NULL DEFAULT 'scheduler'
                );
                CREATE INDEX IF NOT EXISTS idx_cron_runs_job_id  ON cron_job_runs(job_id);
                CREATE INDEX IF NOT EXISTS idx_cron_runs_started ON cron_job_runs(started_at);
            """)
            log.info("Migration 6: created cron_jobs and cron_job_runs tables")

        # ── Migration 7: swarm tables ──────────────────────────────────────────
        if current < 7:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS swarms (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT    NOT NULL,
                    goal            TEXT    NOT NULL,
                    status          TEXT    NOT NULL DEFAULT 'draft',
                    global_model    TEXT,
                    workspace_path  TEXT    NOT NULL DEFAULT '',
                    shared_context  TEXT    NOT NULL DEFAULT '',
                    context_files   TEXT    NOT NULL DEFAULT '[]',
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_swarms_status ON swarms(status);

                CREATE TABLE IF NOT EXISTS swarm_workers (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    swarm_id        INTEGER NOT NULL REFERENCES swarms(id) ON DELETE CASCADE,
                    name            TEXT    NOT NULL,
                    role            TEXT    NOT NULL DEFAULT 'worker',
                    description     TEXT    NOT NULL DEFAULT '',
                    system_prompt   TEXT    NOT NULL,
                    model           TEXT,
                    allowed_tools   TEXT    NOT NULL DEFAULT 'all',
                    status          TEXT    NOT NULL DEFAULT 'idle',
                    workspace_path  TEXT    NOT NULL DEFAULT '',
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_swarm_workers_swarm ON swarm_workers(swarm_id);

                CREATE TABLE IF NOT EXISTS swarm_tasks (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    swarm_id        INTEGER NOT NULL REFERENCES swarms(id) ON DELETE CASCADE,
                    worker_id       INTEGER REFERENCES swarm_workers(id),
                    title           TEXT    NOT NULL,
                    description     TEXT    NOT NULL,
                    depends_on      TEXT    NOT NULL DEFAULT '[]',
                    status          TEXT    NOT NULL DEFAULT 'pending',
                    result          TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_swarm_tasks_swarm  ON swarm_tasks(swarm_id);
                CREATE INDEX IF NOT EXISTS idx_swarm_tasks_worker ON swarm_tasks(worker_id);

                CREATE TABLE IF NOT EXISTS swarm_messages (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    swarm_id        INTEGER NOT NULL REFERENCES swarms(id) ON DELETE CASCADE,
                    from_worker_id  INTEGER REFERENCES swarm_workers(id),
                    to_worker_id    INTEGER REFERENCES swarm_workers(id),
                    message_type    TEXT    NOT NULL DEFAULT 'message',
                    content         TEXT    NOT NULL,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_swarm_msgs_swarm ON swarm_messages(swarm_id);
                CREATE INDEX IF NOT EXISTS idx_swarm_msgs_to     ON swarm_messages(to_worker_id);
            """)
            log.info("Migration 7: created swarm tables")

        # ── Migration 8: content pipeline tables ──────────────────────────────
        # Also defensively ensure migration-5 columns exist (they may be missing
        # on installs that ran migrations 4 & 5 out-of-order in older code).
        if current < 8:
            for _col, _sql in [
                ("description", "ALTER TABLE detected_routines ADD COLUMN description TEXT DEFAULT ''"),
                ("chat_mentioned", "ALTER TABLE detected_routines ADD COLUMN chat_mentioned INTEGER DEFAULT 0"),
            ]:
                try:
                    await self._db.execute(_sql)
                except Exception:
                    pass  # column already exists

        if current < 8:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS content_queue (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_type    TEXT    NOT NULL DEFAULT 'post',
                    platform        TEXT    NOT NULL DEFAULT 'facebook',
                    title           TEXT    NOT NULL DEFAULT '',
                    body            TEXT    NOT NULL DEFAULT '',
                    media_paths     TEXT    NOT NULL DEFAULT '[]',
                    metadata        TEXT    NOT NULL DEFAULT '{}',
                    status          TEXT    NOT NULL DEFAULT 'pending',
                    swarm_id        INTEGER REFERENCES swarms(id) ON DELETE SET NULL,
                    approved_at     TEXT,
                    rejected_at     TEXT,
                    published_at    TEXT,
                    publish_error   TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_content_queue_status   ON content_queue(status);
                CREATE INDEX IF NOT EXISTS idx_content_queue_platform  ON content_queue(platform);
                CREATE INDEX IF NOT EXISTS idx_content_queue_created   ON content_queue(created_at);

                CREATE TABLE IF NOT EXISTS swarm_templates (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT    NOT NULL UNIQUE,
                    description     TEXT    NOT NULL DEFAULT '',
                    goal_template   TEXT    NOT NULL,
                    workers         TEXT    NOT NULL DEFAULT '[]',
                    global_model    TEXT,
                    is_active       INTEGER NOT NULL DEFAULT 1,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_swarm_templates_active ON swarm_templates(is_active);

                CREATE TABLE IF NOT EXISTS social_credentials (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform        TEXT    NOT NULL UNIQUE,
                    credentials     TEXT    NOT NULL DEFAULT '{}',
                    is_active       INTEGER NOT NULL DEFAULT 1,
                    verified_at     TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            log.info("Migration 8: created content_queue, swarm_templates, social_credentials tables")

        # ── Migration 9: cron_job_id + exe_path ───────────────────────────────
        if current < 9:
            for _sql in [
                "ALTER TABLE detected_routines ADD COLUMN cron_job_id INTEGER",
                "ALTER TABLE app_activities ADD COLUMN exe_path TEXT NOT NULL DEFAULT ''",
            ]:
                try:
                    await self._db.execute(_sql)
                except Exception:
                    pass  # column already exists
            log.info("Migration 9: added cron_job_id to detected_routines, exe_path to app_activities")

        if current < 10:
            # Backfill cost=0 rows in llm_usage using litellm's pricing database.
            # Before this fix, _estimate_cost always returned 0 for unknown models.
            try:
                import litellm as _litellm

                def _reprice(model: str, prompt_tokens: int, completion_tokens: int) -> float:
                    try:
                        model_key = model.split("/")[-1] if "/" in model else model
                        pricing = _litellm.model_cost.get(model_key) or _litellm.model_cost.get(model)
                        if not pricing:
                            # Suffix match: grok-3-beta → xai/grok-3-beta, kimi-k2.5 → azure_ai/kimi-k2.5
                            suffix = f"/{model_key}"
                            for k, v in _litellm.model_cost.items():
                                if k.endswith(suffix):
                                    pricing = v
                                    break
                        if pricing:
                            return (
                                pricing.get("input_cost_per_token", 0.0) * prompt_tokens
                                + pricing.get("output_cost_per_token", 0.0) * completion_tokens
                            )
                    except Exception:
                        pass
                    return 0.0

                cursor = await self._db.execute(
                    "SELECT id, model, prompt_tokens, completion_tokens FROM llm_usage WHERE cost = 0 AND total_tokens > 0"
                )
                rows = await cursor.fetchall()
                updated = 0
                for row in rows:
                    new_cost = _reprice(row["model"], row["prompt_tokens"], row["completion_tokens"])
                    if new_cost > 0:
                        await self._db.execute(
                            "UPDATE llm_usage SET cost = ? WHERE id = ?",
                            (new_cost, row["id"]),
                        )
                        updated += 1
                if updated:
                    log.info("Migration 10: backfilled LLM usage costs", updated=updated, total=len(rows))
                else:
                    log.info("Migration 10: no cost rows to backfill", checked=len(rows))
            except Exception as e:
                log.warning("Migration 10: cost backfill failed (non-fatal)", error=str(e))

        if current < 11:
            # Re-run cost backfill using provider+model exact key (no guessing).
            # Old rows store bare model names; join with provider column to reconstruct
            # the canonical litellm pricing key (e.g. xai/grok-3-beta, anthropic/claude-...).
            try:
                import litellm as _litellm

                _PRICING_PREFIX = {
                    "anthropic": "anthropic", "gemini": "gemini", "openrouter": "openrouter",
                    "xai": "xai", "deepinfra": "deepinfra", "fireworks": "fireworks_ai",
                    "together": "together_ai", "groq": "groq", "mistral": "mistral",
                    "cohere": "cohere", "perplexity": "perplexity",
                }

                def _reprice_v2(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
                    try:
                        # Build canonical pricing key from provider+model
                        prefix = _PRICING_PREFIX.get((provider or "").lower())
                        bare = model.split("/")[-1] if "/" in model else model
                        candidates = []
                        if prefix:
                            candidates.append(f"{prefix}/{bare}")
                        candidates += [model, bare]
                        pricing = None
                        for key in candidates:
                            pricing = _litellm.model_cost.get(key)
                            if pricing:
                                break
                        if pricing:
                            return (
                                pricing.get("input_cost_per_token", 0.0) * prompt_tokens
                                + pricing.get("output_cost_per_token", 0.0) * completion_tokens
                            )
                    except Exception:
                        pass
                    return 0.0

                cursor = await self._db.execute(
                    "SELECT id, provider, model, prompt_tokens, completion_tokens FROM llm_usage WHERE cost = 0 AND total_tokens > 0"
                )
                rows = await cursor.fetchall()
                updated = 0
                for row in rows:
                    new_cost = _reprice_v2(row["provider"], row["model"], row["prompt_tokens"], row["completion_tokens"])
                    if new_cost > 0:
                        await self._db.execute(
                            "UPDATE llm_usage SET cost = ? WHERE id = ?",
                            (new_cost, row["id"]),
                        )
                        updated += 1
                if updated:
                    log.info("Migration 11: re-backfilled costs with suffix matching", updated=updated, total=len(rows))
            except Exception as e:
                log.warning("Migration 11: cost re-backfill failed (non-fatal)", error=str(e))

        if current < 12:
            # Final backfill: adds suffix matching for custom-provider models (e.g. opencode_go/kimi-k2.5)
            try:
                import litellm as _litellm

                def _reprice_v3(model: str, prompt_tokens: int, completion_tokens: int) -> float:
                    try:
                        bare = model.split("/")[-1] if "/" in model else model
                        pricing = _litellm.model_cost.get(model) or _litellm.model_cost.get(bare)
                        if not pricing:
                            suffix = f"/{bare}"
                            for k, v in _litellm.model_cost.items():
                                if k.endswith(suffix):
                                    pricing = v
                                    break
                        if pricing:
                            return (
                                pricing.get("input_cost_per_token", 0.0) * prompt_tokens
                                + pricing.get("output_cost_per_token", 0.0) * completion_tokens
                            )
                    except Exception:
                        pass
                    return 0.0

                cursor = await self._db.execute(
                    "SELECT id, model, prompt_tokens, completion_tokens FROM llm_usage WHERE cost = 0 AND total_tokens > 0"
                )
                rows = await cursor.fetchall()
                updated = 0
                for row in rows:
                    new_cost = _reprice_v3(row["model"], row["prompt_tokens"], row["completion_tokens"])
                    if new_cost > 0:
                        await self._db.execute(
                            "UPDATE llm_usage SET cost = ? WHERE id = ?",
                            (new_cost, row["id"]),
                        )
                        updated += 1
                if updated:
                    log.info("Migration 12: backfilled costs for custom-provider models", updated=updated, total=len(rows))
            except Exception as e:
                log.warning("Migration 12: backfill failed (non-fatal)", error=str(e))

        # Save new version
        await self._db.execute(
            "INSERT INTO settings (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(self._SCHEMA_VERSION),),
        )
        await self._db.commit()
        log.info("Migrations complete", version=self._SCHEMA_VERSION)

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
        """Log a conversation message (content encrypted at rest if encryptor configured)."""
        if not self._db:
            return
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO messages (user_id, channel_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, channel_id, role, self._e(content), ts),
        )
        await self._db.commit()

    async def get_conversation(
        self, user_id: str, channel_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get conversation history (content decrypted on read)."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT role, content, timestamp FROM messages "
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
            result.append(r)
        return result

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

    async def get_detailed_stats(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """Return detailed token/cost breakdown: totals, by_model, today, history.

        Args:
            date_from: ISO date string 'YYYY-MM-DD' (inclusive). None = all time start.
            date_to:   ISO date string 'YYYY-MM-DD' (inclusive). None = today.
        """
        if not self._db:
            return {}

        # Build WHERE clause for date range filter
        range_conditions: list[str] = []
        range_params: list[str] = []
        if date_from:
            range_conditions.append("DATE(timestamp) >= ?")
            range_params.append(date_from)
        if date_to:
            range_conditions.append("DATE(timestamp) <= ?")
            range_params.append(date_to)
        range_where = ("WHERE " + " AND ".join(range_conditions)) if range_conditions else ""

        # Totals for the selected range
        cursor = await self._db.execute(
            f"SELECT SUM(prompt_tokens) as prompt, SUM(completion_tokens) as completion, "
            f"SUM(total_tokens) as total, SUM(cost) as cost, COUNT(*) as requests "
            f"FROM llm_usage {range_where}",
            range_params,
        )
        row = await cursor.fetchone()
        totals = dict(row) if row else {}

        # Today's totals (always fixed — not affected by the range filter)
        cursor = await self._db.execute(
            "SELECT SUM(prompt_tokens) as prompt, SUM(completion_tokens) as completion, "
            "SUM(total_tokens) as total, SUM(cost) as cost, COUNT(*) as requests "
            "FROM llm_usage WHERE DATE(timestamp) = DATE('now')"
        )
        row = await cursor.fetchone()
        today = dict(row) if row else {}

        # Per-model breakdown (respects range filter)
        cursor = await self._db.execute(
            f"SELECT model, SUM(prompt_tokens) as prompt_tokens, "
            f"SUM(completion_tokens) as completion_tokens, SUM(total_tokens) as total_tokens, "
            f"SUM(cost) as cost, COUNT(*) as requests, "
            f"AVG(elapsed_ms) as avg_elapsed_ms "
            f"FROM llm_usage {range_where} GROUP BY model ORDER BY total_tokens DESC",
            range_params,
        )
        rows = await cursor.fetchall()
        by_model = [dict(r) for r in rows]

        # Daily history — show all days within range (or last 90 days if no range)
        hist_conditions = list(range_conditions)
        hist_params = list(range_params)
        if not date_from:
            hist_conditions.append("timestamp > datetime('now', '-90 days')")
        hist_where = ("WHERE " + " AND ".join(hist_conditions)) if hist_conditions else ""

        cursor = await self._db.execute(
            f"SELECT DATE(timestamp) as date, COUNT(*) as requests, "
            f"SUM(prompt_tokens) as prompt_tokens, SUM(completion_tokens) as completion_tokens, "
            f"SUM(total_tokens) as tokens, SUM(cost) as cost "
            f"FROM llm_usage {hist_where} "
            f"GROUP BY DATE(timestamp) ORDER BY date",
            hist_params,
        )
        rows = await cursor.fetchall()
        history = [dict(r) for r in rows]

        # Date range of actual data (for UI display)
        cursor = await self._db.execute(
            f"SELECT MIN(DATE(timestamp)) as first_date, MAX(DATE(timestamp)) as last_date "
            f"FROM llm_usage {range_where}",
            range_params,
        )
        row = await cursor.fetchone()
        data_range = dict(row) if row else {}

        return {
            "totals": {
                "prompt_tokens": totals.get("prompt") or 0,
                "completion_tokens": totals.get("completion") or 0,
                "total_tokens": totals.get("total") or 0,
                "cost": round(totals.get("cost") or 0.0, 6),
                "requests": totals.get("requests") or 0,
            },
            "today": {
                "prompt_tokens": today.get("prompt") or 0,
                "completion_tokens": today.get("completion") or 0,
                "total_tokens": today.get("total") or 0,
                "cost": round(today.get("cost") or 0.0, 6),
                "requests": today.get("requests") or 0,
            },
            "by_model": by_model,
            "history": history,
            "filter": {
                "date_from": date_from,
                "date_to": date_to,
                "first_record": data_range.get("first_date"),
                "last_record": data_range.get("last_date"),
            },
        }

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

    # ─── Agents ───────────────────────────────────────────────

    async def create_agent(
        self,
        name: str,
        description: str,
        system_prompt: str,
        allowed_tools: str = "all",
        webhook_secret: str = "",
        telegram_token: str = "",
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO agents (name, description, system_prompt, allowed_tools, webhook_secret, telegram_token) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, description, system_prompt, allowed_tools, webhook_secret, telegram_token),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_agent(self, agent_id: int) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_agents(self) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute("SELECT * FROM agents ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_agent(self, agent_id: int, **kwargs: Any) -> bool:
        if not self._db:
            return False
        allowed = {"name", "description", "system_prompt", "allowed_tools", "is_active", "telegram_token"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(val)
        if not updates:
            return False
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(agent_id)
        await self._db.execute(f"UPDATE agents SET {', '.join(updates)} WHERE id = ?", params)
        await self._db.commit()
        return True

    async def delete_agent(self, agent_id: int) -> bool:
        if not self._db:
            return False
        cursor = await self._db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        await self._db.commit()
        return cursor.rowcount > 0

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

    # ─── App Activity (OS Watcher) ────────────────────────────

    async def log_app_activity(
        self,
        app_name: str,
        window_title: str,
        process_name: str,
        focus_seconds: float,
        session_start: str,
        session_end: str,
        day_of_week: int,
        hour_of_day: int,
        exe_path: str = "",
    ) -> int:
        """Record a single app focus session (sensitive fields encrypted if configured)."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO app_activities "
            "(app_name, window_title, process_name, focus_seconds, "
            " session_start, session_end, day_of_week, hour_of_day, exe_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self._e(app_name),
                self._e(window_title),
                self._e(process_name),
                focus_seconds,
                session_start,
                session_end,
                day_of_week,
                hour_of_day,
                exe_path,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_app_activities(self, limit: int = 5000) -> list[dict[str, Any]]:
        """Return decrypted app activity records ordered by session_start ASC."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM app_activities ORDER BY session_start ASC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._decrypt_activity(dict(r)) for r in rows]

    async def get_app_stats(self) -> list[dict[str, Any]]:
        """
        Return per-app aggregated usage: total seconds + session count.
        When encryption is active, aggregation is done in Python (cannot GROUP BY
        ciphertext in SQL since each ciphertext is unique due to random IVs).
        """
        if not self._db:
            return []

        if self._enc:
            # Fetch all rows, decrypt, aggregate in Python
            cursor = await self._db.execute(
                "SELECT app_name, process_name, focus_seconds FROM app_activities"
            )
            raw = await cursor.fetchall()
            from collections import defaultdict
            agg: dict[str, dict] = defaultdict(lambda: {"total_seconds": 0.0, "session_count": 0, "process_name": ""})
            for row in raw:
                name = self._d(row[0])
                proc = self._d(row[1])
                secs = row[2]
                agg[name]["total_seconds"] += secs
                agg[name]["session_count"] += 1
                agg[name]["process_name"] = proc
            result = [
                {"app_name": k, "process_name": v["process_name"],
                 "total_seconds": v["total_seconds"], "session_count": v["session_count"]}
                for k, v in agg.items()
            ]
            return sorted(result, key=lambda x: -x["total_seconds"])[:30]

        # No encryption — fast SQL path
        cursor = await self._db.execute(
            "SELECT app_name, process_name, "
            "SUM(focus_seconds) as total_seconds, COUNT(*) as session_count "
            "FROM app_activities "
            "GROUP BY app_name "
            "ORDER BY total_seconds DESC "
            "LIMIT 30"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_recent_app_sessions(self, limit: int = 30) -> list[dict[str, Any]]:
        """Return most recent app focus sessions, decrypted."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM app_activities ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._decrypt_activity(dict(r)) for r in rows]

    async def get_activity_count(self) -> int:
        """Total number of recorded activity sessions."""
        if not self._db:
            return 0
        cursor = await self._db.execute("SELECT COUNT(*) as cnt FROM app_activities")
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def get_activity_hours(self) -> float:
        """Total hours of app usage recorded."""
        if not self._db:
            return 0.0
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(focus_seconds), 0) as total FROM app_activities"
        )
        row = await cursor.fetchone()
        return (row["total"] if row else 0) / 3600.0

    # ─── Detected Routines ────────────────────────────────────

    async def create_routine(
        self,
        name: str,
        trigger_type: str,
        trigger_data: str,
        apps: str,
        confidence: float,
        occurrence_count: int,
        status: str = "pending",
        description: str = "",
    ) -> int:
        """Create a new detected routine (sensitive fields encrypted if configured)."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO detected_routines "
            "(name, trigger_type, trigger_data, apps, confidence, occurrence_count, status, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self._e(name),
                trigger_type,
                self._e(trigger_data),
                self._e(apps),
                confidence,
                occurrence_count,
                status,
                self._e(description),
            ),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_routine(self, routine_id: int) -> dict[str, Any] | None:
        """Get a single decrypted routine by id."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM detected_routines WHERE id = ?", (routine_id,)
        )
        row = await cursor.fetchone()
        return self._decrypt_routine(dict(row)) if row else None

    async def get_all_routines(self) -> list[dict[str, Any]]:
        """Return all routines decrypted, ordered by confidence desc."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM detected_routines ORDER BY confidence DESC, occurrence_count DESC"
        )
        rows = await cursor.fetchall()
        return [self._decrypt_routine(dict(r)) for r in rows]

    async def get_routine_by_apps(self, apps: list[str]) -> dict[str, Any] | None:
        """
        Find an existing routine whose app list matches (order-independent).
        We compare JSON-encoded sorted app name lists.
        """
        if not self._db:
            return None
        import json as _json
        all_routines = await self.get_all_routines()
        target = sorted(apps)
        for r in all_routines:
            try:
                stored_apps = _json.loads(r.get("apps", "[]"))
                stored_names = sorted(
                    a["app_name"] if isinstance(a, dict) else a
                    for a in stored_apps
                )
                if stored_names == target:
                    return r
            except Exception:
                pass
        return None

    async def update_routine(self, routine_id: int, **kwargs: Any) -> bool:
        """Update arbitrary fields of a detected routine."""
        if not self._db:
            return False
        allowed = {
            "name", "description", "trigger_type", "trigger_data", "apps",
            "confidence", "status", "last_run", "run_count", "occurrence_count",
            "chat_mentioned", "cron_job_id",
        }
        _encrypt_fields = {"name", "description", "trigger_data", "apps"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(self._e(val) if (key in _encrypt_fields and isinstance(val, str)) else val)
        if not updates:
            return False
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(routine_id)
        await self._db.execute(
            f"UPDATE detected_routines SET {', '.join(updates)} WHERE id = ?", params
        )
        await self._db.commit()
        return True

    async def delete_routine(self, routine_id: int) -> bool:
        """Delete a routine by id."""
        if not self._db:
            return False
        cursor = await self._db.execute(
            "DELETE FROM detected_routines WHERE id = ?", (routine_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_unmentioned_routines(self, limit: int = 2) -> list[dict[str, Any]]:
        """Return pending routines that haven't been mentioned in chat yet."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM detected_routines "
            "WHERE status = 'pending' AND (chat_mentioned = 0 OR chat_mentioned IS NULL) "
            "ORDER BY confidence DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_routines_mentioned(self, routine_ids: list[int]) -> None:
        """Mark routines as mentioned in chat."""
        if not self._db or not routine_ids:
            return
        placeholders = ",".join("?" * len(routine_ids))
        await self._db.execute(
            f"UPDATE detected_routines SET chat_mentioned = 1, updated_at = CURRENT_TIMESTAMP "
            f"WHERE id IN ({placeholders})",
            routine_ids,
        )
        await self._db.commit()

    async def record_routine_run(self, routine_id: int) -> None:
        """Increment run_count and update last_run timestamp."""
        if not self._db:
            return
        ts = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE detected_routines "
            "SET run_count = run_count + 1, last_run = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (ts, routine_id),
        )
        await self._db.commit()

    # ─── Cron Jobs ────────────────────────────────────────────

    async def create_cron_job(
        self,
        name: str,
        description: str,
        cron_expr: str,
        action_type: str,
        action_payload: dict,
        is_enabled: bool = True,
        next_run: str | None = None,
    ) -> dict[str, Any]:
        """Create a new cron job and return the full row."""
        if not self._db:
            return {}
        import json as _json
        cursor = await self._db.execute(
            "INSERT INTO cron_jobs "
            "(name, description, cron_expr, action_type, action_payload, is_enabled, next_run) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, description, cron_expr, action_type,
             _json.dumps(action_payload), int(is_enabled), next_run),
        )
        await self._db.commit()
        row_id = cursor.lastrowid
        return await self.get_cron_job(row_id) or {}

    async def get_all_cron_jobs(self) -> list[dict[str, Any]]:
        """Return all cron jobs ordered by id."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM cron_jobs ORDER BY id"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_cron_job(self, job_id: int) -> dict[str, Any] | None:
        """Return a single cron job by id."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM cron_jobs WHERE id = ?", (job_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_cron_job(self, job_id: int, **kwargs: Any) -> bool:
        """Update allowed fields of a cron job."""
        if not self._db:
            return False
        import json as _json
        allowed = {
            "name", "description", "cron_expr", "action_type",
            "action_payload", "is_enabled", "next_run",
        }
        updates, params = [], []
        for key, val in kwargs.items():
            if key not in allowed:
                continue
            updates.append(f"{key} = ?")
            if key == "action_payload" and isinstance(val, dict):
                params.append(_json.dumps(val))
            elif key == "is_enabled":
                params.append(int(val))
            else:
                params.append(val)
        if not updates:
            return False
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(job_id)
        await self._db.execute(
            f"UPDATE cron_jobs SET {', '.join(updates)} WHERE id = ?", params
        )
        await self._db.commit()
        return True

    async def update_cron_job_after_run(
        self,
        job_id: int,
        last_run: str,
        next_run: str,
        status: str,
        output: str,
    ) -> None:
        """Update last_run, next_run, status, and increment run_count after execution."""
        if not self._db:
            return
        await self._db.execute(
            "UPDATE cron_jobs SET "
            "last_run = ?, next_run = ?, last_status = ?, last_output = ?, "
            "run_count = run_count + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (last_run, next_run or None, status, output[:TRUNCATE_DB_OUTPUT_CHARS] if output else None, job_id),
        )
        await self._db.commit()

    async def delete_cron_job(self, job_id: int) -> bool:
        """Delete a cron job and its run history."""
        if not self._db:
            return False
        cursor = await self._db.execute(
            "DELETE FROM cron_jobs WHERE id = ?", (job_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    # ─── Cron Job Runs ────────────────────────────────────────

    async def create_cron_run(
        self,
        job_id: int,
        started_at: str,
        triggered_by: str = "scheduler",
    ) -> int:
        """Insert a run row with status='running'. Returns the run id."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO cron_job_runs (job_id, started_at, triggered_by) VALUES (?, ?, ?)",
            (job_id, started_at, triggered_by),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def finish_cron_run(
        self,
        run_id: int,
        finished_at: str,
        status: str,
        output: str | None = None,
        error: str | None = None,
    ) -> None:
        """Mark a run as finished with its result."""
        if not self._db:
            return
        await self._db.execute(
            "UPDATE cron_job_runs "
            "SET finished_at = ?, status = ?, output = ?, error = ? "
            "WHERE id = ?",
            (finished_at, status,
             output[:TRUNCATE_DB_OUTPUT_CHARS] if output else None,
             error[:TRUNCATE_DB_ERROR_CHARS] if error else None,
             run_id),
        )
        await self._db.commit()

    async def get_cron_runs(
        self,
        job_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent cron runs, optionally filtered by job_id."""
        if not self._db:
            return []
        if job_id is not None:
            cursor = await self._db.execute(
                "SELECT r.*, j.name as job_name FROM cron_job_runs r "
                "JOIN cron_jobs j ON j.id = r.job_id "
                "WHERE r.job_id = ? ORDER BY r.id DESC LIMIT ?",
                (job_id, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT r.*, j.name as job_name FROM cron_job_runs r "
                "JOIN cron_jobs j ON j.id = r.job_id "
                "ORDER BY r.id DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ─── Swarms ───────────────────────────────────────────────────────────────

    async def create_swarm(
        self, name: str, goal: str, global_model: str | None = None
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO swarms (name, goal, global_model) VALUES (?, ?, ?)",
            (name, goal, global_model),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_swarm(self, swarm_id: int) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM swarms WHERE id = ?", (swarm_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_swarms(self) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT s.*, "
            "(SELECT COUNT(*) FROM swarm_workers w WHERE w.swarm_id = s.id) as worker_count, "
            "(SELECT COUNT(*) FROM swarm_tasks t WHERE t.swarm_id = s.id) as task_count "
            "FROM swarms s ORDER BY s.created_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_swarm(self, swarm_id: int, **kwargs: Any) -> bool:
        if not self._db:
            return False
        allowed = {"name", "goal", "status", "global_model", "workspace_path",
                   "shared_context", "context_files"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(val)
        if not updates:
            return False
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(swarm_id)
        await self._db.execute(
            f"UPDATE swarms SET {', '.join(updates)} WHERE id = ?", params
        )
        await self._db.commit()
        return True

    async def delete_swarm(self, swarm_id: int) -> bool:
        if not self._db:
            return False
        cursor = await self._db.execute("DELETE FROM swarms WHERE id = ?", (swarm_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    # ─── Swarm Workers ────────────────────────────────────────────────────────

    async def create_swarm_worker(
        self,
        swarm_id: int,
        name: str,
        role: str,
        description: str,
        system_prompt: str,
        model: str | None,
        allowed_tools: str,
        workspace_path: str,
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO swarm_workers "
            "(swarm_id, name, role, description, system_prompt, model, allowed_tools, workspace_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (swarm_id, name, role, description, system_prompt, model, allowed_tools, workspace_path),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_swarm_workers(self, swarm_id: int) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM swarm_workers WHERE swarm_id = ? ORDER BY id",
            (swarm_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_swarm_worker(self, worker_id: int, **kwargs: Any) -> bool:
        if not self._db:
            return False
        allowed = {"name", "role", "description", "system_prompt", "model",
                   "allowed_tools", "status", "workspace_path"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(val)
        if not updates:
            return False
        params.append(worker_id)
        await self._db.execute(
            f"UPDATE swarm_workers SET {', '.join(updates)} WHERE id = ?", params
        )
        await self._db.commit()
        return True

    # ─── Swarm Tasks ──────────────────────────────────────────────────────────

    async def create_swarm_task(
        self,
        swarm_id: int,
        worker_id: int | None,
        title: str,
        description: str,
        depends_on: str = "[]",
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO swarm_tasks (swarm_id, worker_id, title, description, depends_on) "
            "VALUES (?, ?, ?, ?, ?)",
            (swarm_id, worker_id, title, description, depends_on),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_swarm_tasks(self, swarm_id: int) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT t.*, w.name as worker_name "
            "FROM swarm_tasks t "
            "LEFT JOIN swarm_workers w ON w.id = t.worker_id "
            "WHERE t.swarm_id = ? ORDER BY t.id",
            (swarm_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_swarm_task(self, task_id: int, **kwargs: Any) -> bool:
        if not self._db:
            return False
        allowed = {"worker_id", "title", "description", "depends_on", "status", "result"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(val)
        if not updates:
            return False
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(task_id)
        await self._db.execute(
            f"UPDATE swarm_tasks SET {', '.join(updates)} WHERE id = ?", params
        )
        await self._db.commit()
        return True

    # ─── Swarm Messages ───────────────────────────────────────────────────────

    async def add_swarm_message(
        self,
        swarm_id: int,
        from_worker_id: int | None,
        to_worker_id: int | None,
        content: str,
        message_type: str = "message",
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO swarm_messages "
            "(swarm_id, from_worker_id, to_worker_id, content, message_type) "
            "VALUES (?, ?, ?, ?, ?)",
            (swarm_id, from_worker_id, to_worker_id, content, message_type),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_swarm_messages(
        self,
        swarm_id: int,
        to_worker_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get messages for a swarm. If to_worker_id given, returns direct + broadcasts."""
        if not self._db:
            return []
        if to_worker_id is not None:
            cursor = await self._db.execute(
                "SELECT m.*, fw.name as from_worker_name "
                "FROM swarm_messages m "
                "LEFT JOIN swarm_workers fw ON fw.id = m.from_worker_id "
                "WHERE m.swarm_id = ? AND (m.to_worker_id = ? OR m.to_worker_id IS NULL) "
                "ORDER BY m.id",
                (swarm_id, to_worker_id),
            )
        else:
            cursor = await self._db.execute(
                "SELECT m.*, fw.name as from_worker_name, tw.name as to_worker_name "
                "FROM swarm_messages m "
                "LEFT JOIN swarm_workers fw ON fw.id = m.from_worker_id "
                "LEFT JOIN swarm_workers tw ON tw.id = m.to_worker_id "
                "WHERE m.swarm_id = ? ORDER BY m.id",
                (swarm_id,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

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

    # ─── Swarm Templates ──────────────────────────────────────

    async def create_swarm_template(
        self,
        name: str,
        description: str,
        goal_template: str,
        workers: str = "[]",
        global_model: str | None = None,
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO swarm_templates (name, description, goal_template, workers, global_model) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, description, goal_template, workers, global_model),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_all_swarm_templates(self) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM swarm_templates WHERE is_active = 1 ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_swarm_template(self, template_id: int) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM swarm_templates WHERE id = ?", (template_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def delete_swarm_template(self, template_id: int) -> bool:
        if not self._db:
            return False
        cursor = await self._db.execute("DELETE FROM swarm_templates WHERE id = ?", (template_id,))
        await self._db.commit()
        return cursor.rowcount > 0

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
