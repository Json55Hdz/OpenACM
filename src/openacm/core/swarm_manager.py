"""
SwarmManager — orchestrates multi-agent swarms.

A swarm is a project-level container where:
- An orchestrator agent plans the work and delegates tasks.
- Worker agents execute tasks in their isolated workspaces.
- Workers can communicate with each other via a shared message bus.
- Each worker can use a different LLM model.
- Swarm workspaces are fully isolated from normal chat workspaces.

Execution flow:
  1. create_swarm(goal, files)  → draft swarm with processed context
  2. plan_swarm(id)             → LLM designs team + initial tasks
  3. start_swarm(id)            → runs tasks in dependency order, workers communicate
  4. Results aggregated by orchestrator → swarm marked completed
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from openacm.constants import (
    SWARM_MAX_PARALLEL_WORKERS,
    SWARM_MAX_TASK_RETRIES,
    TRUNCATE_SWARM_TASK_OUTPUT_CHARS,
)
from openacm.utils.text import truncate

log = structlog.get_logger()

# Event names for real-time updates
EVENT_SWARM_UPDATED = "swarm:updated"
EVENT_SWARM_WORKER_STATUS = "swarm:worker_status"
EVENT_SWARM_MESSAGE = "swarm:message"
EVENT_SWARM_TASK_UPDATED = "swarm:task_updated"


class SwarmManager:
    """Manages swarm lifecycle: planning, execution, and worker coordination."""

    def __init__(self, database, llm_router, tool_registry, memory, event_bus):
        self.db = database
        self.llm_router = llm_router
        self.tool_registry = tool_registry
        self.memory = memory
        self.event_bus = event_bus
        # Running swarm tasks keyed by swarm_id
        self._running: dict[int, asyncio.Task] = {}
        # Retry counters: swarm_id → {task_id → retries_used}
        # Persists across auto-restarts so a task can't retry infinitely across runs.
        self._task_retries: dict[int, dict[int, int]] = {}
        # Per-swarm LLM semaphore — limits concurrent LLM calls to avoid TPM rate limits.
        # Each worker acquires this before its agentic loop; tool calls inside don't count.
        self._llm_semaphores: dict[int, asyncio.Semaphore] = {}
        # Schedule orphaned-task cleanup after the event loop is running
        asyncio.get_event_loop().call_soon(
            lambda: asyncio.ensure_future(self._reset_orphaned_tasks())
        )

    async def _reset_orphaned_tasks(self) -> None:
        """
        On startup, reset tasks and workers that were stuck in 'running' state
        due to a previous crash. Also reset swarms stuck in 'running' to 'idle'.
        """
        try:
            all_swarms = await self.db.list_swarms()
            for swarm in all_swarms:
                swarm_id = swarm["id"]
                # Reset swarm status
                if swarm["status"] == "running":
                    await self.db.update_swarm(swarm_id, status="idle")
                # Reset stuck tasks
                tasks = await self.db.get_swarm_tasks(swarm_id)
                for t in tasks:
                    if t["status"] == "running":
                        await self.db.update_swarm_task(
                            t["id"], status="pending",
                            result="[Reset: backend restarted mid-execution]",
                        )
                # Reset stuck workers
                workers = await self.db.get_swarm_workers(swarm_id)
                for w in workers:
                    if w.get("status") == "busy":
                        await self.db.update_swarm_worker(w["id"], status="idle")
            log.info("Orphaned swarm tasks reset on startup")
        except Exception as e:
            log.warning("Could not reset orphaned swarm tasks", error=str(e))

    # ─── Swarm Lifecycle ──────────────────────────────────────────────────────

    async def create_swarm(
        self,
        name: str,
        goal: str,
        file_contents: list[dict[str, str]] | None = None,
        global_model: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new draft swarm.

        file_contents: list of {"filename": ..., "content": ...} dicts already read.
        """
        swarm_id = await self.db.create_swarm(name, goal, global_model)
        swarm_dir = self._swarm_dir(swarm_id)
        swarm_dir.mkdir(parents=True, exist_ok=True)
        (swarm_dir / "workers").mkdir(exist_ok=True)
        (swarm_dir / "context").mkdir(exist_ok=True)

        shared_context = ""
        context_files: list[str] = []

        if file_contents:
            parts: list[str] = []
            for f in file_contents:
                fname = f.get("filename", "file")
                content = f.get("content", "")
                fpath = swarm_dir / "context" / fname
                fpath.write_text(content, encoding="utf-8", errors="replace")
                context_files.append(fname)
                parts.append(f"### {fname}\n{content}")
            shared_context = "\n\n".join(parts)

        await self.db.update_swarm(
            swarm_id,
            workspace_path=str(swarm_dir),
            shared_context=shared_context,
            context_files=json.dumps(context_files),
        )

        swarm = await self.db.get_swarm(swarm_id)
        await self._emit_swarm_event(swarm_id, "created")
        return swarm

    async def plan_swarm(self, swarm_id: int) -> dict[str, Any]:
        """
        Use the LLM to design the worker team and initial task plan for this swarm.
        Returns the updated swarm with workers created.
        """
        swarm = await self.db.get_swarm(swarm_id)
        if not swarm:
            raise ValueError(f"Swarm {swarm_id} not found")

        await self.db.update_swarm(swarm_id, status="planning")
        await self._emit_swarm_event(swarm_id, "planning")

        plan_prompt = self._build_plan_prompt(swarm)

        try:
            result = await self.llm_router.chat(
                messages=[{"role": "user", "content": plan_prompt}],
                temperature=0.4,
                max_tokens=8192,
                model_override=swarm.get("global_model") or None,
            )
            plan_text = result.get("content", "")
            # Retry once with a simpler prompt if the model returned empty content
            if not plan_text.strip():
                log.warning("Swarm plan response was empty, retrying with simplified prompt", swarm_id=swarm_id)
                retry_prompt = (
                    f"Goal: {swarm.get('goal', '')}\n\n"
                    "Reply with ONLY a JSON object (no prose, no markdown) with this structure:\n"
                    '{"workers":[{"name":"...","role":"worker","description":"...","system_prompt":"...","model":null,"allowed_tools":"all"}],'
                    '"tasks":[{"title":"...","description":"...","worker":"<worker name>","depends_on":[]}]}'
                )
                result2 = await self.llm_router.chat(
                    messages=[{"role": "user", "content": retry_prompt}],
                    temperature=0.2,
                    max_tokens=2048,
                    model_override=swarm.get("global_model") or None,
                )
                plan_text = result2.get("content", "")
            plan = self._parse_plan(plan_text)
        except Exception as e:
            err_str = str(e)
            log.error("Swarm planning LLM call failed", swarm_id=swarm_id, error=err_str)
            await self.db.update_swarm(swarm_id, status="failed")
            if "ContextWindowExceeded" in err_str or "context" in err_str.lower() and "token" in err_str.lower():
                raise ValueError(
                    "The uploaded context is too large for this model. "
                    "Try a model with a larger context window or upload smaller files."
                ) from e
            raise

        # Create workers from plan
        swarm_dir = Path(swarm["workspace_path"])
        worker_specs = plan.get("workers", [])
        await self._emit(swarm_id, "swarm:plan_ready", {
            "worker_count": len(worker_specs),
            "task_count": len(plan.get("tasks", [])),
            "worker_names": [w.get("name") for w in worker_specs],
        })
        for w in worker_specs:
            wname = w.get("name", "worker").lower().replace(" ", "_")
            worker_dir = swarm_dir / "workers" / wname
            worker_dir.mkdir(parents=True, exist_ok=True)

            await self.db.create_swarm_worker(
                swarm_id=swarm_id,
                name=w.get("name", "Worker"),
                role=w.get("role", "worker"),
                description=w.get("description", ""),
                system_prompt=w.get("system_prompt", "You are a helpful AI agent."),
                model=w.get("model") or None,
                allowed_tools=w.get("allowed_tools", "all"),
                workspace_path=str(worker_dir),
            )

        # Create initial tasks from plan
        workers_db = await self.db.get_swarm_workers(swarm_id)
        name_to_id = {w["name"]: w["id"] for w in workers_db}

        for t in plan.get("tasks", []):
            assigned_worker_name = t.get("worker")
            worker_id = name_to_id.get(assigned_worker_name) if assigned_worker_name else None
            await self.db.create_swarm_task(
                swarm_id=swarm_id,
                worker_id=worker_id,
                title=t.get("title", "Task"),
                description=t.get("description", ""),
                depends_on=json.dumps(t.get("depends_on", [])),
            )

        # ── Phase: Contract Generation ────────────────────────────────────────
        # After the plan is locked, generate a shared interface contract so all
        # workers agree on event names, data schemas, file ownership, and import
        # paths BEFORE writing a single line of code.
        try:
            contract_md = await self._generate_contract(
                swarm_id=swarm_id,
                swarm=swarm,
                workers=workers_db,
                tasks=plan.get("tasks", []),
            )
            if contract_md:
                (swarm_dir / "CONTRACT.md").write_text(contract_md, encoding="utf-8")
                await self.db.add_swarm_message(
                    swarm_id=swarm_id,
                    from_worker_id=None,
                    to_worker_id=None,
                    content=f"**Interface Contract generated.**\n\nAll workers will receive this contract before executing any task.\n\n{contract_md[:600]}{'...' if len(contract_md) > 600 else ''}",
                    message_type="broadcast",
                )
                await self._emit(swarm_id, "swarm:contract_ready", {
                    "swarm_id": swarm_id,
                    "contract_preview": contract_md[:300],
                })
                log.info("Swarm interface contract generated", swarm_id=swarm_id)
        except Exception as e:
            log.warning("Contract generation failed (non-fatal)", swarm_id=swarm_id, error=str(e))

        await self.db.update_swarm(swarm_id, status="planned")
        await self._emit_swarm_event(swarm_id, "planned")
        return await self.db.get_swarm(swarm_id)

    async def start_swarm(self, swarm_id: int) -> None:
        """Start swarm execution in the background."""
        if swarm_id in self._running:
            raise ValueError(f"Swarm {swarm_id} is already running")

        task = asyncio.create_task(self._run_swarm(swarm_id))
        self._running[swarm_id] = task
        task.add_done_callback(lambda _: self._running.pop(swarm_id, None))

    async def send_user_message(self, swarm_id: int, message: str) -> str:
        """
        Deliver a user message to the swarm. Stores it and triggers the
        orchestrator to react (create tasks, redirect workers, give feedback).
        """
        swarm = await self.db.get_swarm(swarm_id)
        if not swarm:
            raise ValueError(f"Swarm {swarm_id} not found")

        # Store as user message (visible to all workers via swarm_read_messages)
        await self.db.add_swarm_message(
            swarm_id=swarm_id,
            from_worker_id=None,
            to_worker_id=None,
            content=message,
            message_type="user",
        )
        await self._emit(swarm_id, "swarm:user_message", {
            "swarm_id": swarm_id, "message": message,
        })

        # Run the orchestrator to react to the message
        asyncio.create_task(self._orchestrate_user_message(swarm_id, message))
        return "Message delivered to the swarm."

    async def _orchestrate_user_message(self, swarm_id: int, user_message: str) -> None:
        """Run orchestrator in react mode to process user feedback."""
        from openacm.core.config import AssistantConfig
        from openacm.core.brain import Brain

        try:
            swarm = await self.db.get_swarm(swarm_id)
            workers = await self.db.get_swarm_workers(swarm_id)
            tasks = await self.db.get_swarm_tasks(swarm_id)

            # Find orchestrator, fallback to first worker
            orchestrator = next(
                (w for w in workers if w["role"] == "orchestrator"),
                workers[0] if workers else None,
            )
            if not orchestrator:
                return

            # Reset tasks that were blocked waiting for user input, and notify their workers
            waiting_tasks = [t for t in tasks if t["status"] == "waiting"]
            for wt in waiting_tasks:
                await self.db.update_swarm_task(wt["id"], status="pending")
                # Send user's answer as a direct/broadcast message to reach the blocked worker
                target_worker_id = wt.get("worker_id")
                await self.db.add_swarm_message(
                    swarm_id=swarm_id,
                    from_worker_id=None,
                    to_worker_id=target_worker_id,  # None = broadcast if no specific worker
                    content=f"[User answered your question for task '{wt['title']}']: {user_message}",
                    message_type="user",
                )

            # Re-fetch tasks so summaries reflect the reset waiting→pending tasks
            tasks = await self.db.get_swarm_tasks(swarm_id)

            completed = [t for t in tasks if t["status"] == "completed"]
            results_summary = "\n".join(
                f"- {t['title']}: {(t.get('result') or '')[:200]}" for t in completed
            ) or "No tasks completed yet."

            pending_tasks = [t for t in tasks if t["status"] == "pending"]
            pending_summary = "\n".join(f"- {t['title']}" for t in pending_tasks) or "None"

            react_prompt = (
                f"You are the orchestrator of swarm '{swarm['name']}'.\n"
                f"Project goal: {swarm['goal']}\n\n"
                f"Work completed so far:\n{results_summary}\n\n"
                f"Currently pending tasks: {pending_summary}\n\n"
                f"**The user just sent this message:**\n\n{user_message}\n\n"
                f"---\n"
                f"IMPORTANT: You are in coordination mode. Your available tools are:\n"
                f"- `read_file`, `list_directory`, `grep_in_files` — read project files for context\n"
                f"- `swarm_create_task(title, description, assign_to)` — create work for a worker\n"
                f"- `swarm_broadcast(message)` — send a message to all workers\n"
                f"- `swarm_send_message(to_worker, message)` — send a direct message\n"
                f"- `swarm_ask_user(question)` — ask the user something\n"
                f"You do NOT have run_command, write_file, or any execution tools — delegate that to workers.\n\n"
                f"Your job right now:\n"
                f"1. Read what the user said and decide what work needs to happen.\n"
                f"2. Call `swarm_create_task` once for EACH unit of work — assign it to the right worker by name.\n"
                f"3. Write detailed task descriptions so the worker knows exactly what to do.\n"
                f"4. After creating all tasks, briefly summarize what you scheduled.\n\n"
                f"Do NOT describe the work in plain text — CREATE the tasks using the tool. "
                f"Workers are available and will execute whatever tasks you create immediately."
            )

            config = AssistantConfig(
                name=orchestrator["name"],
                system_prompt=orchestrator["system_prompt"],
                max_tool_iterations=12,
                onboarding_completed=True,
            )
            model_override = orchestrator.get("model") or swarm.get("global_model") or None

            brain = Brain(
                config=config,
                llm_router=self.llm_router,
                memory=self.memory,
                event_bus=self.event_bus,
                # React mode: ONLY swarm coordination tools — no run_command, no file tools.
                # This forces the orchestrator to DELEGATE work via swarm_create_task
                # instead of executing commands itself and getting stuck.
                tool_registry=self._build_swarm_only_registry(
                    swarm_id, orchestrator["id"], workers, orchestrator
                ),
            )
            if model_override:
                _orig = brain.llm_router.chat
                async def _patched(*a, **kw):
                    kw.setdefault("model_override", model_override)
                    return await _orig(*a, **kw)
                brain.llm_router.chat = _patched

            import time as _time_mod
            _react_channel = f"swarm_{swarm_id}_orchestrator_react_{int(_time_mod.time())}"
            response = await brain.process_message(
                content=react_prompt,
                user_id=f"swarm_{swarm_id}",
                channel_id=_react_channel,
                channel_type="swarm",
            )

            # Store orchestrator's response as a broadcast so everyone sees it
            if response:
                await self.db.add_swarm_message(
                    swarm_id=swarm_id,
                    from_worker_id=orchestrator["id"],
                    to_worker_id=None,
                    content=f"[Orchestrator reaction to user feedback]: {response}",
                    message_type="broadcast",
                )
                await self._emit(swarm_id, "swarm:orchestrator_reacted", {
                    "swarm_id": swarm_id, "response_preview": response[:300],
                })

            # If swarm is not already running but there are pending tasks, auto-restart
            current = await self.db.get_swarm(swarm_id)
            new_pending = await self.db.get_swarm_tasks(swarm_id)
            has_pending = any(t["status"] == "pending" for t in new_pending)
            already_running = swarm_id in self._running
            if has_pending and not already_running:
                await self.db.update_swarm(swarm_id, status="planned")
                await self._emit_swarm_event(swarm_id, "planned", {"reason": "new tasks from user feedback"})
                await self.start_swarm(swarm_id)

        except Exception as e:
            log.error("Orchestrator react failed", swarm_id=swarm_id, error=str(e))

    async def stop_swarm(self, swarm_id: int) -> None:
        """Stop a running swarm."""
        task = self._running.get(swarm_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.db.update_swarm(swarm_id, status="paused")
        await self._emit_swarm_event(swarm_id, "paused")

    # ─── Execution Engine ─────────────────────────────────────────────────────

    async def _run_swarm(self, swarm_id: int) -> None:
        """
        Main execution loop.

        Tasks with no pending dependencies are executed IN PARALLEL (up to
        MAX_PARALLEL workers at a time to avoid SQLite lock contention).
        Each worker runs in its own isolated workspace / memory namespace.
        Events are emitted for every state change so the UI can react in real time.
        """
        sem = asyncio.Semaphore(SWARM_MAX_PARALLEL_WORKERS)

        try:
            await self.db.update_swarm(swarm_id, status="running")
            await self._emit(swarm_id, "swarm:running", {"swarm_id": swarm_id})

            swarm = await self.db.get_swarm(swarm_id)
            workers = await self.db.get_swarm_workers(swarm_id)
            id_to_worker = {w["id"]: w for w in workers}

            # Pre-populate with already-completed task titles so dependency checks
            # work correctly when the swarm resumes after being idle/waiting.
            all_tasks_now = await self.db.get_swarm_tasks(swarm_id)
            completed_titles: set[str] = {
                t["title"] for t in all_tasks_now if t["status"] == "completed"
            }
            max_rounds = 30
            MAX_TASK_RETRIES = SWARM_MAX_TASK_RETRIES
            # Use persistent retry counts so retries survive auto-restarts
            if swarm_id not in self._task_retries:
                self._task_retries[swarm_id] = {}
            retry_counts = self._task_retries[swarm_id]

            for round_no in range(max_rounds):
                tasks = await self.db.get_swarm_tasks(swarm_id)
                pending = [t for t in tasks if t["status"] == "pending"]
                waiting = [t for t in tasks if t["status"] == "waiting"]

                if not pending:
                    if waiting:
                        log.info(
                            "Swarm idle — tasks waiting for user input",
                            swarm_id=swarm_id, waiting=[t["title"] for t in waiting],
                        )
                        await self._emit(swarm_id, "swarm:waiting_for_user", {
                            "swarm_id": swarm_id,
                            "waiting_tasks": [t["title"] for t in waiting],
                        })
                    break

                # Find tasks whose dependencies are all met
                def _deps(t: dict) -> list:
                    try:
                        return json.loads(t.get("depends_on") or "[]")
                    except Exception:
                        return []

                ready = [
                    t for t in pending
                    if all(d in completed_titles for d in _deps(t))
                ]

                if not ready:
                    log.warning("Swarm stalled — no ready tasks", swarm_id=swarm_id, round=round_no)
                    await self._emit(swarm_id, "swarm:stalled", {"swarm_id": swarm_id, "round": round_no})
                    break

                await self._emit(swarm_id, "swarm:round", {
                    "swarm_id": swarm_id,
                    "round": round_no,
                    "ready_tasks": [t["title"] for t in ready],
                })

                # Run all ready tasks IN PARALLEL (throttled by semaphore)
                # _run_one is defined outside the loop to avoid re-definition on each round
                async def _run_one(task, _sem=sem, _itw=id_to_worker, _ws=workers,
                                   _sw=swarm, _aw=workers,
                                   _rc=retry_counts, _max_rc=MAX_TASK_RETRIES):
                    async with _sem:
                        worker = _itw.get(task.get("worker_id"))
                        if not worker and _ws:
                            worker = _ws[task["id"] % len(_ws)]
                        if not worker:
                            await self.db.update_swarm_task(
                                task["id"], status="failed", result="No worker assigned"
                            )
                            return None
                        result_status = await self._execute_task(_sw, worker, task, _aw)
                        if result_status == "completed":
                            return task["title"]
                        if result_status == "failed":
                            used = _rc.get(task["id"], 0)
                            if used < _max_rc:
                                _rc[task["id"]] = used + 1
                                log.info(
                                    "Task failed — retrying",
                                    task_id=task["id"],
                                    task_title=task["title"],
                                    attempt=used + 2,
                                    max_attempts=_max_rc + 1,
                                )
                                # Persist the failed attempt result so the next worker
                                # gets a full history of what was tried and why it failed.
                                import json as _json_retry
                                prev_result = task.get("result") or ""
                                _, prev_fail = self._parse_task_status(prev_result)
                                new_entry = {"result": prev_result, "fail_reason": prev_fail or "Task did not complete"}
                                try:
                                    existing = _json_retry.loads(task.get("retry_history_json") or "[]")
                                except Exception:
                                    existing = []
                                history_json = _json_retry.dumps(existing + [new_entry])
                                await self.db.update_swarm_task(
                                    task["id"], status="pending",
                                    result=f"[Retry {used + 1}/{_max_rc}]",
                                    retry_history_json=history_json,
                                )
                                await self._emit_task_event(swarm_id, task["id"], "pending", {
                                    "task_title": task["title"],
                                    "retry_attempt": used + 2,
                                })
                                return None  # will be picked up as pending in next round
                            # Exhausted retries — cascade failure to all dependent tasks so
                            # the swarm can continue with independent tasks instead of stalling.
                            log.warning(
                                "Task exhausted retries — cascading failure to dependents",
                                task_id=task["id"],
                                task_title=task["title"],
                                attempts=_max_rc + 1,
                            )
                            await self._cascade_fail(swarm_id, task["title"])
                        return None  # waiting or permanently failed — do NOT unblock dependents

                results = await asyncio.gather(*[_run_one(t) for t in ready], return_exceptions=True)
                for r in results:
                    if isinstance(r, str):
                        completed_titles.add(r)

                # Check for cancellation / pause
                current = await self.db.get_swarm(swarm_id)
                if current and current["status"] == "paused":
                    await self._emit(swarm_id, "swarm:paused_mid_run", {"swarm_id": swarm_id})
                    return

            # Check final state to decide whether to synthesize or just go idle
            tasks_final = await self.db.get_swarm_tasks(swarm_id)
            has_waiting = any(t["status"] == "waiting" for t in tasks_final)
            has_pending = any(t["status"] == "pending" for t in tasks_final)

            if has_waiting or has_pending:
                if has_pending and not has_waiting:
                    # Check if any pending task is actually runnable (deps all completed).
                    # If a task FAILED and new tasks depend on it, they'll never be ready →
                    # don't restart or we loop forever.
                    completed_now = {
                        t["title"] for t in tasks_final if t["status"] == "completed"
                    }

                    def _deps_final(t: dict) -> list:
                        try:
                            return json.loads(t.get("depends_on") or "[]")
                        except Exception:
                            return []

                    pending_tasks_final = [t for t in tasks_final if t["status"] == "pending"]
                    has_runnable = any(
                        all(d in completed_now for d in _deps_final(t))
                        for t in pending_tasks_final
                    )

                    if not has_runnable:
                        # All pending tasks are blocked on failed/missing dependencies — truly stalled.
                        log.warning(
                            "Swarm has pending tasks but none are runnable (blocked deps) — going idle",
                            swarm_id=swarm_id,
                            pending=[t["title"] for t in pending_tasks_final],
                        )
                        await self.db.update_swarm(swarm_id, status="idle")
                        await self._emit(swarm_id, "swarm:stalled", {"swarm_id": swarm_id, "round": -1})
                        await self._emit(swarm_id, "swarm:idle", {"swarm_id": swarm_id})
                    else:
                        # Pending tasks exist that are NOT blocked on user input and ARE runnable.
                        # This happens when workers create new tasks via swarm_report_bug or
                        # swarm_create_task during the last round — the loop exited before
                        # picking them up. Auto-restart instead of going idle.
                        log.info(
                            "Swarm has unblocked pending tasks after loop exit — auto-restarting",
                            swarm_id=swarm_id,
                        )
                        await self._emit(swarm_id, "swarm:restarting", {
                            "swarm_id": swarm_id,
                            "reason": "new_tasks_created_by_workers",
                        })
                        # Schedule a fresh run after this coroutine exits so self._running
                        # is clean before the new task registers itself.
                        async def _delayed_restart():
                            await asyncio.sleep(0.5)  # let the current task finish + done callback fire
                            if swarm_id not in self._running:
                                await self.db.update_swarm(swarm_id, status="running")
                                t = asyncio.create_task(self._run_swarm(swarm_id))
                                self._running[swarm_id] = t
                                t.add_done_callback(lambda _: self._running.pop(swarm_id, None))
                        asyncio.ensure_future(_delayed_restart())
                        return
                else:
                    # Tasks are blocked on user input — go idle and wait for user message.
                    await self.db.update_swarm(swarm_id, status="idle")
                    await self._emit_swarm_event(swarm_id, "idle", {"reason": "waiting_for_user"})
                    await self._emit(swarm_id, "swarm:idle", {"swarm_id": swarm_id})
            else:
                # All tasks finished — synthesize and mark idle
                self._task_retries.pop(swarm_id, None)   # clean up retry state
                self._llm_semaphores.pop(swarm_id, None)  # clean up LLM throttle
                await self._emit(swarm_id, "swarm:synthesizing", {"swarm_id": swarm_id})
                final_result = await self._synthesize(swarm, workers)

                swarm_dir = Path(swarm["workspace_path"])
                (swarm_dir / "result.md").write_text(final_result, encoding="utf-8")

                await self.db.update_swarm(swarm_id, status="idle")
                await self._emit_swarm_event(swarm_id, "idle", {"result_preview": final_result[:500]})
                await self._emit(swarm_id, "swarm:idle", {
                    "swarm_id": swarm_id,
                    "result_preview": final_result[:500],
                    "workspace_path": str(swarm_dir),
                })

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Swarm execution failed", swarm_id=swarm_id, error=str(e))
            await self.db.update_swarm(swarm_id, status="failed")
            await self._emit_swarm_event(swarm_id, "failed", {"error": str(e)})

    async def _execute_task(
        self,
        swarm: dict,
        worker: dict,
        task: dict,
        all_workers: list[dict],
    ) -> str:
        """Run a single task through its assigned worker."""
        from openacm.core.config import AssistantConfig
        from openacm.core.brain import Brain

        swarm_id = swarm["id"]
        worker_id = worker["id"]
        task_id = task["id"]

        await self.db.update_swarm_worker(worker_id, status="busy")
        await self.db.update_swarm_task(task_id, status="running")
        await self._emit_worker_event(swarm_id, worker_id, "busy", {
            "worker_name": worker["name"], "task_id": task_id, "task_title": task["title"],
        })
        await self._emit_task_event(swarm_id, task_id, "running", {
            "task_title": task["title"], "worker_id": worker_id, "worker_name": worker["name"],
        })
        await self._emit(swarm_id, "swarm:worker_thinking", {
            "worker_id": worker_id, "worker_name": worker["name"],
            "task_title": task["title"],
        })

        try:
            # Collect outputs from tasks this task depends on so the worker has
            # full context of what teammates already produced.
            dep_outputs: list[tuple[str, str]] = []
            try:
                dep_titles = json.loads(task.get("depends_on") or "[]")
                if dep_titles:
                    all_tasks_now = await self.db.get_swarm_tasks(swarm_id)
                    completed_map = {
                        t["title"]: t for t in all_tasks_now if t["status"] == "completed"
                    }
                    for dep_title in dep_titles:
                        dep_task = completed_map.get(dep_title)
                        if dep_task and dep_task.get("result"):
                            dep_outputs.append((dep_title, dep_task["result"]))
            except Exception as e:
                log.warning("Could not gather dependency outputs for task", error=str(e))

            # Collect previous attempt results so the worker knows what was tried and why it failed.
            retry_history: list[dict] = []
            try:
                prev_result = task.get("result") or ""
                if prev_result and not prev_result.startswith("[Retry ") and not prev_result.startswith("[Rate ") and not prev_result.startswith("[Network ") and not prev_result.startswith("[Skipped"):
                    task_status_prev, fail_reason_prev = self._parse_task_status(prev_result)
                    retry_history.append({"result": prev_result, "fail_reason": fail_reason_prev or "Task did not complete"})
                # Also grab accumulated history stored in task metadata key
                import json as _rjson
                stored = task.get("retry_history_json") or "[]"
                extra = _rjson.loads(stored) if stored != "[]" else []
                retry_history = extra + retry_history
            except Exception:
                pass

            # Build context: shared contract + dependency outputs + messages + task description
            messages_in = await self.db.get_swarm_messages(swarm_id, to_worker_id=worker_id)
            messages_in = messages_in[-20:]  # cap to last 20 to avoid context overflow
            swarm_context = self._build_worker_context(
                swarm, worker, task, messages_in, dep_outputs,
                retry_history=retry_history or None,
            )

            # System prompt with swarm awareness
            system_prompt = self._build_worker_system_prompt(worker, swarm, all_workers)

            config = AssistantConfig(
                name=worker["name"],
                system_prompt=system_prompt,
                max_tool_iterations=30,  # swarm tasks are complex — need more steps than chat
                onboarding_completed=True,  # workers skip onboarding entirely
            )

            # Model override: worker-specific > swarm global > system default
            model_override = worker.get("model") or swarm.get("global_model") or None

            # Create a Brain for this worker with communication tools injected
            brain = Brain(
                config=config,
                llm_router=self.llm_router,
                memory=self.memory,
                event_bus=self.event_bus,
                tool_registry=self._build_worker_tool_registry(
                    swarm_id, worker_id, all_workers, worker
                ),
            )

            # If a model override is set, patch the router call
            if model_override:
                _orig_chat = brain.llm_router.chat

                async def _patched_chat(*args, **kwargs):
                    kwargs.setdefault("model_override", model_override)
                    return await _orig_chat(*args, **kwargs)

                brain.llm_router.chat = _patched_chat

            # Unique channel per task so memory never bleeds between task executions
            channel_id = f"swarm_{swarm_id}_worker_{worker_id}_task_{task_id}"

            # Acquire per-swarm LLM semaphore to throttle concurrent LLM calls.
            # Default: max 2 workers active at the same time per swarm.
            # This prevents TPM rate limits when running many workers in parallel.
            if swarm_id not in self._llm_semaphores:
                self._llm_semaphores[swarm_id] = asyncio.Semaphore(2)
            llm_sem = self._llm_semaphores[swarm_id]

            # 10-minute hard timeout per task — prevents infinite hangs
            try:
                async with llm_sem:
                    response = await asyncio.wait_for(
                        brain.process_message(
                            content=swarm_context,
                            user_id=f"swarm_{swarm_id}",
                            channel_id=channel_id,
                            channel_type="swarm",
                        ),
                        timeout=600.0,
                    )
            except asyncio.TimeoutError:
                raise RuntimeError(f"Task timed out after 10 minutes")

            # Save result
            worker_dir = Path(worker["workspace_path"])
            worker_dir.mkdir(parents=True, exist_ok=True)
            (worker_dir / f"task_{task_id}_result.md").write_text(
                response or "", encoding="utf-8"
            )

            # Determine actual task status from the worker's explicit marker
            task_status, fail_reason = self._parse_task_status(response or "")

            result_preview = (response or "")[:200]
            await self.db.update_swarm_task(task_id, status=task_status, result=response or "")
            await self.db.update_swarm_worker(worker_id, status="idle")

            # Store task result as activity message so the feed shows it
            if task_status == "completed":
                msg_type = "task_result"
                msg_content = f"**[{task['title']}]**\n\n{response or '(no output)'}"
            elif task_status == "waiting":
                msg_type = "task_waiting"
                msg_content = f"**[{task['title']}]** waiting for user input."
            else:
                msg_type = "task_failed"
                msg_content = f"**[{task['title']}] FAILED:** {fail_reason}\n\n{response or ''}"

            await self.db.add_swarm_message(
                swarm_id=swarm_id,
                from_worker_id=worker_id,
                to_worker_id=None,
                content=msg_content,
                message_type=msg_type,
            )
            await self._emit_task_event(swarm_id, task_id, task_status, {
                "task_title": task["title"], "worker_name": worker["name"],
                "result_preview": result_preview,
            })
            await self._emit_worker_event(swarm_id, worker_id, "idle", {"worker_name": worker["name"]})
            await self._emit(swarm_id, "swarm:worker_done", {
                "worker_id": worker_id, "worker_name": worker["name"],
                "task_title": task["title"], "result_preview": result_preview,
            })
            return task_status  # return status so _run_swarm can track completed_titles correctly

        except Exception as e:
            err_str = str(e)
            err_type = type(e).__name__.lower()
            is_rate_limit = "RateLimitError" in err_str or "rate limit" in err_str.lower() or "429" in err_str
            is_network_drop = (
                "readerror" in err_type
                or "connectionerror" in err_type
                or "remotedisconnected" in err_type
                or "ReadError" in err_str
                or "read error" in err_str.lower()
            )

            if is_network_drop and not is_rate_limit:
                # Transient network failure (server dropped the stream) — requeue with backoff
                log.warning(
                    "Task hit network drop — requeueing as pending",
                    task_id=task_id, task_title=task["title"], error=err_str,
                )
                await self.db.update_swarm_task(
                    task_id, status="pending",
                    result=f"[Network drop — requeued for retry]",
                )
                await self.db.update_swarm_worker(worker_id, status="idle")
                await self._emit_task_event(swarm_id, task_id, "pending", {
                    "task_title": task["title"], "reason": "network_drop",
                })
                await asyncio.sleep(15)
                return "rate_limited"  # same treatment: neither completed nor failed

            if is_rate_limit:
                # Transient error — reset to pending without burning a retry attempt.
                # Extract suggested wait time from the error message if available.
                import re as _re
                wait_match = _re.search(r"try again in (\d+(?:\.\d+)?)s", err_str, _re.IGNORECASE)
                wait_secs = float(wait_match.group(1)) + 1.0 if wait_match else 15.0
                log.warning(
                    "Task hit rate limit — requeueing as pending",
                    task_id=task_id, task_title=task["title"], wait_secs=wait_secs,
                )
                await self.db.update_swarm_task(
                    task_id, status="pending",
                    result=f"[Rate limited — requeued after {wait_secs:.0f}s wait]"
                )
                await self.db.update_swarm_worker(worker_id, status="idle")
                await self._emit_task_event(swarm_id, task_id, "pending", {
                    "task_title": task["title"], "reason": "rate_limited",
                })
                await asyncio.sleep(wait_secs)
                return "rate_limited"  # treated as neither completed nor failed

            log.error("Task execution failed", task_id=task_id, error=err_str)
            await self.db.update_swarm_task(task_id, status="failed", result=err_str)
            await self.db.update_swarm_worker(worker_id, status="idle")
            # Store failure as activity message
            await self.db.add_swarm_message(
                swarm_id=swarm_id,
                from_worker_id=worker_id,
                to_worker_id=None,
                content=f"**[{task['title']}]** failed: {e}",
                message_type="task_failed",
            )
            await self._emit_task_event(swarm_id, task_id, "failed", {
                "task_title": task["title"], "error": err_str,
            })
            await self._emit_worker_event(swarm_id, worker_id, "idle", {"worker_name": worker["name"]})
            await self._emit(swarm_id, "swarm:worker_error", {
                "worker_id": worker_id, "worker_name": worker["name"],
                "task_title": task["title"], "error": err_str,
            })
            return f"Error: {e}"

    async def _synthesize(self, swarm: dict, workers: list[dict]) -> str:
        """Orchestrator final synthesis of all task results."""
        swarm_id = swarm["id"]
        tasks = await self.db.get_swarm_tasks(swarm_id)
        completed = [t for t in tasks if t["status"] == "completed"]

        if not completed:
            return "No tasks completed."

        results_text = "\n\n".join(
            f"### Task: {t['title']}\n{t.get('result', '')}" for t in completed
        )

        synthesis_prompt = (
            f"You are the project orchestrator. The following tasks were completed "
            f"by the worker team for this goal:\n\n"
            f"**Goal:** {swarm['goal']}\n\n"
            f"**Task Results:**\n{results_text}\n\n"
            f"Please write a concise final summary of what was accomplished, "
            f"any key outputs, and next steps if applicable."
        )

        try:
            result = await self.llm_router.chat(
                messages=[{"role": "user", "content": synthesis_prompt}],
                temperature=0.3,
                max_tokens=2048,
                model_override=swarm.get("global_model") or None,
            )
            content = result.get("content", "Synthesis failed.")
            # Persist synthesis as a special activity message
            await self.db.add_swarm_message(
                swarm_id=swarm_id,
                from_worker_id=None,
                to_worker_id=None,
                content=content,
                message_type="synthesis",
            )
            return content
        except Exception as e:
            return f"Synthesis error: {e}"

    # ─── Worker Tool Registry ─────────────────────────────────────────────────

    def _build_worker_tool_registry(
        self, swarm_id: int, worker_id: int, all_workers: list[dict], worker: dict
    ):
        """
        Return a tool registry that includes normal tools PLUS swarm communication tools.
        """
        from openacm.core.swarm_tools import build_swarm_tools

        if not self.tool_registry:
            return None

        # Build the swarm-specific tools bound to this worker
        swarm_tool_fns = build_swarm_tools(
            swarm_id=swarm_id,
            worker_id=worker_id,
            all_workers=all_workers,
            database=self.db,
            event_bus=self.event_bus,
        )

        # Respect allowed_tools policy
        allowed = worker.get("allowed_tools", "all")

        from openacm.tools.base import ToolDefinition as _TD

        # Wrap swarm comm functions into ToolDefinition objects so the registry
        # can find and execute them like any other tool.
        swarm_tool_defs = {}
        for fn in swarm_tool_fns:
            schema = fn._tool_schema
            fn_schema = schema["function"]
            td = _TD(
                name=fn_schema["name"],
                description=fn_schema["description"],
                parameters=fn_schema.get("parameters", {"type": "object", "properties": {}, "required": []}),
                handler=fn,
                risk_level="low",
                category="swarm",
            )
            swarm_tool_defs[td.name] = td

        async def _swarm_auto_approve(tool: str, command: str, channel_id: str) -> bool:
            """Swarm workers always auto-approve tool calls — no user blocking."""
            return True

        class _SwarmRegistry:
            def __init__(self_inner):
                self_inner._base = self.tool_registry
                # Merge base ToolDefinitions + swarm ToolDefinitions (all proper objects)
                self_inner.tools = {**self.tool_registry.tools, **swarm_tool_defs}
                # Override confirm_callback so workers never block waiting for the user
                self_inner.confirm_callback = _swarm_auto_approve

            def get_tools_schema(self_inner):
                base_tools = []
                if allowed == "all":
                    base_tools = self_inner._base.get_tools_schema()
                elif allowed != "none":
                    try:
                        names = json.loads(allowed)
                        all_base = self_inner._base.get_tools_schema()
                        base_tools = [t for t in all_base if t["function"]["name"] in names]
                    except Exception:
                        base_tools = self_inner._base.get_tools_schema()

                swarm_schemas = [td.to_openai_schema() for td in swarm_tool_defs.values()]
                return base_tools + swarm_schemas

            def get_tools_by_intent(self_inner, msg):
                return self_inner.get_tools_schema()

            def __getattr__(self_inner, name):
                return getattr(self_inner._base, name)

        return _SwarmRegistry()

    # Read-only tool names the orchestrator can use in react mode to understand context.
    # Excludes anything that writes, executes, or modifies state.
    _READONLY_TOOL_NAMES = frozenset({
        "read_file", "read_file_range", "list_directory",
        "grep_in_files", "glob_files", "search_files",
    })

    def _build_swarm_only_registry(
        self, swarm_id: int, worker_id: int, all_workers: list[dict], worker: dict
    ):
        """
        Coordination + read-only registry for orchestrator react mode.
        Includes swarm tools + read-only file tools.
        Excludes run_command, write_file, run_python, and all other execution tools
        so the orchestrator is forced to DELEGATE work via swarm_create_task.
        """
        from openacm.core.swarm_tools import build_swarm_tools
        from openacm.tools.base import ToolDefinition as _TD

        swarm_tool_fns = build_swarm_tools(
            swarm_id=swarm_id,
            worker_id=worker_id,
            all_workers=all_workers,
            database=self.db,
            event_bus=self.event_bus,
        )

        swarm_tool_defs = {}
        for fn in swarm_tool_fns:
            schema = fn._tool_schema
            fn_schema = schema["function"]
            td = _TD(
                name=fn_schema["name"],
                description=fn_schema["description"],
                parameters=fn_schema.get("parameters", {"type": "object", "properties": {}, "required": []}),
                handler=fn,
                risk_level="low",
                category="swarm",
            )
            swarm_tool_defs[td.name] = td

        async def _auto_approve(tool: str, command: str, channel_id: str) -> bool:
            return True

        class _SwarmOnlyRegistry:
            def __init__(self_inner):
                self_inner._base = self.tool_registry
                # Swarm tools + read-only base tools
                readonly_base = {
                    name: td
                    for name, td in self.tool_registry.tools.items()
                    if name in SwarmManager._READONLY_TOOL_NAMES
                }
                self_inner.tools = {**readonly_base, **swarm_tool_defs}
                self_inner.confirm_callback = _auto_approve

            def get_tools_schema(self_inner):
                return [td.to_openai_schema() for td in self_inner.tools.values()]

            def get_tools_by_intent(self_inner, msg):
                return self_inner.get_tools_schema()

            def __getattr__(self_inner, name):
                return getattr(self_inner._base, name)

        return _SwarmOnlyRegistry()

    # ─── Contract Generator ───────────────────────────────────────────────────

    async def _generate_contract(
        self,
        swarm_id: int,
        swarm: dict,
        workers: list[dict],
        tasks: list[dict],
    ) -> str:
        """
        Generate a shared interface contract for the swarm.

        The contract defines — before any worker writes code — the agreed-upon:
        - Event names and payloads
        - Data schemas / TypeScript interfaces
        - File ownership (which worker writes which files)
        - DOM element IDs UI workers must create
        - Canonical import paths for shared modules
        - Public API signatures for classes other workers will import

        This is the primary fix for cross-worker incompatibility.
        """
        worker_list = "\n".join(
            f"- {w['name']} ({w.get('role','worker')}): {w.get('description','')}"
            for w in workers
        )
        task_list = "\n".join(
            f"- [{t.get('worker','?')}] {t['title']} (depends_on: {t.get('depends_on', [])})"
            for t in tasks
        )

        prompt = (
            f"You are a software architect for a multi-agent AI development team.\n\n"
            f"**Project Goal:** {swarm['goal']}\n\n"
            f"**Team:**\n{worker_list}\n\n"
            f"**Planned Tasks (in dependency order):**\n{task_list}\n\n"
            f"Generate a concise `CONTRACT.md` that ALL workers must follow before writing any code.\n\n"
            f"The contract must specify:\n"
            f"1. **File Ownership** — which worker owns which files/directories.\n"
            f"   Only the owner writes to those files. Others only read them.\n"
            f"2. **Shared Events** — if using an event bus or pub/sub, list every event name\n"
            f"   with its exact payload structure (as a JSON example or TypeScript interface).\n"
            f"3. **Data Schemas** — exact shape of shared data objects that cross worker boundaries.\n"
            f"4. **Public APIs** — for any class/module that another worker will import: the file path,\n"
            f"   class name, constructor signature, and public method signatures.\n"
            f"5. **DOM Requirements** — if there is a UI worker: the exact element IDs that MUST exist\n"
            f"   in the HTML (e.g. `#app`, `#subtitle-text`). UI worker creates them; others reference them.\n"
            f"6. **Import Paths** — canonical relative import paths from the entry-point file (e.g. `main.js`)\n"
            f"   to every shared module.\n"
            f"7. **Entry Point** — the single file that wires everything together. ONLY the Integration\n"
            f"   worker (or orchestrator) writes this file.\n\n"
            f"Be CONCRETE and SPECIFIC. Use real file paths, real method names, real event names.\n"
            f"Avoid vague statements like 'workers should coordinate'. Write exact interfaces.\n\n"
            f"Output ONLY the markdown content of CONTRACT.md — no preamble."
        )

        result = await self.llm_router.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=4096,
            model_override=swarm.get("global_model") or None,
        )
        return result.get("content", "")

    # ─── Prompt Builders ─────────────────────────────────────────────────────

    # ~200k chars ≈ ~50k tokens — safe for all providers including Gemini 1M limit
    _MAX_CONTEXT_CHARS = 200_000

    def _build_plan_prompt(self, swarm: dict) -> str:
        ctx = swarm.get("shared_context", "") or ""
        if len(ctx) > self._MAX_CONTEXT_CHARS:
            ctx = ctx[: self._MAX_CONTEXT_CHARS] + "\n\n[...context truncated for planning...]"
        ctx_section = f"\n\n**Provided context files:**\n{ctx}" if ctx else ""

        return f"""You are a project planning AI. Design an optimal team of AI worker agents
to accomplish the following goal.{ctx_section}

**Goal:** {swarm["goal"]}

Return ONLY valid JSON with this exact structure:
{{
  "workers": [
    {{
      "name": "Worker Name",
      "role": "orchestrator|worker",
      "description": "What this worker does",
      "system_prompt": "Detailed system prompt for this worker...",
      "model": null,
      "allowed_tools": "all"
    }}
  ],
  "tasks": [
    {{
      "title": "Task title",
      "description": "Detailed task description",
      "worker": "Worker Name",
      "depends_on": []
    }}
  ]
}}

Rules:
- Include exactly ONE worker with role "orchestrator" (project lead)
- Include 2-5 specialist workers depending on complexity
- The model field can be null (use global) or a LiteLLM model string like "anthropic/claude-opus-4-6"
- Tasks in depends_on must reference titles of earlier tasks EXACTLY as written
- Workers WILL be able to communicate with each other during execution
- Each worker should have a clear, focused role and own a specific set of files
- System prompts must include the worker's specialty and which files they own
- If the goal involves testing, QA, or validation: include a dedicated QA worker whose system prompt explicitly instructs it to use the `swarm_report_bug` tool for every issue found (NOT just fail the task). The QA worker should also schedule its verification tasks AFTER the implementation tasks (via depends_on).
- When a QA worker is present, also ensure there is a developer/fixer worker who can receive bug fix tasks.
- ALWAYS include a final "Integration" task assigned to the orchestrator (or most senior worker). This task must: (1) read ALL files produced by other workers using read_file, (2) wire them together into the project entry point (e.g., main.js, index.py, App.tsx), (3) have depends_on listing ALL other implementation tasks. Without this task the project will be a collection of disconnected files.
- After planning, a shared interface CONTRACT will be auto-generated and given to every worker. Design the plan so interfaces between workers are clean and minimal — fewer cross-worker dependencies means fewer integration bugs."""

    @staticmethod
    async def _cascade_fail(self, swarm_id: int, failed_title: str) -> None:
        """Recursively fail all tasks that (directly or transitively) depend on failed_title.

        This prevents the swarm from stalling when a task permanently fails — independent
        tasks continue running and only tasks that actually needed the failed output are skipped.
        """
        all_tasks = await self.db.get_swarm_tasks(swarm_id)
        to_fail: list[dict] = []

        def _collect(blocked_by: str) -> None:
            for t in all_tasks:
                if t["status"] not in ("pending", "running"):
                    continue
                try:
                    deps = json.loads(t.get("depends_on") or "[]")
                except Exception:
                    deps = []
                if blocked_by in deps and t not in to_fail:
                    to_fail.append(t)
                    _collect(t["title"])  # recurse for transitively dependent tasks

        _collect(failed_title)

        for t in to_fail:
            reason = f"Dependency '{failed_title}' permanently failed"
            await self.db.update_swarm_task(
                t["id"], status="failed",
                result=f"[Skipped] {reason}",
            )
            await self._emit_task_event(swarm_id, t["id"], "failed", {
                "task_title": t["title"],
                "reason": reason,
            })
            log.info("Cascade-failed dependent task", task_title=t["title"], blocked_by=failed_title)

    @staticmethod
    def _parse_task_status(response: str) -> tuple[str, str]:
        """
        Scan the last few lines of a worker response for an explicit status marker.
        Returns (status, fail_reason) where status is 'completed', 'failed', or 'waiting'.
        'waiting' means the worker asked the user a question and needs an answer to proceed.
        Falls back to failure detection heuristics before defaulting to 'completed'.
        """
        import re as _re

        # Signals that the brain interrupted the worker before it could finish.
        # These must be detected BEFORE checking for TASK_STATUS markers so a
        # partial response that happens to precede one of these strings doesn't
        # accidentally get marked completed.
        _BRAIN_INTERRUPTS = (
            "alcanzé el límite de pasos",       # brain: max_iterations in Spanish
            "no obtuve una respuesta final",     # brain: empty_response fallback
            "❌ request timed out",              # brain/swarm: readError/timeout
            "readError",                         # raw exception string
            "readerror",
            "timed out",
            "task timed out",
        )
        response_lower = response.lower()
        if any(sig.lower() in response_lower for sig in _BRAIN_INTERRUPTS):
            return "failed", "Worker hit step limit or connection timeout before completing"

        for line in reversed(response.strip().splitlines()):
            line = line.strip()
            m = _re.match(r"TASK_STATUS:\s*(COMPLETED|FAILED)(?::\s*(.*))?", line, _re.IGNORECASE)
            if m:
                status = m.group(1).lower()
                reason = (m.group(2) or "").strip()
                # Special case: waiting_for_user means blocked on user input, not a real failure
                if "waiting_for_user" in reason.lower():
                    return "waiting", reason
                return status, reason
        # No marker — worker didn't follow the protocol. Treat as completed so
        # well-behaved models that produce real output are not penalised.
        # Workers that genuinely failed should use TASK_STATUS: FAILED.
        return "completed", ""

    def _build_worker_system_prompt(
        self, worker: dict, swarm: dict, all_workers: list[dict]
    ) -> str:
        teammates = [
            f"- {w['name']}: {w.get('description', w.get('role', 'worker'))}"
            for w in all_workers
            if w["id"] != worker["id"]
        ]
        team_section = "\n".join(teammates) if teammates else "None"

        return (
            f"{worker['system_prompt']}\n\n"
            f"---\n"
            f"**Swarm context:**\n"
            f"Project goal: {swarm['goal']}\n"
            f"Your role: {worker.get('role', 'worker')}\n"
            f"Your workspace: {worker['workspace_path']}\n\n"
            f"**Your teammates:**\n{team_section}\n\n"
            f"**Swarm communication tools:**\n"
            f"- `swarm_send_message`: send a message to a specific teammate\n"
            f"- `swarm_broadcast`: send a message to all teammates\n"
            f"- `swarm_read_messages`: read messages sent to you or from the user\n"
            f"- `swarm_ask_user`: post a question to the user in the Activity feed (they will reply as a message)\n"
            f"- `swarm_create_task`: create a new task for yourself or a teammate\n"
            f"- `swarm_report_bug`: (QA workers) report a bug — auto-creates a fix task + re-test task\n\n"
            f"**IMPORTANT RULES:**\n"
            f"- **Read the CONTRACT first**: your task context includes a SHARED INTERFACE CONTRACT.\n"
            f"  Follow it exactly — do not invent your own event names, data formats, DOM IDs, or import paths.\n"
            f"- **File ownership**: only write to the files your role owns per the contract.\n"
            f"  To use another worker's module, import it — do NOT rewrite it.\n"
            f"- **Read dependency outputs**: your context includes the full output of tasks you depend on.\n"
            f"  Read them carefully and build on the actual code/files produced, not assumptions.\n"
            f"- If you need information from the user, call `swarm_ask_user` — NEVER write questions to files.\n"
            f"- Do NOT create README or question files just to ask the user something.\n"
            f"- If blocked waiting for user input, use `swarm_ask_user` then end with TASK_STATUS: FAILED: waiting_for_user\n"
            f"- Read your messages with `swarm_read_messages` before starting — the user may have already answered.\n"
            f"- **If your role is QA/testing**: use `swarm_report_bug` for every issue found. NEVER just mark a task failed silently — report the bug so it gets fixed and re-tested automatically.\n"
            f"- **If your role is orchestrator/auditor**: when reviewing work and finding problems (missing imports, disconnected files, broken wiring), call `swarm_create_task` immediately to create a fix task for the responsible worker. Do NOT just note the problem — create the task so it gets done.\n"
            f"- **Integration tasks**: use `read_file` on EVERY file teammates created, then write the actual wiring code into the entry point (main.js, index.py, etc.). Do not write a summary — write real, runnable code.\n\n"
            f"---\n"
            f"**REQUIRED — always end your response with exactly one of these lines:**\n"
            f"  TASK_STATUS: COMPLETED\n"
            f"  TASK_STATUS: FAILED: <brief reason>\n"
            f"This is mandatory for progress tracking. No exceptions."
        )

    def _build_worker_context(
        self,
        swarm: dict,
        worker: dict,
        task: dict,
        messages_in: list[dict],
        dep_outputs: list[tuple[str, str]] | None = None,
        retry_history: list[dict] | None = None,
    ) -> str:
        parts = [
            f"# Task: {task['title']}\n\n{task['description']}",
        ]

        # ── 0. Retry History ──────────────────────────────────────────────────
        # If this task was attempted before, inject a summary of what was tried,
        # what was accomplished, and why it failed so the worker can continue
        # from where the previous attempt left off rather than starting over.
        if retry_history:
            history_lines = []
            for i, h in enumerate(retry_history, 1):
                entry = (
                    f"### Attempt {i} (failed)\n"
                    f"**Why it failed:** {h.get('fail_reason', 'Unknown')}\n\n"
                    f"**What was done / partial output:**\n{truncate(h.get('result', '(no output)'), 3000)}"
                )
                if h.get("user_notes"):
                    entry += f"\n\n**👤 User guidance for this retry:** {h['user_notes']}"
                history_lines.append(entry)
            parts.append(
                f"\n## ⚠️ RETRY — Previous Attempt(s) Failed\n"
                f"This task was attempted {len(retry_history)} time(s) and did not complete.\n"
                f"**Do NOT start over** — read the history below, check what files were already\n"
                f"created in the workspace, and continue or fix from where the last attempt stopped.\n\n"
                + "\n\n".join(history_lines)
            )

        # ── 1. Shared Interface Contract ──────────────────────────────────────
        # Inject CONTRACT.md so workers follow agreed interfaces, not their own
        # invented ones. This is the #1 fix for cross-worker incompatibility.
        try:
            swarm_ws = Path(swarm.get("workspace_path", ""))
            contract_path = swarm_ws / "CONTRACT.md"
            if contract_path.exists():
                contract_content = contract_path.read_text(encoding="utf-8")
                parts.append(
                    f"\n## ⚠️ SHARED INTERFACE CONTRACT (MANDATORY)\n"
                    f"All workers agreed on these interfaces BEFORE any code was written.\n"
                    f"You MUST follow this contract exactly — do not invent your own event names,\n"
                    f"data formats, DOM IDs, or import paths.\n\n"
                    f"{contract_content}"
                )
        except Exception as e:
            log.debug("Could not read swarm contract file", error=str(e))

        # ── 2. Dependency Outputs ─────────────────────────────────────────────
        # If this task depends on others, inject their FULL outputs so the worker
        # knows exactly what was built and can import/extend it correctly.
        if dep_outputs:
            dep_section = "\n\n".join(
                f"### Output of: {title}\n\n{truncate(output, TRUNCATE_SWARM_TASK_OUTPUT_CHARS)}"
                for title, output in dep_outputs
            )
            parts.append(
                f"\n## Output from Tasks You Depend On\n"
                f"Read these carefully — your task builds on this work.\n\n"
                f"{dep_section}"
            )

        # ── 3. Shared Project Context (uploaded files) ────────────────────────
        if swarm.get("shared_context"):
            parts.append(
                f"\n## Shared Project Context\n\n{swarm['shared_context']}"
            )

        # ── 4. Workspace File Listing ─────────────────────────────────────────
        # Shows all files created by the team so far. Workers use read_file to
        # inspect them and build on each other's actual output.
        try:
            swarm_ws = Path(swarm.get("workspace_path", ""))
            if swarm_ws.is_dir():
                workspace_files = []
                for root, dirs, fnames in os.walk(swarm_ws):
                    dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__", ".venv")]
                    for f in fnames:
                        rel = Path(root, f).relative_to(swarm_ws)
                        workspace_files.append(str(rel))
                if workspace_files:
                    file_list = "\n".join(f"- {f}" for f in sorted(workspace_files)[:150])
                    parts.append(
                        f"\n## Workspace Files (created by the team so far)\n"
                        f"Use `read_file` to inspect any file and build on teammates' work.\n"
                        f"Workspace root: {swarm_ws}\n\n{file_list}"
                    )
        except Exception as e:
            log.debug("Could not list swarm workspace files", error=str(e))

        # ── 5. Incoming Messages ──────────────────────────────────────────────
        if messages_in:
            msgs_formatted = "\n".join(
                f"- From {m.get('from_worker_name', 'unknown')}: {m['content']}"
                for m in messages_in
            )
            parts.append(f"\n## Messages from teammates\n\n{msgs_formatted}")

        return "\n\n".join(parts)

    # ─── Plan Parser ─────────────────────────────────────────────────────────

    @staticmethod
    def _repair_json(text: str) -> str:
        """
        Best-effort repair of common LLM JSON mistakes:
        - Trailing commas before } or ]
        - Truncated JSON (attempt to close open brackets)
        """
        import re as _re
        # Remove trailing commas before closing brackets/braces
        text = _re.sub(r",\s*([}\]])", r"\1", text)
        # If JSON appears truncated (unbalanced braces), try to close it
        opens = text.count("{") - text.count("}")
        arr_opens = text.count("[") - text.count("]")
        if opens > 0 or arr_opens > 0:
            # Truncate to last complete value boundary and close
            # Find last complete "...": "..." or "...": [...] or "...": {...}
            text = text.rstrip().rstrip(",")
            text += "]" * max(arr_opens, 0)
            text += "}" * max(opens, 0)
        return text

    def _parse_plan(self, text: str) -> dict:
        """Extract JSON plan from LLM response."""
        import re
        stripped = text.strip()

        # 1. Direct parse (model returned raw JSON)
        try:
            return json.loads(stripped)
        except Exception:
            pass

        # 2. Extract content from markdown fence using regex (handles trailing newlines, ```json, etc.)
        fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", stripped)
        if fence_match:
            candidate = fence_match.group(1).strip()
            try:
                return json.loads(candidate)
            except Exception:
                # Try repairing the fenced content (truncated JSON)
                try:
                    return json.loads(self._repair_json(candidate))
                except Exception:
                    pass

        # 3. Find any {...} JSON object in the text (greedy — catches the outermost object)
        obj_match = re.search(r"\{[\s\S]*\}", stripped)
        if obj_match:
            candidate = obj_match.group()
            try:
                return json.loads(candidate)
            except Exception:
                try:
                    return json.loads(self._repair_json(candidate))
                except Exception:
                    pass

        # 4. The fence may be unclosed (model cut off mid-response) — try from first { to end
        first_brace = stripped.find("{")
        if first_brace != -1:
            try:
                return json.loads(self._repair_json(stripped[first_brace:]))
            except Exception:
                pass

        log.error("Failed to parse swarm plan", text=text[:500])
        # Return minimal fallback plan
        return {
            "workers": [
                {
                    "name": "General Worker",
                    "role": "worker",
                    "description": "General purpose worker",
                    "system_prompt": "You are a helpful AI assistant. Complete the given task.",
                    "model": None,
                    "allowed_tools": "all",
                }
            ],
            "tasks": [
                {
                    "title": "Main Task",
                    "description": "Complete the project goal.",
                    "worker": "General Worker",
                    "depends_on": [],
                }
            ],
        }

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _swarm_dir(self, swarm_id: int) -> Path:
        workspace = Path(os.environ.get("OPENACM_WORKSPACE", "workspace"))
        return workspace / "swarms" / str(swarm_id)

    async def _emit(self, swarm_id: int, event_type: str, payload: dict):
        """Emit any swarm-related event.  All events carry swarm_id for filtering."""
        payload.setdefault("swarm_id", swarm_id)
        payload["_ts"] = datetime.now(timezone.utc).isoformat()
        try:
            await self.event_bus.emit(event_type, payload)
        except Exception:
            pass

    # Convenience wrappers kept for readability
    async def _emit_swarm_event(self, swarm_id: int, status: str, extra: dict | None = None):
        await self._emit(swarm_id, EVENT_SWARM_UPDATED, {"status": status, **(extra or {})})

    async def _emit_worker_event(self, swarm_id: int, worker_id: int, status: str, extra: dict | None = None):
        await self._emit(swarm_id, EVENT_SWARM_WORKER_STATUS, {"worker_id": worker_id, "status": status, **(extra or {})})

    async def _emit_task_event(self, swarm_id: int, task_id: int, status: str, extra: dict | None = None):
        await self._emit(swarm_id, EVENT_SWARM_TASK_UPDATED, {"task_id": task_id, "status": status, **(extra or {})})
