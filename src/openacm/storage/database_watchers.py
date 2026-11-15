"""What the OS watcher sees, detected routines and the cron scheduler's jobs."""
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


class WatchersMixin:
    """Part of Database (what the os watcher sees, detected routines and the cron scheduler's jobs); Database inherits it."""

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
        project_name: str = "",
    ) -> int:
        """Record a single app focus session (sensitive fields encrypted if configured)."""
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO app_activities "
            "(app_name, window_title, process_name, focus_seconds, "
            " session_start, session_end, day_of_week, hour_of_day, exe_path, project_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                self._e(project_name) if project_name else "",
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
        Find an existing routine whose composite app keys match (order-independent).
        Composite key = "AppName [ProjectName]" when project is set, else "AppName".
        """
        if not self._db:
            return None
        import json as _json
        all_routines = await self.get_all_routines()
        target = sorted(apps)
        for r in all_routines:
            try:
                stored_apps = _json.loads(r.get("apps", "[]"))
                stored_keys = sorted(
                    (
                        f"{a['app_name']} [{a['project_name']}]"
                        if isinstance(a, dict) and a.get("project_name")
                        else (a["app_name"] if isinstance(a, dict) else str(a))
                    )
                    for a in stored_apps
                )
                if stored_keys == target:
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
            (last_run, next_run or None, status, truncate(output, TRUNCATE_DB_OUTPUT_CHARS) if output else None, job_id),
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
             truncate(output, TRUNCATE_DB_OUTPUT_CHARS) if output else None,
             truncate(error, TRUNCATE_DB_ERROR_CHARS) if error else None,
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
