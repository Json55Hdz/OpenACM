# Cron Scheduler

OpenACM includes a built-in asyncio-based cron scheduler that runs recurring background jobs on a configurable schedule — with no external cron library required.

---

## Overview

The Cron Scheduler allows you to automate tasks inside OpenACM that should run on a time-based schedule. Examples:

- Run pattern analysis every night at 2 AM
- Execute a skill every weekday morning
- Run a shell script on the first of each month
- Launch a detected routine every Monday at 9 AM

The scheduler starts automatically with OpenACM, polls every 30 seconds for due jobs, and fires them concurrently without blocking the main loop.

---

## Cron Expression Format

Jobs use standard 5-field cron expressions:

```
MIN  HOUR  DOM  MONTH  DOW
```

| Field | Range | Special |
|-------|-------|---------|
| MIN | 0–59 | `*`, `*/N`, `N-M`, `N,M` |
| HOUR | 0–23 | same |
| DOM | 1–31 | same |
| MONTH | 1–12 | same |
| DOW | 0–6 (0=Sun) | same |

### Examples

| Expression | Meaning |
|------------|---------|
| `0 9 * * 1-5` | Every weekday at 9:00 AM |
| `*/5 * * * *` | Every 5 minutes |
| `0 0 * * *` | Every day at midnight |
| `0 8 * * 1` | Every Monday at 8:00 AM |
| `30 14 1 * *` | 1st of each month at 14:30 |
| `@hourly` | Every hour (shortcut) |
| `@daily` | Every day at midnight (shortcut) |
| `@weekly` | Every Sunday at midnight (shortcut) |
| `@monthly` | Every 1st of month at midnight (shortcut) |

---

## Action Types

Each cron job has an **action type** that determines what runs when the schedule fires.

### `analyze_patterns`
Runs the OS activity pattern analyzer to detect new routines from recent app usage.

```json
{ "action_payload": {} }
```

No configuration needed.

### `run_skill`
Executes a named skill through the AI brain.

```json
{
  "action_payload": {
    "skill_name": "daily_summary"
  }
}
```

### `run_routine`
Launches a detected routine by ID, opening all its configured apps.

```json
{
  "action_payload": {
    "routine_id": 3
  }
}
```

### `custom_command`
Runs an arbitrary shell command.

```json
{
  "action_payload": {
    "command": "python /scripts/backup.py",
    "shell": true,
    "timeout": 60
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `command` | required | The command to run |
| `shell` | `true` | Run via shell (allows pipes, env vars) |
| `timeout` | `30` | Max seconds before killing the process |

---

## Dashboard UI

Navigate to **Cron Scheduler** in the sidebar (clock icon).

### Creating a job
1. Click **New Job**
2. Enter a name and optional description
3. Type a cron expression, or click a **quick preset**
4. The human-readable description updates live as you type
5. Select an action type and fill in its configuration
6. Toggle enabled and save

### Managing jobs
Each job card shows:
- Cron expression with human-readable translation
- Last run time and status
- Next scheduled run time
- Run count
- Last output (expandable)

Actions per card:
- **Toggle** (enable/disable)
- **Run now** (trigger immediately, regardless of schedule)
- **Edit**
- **Delete**

### Execution History
Click **Execution History** at the bottom of the page to expand the run log. Each entry shows the job name, timestamp, trigger source (scheduler or manual), status, and truncated output.

---

## REST API Reference

All endpoints require the standard `Authorization: Bearer <token>` header.

### List jobs
```
GET /api/cron/jobs
```
Returns `{ "jobs": [...] }`.

### Create job
```
POST /api/cron/jobs
Content-Type: application/json

{
  "name": "Daily Analysis",
  "description": "Run pattern analysis every night",
  "cron_expr": "0 2 * * *",
  "action_type": "analyze_patterns",
  "action_payload": {},
  "is_enabled": true
}
```

### Get job
```
GET /api/cron/jobs/{job_id}
```

### Update job
```
PUT /api/cron/jobs/{job_id}
Content-Type: application/json

