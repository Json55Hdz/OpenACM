#!/usr/bin/env python3
"""
OpenACM Manager CLI
Manage swarms, cron jobs, routines, activity, skills, and agents
from the console while the server is running.

Usage:
  openacm-manage              -> interactive main menu
  openacm-manage swarms       -> go directly to swarms
  openacm-manage cron         -> go directly to cron jobs
  openacm-manage routines     -> go directly to routines
  openacm-manage skills       -> go directly to skills
  openacm-manage agents       -> go directly to agents
  openacm-manage stats        -> go directly to stats
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values
from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.rule import Rule
from rich.table import Table

console = Console()


# ─── Client ───────────────────────────────────────────────────────────────────


def _find_root() -> Path:
    current = Path.cwd()
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return Path.cwd()


ROOT = _find_root()


def _load_connection() -> tuple[str, str]:
    env_path = ROOT / "config" / ".env"
    env: dict[str, str] = {}
    if env_path.exists():
        env = {k: v for k, v in dotenv_values(env_path).items() if v}

    port = 47821
    local_yaml = ROOT / "config" / "local.yaml"
    if local_yaml.exists():
        try:
            import yaml
            cfg = yaml.safe_load(local_yaml.read_text(encoding="utf-8")) or {}
            port = cfg.get("web", {}).get("port", 47821)
        except Exception:
            pass

    base_url = f"http://127.0.0.1:{port}"
    token = env.get("DASHBOARD_TOKEN", "")
    return base_url, token


class OpenACMClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get(self, path: str, params: dict | None = None) -> Any:
        r = httpx.get(self._url(path), headers=self.headers, params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, data: dict | None = None, form: dict | None = None) -> Any:
        if form:
            r = httpx.post(self._url(path), headers=self.headers, data=form, timeout=30)
        else:
            r = httpx.post(self._url(path), headers=self.headers, json=data or {}, timeout=30)
        r.raise_for_status()
        return r.json()

    def put(self, path: str, data: dict) -> Any:
        r = httpx.put(self._url(path), headers=self.headers, json=data, timeout=15)
        r.raise_for_status()
        return r.json()

    def delete(self, path: str, data: dict | None = None) -> Any:
        r = httpx.delete(self._url(path), headers=self.headers, json=data, timeout=15)
        r.raise_for_status()
        return r.json()

    def ping(self) -> bool:
        try:
            r = httpx.get(self._url("/api/ping"), headers=self.headers, timeout=5)
            return r.status_code == 200
        except Exception:
            return False


# ─── UI helpers ───────────────────────────────────────────────────────────────


def header(title: str, subtitle: str = "") -> None:
    console.clear()
    sub = f"\n[dim]{subtitle}[/dim]" if subtitle else ""
    console.print(Panel(
        f"[bold cyan]OpenACM[/bold cyan]  [dim]>[/dim]  [bold]{title}[/bold]{sub}",
        border_style="cyan", padding=(0, 2),
    ))
    console.print()


def pause(msg: str = "Press Enter to go back") -> None:
    Prompt.ask(f"\n  [dim]{msg}[/dim]", default="", show_default=False)


def err(msg: str) -> None:
    console.print(f"\n  [red]Error:[/red] {msg}")


def ok_msg(msg: str) -> None:
    console.print(f"\n  [green]{msg}[/green]")


STATUS_COLORS: dict[str, str] = {
    "running":    "green",
    "active":     "green",
    "completed":  "blue",
    "failed":     "red",
    "paused":     "yellow",
    "pending":    "dim",
    "draft":      "dim",
    "planned":    "cyan",
    "idle":       "dim",
    "inactive":   "dim",
}


def status_tag(s: str) -> str:
    color = STATUS_COLORS.get(s.lower(), "white")
    return f"[{color}]{s}[/{color}]"


# ─── SWARMS ───────────────────────────────────────────────────────────────────


def swarms_menu(client: OpenACMClient) -> None:
    while True:
        header("Swarms", "Multi-agent orchestration")

        try:
            swarms = client.get("/api/swarms")
        except Exception as e:
            err(str(e))
            pause()
            return

        if swarms:
            t = Table(box=box.ROUNDED)
            t.add_column("ID",      style="dim", width=5)
            t.add_column("Name",    min_width=18)
            t.add_column("Goal",    min_width=35)
            t.add_column("Status",  width=12)
            t.add_column("Workers", width=8)
            for s in swarms:
                goal = s.get("goal", "")
                t.add_row(
                    str(s["id"]),
                    s.get("name", ""),
                    (goal[:48] + "...") if len(goal) > 48 else goal,
                    status_tag(s.get("status", "?")),
                    str(len(s.get("workers", []))),
                )
            console.print(t)
        else:
            console.print("  [dim]No swarms yet. Create one with [A].[/dim]\n")

        console.print("  [cyan][A][/cyan]  Create new swarm")
        if swarms:
            console.print("  [cyan][V][/cyan]  View / manage swarm")
            console.print("  [cyan][M][/cyan]  Monitor swarm live")
        console.print("  [cyan][0][/cyan]  Back\n")

        choice = Prompt.ask("  Option", default="0", show_default=False).strip().lower()

        if choice == "0":
            break
        elif choice == "a":
            _swarm_create(client)
        elif choice == "v" and swarms:
            sid = Prompt.ask("  Swarm ID")
            try:
                _swarm_detail(client, int(sid))
            except ValueError:
                err("Invalid ID.")
        elif choice == "m" and swarms:
            sid = Prompt.ask("  Swarm ID to monitor")
            try:
                _swarm_monitor(client, int(sid))
            except ValueError:
                err("Invalid ID.")


def _swarm_create(client: OpenACMClient) -> None:
    header("Create Swarm")

    name = Prompt.ask("  Swarm name")
    console.print("  [dim]Describe the goal -- the more detail, the better the plan[/dim]")
    goal = Prompt.ask("  Goal")

    model = Prompt.ask(
        "  Global model  [dim](Enter to use the default)[/dim]",
        default="", show_default=False,
    )
    working_path = Prompt.ask(
        "  Working directory  [dim](Enter to use current)[/dim]",
        default="", show_default=False,
    )

    try:
        form: dict[str, str] = {"name": name, "goal": goal}
        if model:
            form["global_model"] = model
        if working_path:
            form["working_path"] = working_path

        swarm = client.post("/api/swarms", form=form)
        swarm_id = swarm["id"]
        ok_msg(f"Swarm #{swarm_id} '{name}' created.")
    except Exception as e:
        err(str(e))
        pause()
        return

    if Confirm.ask("\n  Get clarification questions from the agent?", default=True):
        try:
            console.print("  [dim]Generating questions...[/dim]")
            result = client.post(f"/api/swarms/{swarm_id}/clarify")
            questions: list[str] = result.get("questions", [])

            if questions:
                console.print(f"\n  The agent has [bold]{len(questions)}[/bold] question(s):\n")
                answers = []
                for i, q in enumerate(questions, 1):
                    console.print(f"  [cyan]{i}.[/cyan] {q}")
                    ans = Prompt.ask("  Your answer")
                    answers.append({"question": q, "answer": ans})

                console.print("\n  [dim]Submitting answers and generating plan...[/dim]")
                client.post(
                    f"/api/swarms/{swarm_id}/clarify/answer",
                    form={"answers": str(answers)},
                )
                ok_msg("Plan generated.")
            else:
                console.print("  [dim]No questions -- generating plan directly...[/dim]")
                client.post(f"/api/swarms/{swarm_id}/plan")
                ok_msg("Plan generated.")
        except Exception as e:
            err(f"Clarification error: {e}")
    else:
        if Confirm.ask("  Generate plan now?", default=True):
            try:
                client.post(f"/api/swarms/{swarm_id}/plan")
                ok_msg("Plan generated.")
            except Exception as e:
                err(str(e))

    if Confirm.ask("\n  Start the swarm now?", default=False):
        try:
            client.post(f"/api/swarms/{swarm_id}/start")
            ok_msg(f"Swarm #{swarm_id} started.")
        except Exception as e:
            err(str(e))

    pause()


def _swarm_detail(client: OpenACMClient, swarm_id: int) -> None:
    while True:
        header(f"Swarm #{swarm_id}")

        try:
            data = client.get(f"/api/swarms/{swarm_id}")
        except Exception as e:
            err(str(e))
            pause()
            return

        swarm = data.get("swarm", data)
        workers: list[dict] = data.get("workers", [])
        tasks: list[dict] = data.get("tasks", [])
        status = swarm.get("status", "?")

        console.print(Panel(
            f"[bold]{swarm.get('name', '')}[/bold]\n"
            f"Status: {status_tag(status)}\n"
            f"Goal: [dim]{swarm.get('goal', '')[:120]}[/dim]",
            border_style="cyan", padding=(0, 2),
        ))

        if workers:
            console.print("\n  [bold]Workers:[/bold]")
            wt = Table(box=box.SIMPLE)
            wt.add_column("ID",    style="dim", width=5)
            wt.add_column("Name",  min_width=16)
            wt.add_column("Role",  min_width=16)
            wt.add_column("Model", min_width=14)
            for w in workers:
                wt.add_row(str(w["id"]), w.get("name", ""), w.get("role", ""), w.get("model", "default"))
            console.print(wt)

        if tasks:
            console.print("\n  [bold]Tasks:[/bold]")
            tt = Table(box=box.SIMPLE)
            tt.add_column("ID",     style="dim", width=5)
            tt.add_column("Title",  min_width=35)
            tt.add_column("Status", width=14)
            for task in tasks:
                tt.add_row(str(task["id"]), task.get("title", "")[:55], status_tag(task.get("status", "?")))
            console.print(tt)

        console.print()

        if status in ("draft", "planned", "idle"):
            console.print("  [cyan][I][/cyan]  Start")
            console.print("  [cyan][P][/cyan]  Re-plan")
        if status == "running":
            console.print("  [cyan][S][/cyan]  Stop / Pause")
            console.print("  [cyan][F][/cyan]  Mark as completed")
        if status in ("paused", "failed"):
            console.print("  [cyan][I][/cyan]  Resume")

        failed_tasks = [t for t in tasks if t.get("status") == "failed"]
        if failed_tasks:
            console.print("  [cyan][R][/cyan]  Retry failed task")

        console.print("  [cyan][M][/cyan]  Send message to swarm")
        console.print("  [cyan][D][/cyan]  Delete swarm")
        console.print("  [cyan][0][/cyan]  Back\n")

        choice = Prompt.ask("  Option", default="0", show_default=False).strip().lower()

        if choice == "0":
            break
        elif choice == "i":
            try:
                client.post(f"/api/swarms/{swarm_id}/start")
                ok_msg("Swarm started / resumed.")
            except Exception as e:
                err(str(e))
        elif choice == "s":
            try:
                client.post(f"/api/swarms/{swarm_id}/stop")
                ok_msg("Swarm stopped.")
            except Exception as e:
                err(str(e))
        elif choice == "f":
            try:
                client.post(f"/api/swarms/{swarm_id}/complete")
                ok_msg("Swarm marked as completed.")
            except Exception as e:
                err(str(e))
        elif choice == "p":
            try:
                client.post(f"/api/swarms/{swarm_id}/plan")
                ok_msg("Re-planning done.")
            except Exception as e:
                err(str(e))
        elif choice == "r" and failed_tasks:
            console.print("\n  Failed tasks:")
            for t in failed_tasks:
                console.print(f"  [{t['id']}] {t.get('title', '')}")
            task_id_s = Prompt.ask("  Task ID to retry")
            notes = Prompt.ask(
                "  Notes for the retry  [dim](optional)[/dim]",
                default="", show_default=False,
            )
            try:
                client.post(
                    f"/api/swarms/{swarm_id}/tasks/{task_id_s}/retry",
                    data={"user_notes": notes},
                )
                ok_msg("Task queued for retry.")
            except Exception as e:
                err(str(e))
        elif choice == "m":
            msg = Prompt.ask("  Message")
            try:
                result = client.post(f"/api/swarms/{swarm_id}/message", data={"message": msg})
                ok_msg("Message sent.")
                if result.get("result"):
                    console.print(f"  Response: [dim]{result['result']}[/dim]")
            except Exception as e:
                err(str(e))
        elif choice == "d":
            if Confirm.ask("  Delete this swarm?", default=False):
                try:
                    client.delete(f"/api/swarms/{swarm_id}")
                    ok_msg("Swarm deleted.")
                    pause()
                    return
                except Exception as e:
                    err(str(e))

        if choice != "0":
            pause("Press Enter to refresh")


def _swarm_monitor(client: OpenACMClient, swarm_id: int) -> None:
    console.print("\n  [dim]Monitoring swarm... Ctrl+C to stop[/dim]\n")
    try:
        with Live(console=console, refresh_per_second=0.5) as live:
            while True:
                try:
                    data = client.get(f"/api/swarms/{swarm_id}")
                    swarm = data.get("swarm", data)
                    tasks: list[dict] = data.get("tasks", [])
                    workers: list[dict] = data.get("workers", [])

                    t = Table(
                        title=f"Swarm #{swarm_id} -- {swarm.get('name', '')} -- {swarm.get('status', '?')}",
                        box=box.ROUNDED,
                    )
                    t.add_column("Task",   min_width=38)
                    t.add_column("Worker", min_width=14)
                    t.add_column("Status", width=14)

                    worker_map = {w["id"]: w.get("name", "?") for w in workers}
                    for task in tasks:
                        wid = task.get("worker_id")
                        wname = worker_map.get(wid, "-") if wid else "-"
                        t.add_row(
                            task.get("title", "")[:58],
                            wname,
                            status_tag(task.get("status", "?")),
                        )

                    live.update(t)

                    if swarm.get("status") in ("completed", "failed"):
                        break
                except Exception:
                    break
                time.sleep(3)
    except KeyboardInterrupt:
        pass
    console.print("\n  [dim]Monitor stopped.[/dim]")
    pause()


# ─── CRON ─────────────────────────────────────────────────────────────────────


def cron_menu(client: OpenACMClient) -> None:
    while True:
        header("Cron Jobs", "Scheduled tasks")

        try:
            jobs = client.get("/api/cron/jobs")
            sched = client.get("/api/cron/status")
        except Exception as e:
            err(str(e))
            pause()
            return

        running = sched.get("running", False)
        next_job = sched.get("next_job_name")
        next_at = sched.get("next_job_at", "")
        console.print(
            f"  Scheduler: {'[green]running[/green]' if running else '[red]stopped[/red]'}"
            + (f"   Next: [cyan]{next_job}[/cyan]  [dim]{next_at}[/dim]" if next_job else "")
        )
        console.print()

        if jobs:
            t = Table(box=box.ROUNDED)
            t.add_column("ID",          style="dim", width=5)
            t.add_column("Name",        min_width=18)
            t.add_column("Expression",  width=16)
            t.add_column("Action",      min_width=16)
            t.add_column("Status",      width=10)
            t.add_column("Next run",    min_width=18)
            for j in jobs:
                enabled = j.get("is_enabled", True)
                next_run = str(j.get("next_run", "-"))[:19]
                t.add_row(
                    str(j["id"]),
                    j.get("name", ""),
                    j.get("cron_expr", ""),
                    j.get("action_type", ""),
                    "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]",
                    next_run,
                )
            console.print(t)
        else:
            console.print("  [dim]No cron jobs. Create one with [A].[/dim]\n")

        console.print("  [cyan][A][/cyan]  Create job")
        if jobs:
            console.print("  [cyan][T][/cyan]  Trigger job now")
            console.print("  [cyan][E][/cyan]  Enable / Disable job")
            console.print("  [cyan][H][/cyan]  View run history")
            console.print("  [cyan][D][/cyan]  Delete job")
        console.print("  [cyan][0][/cyan]  Back\n")

        choice = Prompt.ask("  Option", default="0", show_default=False).strip().lower()

        if choice == "0":
            break
        elif choice == "a":
            _cron_create(client)
        elif choice == "t" and jobs:
            jid = Prompt.ask("  Job ID")
            try:
                result = client.post(f"/api/cron/jobs/{jid}/trigger")
                ok_msg("Job triggered.")
                if result.get("result"):
                    console.print(f"  Result: [dim]{str(result['result'])[:200]}[/dim]")
            except Exception as e:
                err(str(e))
            pause()
        elif choice == "e" and jobs:
            jid = Prompt.ask("  Job ID")
            try:
                result = client.post(f"/api/cron/jobs/{jid}/toggle")
                state = "enabled" if result.get("is_enabled") else "disabled"
                ok_msg(f"Job {state}.")
            except Exception as e:
                err(str(e))
            pause()
        elif choice == "h" and jobs:
            jid_s = Prompt.ask(
                "  Job ID  [dim](Enter for all)[/dim]", default="", show_default=False
            )
            params: dict = {"limit": 30}
            if jid_s.strip():
                params["job_id"] = jid_s.strip()
            try:
                hist = client.get("/api/cron/runs", params=params)
                runs = hist.get("runs", hist) if isinstance(hist, dict) else hist
                if runs:
                    ht = Table(box=box.SIMPLE)
                    ht.add_column("Job",      min_width=18)
                    ht.add_column("Started",  min_width=18)
                    ht.add_column("Duration", width=10)
                    ht.add_column("Status",   width=10)
                    ht.add_column("Output",   min_width=30)
                    for r in runs[:20]:
                        ht.add_row(
                            r.get("job_name", str(r.get("job_id", "?"))),
                            str(r.get("started_at", ""))[:19],
                            f"{r.get('duration_ms', '?')} ms",
                            status_tag(r.get("status", "?")),
                            str(r.get("output", ""))[:60],
                        )
                    console.print(ht)
                else:
                    console.print("  [dim]No history found.[/dim]")
            except Exception as e:
                err(str(e))
            pause()
        elif choice == "d" and jobs:
            jid = Prompt.ask("  Job ID to delete")
            if Confirm.ask(f"  Delete job {jid}?", default=False):
                try:
                    client.delete(f"/api/cron/jobs/{jid}")
                    ok_msg("Job deleted.")
                except Exception as e:
                    err(str(e))
                pause()


def _cron_create(client: OpenACMClient) -> None:
    header("Create Cron Job")

    name = Prompt.ask("  Job name")
    desc = Prompt.ask(
        "  Description  [dim](optional)[/dim]", default="", show_default=False
    )

    console.print(
        "\n  [bold]Cron expression[/bold]  [dim](5 fields: min hour day month weekday)[/dim]\n"
        "  Shortcuts:  @hourly  @daily  @midnight  @weekly  @monthly\n"
        "  Examples:\n"
        "    0 9 * * 1-5   -> weekdays at 9:00\n"
        "    */30 * * * *  -> every 30 minutes\n"
        "    0 8 * * 1     -> every Monday at 8:00\n"
    )
    cron_expr = Prompt.ask("  Expression")

    action_types = ["run_skill", "run_routine", "analyze_patterns", "custom_command"]
    console.print("\n  [bold]Action type:[/bold]\n")
    for i, at in enumerate(action_types, 1):
        console.print(f"  [cyan][{i}][/cyan]  {at}")
    console.print()
    at_choice = IntPrompt.ask("  Type", default=4)
    action_type = action_types[at_choice - 1] if 1 <= at_choice <= len(action_types) else "custom_command"

    payload: dict = {}
    if action_type == "run_skill":
        skill_name = Prompt.ask("  Skill name")
        payload = {"skill": skill_name}
    elif action_type == "run_routine":
        routine_id = Prompt.ask("  Routine ID")
        payload = {"routine_id": routine_id}
    elif action_type == "custom_command":
        cmd = Prompt.ask("  Command / prompt for the agent")
        payload = {"command": cmd}

    enabled = Confirm.ask("\n  Enable immediately?", default=True)

    try:
        result = client.post("/api/cron/jobs", data={
            "name": name,
            "description": desc,
            "cron_expr": cron_expr,
            "action_type": action_type,
            "action_payload": payload,
            "is_enabled": enabled,
        })
        ok_msg(f"Job '{name}' created  (ID: {result.get('id', '?')}).")
        if result.get("next_run"):
            console.print(f"  Next run: [dim]{result['next_run']}[/dim]")
    except Exception as e:
        err(str(e))

    pause()


# ─── ROUTINES ─────────────────────────────────────────────────────────────────


def routines_menu(client: OpenACMClient) -> None:
    while True:
        header("Routines", "Automatically detected activity patterns")

        try:
            routines = client.get("/api/routines")
        except Exception as e:
            err(str(e))
            pause()
            return

        if routines:
            t = Table(box=box.ROUNDED)
            t.add_column("ID",      style="dim", width=5)
            t.add_column("Name",    min_width=22)
            t.add_column("Trigger", width=16)
            t.add_column("Apps",    min_width=22)
            t.add_column("Status",  width=10)
            for r in routines:
                trigger = r.get("trigger_type", "manual")
                if trigger == "time_based":
                    td = r.get("trigger_data", {})
                    trigger = f"time {td.get('hour', 0):02}:{td.get('minute', 0):02}"
                apps = (r.get("apps") or [])
                apps_str = ", ".join(apps[:3]) + ("..." if len(apps) > 3 else "")
                t.add_row(
                    str(r["id"]),
                    r.get("name", ""),
                    trigger,
                    apps_str,
                    status_tag(r.get("status", "pending")),
                )
            console.print(t)
        else:
            console.print(
                "  [dim]No routines yet. Use [AN] to analyze activity patterns.[/dim]\n"
            )

        console.print("  [cyan][E][/cyan]   Execute routine now")
        console.print("  [cyan][T][/cyan]   Toggle status  (active / inactive)")
        console.print("  [cyan][AN][/cyan]  Analyze new activity patterns")
        console.print("  [cyan][D][/cyan]   Delete routine")
        console.print("  [cyan][A][/cyan]   View activity stats")
        console.print("  [cyan][0][/cyan]   Back\n")

        choice = Prompt.ask("  Option", default="0", show_default=False).strip().lower()

        if choice == "0":
            break
        elif choice == "e" and routines:
            rid = Prompt.ask("  Routine ID")
            try:
                result = client.post(f"/api/routines/{rid}/execute")
                ok_msg("Routine executed.")
                for r in (result.get("results") or [])[:5]:
                    console.print(f"  [dim]  {r}[/dim]")
            except Exception as e:
                err(str(e))
            pause()
        elif choice == "t" and routines:
            rid = Prompt.ask("  Routine ID")
            console.print("  [cyan][1][/cyan] active  [cyan][2][/cyan] inactive  [cyan][3][/cyan] pending")
            sc = IntPrompt.ask("  New status", default=1)
            states = ["active", "inactive", "pending"]
            new_status = states[sc - 1] if 1 <= sc <= 3 else "active"
            try:
                client.put(f"/api/routines/{rid}", {"status": new_status})
                ok_msg(f"Status changed to: {new_status}")
            except Exception as e:
                err(str(e))
            pause()
        elif choice == "an":
            console.print("\n  [dim]Analyzing activity patterns...[/dim]")
            try:
                result = client.post("/api/routines/analyze")
                n = result.get("new_routines", 0)
                ok_msg(f"{n} new routine(s) detected." if n > 0 else "No new routines detected.")
            except Exception as e:
                err(str(e))
            pause()
        elif choice == "d" and routines:
            rid = Prompt.ask("  Routine ID to delete")
            if Confirm.ask(f"  Delete routine {rid}?", default=False):
                try:
                    client.delete(f"/api/routines/{rid}")
                    ok_msg("Routine deleted.")
                except Exception as e:
                    err(str(e))
                pause()
        elif choice == "a":
            _activity_stats(client)


def _activity_stats(client: OpenACMClient) -> None:
    header("Activity")

    try:
        watcher = client.get("/api/watcher/status")
        stats = client.get("/api/activity/stats")
        sessions = client.get("/api/activity/sessions", params={"limit": 10})
    except Exception as e:
        err(str(e))
        pause()
        return

    running = watcher.get("running", False)
    current_app = watcher.get("current_app", "")
    console.print(
        f"  Watcher: {'[green]active[/green]' if running else '[red]inactive[/red]'}"
        + (f"   Current app: [cyan]{current_app}[/cyan]" if current_app else "")
    )
    console.print(f"  Sessions recorded: [cyan]{watcher.get('sessions_recorded', 0)}[/cyan]\n")

    apps = stats.get("apps", [])
    if apps:
        console.print("  [bold]Top apps today:[/bold]")
        at = Table(box=box.SIMPLE, show_header=False)
        at.add_column("App",      min_width=22)
        at.add_column("Time",     style="cyan", width=10)
        at.add_column("Sessions", style="dim",  width=10)
        for app in apps[:8]:
            at.add_row(
                app.get("name", "?"),
                f"{app.get('duration_hours', 0):.1f}h",
                str(app.get("sessions", 0)),
            )
        console.print(at)

    if sessions:
        console.print("\n  [bold]Recent sessions:[/bold]")
        st = Table(box=box.SIMPLE, show_header=False)
        st.add_column("App",      min_width=22)
        st.add_column("Started",  style="dim", min_width=18)
        st.add_column("Duration", style="cyan", width=10)
        for s in sessions[:8]:
            mins = round((s.get("duration") or 0) / 60, 1)
            st.add_row(
                s.get("app_name", "?"),
                str(s.get("start_time", ""))[:19],
                f"{mins}m",
            )
        console.print(st)

    pause()


# ─── SKILLS ───────────────────────────────────────────────────────────────────


def skills_menu(client: OpenACMClient) -> None:
    while True:
        header("Skills", "Reusable agent capabilities")

        try:
            skills = client.get("/api/skills")
        except Exception as e:
            err(str(e))
            pause()
            return

        if skills:
            t = Table(box=box.ROUNDED)
            t.add_column("ID",       style="dim", width=5)
            t.add_column("Name",     min_width=20)
            t.add_column("Category", min_width=14)
            t.add_column("Description", min_width=38)
            t.add_column("Active",   width=8)
            for s in skills:
                desc = s.get("description", "")
                t.add_row(
                    str(s["id"]),
                    s.get("name", ""),
                    s.get("category", "general"),
                    (desc[:58] + "...") if len(desc) > 58 else desc,
                    "[green]yes[/green]" if s.get("is_active") else "[dim]no[/dim]",
                )
            console.print(t)
        else:
            console.print("  [dim]No skills yet.[/dim]\n")

        console.print("  [cyan][A][/cyan]  Create skill  (manual)")
        console.print("  [cyan][G][/cyan]  Generate skill with AI")
        if skills:
            console.print("  [cyan][T][/cyan]  Toggle active / inactive")
            console.print("  [cyan][D][/cyan]  Delete skill")
        console.print("  [cyan][0][/cyan]  Back\n")

        choice = Prompt.ask("  Option", default="0", show_default=False).strip().lower()

        if choice == "0":
            break
        elif choice == "a":
            name = Prompt.ask("  Name")
            desc = Prompt.ask("  Description")
            cat = Prompt.ask("  Category  [dim](Enter = general)[/dim]", default="general")
            console.print(
                "  Skill content  [dim](markdown instructions, empty line to finish):[/dim]\n"
            )
            lines: list[str] = []
            try:
                while True:
                    line = input()
                    if not line:
                        break
                    lines.append(line)
            except EOFError:
                pass
            try:
                r = client.post("/api/skills", data={
                    "name": name, "description": desc,
                    "content": "\n".join(lines), "category": cat,
                })
                ok_msg(f"Skill '{name}' created (ID: {r.get('id', '?')}).")
            except Exception as e:
                err(str(e))
            pause()
        elif choice == "g":
            name = Prompt.ask("  Skill name")
            desc = Prompt.ask("  Description / what it should do")
            uses = Prompt.ask(
                "  Use cases  [dim](comma-separated, optional)[/dim]",
                default="", show_default=False,
            )
            console.print("  [dim]Generating with AI...[/dim]")
            try:
                r = client.post("/api/skills/generate", data={
                    "name": name, "description": desc, "use_cases": uses,
                })
                ok_msg(f"Skill '{r.get('name', name)}' generated (ID: {r.get('id', '?')}).")
            except Exception as e:
                err(str(e))
            pause()
        elif choice == "t" and skills:
            sid = Prompt.ask("  Skill ID")
            try:
                client.post(f"/api/skills/{sid}/toggle")
                ok_msg("Status toggled.")
            except Exception as e:
                err(str(e))
            pause()
        elif choice == "d" and skills:
            sid = Prompt.ask("  Skill ID to delete")
            if Confirm.ask(f"  Delete skill {sid}?", default=False):
                try:
                    client.delete(f"/api/skills/{sid}")
                    ok_msg("Skill deleted.")
                except Exception as e:
                    err(str(e))
                pause()


# ─── AGENTS ───────────────────────────────────────────────────────────────────


def agents_menu(client: OpenACMClient) -> None:
    while True:
        header("Agents", "Sub-agents with their own personality and tools")

        try:
            agents = client.get("/api/agents")
        except Exception as e:
            err(str(e))
            pause()
            return

        if agents:
            t = Table(box=box.ROUNDED)
            t.add_column("ID",          style="dim", width=5)
            t.add_column("Name",        min_width=18)
            t.add_column("Description", min_width=38)
            t.add_column("Active",      width=8)
            for a in agents:
                desc = a.get("description", "")
                t.add_row(
                    str(a["id"]),
                    a.get("name", ""),
                    (desc[:58] + "...") if len(desc) > 58 else desc,
                    "[green]yes[/green]" if a.get("is_active") else "[dim]no[/dim]",
                )
            console.print(t)
        else:
            console.print("  [dim]No agents yet.[/dim]\n")

        console.print("  [cyan][A][/cyan]  Create agent  (manual)")
        console.print("  [cyan][G][/cyan]  Generate agent with AI")
        if agents:
            console.print("  [cyan][C][/cyan]  Chat with / test agent")
            console.print("  [cyan][D][/cyan]  Delete agent")
        console.print("  [cyan][0][/cyan]  Back\n")

        choice = Prompt.ask("  Option", default="0", show_default=False).strip().lower()

        if choice == "0":
            break
        elif choice == "a":
            name = Prompt.ask("  Name")
            desc = Prompt.ask("  Description")
            console.print(
                "  System prompt  [dim](agent instructions, empty line to finish):[/dim]\n"
            )
            lines: list[str] = []
            try:
                while True:
                    line = input()
                    if not line:
                        break
                    lines.append(line)
            except EOFError:
                pass
            try:
                r = client.post("/api/agents", data={
                    "name": name, "description": desc,
                    "system_prompt": "\n".join(lines),
                })
                ok_msg(f"Agent '{name}' created (ID: {r.get('id', '?')}).")
            except Exception as e:
                err(str(e))
            pause()
        elif choice == "g":
            desc = Prompt.ask("  Describe what the agent should do")
            console.print("  [dim]Generating with AI...[/dim]")
            try:
                r = client.post("/api/agents/generate", data={"description": desc})
                ok_msg(f"Agent '{r.get('name', '?')}' generated.")
                console.print(f"  Description: [dim]{r.get('description', '')}[/dim]")
            except Exception as e:
                err(str(e))
            pause()
        elif choice == "c" and agents:
            aid = Prompt.ask("  Agent ID")
            console.print("  [dim]Type messages (empty line to quit):[/dim]\n")
            while True:
                msg = Prompt.ask("  You", default="", show_default=False)
                if not msg.strip():
                    break
                try:
                    r = client.post(f"/api/agents/{aid}/test", data={"message": msg})
                    console.print(f"\n  [cyan]Agent:[/cyan] {r.get('response', '?')}\n")
                except Exception as e:
                    err(str(e))
                    break
        elif choice == "d" and agents:
            aid = Prompt.ask("  Agent ID to delete")
            if Confirm.ask(f"  Delete agent {aid}?", default=False):
                try:
                    client.delete(f"/api/agents/{aid}")
                    ok_msg("Agent deleted.")
                except Exception as e:
                    err(str(e))
                pause()


# ─── STATS ────────────────────────────────────────────────────────────────────


def stats_menu(client: OpenACMClient) -> None:
    header("Stats & Usage")

    try:
        stats = client.get("/api/stats")
        mem = client.get("/api/memory/stats")
    except Exception as e:
        err(str(e))
        pause()
        return

    t = Table(box=box.SIMPLE, show_header=False)
    t.add_column("", style="dim", min_width=24)
    t.add_column("", style="cyan")
    t.add_row("Prompt tokens",    f"{stats.get('prompt_tokens', 0):,}")
    t.add_row("Completion tokens", f"{stats.get('completion_tokens', 0):,}")
    t.add_row("Total requests",   f"{stats.get('requests', 0):,}")
    t.add_row("Estimated cost",   f"${stats.get('cost', 0):.4f}")
    t.add_row("Default model",    str(stats.get("model", "?")))
    console.print(Panel(t, title="LLM Usage", border_style="cyan"))

    mt = Table(box=box.SIMPLE, show_header=False)
    mt.add_column("", style="dim", min_width=24)
    mt.add_column("", style="cyan")
    mt.add_row("RAG documents", str(mem.get("total", 0)))
    mt.add_row("Size",          f"{mem.get('size_bytes', 0) / 1024:.1f} KB")
    mt.add_row("Status",        str(mem.get("status", "?")))
    console.print(Panel(mt, title="RAG Memory", border_style="cyan"))

    if Confirm.ask("\n  View daily usage history?", default=False):
        try:
            hist = client.get("/api/stats/history")
            if hist:
                ht = Table(box=box.SIMPLE)
                ht.add_column("Date",   min_width=12)
                ht.add_column("Tokens", style="cyan", width=12)
                ht.add_column("Cost",   style="dim",  width=10)
                for h in hist[:14]:
                    ht.add_row(
                        str(h.get("date", "?"))[:10],
                        f"{h.get('tokens', 0):,}",
                        f"${h.get('cost', 0):.4f}",
                    )
                console.print(ht)
        except Exception as e:
            err(str(e))

    pause()


# ─── MAIN MENU ────────────────────────────────────────────────────────────────


def main_menu(client: OpenACMClient) -> None:
    while True:
        console.clear()
        console.print(Panel(
            f"[bold cyan]OpenACM Manager[/bold cyan]  [dim]{client.base_url}[/dim]\n"
            "[dim]Manage swarms, cron jobs, routines, skills, and agents from the console[/dim]",
            border_style="cyan", padding=(1, 4),
        ))

        try:
            cron_status = client.get("/api/cron/status")
            routines = client.get("/api/routines")
            swarms = client.get("/api/swarms")
            active_swarms = sum(1 for s in swarms if s.get("status") == "running")
            active_routines = sum(1 for r in routines if r.get("status") == "active")
            next_cron = cron_status.get("next_job_name", "none")

            t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
            t.add_column("", style="dim")
            t.add_column("", style="cyan")
            t.add_row("Running swarms",   str(active_swarms))
            t.add_row("Active routines",  str(active_routines))
            t.add_row("Next cron job",    next_cron)
            console.print(t)
        except Exception:
            pass

        console.print()
        console.print("  [cyan][S][/cyan]  Swarms       -- multi-agent orchestration")
        console.print("  [cyan][C][/cyan]  Cron Jobs    -- scheduled tasks")
        console.print("  [cyan][R][/cyan]  Routines     -- activity patterns")
        console.print("  [cyan][K][/cyan]  Skills       -- agent capabilities")
        console.print("  [cyan][A][/cyan]  Agents       -- custom sub-agents")
        console.print("  [cyan][T][/cyan]  Stats        -- tokens, costs, memory")
        console.print()
        console.print("  [dim][0]  Exit[/dim]")
        console.print()

        choice = Prompt.ask("  Option", default="0", show_default=False).strip().lower()

        if choice == "0":
            break
        elif choice == "s":
            swarms_menu(client)
        elif choice == "c":
            cron_menu(client)
        elif choice == "r":
            routines_menu(client)
        elif choice == "k":
            skills_menu(client)
        elif choice == "a":
            agents_menu(client)
        elif choice == "t":
            stats_menu(client)


# ─── Entry point ──────────────────────────────────────────────────────────────


_DIRECT: dict[str, str] = {
    "swarms":   "s",
    "cron":     "c",
    "routines": "r",
    "skills":   "k",
    "agents":   "a",
    "stats":    "t",
}


def main() -> None:
    base_url, token = _load_connection()

    if not token:
        console.print(
            "[red]No DASHBOARD_TOKEN configured.[/red]\n"
            "Run [bold]openacm-setup[/bold] first to generate one."
        )
        sys.exit(1)

    client = OpenACMClient(base_url, token)

    console.print(f"  [dim]Connecting to {base_url}...[/dim]")
    if not client.ping():
        console.print(
            f"[red]Cannot connect to {base_url}[/red]\n"
            "Make sure OpenACM is running:  [bold]openacm[/bold]"
        )
        sys.exit(1)

    console.print("  [green]Connected.[/green]\n")

    arg = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    target = _DIRECT.get(arg, "")

    try:
        if target == "s":
            swarms_menu(client)
        elif target == "c":
            cron_menu(client)
        elif target == "r":
            routines_menu(client)
        elif target == "k":
            skills_menu(client)
        elif target == "a":
            agents_menu(client)
        elif target == "t":
            stats_menu(client)
        else:
            main_menu(client)
    except (KeyboardInterrupt, EOFError):
        console.print("\n\n  [dim]Exiting...[/dim]\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
