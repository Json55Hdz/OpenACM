"""Dashboard statistics and the skills store."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from openacm.constants import TRUNCATE_DB_OUTPUT_CHARS, TRUNCATE_DB_ERROR_CHARS
from openacm.utils.text import truncate

log = structlog.get_logger()


class SkillsStatsMixin:
    """Part of Database (dashboard statistics and the skills store); Database inherits it."""

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

    async def get_swarm_channel_stats(self, user_id: str) -> list[dict[str, Any]]:
        """Get channel stats for a specific swarm user_id (e.g. 'swarm_myswarm')."""
        if not self._db:
            return []
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
            WHERE user_id = ?
            GROUP BY user_id, channel_id
            ORDER BY last_updated DESC
        """
        cursor = await self._db.execute(query, (user_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_channel_stats(self) -> list[dict[str, Any]]:
        """Get message counts and last activity grouped by user and channel."""
        if not self._db:
            return []

        # We use a subquery to fetch the content of the most recent message,
        # and subquery customer_names to include saved names.
        query = """
            SELECT
                m.user_id,
                m.channel_id,
                COUNT(*) as message_count,
                MAX(m.timestamp) as last_updated,
                (SELECT content FROM messages m2
                 WHERE m2.user_id = m.user_id AND m2.channel_id = m.channel_id
                 ORDER BY id DESC LIMIT 1) as last_message,
                (SELECT cn.name FROM customer_names cn
                 WHERE (cn.user_id = m.user_id AND cn.channel_id = m.channel_id)
                    OR (cn.channel_id = m.channel_id)
                 LIMIT 1) as customer_name
            FROM messages m
            WHERE m.user_id NOT LIKE 'swarm_%'
            GROUP BY m.user_id, m.channel_id
            ORDER BY last_updated DESC
        """
        cursor = await self._db.execute(query)
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            r = dict(row)
            if r.get("last_message"):
                try:
                    r["last_message"] = self._d(r["last_message"])
                except Exception:
                    pass
            result.append(r)
        return result

    # ─── Skills ───────────────────────────────────────────────

    async def create_skill(
        self,
        name: str,
        description: str,
        content: str,
        category: str = "general",
        is_builtin: bool = False,
        worker_id: int | None = None,
        agent_id: int | None = None,
        flow_id: int | None = None,
    ) -> int:
        """Create a new skill. worker_id=None + agent_id=None + flow_id=None
        makes it a global system skill; setting exactly one of the three
        scopes it privately to that worker/agent/flow."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO skills (name, description, content, category, is_builtin, worker_id, agent_id, flow_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, description, content, category, int(is_builtin), worker_id, agent_id, flow_id),
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
        """Get all GLOBAL skills (never includes a worker- or agent-private skill)."""
        if not self._db:
            return []
        query = "SELECT * FROM skills WHERE worker_id IS NULL AND agent_id IS NULL AND flow_id IS NULL"
        if active_only:
            query += " AND is_active = 1"
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

    async def get_worker_private_skills(self, worker_id: int) -> list[dict[str, Any]]:
        """Get a worker's own private skills (worker_id set to it)."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM skills WHERE worker_id = ? ORDER BY category, name",
            (worker_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_worker_enabled_global_skill_ids(self, worker_id: int) -> set[int]:
        """IDs of global skills this worker has opted into."""
        if not self._db:
            return set()
        cursor = await self._db.execute(
            "SELECT skill_id FROM worker_skills WHERE worker_id = ?", (worker_id,)
        )
        rows = await cursor.fetchall()
        return {row["skill_id"] for row in rows}

    async def enable_worker_skill(self, worker_id: int, skill_id: int) -> None:
        """Enable a global skill for a worker. Idempotent."""
        if not self._db:
            return
        await self._db.execute(
            "INSERT OR IGNORE INTO worker_skills (worker_id, skill_id) VALUES (?, ?)",
            (worker_id, skill_id),
        )
        await self._db.commit()

    async def disable_worker_skill(self, worker_id: int, skill_id: int) -> None:
        """Disable a global skill for a worker. Idempotent."""
        if not self._db:
            return
        await self._db.execute(
            "DELETE FROM worker_skills WHERE worker_id = ? AND skill_id = ?",
            (worker_id, skill_id),
        )
        await self._db.commit()

    async def get_agent_private_skills(self, agent_id: int) -> list[dict[str, Any]]:
        """Get an Agent's own private skills (agent_id set to it)."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM skills WHERE agent_id = ? ORDER BY category, name",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_agent_enabled_global_skill_ids(self, agent_id: int) -> set[int]:
        """IDs of global skills this Agent has opted into."""
        if not self._db:
            return set()
        cursor = await self._db.execute(
            "SELECT skill_id FROM agent_skills WHERE agent_id = ?", (agent_id,)
        )
        rows = await cursor.fetchall()
        return {row["skill_id"] for row in rows}

    async def enable_agent_skill(self, agent_id: int, skill_id: int) -> None:
        """Enable a global skill for an Agent. Idempotent."""
        if not self._db:
            return
        await self._db.execute(
            "INSERT OR IGNORE INTO agent_skills (agent_id, skill_id) VALUES (?, ?)",
            (agent_id, skill_id),
        )
        await self._db.commit()

    async def disable_agent_skill(self, agent_id: int, skill_id: int) -> None:
        """Disable a global skill for an Agent. Idempotent."""
        if not self._db:
            return
        await self._db.execute(
            "DELETE FROM agent_skills WHERE agent_id = ? AND skill_id = ?",
            (agent_id, skill_id),
        )
        await self._db.commit()

    async def get_flow_skill(self, flow_id: int) -> dict[str, Any] | None:
        """A flow has zero or one skill (singular by design, unlike the
        many-global-skills-per-agent/worker pattern)."""
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM skills WHERE flow_id = ?", (flow_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
