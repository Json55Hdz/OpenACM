"""
Asyncio-based cron scheduler for OpenACM.

Runs scheduled jobs (skills, routines, pattern analysis, shell commands)
without any external cron library dependency. Uses a pure-Python 5-field
cron expression parser with a 30-second polling loop.
"""

import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

log = structlog.get_logger()


# ─── Cron Expression Parser ───────────────────────────────────────────────────

def _parse_field(expr: str, lo: int, hi: int) -> set[int]:
    """Parse one cron field into a set of matching integers."""
    values: set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(lo, hi + 1))
        elif part.startswith("*/"):
            step = int(part[2:])
            values.update(range(lo, hi + 1, step))
        elif "-" in part:
            a, b = part.split("-", 1)
            values.update(range(int(a), int(b) + 1))
        else:
            values.add(int(part))
    return values


def _next_cron_datetime(expr: str, after: datetime) -> datetime:
    """Return the next datetime >= after+1min that matches the cron expression."""
    # Handle named shortcuts
    shortcuts = {
        "@hourly":   "0 * * * *",
        "@daily":    "0 0 * * *",
        "@midnight": "0 0 * * *",
        "@weekly":   "0 0 * * 0",
        "@monthly":  "0 0 1 * *",
    }
    expr = shortcuts.get(expr.strip(), expr)

    fields = expr.strip().split()
    if len(fields) != 5:
        raise ValueError(f"Invalid cron expression (need 5 fields): {expr!r}")

    mins   = _parse_field(fields[0], 0, 59)
    hours  = _parse_field(fields[1], 0, 23)
    mdays  = _parse_field(fields[2], 1, 31)
    months = _parse_field(fields[3], 1, 12)
    wdays  = _parse_field(fields[4], 0, 6)  # 0=Sunday … 6=Saturday

    # Start searching from the next minute
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

    # Safety cap: never loop more than 366 days
    limit = candidate + timedelta(days=366)
    while candidate < limit:
        if candidate.month not in months:
            # Jump to first day of next matching month
            candidate = candidate.replace(day=1, hour=0, minute=0)
            candidate += timedelta(days=32)
            candidate = candidate.replace(day=1)
            continue
        if candidate.day not in mdays and (candidate.weekday() + 1) % 7 not in wdays:
            # weekday(): Mon=0…Sun=6 → cron: Sun=0…Sat=6
            candidate = candidate.replace(hour=0, minute=0) + timedelta(days=1)
            continue
        if candidate.hour not in hours:
            candidate = candidate.replace(minute=0) + timedelta(hours=1)
            continue
        if candidate.minute not in mins:
            candidate += timedelta(minutes=1)
            continue
        return candidate

    raise RuntimeError(f"Could not find next occurrence for cron expression: {expr!r}")


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class CronJob:
    id: int
    name: str
    description: str
    cron_expr: str
    action_type: str   # run_skill | run_routine | analyze_patterns | custom_command | run_swarm_template
    action_payload: dict
    is_enabled: bool
    last_run: str | None
    next_run: str | None
    run_count: int = 0
    last_status: str = "pending"

    @property
    def next_run_dt(self) -> datetime | None:
        if not self.next_run:
            return None
        try:
            return datetime.fromisoformat(self.next_run)
        except Exception:
            return None


# ─── Scheduler ───────────────────────────────────────────────────────────────

