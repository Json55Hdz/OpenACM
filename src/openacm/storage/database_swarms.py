"""Swarms, their workers, tasks, messages and templates."""
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


class SwarmsMixin:
    """Part of Database (swarms, their workers, tasks, messages and templates); Database inherits it."""

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
                   "shared_context", "context_files", "working_path",
                   "clarification_questions", "clarification_answers"}
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

    async def clear_swarm_plan(self, swarm_id: int) -> None:
        """Delete all workers and tasks for a swarm (used before re-planning)."""
        if not self._db:
            return
        await self._db.execute("DELETE FROM swarm_tasks WHERE swarm_id = ?", (swarm_id,))
        await self._db.execute("DELETE FROM swarm_workers WHERE swarm_id = ?", (swarm_id,))
        await self._db.commit()

    async def clear_swarm_messages(self, swarm_id: int) -> None:
        """Delete all activity messages for a swarm."""
        if not self._db:
            return
        await self._db.execute("DELETE FROM swarm_messages WHERE swarm_id = ?", (swarm_id,))
        await self._db.commit()

    async def reset_swarm_tasks(self, swarm_id: int) -> None:
        """Reset all tasks for a swarm back to pending with cleared results (keeps task definitions)."""
        if not self._db:
            return
        await self._db.execute(
            "UPDATE swarm_tasks SET status = 'pending', result = NULL, retry_history_json = '[]' WHERE swarm_id = ?",
            (swarm_id,),
        )
        await self._db.execute(
            "UPDATE swarm_workers SET status = 'idle' WHERE swarm_id = ?",
            (swarm_id,),
        )
        await self._db.commit()

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
        task_type: str = "standard",
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO swarm_tasks (swarm_id, worker_id, title, description, depends_on, task_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (swarm_id, worker_id, title, description, depends_on, task_type),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_swarm_task(self, task_id: int) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM swarm_tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

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
        allowed = {"worker_id", "title", "description", "depends_on", "status", "result", "retry_history_json"}
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

    async def get_swarm_team_updates(self, swarm_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent team bulletin board updates (posted via swarm_post_update)."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT m.*, fw.name as from_worker_name "
            "FROM swarm_messages m "
            "LEFT JOIN swarm_workers fw ON fw.id = m.from_worker_id "
            "WHERE m.swarm_id = ? AND m.message_type = 'team_update' "
            "ORDER BY m.id DESC LIMIT ?",
            (swarm_id, limit),
        )
        rows = await cursor.fetchall()
        return list(reversed([dict(r) for r in rows]))

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