{
  "name": "New name",
  "cron_expr": "0 3 * * *",
  "is_enabled": false
}
```
Only the fields you include are updated. If `cron_expr` changes, `next_run` is automatically recomputed.

### Delete job
```
DELETE /api/cron/jobs/{job_id}
```
Deletes the job and all its run history.

### Trigger immediately
```
POST /api/cron/jobs/{job_id}/trigger
```
Fires the job right now and returns the result:
```json
{
  "status": "success",
  "output": "Pattern analysis complete. 2 new routine(s) detected.",
  "error": "",
  "elapsed_ms": 1234,
  "next_run": "2026-04-05T02:00:00+00:00"
}
```

### Toggle enabled/disabled
```
POST /api/cron/jobs/{job_id}/toggle
```
Returns `{ "status": "ok", "is_enabled": true }`.

### Run history
```
GET /api/cron/runs?job_id=3&limit=50
```
`job_id` is optional. Returns `{ "runs": [...] }`.

### Scheduler status
```
GET /api/cron/status
```
```json
{
  "running": true,
  "job_count": 4,
  "enabled_count": 3,
  "next_job_name": "Daily Analysis",
  "next_job_at": "2026-04-05T02:00:00+00:00"
}
```

---

## Architecture

The scheduler lives in `src/openacm/watchers/cron_scheduler.py` as the `CronScheduler` class.

```
app.py
 └─ _init_watchers()
     └─ CronScheduler(database, brain).start()
         └─ asyncio.Task: _loop()
             ├─ _sync_jobs()   ← reloads DB every 30 s
             └─ _fire_job()    ← asyncio.create_task per due job
```

**Key design decisions:**

- **No external library.** The cron expression parser is pure Python using set arithmetic. Supports `*`, `*/N`, `N-M`, `N,M`, and `@shortcuts`.
- **30-second poll.** Jobs fire within ±30 seconds of their scheduled time. This is intentional — sub-minute precision is rarely needed for background automation.
- **Concurrent execution.** Each due job runs as an independent `asyncio.Task` so slow jobs don't delay others.
- **Persistent run log.** Every execution writes to the `cron_job_runs` table. The job row stores a summary (`last_status`, `last_output`, `last_run`, `next_run`).
- **DB sync on every poll.** Changes made via the API (create/update/toggle/delete) take effect within 30 seconds without a restart.

---

## Database Schema

### `cron_jobs`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| name | TEXT | Job name |
| description | TEXT | Optional description |
| cron_expr | TEXT | 5-field cron or @shortcut |
| action_type | TEXT | `run_skill` / `run_routine` / `analyze_patterns` / `custom_command` |
| action_payload | TEXT | JSON configuration for the action |
| is_enabled | INTEGER | 1 = enabled, 0 = disabled |
| last_run | TEXT | ISO datetime of last execution |
| next_run | TEXT | ISO datetime of next scheduled execution |
| run_count | INTEGER | Total number of times fired |
| last_status | TEXT | `pending` / `success` / `error` / `running` |
| last_output | TEXT | Truncated output of last run |
| created_at | DATETIME | Creation timestamp |
| updated_at | DATETIME | Last update timestamp |

### `cron_job_runs`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| job_id | INTEGER | FK → cron_jobs.id (CASCADE DELETE) |
| started_at | TEXT | ISO datetime when execution started |
| finished_at | TEXT | ISO datetime when execution ended |
| status | TEXT | `running` / `success` / `error` |
| output | TEXT | Stdout/result (truncated to 4000 chars) |
| error | TEXT | Error message if failed |
| triggered_by | TEXT | `scheduler` or `manual` |

---

## Limitations

- **Precision:** Jobs fire within ~30 seconds of the scheduled time, not exactly at the second.
- **Missed jobs:** If OpenACM was stopped when a job was due, the missed execution is NOT replayed on restart. The scheduler simply computes the next future occurrence.
- **Single node:** No distributed locking — intended for single-instance deployments.
- **Cron precision minimum:** The minimum effective interval is ~30 seconds (one poll cycle). Using `* * * * *` (every minute) will fire approximately every 30–90 seconds in practice.