class CronScheduler:
    """Asyncio-based scheduler — polls every 30 s, fires due jobs concurrently."""

    POLL_INTERVAL = 30  # seconds

    def __init__(self, database: Any, brain: Any = None, swarm_manager: Any = None):
        self._db = database
        self._brain = brain
        self._swarm_manager = swarm_manager
        self._task: asyncio.Task | None = None
        self._running = False
        self._jobs: dict[int, CronJob] = {}

    # ── Public control ────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self._sync_jobs()
        self._task = asyncio.create_task(self._loop())
        log.info("CronScheduler started", job_count=len(self._jobs))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("CronScheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    async def trigger_now(self, job_id: int) -> dict:
        """Immediately fire a job regardless of schedule. Returns result dict."""
        job = self._jobs.get(job_id)
        if job is None:
            # Reload from DB in case it was just created
            await self._sync_jobs()
            job = self._jobs.get(job_id)
        if job is None:
            return {"status": "error", "error": f"Job {job_id} not found"}
        return await self._fire_job(job, triggered_by="manual")

    def next_due_job(self) -> CronJob | None:
        """Return the enabled job with the earliest next_run, or None."""
        enabled = [j for j in self._jobs.values() if j.is_enabled and j.next_run]
        if not enabled:
            return None
        return min(enabled, key=lambda j: j.next_run or "")

    # ── Internal loop ─────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._sync_jobs()
                now = datetime.now(timezone.utc)
                due = [
                    j for j in self._jobs.values()
                    if j.is_enabled and j.next_run_dt and j.next_run_dt <= now
                ]
                for job in due:
                    asyncio.create_task(self._fire_job(job))
            except Exception as exc:
                log.error("CronScheduler loop error", error=str(exc))

            await asyncio.sleep(self.POLL_INTERVAL)

    async def _sync_jobs(self) -> None:
        """Reload enabled job definitions from the DB."""
        if not self._db:
            return
        try:
            rows = await self._db.get_all_cron_jobs()
            self._jobs = {}
            for row in rows:
                payload = row.get("action_payload", "{}")
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                self._jobs[row["id"]] = CronJob(
                    id=row["id"],
                    name=row["name"],
                    description=row.get("description", ""),
                    cron_expr=row["cron_expr"],
                    action_type=row["action_type"],
                    action_payload=payload,
                    is_enabled=bool(row.get("is_enabled", 1)),
                    last_run=row.get("last_run"),
                    next_run=row.get("next_run"),
                    run_count=row.get("run_count", 0),
                    last_status=row.get("last_status", "pending"),
                )
        except Exception as exc:
            log.error("CronScheduler _sync_jobs failed", error=str(exc))

    # ── Job execution ─────────────────────────────────────────

    async def _fire_job(self, job: CronJob, triggered_by: str = "scheduler") -> dict:
        """Execute a job, record the run, update next_run."""
        now_str = datetime.now(timezone.utc).isoformat()
        run_id: int | None = None

        try:
            run_id = await self._db.create_cron_run(job.id, now_str, triggered_by)
        except Exception:
            pass

        output = ""
        error_msg = ""
        status = "success"
        start_ms = _now_ms()

        try:
            log.info("CronJob firing", job_id=job.id, name=job.name, action=job.action_type)
            match job.action_type:
                case "run_skill":
                    output = await self._run_skill(job.action_payload)
                case "run_routine":
                    output = await self._run_routine(job.action_payload)
                case "analyze_patterns":
                    output = await self._analyze_patterns(job.action_payload)
                case "custom_command":
                    output = await self._custom_command(job.action_payload)
                case "run_swarm_template":
                    output = await self._run_swarm_template(job.action_payload)
                case _:
                    raise ValueError(f"Unknown action_type: {job.action_type!r}")
        except Exception as exc:
            status = "error"
            error_msg = str(exc)
            log.error("CronJob failed", job_id=job.id, name=job.name, error=error_msg)

        elapsed_ms = _now_ms() - start_ms
        finish_str = datetime.now(timezone.utc).isoformat()

        # Compute next_run
        try:
            next_dt = _next_cron_datetime(job.cron_expr, datetime.now(timezone.utc))
            next_run_str = next_dt.isoformat()
        except Exception:
            next_run_str = None

        # Persist results
        try:
            if run_id:
                await self._db.finish_cron_run(
                    run_id, finish_str, status,
                    output=output or None,
                    error=error_msg or None,
                )
            await self._db.update_cron_job_after_run(
                job.id, finish_str, next_run_str or "", status,
                output=(output or error_msg or ""),
            )
            # Update local cache
            if job.id in self._jobs:
                self._jobs[job.id].last_run = finish_str
                self._jobs[job.id].next_run = next_run_str
                self._jobs[job.id].last_status = status
        except Exception as exc:
            log.error("CronJob persist failed", error=str(exc))

        return {
            "status": status,
            "output": output,
            "error": error_msg,
            "elapsed_ms": elapsed_ms,
            "next_run": next_run_str,
        }

    # ── Action handlers ───────────────────────────────────────

    async def _run_skill(self, payload: dict) -> str:
        skill_name = payload.get("skill_name", "")
        if not skill_name:
            raise ValueError("skill_name is required for run_skill action")
        if not self._brain:
            raise RuntimeError("Brain not available")
        response = await self._brain.process_message(
            content=f"/skill {skill_name}",
            user_id="cron",
            channel_id="cron",
            channel_type="cron",
        )
        return str(response)[:2000]

    async def _run_routine(self, payload: dict) -> str:
        routine_id = payload.get("routine_id")
        if routine_id is None:
            raise ValueError("routine_id is required for run_routine action")
        if not self._db:
            raise RuntimeError("Database not available")
        routine = await self._db.get_routine(int(routine_id))
        if not routine:
            raise ValueError(f"Routine {routine_id} not found")
        from openacm.watchers.routine_executor import RoutineExecutor
        executor = RoutineExecutor()
        await executor.execute(routine)
        return f"Routine '{routine['name']}' executed"

    async def _analyze_patterns(self, payload: dict) -> str:
        if not self._db:
            raise RuntimeError("Database not available")
        llm = self._brain.llm_router if self._brain else None
        from openacm.watchers.pattern_analyzer import PatternAnalyzer
        analyzer = PatternAnalyzer(self._db, llm_router=llm)
        new_routines = await analyzer.analyze()
        return f"Pattern analysis complete. {len(new_routines)} new routine(s) detected."

    async def _run_swarm_template(self, payload: dict) -> str:
        """Create and start a swarm from a saved template.

        Payload keys:
          template_id (int)  — ID of the swarm_templates row
          goal_override (str) — optional goal text that replaces the template's goal_template
                                (supports {date} placeholder)
        """
        template_id = payload.get("template_id")
        if not template_id:
            raise ValueError("template_id is required for run_swarm_template action")
        if not self._db:
            raise RuntimeError("Database not available")
        if not self._swarm_manager:
            raise RuntimeError("SwarmManager not available")

        template = await self._db.get_swarm_template(int(template_id))
        if not template:
            raise ValueError(f"Swarm template {template_id} not found")

        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        goal_override = payload.get("goal_override", "")
        goal = goal_override or template["goal_template"]
        goal = goal.replace("{date}", today)

        # Create swarm from template
        workers = json.loads(template.get("workers", "[]"))
        swarm_id = await self._db.create_swarm(
            name=f"{template['name']} — {today}",
            goal=goal,
            global_model=template.get("global_model") or "",
        )
        for w in workers:
            await self._db.create_swarm_worker(
                swarm_id=swarm_id,
                name=w["name"],
                role=w.get("role", "worker"),
                description=w.get("description", ""),
                system_prompt=w.get("system_prompt", ""),
                model=w.get("model"),
                allowed_tools=w.get("allowed_tools", "all"),
            )

        # Start the swarm in the background
        asyncio.create_task(self._swarm_manager.start(swarm_id))
        return f"Swarm '{template['name']}' started from template (swarm_id={swarm_id}, date={today})"

    async def _custom_command(self, payload: dict) -> str:
        command = payload.get("command", "")
        if not command:
            raise ValueError("command is required for custom_command action")
        use_shell = bool(payload.get("shell", True))
        timeout = int(payload.get("timeout", 30))

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ) if use_shell else await asyncio.create_subprocess_exec(
            *command.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace").strip()
            if proc.returncode != 0:
                raise RuntimeError(f"Exit code {proc.returncode}: {output[:500]}")
            return output[:2000]
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Command timed out after {timeout}s")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def compute_next_run(cron_expr: str) -> str | None:
    """Public helper: compute next ISO timestamp for a cron expression."""
    try:
        dt = _next_cron_datetime(cron_expr, datetime.now(timezone.utc))
        return dt.isoformat()
    except Exception:
        return None
