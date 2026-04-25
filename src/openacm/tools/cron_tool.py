"""
Cron Scheduler Tools — let the LLM manage scheduled background jobs.

The AI can list, create, delete, enable/disable, and trigger cron jobs.
This makes it possible to automate tasks conversationally:
  "Schedule pattern analysis every night at 2 AM"
  "Look at my routines and create cron jobs for the time-based ones"
  "Show me all scheduled jobs"
"""

import json

import structlog

from openacm.tools.base import tool

log = structlog.get_logger()

# Module-level scheduler reference — set by app.py after init
_cron_scheduler = None


# ─── list_cron_jobs ───────────────────────────────────────────────────────────

@tool(
    name="list_cron_jobs",
    description=(
        "List all scheduled cron jobs. Shows each job's name, cron expression, "
        "action type, enabled state, last run, next run, and run count. "
        "Use this to understand what automated tasks are configured."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    risk_level="low",
    category="system",
)
async def list_cron_jobs(_brain=None, **kwargs) -> str:
    db = _get_db(_brain)
    if not db:
        return "Error: database not available."

    jobs = await db.get_all_cron_jobs()
    if not jobs:
        return "No cron jobs scheduled yet."

    import os
    port = os.environ.get("OPENACM_PORT", "47821")
    lines = [f"📅 Cron Jobs ({len(jobs)} total)\n"]
    for job in jobs:
        enabled = "✅" if job.get("is_enabled") else "⏸️"
        payload = _fmt_payload(job.get("action_type", ""), job.get("action_payload", "{}"))
        lines.append(
            f"{enabled} [{job['id']}] {job['name']}\n"
            f"   Expr:   {job['cron_expr']}  →  {_describe_cron(job['cron_expr'])}\n"
            f"   Action: {job['action_type']}{payload}\n"
            f"   Runs:   {job.get('run_count', 0)}  |  "
            f"Last: {_fmt_dt(job.get('last_run'))}  |  "
            f"Next: {_fmt_dt(job.get('next_run'))}\n"
            f"   Status: {job.get('last_status', 'pending')}"
            + (f"\n   Desc:   {job['description']}" if job.get('description') else "")
        )

    lines.append(f"\n[Ver Cron Jobs →](http://localhost:{port}/cron)")
    return "\n\n".join(lines)


# ─── create_cron_job ──────────────────────────────────────────────────────────

@tool(
    name="create_cron_job",
    description=(
        "Create a new scheduled cron job. Supports five action types:\n"
        "- 'analyze_patterns': runs the OS activity pattern analyzer (no payload needed)\n"
        "- 'run_skill': runs a named skill (payload: {\"skill_name\": \"name\"})\n"
        "- 'run_routine': launches a detected routine by ID (payload: {\"routine_id\": N})\n"
        "- 'custom_command': runs a shell command (payload: {\"command\": \"...\", \"shell\": true})\n"
        "- 'send_message': sends a message to the AI brain on schedule (payload: {\"message\": \"...\"})\n"
        "  Use 'send_message' to schedule any AI task: 'every morning summarize my emails', 'at 9am check system health'\n\n"
        "Cron expression uses 5 fields: MIN HOUR DOM MONTH DOW. Examples:\n"
        "'0 9 * * 1-5' = every weekday at 9am, '0 2 * * *' = every day at 2am, "
        "'*/30 * * * *' = every 30 minutes. Also accepts @hourly, @daily, @weekly."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Short descriptive name for the job",
            },
            "cron_expr": {
                "type": "string",
                "description": "Cron expression (5 fields) or @shortcut. E.g. '0 9 * * 1-5'",
            },
            "action_type": {
                "type": "string",
                "description": "What to run: 'analyze_patterns', 'run_skill', 'run_routine', 'custom_command', 'send_message'",
                "enum": ["analyze_patterns", "run_skill", "run_routine", "custom_command", "send_message"],
            },
            "action_payload": {
                "type": "object",
                "description": "Configuration for the action. See tool description for shape per action_type.",
            },
            "description": {
                "type": "string",
                "description": "Optional human-friendly description of why this job exists",
            },
            "enabled": {
                "type": "boolean",
                "description": "Whether to enable the job immediately (default true)",
                "default": True,
            },
        },
        "required": ["name", "cron_expr", "action_type"],
    },
    risk_level="medium",
    category="system",
)
async def create_cron_job(
    name: str,
    cron_expr: str,
    action_type: str,
    action_payload: dict | None = None,
    description: str = "",
    enabled: bool = True,
    _brain=None,
    **kwargs,
) -> str:
    db = _get_db(_brain)
    if not db:
        return "Error: database not available."

    if not _validate_expr(cron_expr):
        return f"Error: invalid cron expression '{cron_expr}'. Need 5 fields (min hour dom month dow) or @shortcut."

    valid_types = {"analyze_patterns", "run_skill", "run_routine", "custom_command"}
    if action_type not in valid_types:
        return f"Error: action_type must be one of {valid_types}"

    payload = action_payload or {}

    # Validation per action type
    if action_type == "run_skill" and not payload.get("skill_name"):
        return "Error: 'run_skill' requires action_payload.skill_name"
    if action_type == "run_routine" and payload.get("routine_id") is None:
        return "Error: 'run_routine' requires action_payload.routine_id"
    if action_type == "custom_command" and not payload.get("command"):
        return "Error: 'custom_command' requires action_payload.command"
    if action_type == "send_message" and not payload.get("message"):
        return "Error: 'send_message' requires action_payload.message"

    from openacm.watchers.cron_scheduler import compute_next_run
    next_run = compute_next_run(cron_expr)

    job = await db.create_cron_job(
        name=name,
        description=description,
        cron_expr=cron_expr,
        action_type=action_type,
        action_payload=payload,
        is_enabled=enabled,
        next_run=next_run,
    )

    # Reload scheduler
    if _cron_scheduler:
        await _cron_scheduler._sync_jobs()

    import os
    port = os.environ.get("OPENACM_PORT", "47821")
    return (
        f"✅ Cron job creado (ID: {job.get('id')})\n"
        f"   Nombre: {name}\n"
        f"   Expr:   {cron_expr}  →  {_describe_cron(cron_expr)}\n"
        f"   Acción: {action_type}" + (_fmt_payload(action_type, json.dumps(payload)) or "") + "\n"
        f"   Próxima ejecución: {_fmt_dt(next_run)}\n"
        f"   Habilitado: {'sí' if enabled else 'no'}\n\n"
        f"[Ver Cron Jobs →](http://localhost:{port}/cron)"
    )


