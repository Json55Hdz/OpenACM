"""Schema versioning: every incremental migration, run once on startup."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from openacm.constants import TRUNCATE_DB_OUTPUT_CHARS, TRUNCATE_DB_ERROR_CHARS
from openacm.utils.text import truncate

log = structlog.get_logger()


class MigrationsMixin:
    """Part of Database (schema versioning: every incremental migration, run once on startup); Database inherits it."""

    # ─── Migrations ───────────────────────────────────────────

    # Bump this number every time you add a new migration below.
    _SCHEMA_VERSION = 42

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
                except Exception as e:
                    log.warning("Could not repair tool-call ids in a stored message", error=str(e))
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

        if current < 13:
            try:
                await self._db.execute(
                    "ALTER TABLE swarm_tasks ADD COLUMN retry_history_json TEXT DEFAULT '[]'"
                )
                log.info("Migration 13: added retry_history_json to swarm_tasks")
            except Exception:
                pass  # column already exists

        if current < 14:
            try:
                await self._db.execute(
                    "ALTER TABLE swarms ADD COLUMN working_path TEXT DEFAULT ''"
                )
                log.info("Migration 14: added working_path to swarms")
            except Exception:
                pass  # column already exists

        if current < 15:
            for col_sql, label in [
                ("ALTER TABLE swarms ADD COLUMN clarification_questions TEXT DEFAULT ''", "clarification_questions"),
                ("ALTER TABLE swarms ADD COLUMN clarification_answers TEXT DEFAULT ''", "clarification_answers"),
            ]:
                try:
                    await self._db.execute(col_sql)
                    log.info(f"Migration 15: added {label} to swarms")
                except Exception:
                    pass  # column already exists

        if current < 16:
            try:
                await self._db.execute(
                    "ALTER TABLE app_activities ADD COLUMN project_name TEXT NOT NULL DEFAULT ''"
                )
                log.info("Migration 16: added project_name to app_activities")
            except Exception:
                pass  # column already exists

        if current < 17:
            try:
                await self._db.execute(
                    "ALTER TABLE swarm_tasks ADD COLUMN task_type TEXT DEFAULT 'standard'"
                )
                log.info("Migration 17: added task_type to swarm_tasks")
            except Exception:
                pass  # column already exists

        if current < 18:
            try:
                await self._db.execute(
                    "ALTER TABLE swarms ADD COLUMN parent_swarm_id INTEGER"
                )
                log.info("Migration 18: added parent_swarm_id to swarms")
            except Exception:
                pass  # column already exists

        if current < 19:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS gmail_categories (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    NOT NULL UNIQUE,
                    description TEXT    NOT NULL DEFAULT '',
                    color       TEXT    NOT NULL DEFAULT '#6366f1',
                    icon        TEXT    NOT NULL DEFAULT 'Tag',
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS gmail_emails (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    gmail_id      TEXT    NOT NULL UNIQUE,
                    thread_id     TEXT    NOT NULL DEFAULT '',
                    subject       TEXT    NOT NULL DEFAULT '',
                    sender_name   TEXT    NOT NULL DEFAULT '',
                    sender_email  TEXT    NOT NULL DEFAULT '',
                    snippet       TEXT    NOT NULL DEFAULT '',
                    category_id   INTEGER REFERENCES gmail_categories(id),
                    is_read       INTEGER NOT NULL DEFAULT 0,
                    is_replied    INTEGER NOT NULL DEFAULT 0,
                    ai_classified INTEGER NOT NULL DEFAULT 0,
                    received_at   DATETIME,
                    last_synced   DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_gmail_emails_category
                    ON gmail_emails(category_id);
                CREATE INDEX IF NOT EXISTS idx_gmail_emails_received
                    ON gmail_emails(received_at);

                CREATE TABLE IF NOT EXISTS gmail_classifier_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                );
            """)
            await self._db.execute(
                "INSERT OR IGNORE INTO gmail_categories (name, description, color, icon) "
                "VALUES ('Otros', 'Correos que no encajan en ninguna categoría', '#6b7280', 'Inbox')"
            )
            log.info("Migration 19: created gmail_classifier tables")

        if current < 20:
            try:
                await self._db.execute(
                    "ALTER TABLE gmail_emails ADD COLUMN body_text TEXT NOT NULL DEFAULT ''"
                )
                log.info("Migration 20: added body_text to gmail_emails")
            except Exception:
                pass  # column already exists

        if current < 21:
            try:
                await self._db.execute(
                    "ALTER TABLE gmail_emails ADD COLUMN body_html TEXT NOT NULL DEFAULT ''"
                )
                log.info("Migration 21: added body_html to gmail_emails")
            except Exception:
                pass  # column already exists

        if current < 22:
            for col, default in (
                ("context", "''"),
                ("known_senders", "'[]'"),
                ("patterns", "'[]'"),
            ):
                try:
                    await self._db.execute(
                        f"ALTER TABLE gmail_categories ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}"
                    )
                except Exception:
                    pass  # column already exists
            log.info("Migration 22: added context/known_senders/patterns to gmail_categories")

        if current < 23:
            try:
                await self._db.execute(
                    "ALTER TABLE gmail_emails ADD COLUMN manual_override INTEGER NOT NULL DEFAULT 0"
                )
                log.info("Migration 23: added manual_override to gmail_emails")
            except Exception:
                pass  # column already exists

        if current < 24:
            for col, default in (
                ("thread_last_sender_email", "''"),
                ("ai_suggestion",            "''"),
            ):
                try:
                    await self._db.execute(
                        f"ALTER TABLE gmail_emails ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}"
                    )
                except Exception:
                    pass  # column already exists
            log.info("Migration 24: added thread_last_sender_email, ai_suggestion to gmail_emails")

        if current < 25:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS gmail_reply_drafts (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id       INTEGER NOT NULL UNIQUE REFERENCES gmail_emails(id),
                    gmail_draft_id TEXT    NOT NULL DEFAULT '',
                    draft_body     TEXT    NOT NULL DEFAULT '',
                    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            log.info("Migration 25: created gmail_reply_drafts table")

        if current < 26:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS gmail_reply_examples (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id         INTEGER NOT NULL REFERENCES gmail_categories(id),
                    source_email_id     INTEGER,
                    subtype_label       TEXT    NOT NULL DEFAULT '',
                    email_context       TEXT    NOT NULL DEFAULT '',
                    original_suggestion TEXT    NOT NULL DEFAULT '',
                    final_response      TEXT    NOT NULL DEFAULT '',
                    embedding           BLOB,
                    use_count           INTEGER NOT NULL DEFAULT 0,
                    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_reply_examples_category
                    ON gmail_reply_examples(category_id);
                CREATE INDEX IF NOT EXISTS idx_reply_examples_source
                    ON gmail_reply_examples(source_email_id);
            """)
            log.info("Migration 26: created gmail_reply_examples table")

        if current < 27:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_knowledge (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    type        TEXT NOT NULL CHECK(type IN ('file', 'text')),
                    title       TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    filename    TEXT,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_agent_knowledge_agent
                    ON agent_knowledge(agent_id);
            """)
            log.info("Migration 27: created agent_knowledge table")

        if current < 28:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_channels (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    type        TEXT NOT NULL CHECK(type IN ('telegram', 'whatsapp')),
                    config      TEXT NOT NULL DEFAULT '{}',
                    is_active   INTEGER NOT NULL DEFAULT 1,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_agent_channels_agent
                    ON agent_channels(agent_id);
                CREATE INDEX IF NOT EXISTS idx_agent_channels_type_active
                    ON agent_channels(type, is_active);
            """)
            # Migrate existing telegram_token values into agent_channels
            await self._db.execute("""
                INSERT INTO agent_channels (agent_id, type, config)
                SELECT id, 'telegram', json_object('token', telegram_token)
                FROM agents
                WHERE telegram_token IS NOT NULL AND telegram_token != ''
            """)
            await self._db.execute("""
                UPDATE agents SET telegram_token = ''
                WHERE telegram_token IS NOT NULL AND telegram_token != ''
            """)
            await self._db.commit()
            log.info("Migration 28: created agent_channels table, migrated telegram_token values")

        if current < 29:
            # Recreate agent_channels with expanded type CHECK to include whatsapp_web
            await self._db.execute("PRAGMA foreign_keys = OFF")
            await self._db.execute("""
                CREATE TABLE IF NOT EXISTS agent_channels_new (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    type        TEXT NOT NULL CHECK(type IN ('telegram', 'whatsapp', 'whatsapp_web')),
                    config      TEXT NOT NULL DEFAULT '{}',
                    is_active   INTEGER NOT NULL DEFAULT 1,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await self._db.execute(
                "INSERT INTO agent_channels_new SELECT * FROM agent_channels"
            )
            await self._db.execute("DROP TABLE agent_channels")
            await self._db.execute(
                "ALTER TABLE agent_channels_new RENAME TO agent_channels"
            )
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_channels_agent ON agent_channels(agent_id)"
            )
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_channels_type_active ON agent_channels(type, is_active)"
            )
            # Commit before re-enabling FK: SQLite ignores PRAGMA foreign_keys inside a transaction
            await self._db.commit()
            await self._db.execute("PRAGMA foreign_keys = ON")
            log.info("Migration 29: expanded agent_channels type to include whatsapp_web")

        if current < 30:
            # Expression index speeds up PARTITION BY COALESCE(thread_id, gmail_id)
            # used in the threads window-function query.
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_gmail_emails_eff_thread "
                "ON gmail_emails((COALESCE(thread_id, gmail_id)), received_at)"
            )
            await self._db.commit()
            log.info("Migration 30: add expression index on gmail_emails eff_thread")

        # ── Migration 31: add plugin_state table (Phase 1 plugin dashboard) ──
        if current < 31:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS plugin_state (
                    plugin_name  TEXT PRIMARY KEY,
                    enabled      BOOLEAN NOT NULL DEFAULT 1,
                    config_json  TEXT NOT NULL DEFAULT '{}'
                );
            """)
            await self._db.commit()
            log.info("Migration 31: add plugin_state table")

        # ── Migration 32: per-worker skill scoping ────────────────────────
        # Adds skills.worker_id (NULL = global system skill, unchanged;
        # set = private to that one swarm worker) and worker_skills (which
        # GLOBAL skills a given worker has enabled). SQLite can't ALTER a
        # UNIQUE constraint in place, so we rebuild skills with the same
        # columns plus worker_id, then replace the bare UNIQUE(name) with
        # two partial unique indexes — a plain composite UNIQUE(name,
        # worker_id) would NOT work here since SQL treats NULL != NULL,
        # which would let multiple global skills share a name.
        if current < 32:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS skills_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    is_active INTEGER DEFAULT 1,
                    is_builtin INTEGER DEFAULT 0,
                    worker_id INTEGER REFERENCES swarm_workers(id) ON DELETE CASCADE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO skills_new (id, name, description, content, category, is_active, is_builtin, created_at, updated_at)
                    SELECT id, name, description, content, category, is_active, is_builtin, created_at, updated_at FROM skills;
                DROP TABLE skills;
                ALTER TABLE skills_new RENAME TO skills;

                CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category);
                CREATE INDEX IF NOT EXISTS idx_skills_active ON skills(is_active);
                CREATE INDEX IF NOT EXISTS idx_skills_worker ON skills(worker_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name_global ON skills(name) WHERE worker_id IS NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name_per_worker ON skills(name, worker_id) WHERE worker_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS worker_skills (
                    worker_id INTEGER NOT NULL REFERENCES swarm_workers(id) ON DELETE CASCADE,
                    skill_id  INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                    PRIMARY KEY (worker_id, skill_id)
                );
            """)
            await self._db.commit()
            log.info("Migration 32: per-worker skill scoping (skills.worker_id, worker_skills)")

        # ── Migration 33: per-agent skill scoping ─────────────────────────
        # Adds skills.agent_id (NULL = not agent-scoped, unchanged; set =
        # private to that one Agent) and agent_skills (which GLOBAL skills a
        # given agent has enabled) — the exact same shape as Migration 32's
        # worker_id/worker_skills, but for the separate Agents feature.
        # Unlike Migration 32, adding this column needs no table rebuild —
        # SQLite supports ALTER TABLE ADD COLUMN for a plain nullable column
        # fine; only the existing idx_skills_name_global index needs to be
        # dropped and recreated, since its WHERE clause (worker_id IS NULL)
        # doesn't yet know agent_id exists, and a global skill + an
        # agent-scoped skill could otherwise collide on name.
        if current < 33:
            await self._db.execute(
                "ALTER TABLE skills ADD COLUMN agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE"
            )
            await self._db.executescript("""
                DROP INDEX IF EXISTS idx_skills_name_global;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name_global
                    ON skills(name) WHERE worker_id IS NULL AND agent_id IS NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name_per_agent
                    ON skills(name, agent_id) WHERE agent_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_skills_agent ON skills(agent_id);

                CREATE TABLE IF NOT EXISTS agent_skills (
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                    PRIMARY KEY (agent_id, skill_id)
                );
            """)
            await self._db.commit()
            log.info("Migration 33: per-agent skill scoping (skills.agent_id, agent_skills)")

        # ── Migration 34: agent node flows + reusable connections ────────
        # A Flow is a node graph (JSON) that becomes a dynamically-registered
        # tool for its owning agent. A Connection is a reusable set of
        # credentials (e.g. a WooCommerce store's API keys) a flow's nodes
        # can reference, so the same store doesn't need re-entering per flow.
        # Both are 100% private to one agent (ON DELETE CASCADE, no sharing).
        if current < 34:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS flows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    graph_json TEXT NOT NULL DEFAULT '{"nodes":[],"edges":[]}',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_flows_agent ON flows(agent_id);

                CREATE TABLE IF NOT EXISTS connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    config TEXT NOT NULL DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_connections_agent ON connections(agent_id);
            """)
            await self._db.commit()
            log.info("Migration 34: agent node flows (flows, connections)")

        # ── Migration 35: per-flow skill scoping ──────────────────────────
        # Adds skills.flow_id (NULL = not flow-scoped, unchanged; set =
        # private to that one flow). Unlike worker_id/agent_id, a flow-skill
        # is singular by design (zero or one skill per flow, enforced at the
        # API layer in Task 7) — no flow_skills join table, since there is
        # no "flow opts into a global skill" concept to track.
        if current < 35:
            await self._db.execute(
                "ALTER TABLE skills ADD COLUMN flow_id INTEGER REFERENCES flows(id) ON DELETE CASCADE"
            )
            await self._db.executescript("""
                DROP INDEX IF EXISTS idx_skills_name_global;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name_global
                    ON skills(name) WHERE worker_id IS NULL AND agent_id IS NULL AND flow_id IS NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name_per_flow
                    ON skills(name, flow_id) WHERE flow_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_skills_flow ON skills(flow_id);
            """)
            await self._db.commit()
            log.info("Migration 35: per-flow skill scoping (skills.flow_id)")

        # ── Migration 36: close the flow-skill singularity TOCTOU race ────
        # Migration 35's idx_skills_name_per_flow is (name, flow_id), not
        # flow_id alone — it does nothing to stop two skills with *different*
        # names being inserted for the same flow_id. The API layer's
        # get_flow_skill() check-then-create_skill() insert in Task 7 has a
        # suspension point between the two awaits, so two near-simultaneous
        # POSTs can both observe "no skill yet" and both insert. This partial
        # unique index closes that race at the data layer as defense-in-depth
        # — the API-layer pre-check stays as the fast/clean path, and the DB
        # now rejects the loser of a race with a genuine constraint error
        # that the router translates into a 409.
        if current < 36:
            await self._db.executescript("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_one_per_flow
                    ON skills(flow_id) WHERE flow_id IS NOT NULL;
            """)
            await self._db.commit()
            log.info("Migration 36: one-skill-per-flow unique index (race-condition guard)")

        # ── Migration 37: webhook connectors ──────────────────────────────
        # A connector = a dashboard-configured, publicly reachable webhook
        # (POST /api/webhooks/{slug}) that verifies its own request per
        # auth_scheme/auth_config and runs flow_id on a valid request. See
        # docs/superpowers/specs/2026-09-09-webhook-connectors-and-agent-flow-node-design.md.
        if current < 37:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS webhook_connectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    auth_scheme TEXT NOT NULL,
                    auth_config TEXT NOT NULL,
                    flow_id INTEGER NOT NULL REFERENCES flows(id) ON DELETE CASCADE,
                    dedupe_header TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS webhook_connector_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    connector_id INTEGER NOT NULL REFERENCES webhook_connectors(id) ON DELETE CASCADE,
                    dedupe_key TEXT,
                    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    body TEXT,
                    status TEXT NOT NULL,
                    result TEXT,
                    duration_ms INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_webhook_connector_events_connector
                    ON webhook_connector_events(connector_id);
                CREATE INDEX IF NOT EXISTS idx_webhook_connector_events_dedupe
                    ON webhook_connector_events(connector_id, dedupe_key);
            """)
            await self._db.commit()
            log.info("Migration 37: webhook connectors (webhook_connectors, webhook_connector_events)")

        # ── Migration 38: per-agent memory TTL policy ─────────────────────
        # memory_mode: 'persistent' (default, remember forever) or
        # 'session_ttl' (reset context after memory_ttl_hours of inactivity).
        # Old messages are never deleted by this — see MemoryManager.get_or_create.
        if current < 38:
            await self._db.executescript("""
                ALTER TABLE agents ADD COLUMN memory_mode TEXT NOT NULL DEFAULT 'persistent';
                ALTER TABLE agents ADD COLUMN memory_ttl_hours INTEGER NOT NULL DEFAULT 24;
            """)
            await self._db.commit()
            log.info("Migration 38: added memory_mode/memory_ttl_hours to agents")

        # ── Migration 39: persistent customer names ───────────────────────
        # A conversation's customer name survives independently of memory_ttl
        # resets — it's the one thing an agent is told to remember forever
        # even when its conversation context resets every N hours.
        if current < 39:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS customer_names (
                    user_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, channel_id)
                );
            """)
            await self._db.commit()
        # ── Migration 40: per-agent inactivity follow-up nudges ───────────
        # inactivity_timeout_minutes: 0 = disabled, >0 = minutes of silence before sending follow-up
        # inactivity_message: template message sent to user on timeout (supports {name})
        if current < 40:
            await self._db.executescript("""
                ALTER TABLE agents ADD COLUMN inactivity_timeout_minutes INTEGER NOT NULL DEFAULT 0;
                ALTER TABLE agents ADD COLUMN inactivity_message TEXT NOT NULL DEFAULT '';
            """)
            await self._db.commit()
            log.info("Migration 40: added inactivity_timeout_minutes and inactivity_message to agents")

        # ── Migration 41: per-agent show_in_chat visibility flag ───────────
        if current < 41:
            try:
                await self._db.executescript("""
                    ALTER TABLE agents ADD COLUMN show_in_chat INTEGER NOT NULL DEFAULT 1;
                """)
                await self._db.commit()
            except sqlite3.OperationalError:
                pass
            log.info("Migration 41: added show_in_chat column to agents")

        # ── Migration 42: where a skill comes from ────────────────────────────
        # system = ships with OpenACM, user = made here, plugin:<name> = provided by a plugin,
        # market = installed from the skill marketplace. Skills that left the product are dropped.
        if current < 42:
            try:
                await self._db.executescript("""
                    ALTER TABLE skills ADD COLUMN source TEXT NOT NULL DEFAULT 'user';
                """)
            except sqlite3.OperationalError:
                pass
            await self._db.execute("UPDATE skills SET source = 'system' WHERE is_builtin = 1")
            await self._db.execute(
                "UPDATE skills SET source = 'system' WHERE name IN "
                "('agent-creator', 'file-generator', 'video-capture', 'windows_file_manager', 'skill-security-auditor')"
            )
            await self._db.execute(
                "UPDATE skills SET source = 'plugin:home_assistant' WHERE name = 'home-assistant-control'"
            )
            await self._db.execute(
                "DELETE FROM skills WHERE name IN ('blender-modeling', 'flutter-app-creator', 'unity-mpc-skill')"
            )
            await self._db.commit()
            log.info("Migration 42: skills now record their source; retired skills removed")

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