# ─── delete_cron_job ──────────────────────────────────────────────────────────

@tool(
    name="delete_cron_job",
    description="Delete a cron job by its ID. Also deletes all its run history.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {
                "type": "integer",
                "description": "The numeric ID of the cron job to delete",
            },
        },
        "required": ["job_id"],
    },
    risk_level="medium",
    category="system",
)
async def delete_cron_job(job_id: int, _brain=None, **kwargs) -> str:
    db = _get_db(_brain)
    if not db:
        return "Error: database not available."

    job = await db.get_cron_job(job_id)
    if not job:
        return f"Error: cron job ID {job_id} not found."

    await db.delete_cron_job(job_id)
    if _cron_scheduler:
        await _cron_scheduler._sync_jobs()

    return f"🗑️ Cron job '{job['name']}' (ID: {job_id}) deleted."


# ─── toggle_cron_job ──────────────────────────────────────────────────────────

@tool(
    name="toggle_cron_job",
    description="Enable or disable a cron job by its ID without deleting it.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {
                "type": "integer",
                "description": "The numeric ID of the cron job to toggle",
            },
            "enabled": {
                "type": "boolean",
                "description": "True to enable, false to disable. If omitted, flips the current state.",
            },
        },
        "required": ["job_id"],
    },
    risk_level="low",
    category="system",
)
async def toggle_cron_job(job_id: int, enabled: bool | None = None, _brain=None, **kwargs) -> str:
    db = _get_db(_brain)
    if not db:
        return "Error: database not available."

    job = await db.get_cron_job(job_id)
    if not job:
        return f"Error: cron job ID {job_id} not found."

    new_state = enabled if enabled is not None else not bool(job.get("is_enabled"))
    await db.update_cron_job(job_id, is_enabled=new_state)
    if _cron_scheduler:
        await _cron_scheduler._sync_jobs()

    state_str = "enabled ✅" if new_state else "disabled ⏸️"
    return f"Cron job '{job['name']}' (ID: {job_id}) is now {state_str}."


# ─── trigger_cron_job ─────────────────────────────────────────────────────────

@tool(
    name="trigger_cron_job",
    description=(
        "Run a cron job immediately, regardless of its schedule. "
        "Returns the execution output. Useful to test a job or run it on-demand."
    ),
    parameters={
        "type": "object",
        "properties": {
            "job_id": {
                "type": "integer",
                "description": "The numeric ID of the cron job to trigger",
            },
        },
        "required": ["job_id"],
    },
    risk_level="medium",
    category="system",
)
async def trigger_cron_job(job_id: int, _brain=None, **kwargs) -> str:
    if not _cron_scheduler:
        return "Error: cron scheduler is not running."

    db = _get_db(_brain)
    if db:
        job = await db.get_cron_job(job_id)
        if not job:
            return f"Error: cron job ID {job_id} not found."
        job_name = job["name"]
    else:
        job_name = f"job {job_id}"

    result = await _cron_scheduler.trigger_now(job_id)

    if result.get("status") == "error":
        return (
            f"❌ Job '{job_name}' failed.\n"
            f"   Error: {result.get('error', 'unknown')}"
        )

    output = result.get("output", "").strip()
    elapsed = result.get("elapsed_ms", 0)
    next_run = _fmt_dt(result.get("next_run"))
    return (
        f"✅ Job '{job_name}' completed in {elapsed}ms.\n"
        + (f"   Output: {output[:800]}\n" if output else "")
        + f"   Next scheduled run: {next_run}"
    )


# ─── update_cron_job ──────────────────────────────────────────────────────────

@tool(
    name="update_cron_job",
    description=(
        "Update an existing cron job's name, schedule, or action. "
        "Only pass the fields you want to change; others stay as-is."
    ),
    parameters={
        "type": "object",
        "properties": {
            "job_id": {
                "type": "integer",
                "description": "The numeric ID of the cron job to update",
            },
            "name": {"type": "string", "description": "New name (optional)"},
            "cron_expr": {"type": "string", "description": "New cron expression (optional)"},
            "action_type": {
                "type": "string",
                "description": "New action type (optional)",
                "enum": ["analyze_patterns", "run_skill", "run_routine", "custom_command", "send_message"],
            },
            "action_payload": {"type": "object", "description": "New action payload (optional)"},
            "description": {"type": "string", "description": "New description (optional)"},
        },
        "required": ["job_id"],
    },
    risk_level="medium",
    category="system",
)
async def update_cron_job(
    job_id: int,
    name: str | None = None,
    cron_expr: str | None = None,
    action_type: str | None = None,
    action_payload: dict | None = None,
    description: str | None = None,
    _brain=None,
    **kwargs,
) -> str:
    db = _get_db(_brain)
    if not db:
        return "Error: database not available."

    job = await db.get_cron_job(job_id)
    if not job:
        return f"Error: cron job ID {job_id} not found."

    if cron_expr and not _validate_expr(cron_expr):
        return f"Error: invalid cron expression '{cron_expr}'."

    updates: dict = {}
    if name is not None:
        updates["name"] = name
    if cron_expr is not None:
        updates["cron_expr"] = cron_expr
        from openacm.watchers.cron_scheduler import compute_next_run
        updates["next_run"] = compute_next_run(cron_expr)
    if action_type is not None:
        updates["action_type"] = action_type
    if action_payload is not None:
        updates["action_payload"] = action_payload
    if description is not None:
        updates["description"] = description

    if not updates:
        return "Nada que actualizar — no enviaste campos nuevos."

    await db.update_cron_job(job_id, **updates)
    if _cron_scheduler:
        await _cron_scheduler._sync_jobs()

    import os
    port = os.environ.get("OPENACM_PORT", "47821")
    return (
        f"✅ Cron job '{job['name']}' (ID: {job_id}) actualizado.\n\n"
        f"[Ver Cron Jobs →](http://localhost:{port}/cron)"
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_db(brain):
    """Get the database from the brain's skill manager."""
    if brain and brain.skill_manager and brain.skill_manager.database:
        return brain.skill_manager.database
    return None


def _validate_expr(expr: str) -> bool:
    shortcuts = {"@hourly", "@daily", "@midnight", "@weekly", "@monthly"}
    if expr.strip() in shortcuts:
        return True
    return len(expr.strip().split()) == 5


def _describe_cron(expr: str) -> str:
    shortcuts = {
        "@hourly": "every hour",
        "@daily": "every day at midnight",
        "@weekly": "every Sunday at midnight",
        "@monthly": "every 1st at midnight",
    }
    if expr.strip() in shortcuts:
        return shortcuts[expr.strip()]
    parts = expr.strip().split()
    if len(parts) != 5:
        return expr
    min_, hour, dom, _, dow = parts
    time_s = (
        "every minute" if (min_ == "*" and hour == "*") else
        "every hour" if (min_ == "0" and hour == "*") else
        f"every {min_[2:]} min" if (min_.startswith("*/") and hour == "*") else
        f"at {hour.zfill(2)}:{min_.zfill(2)}"
    )
    dow_map = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat"}
    dow_s = "" if dow == "*" else f" on {','.join(dow_map.get(d, d) for d in dow.split(','))}"
    dom_s = "" if dom == "*" else f" on day {dom}"
    return f"{time_s}{dom_s}{dow_s}"


def _fmt_payload(action_type: str, payload_raw: str) -> str:
    try:
        p = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
    except Exception:
        return ""
    if action_type == "run_skill":
        return f" ({p.get('skill_name', '')})"
    if action_type == "run_routine":
        return f" (routine ID {p.get('routine_id', '')})"
    if action_type == "custom_command":
        cmd = str(p.get("command", ""))[:50]
        return f" (`{cmd}`)"
    return ""


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso
