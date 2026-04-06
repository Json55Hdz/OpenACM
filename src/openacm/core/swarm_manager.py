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
                max_tokens=4096,
                model_override=swarm.get("global_model") or None,
            )
            plan_text = result.get("content", "")
            plan = self._parse_plan(plan_text)
        except Exception as e:
            log.error("Swarm planning LLM call failed", swarm_id=swarm_id, error=str(e))
            await self.db.update_swarm(swarm_id, status="failed")
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

            completed = [t for t in tasks if t["status"] == "completed"]
            results_summary = "\n".join(
                f"- {t['title']}: {(t.get('result') or '')[:200]}" for t in completed
            ) or "No tasks completed yet."

            react_prompt = (
                f"You are the orchestrator of swarm '{swarm['name']}'.\n"
                f"Goal: {swarm['goal']}\n\n"
                f"Current status: {swarm['status']}\n\n"
                f"Completed work so far:\n{results_summary}\n\n"
                f"**The user just sent you this message:**\n{user_message}\n\n"
                f"React to the user's feedback. You can:\n"
                f"- Use `swarm_create_task` to create new tasks\n"
                f"- Use `swarm_broadcast` to inform all workers\n"
                f"- Use `swarm_send_message` to direct a specific worker\n"
                f"- Respond with a plan if major changes are needed\n"
                f"Always acknowledge the user's request and take concrete action."
            )

            config = AssistantConfig(
                name=orchestrator["name"],
                system_prompt=orchestrator["system_prompt"],
                max_tool_iterations=8,
            )
            model_override = orchestrator.get("model") or swarm.get("global_model") or None

            brain = Brain(
                config=config,
                llm_router=self.llm_router,
                memory=self.memory,
                event_bus=self.event_bus,
                tool_registry=self._build_worker_tool_registry(
                    swarm_id, orchestrator["id"], workers, orchestrator
                ),
            )
            if model_override:
                _orig = brain.llm_router.chat
                async def _patched(*a, **kw):
                    kw.setdefault("model_override", model_override)
                    return await _orig(*a, **kw)
                brain.llm_router.chat = _patched

            response = await brain.process_message(
                content=react_prompt,
                user_id=f"swarm_{swarm_id}",
                channel_id=f"swarm_{swarm_id}_orchestrator_react",
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

            # If swarm is not running but new tasks were created, auto-restart
            current = await self.db.get_swarm(swarm_id)
            new_pending = await self.db.get_swarm_tasks(swarm_id)
            has_new = any(t["status"] == "pending" for t in new_pending)
            if has_new and current and current["status"] not in ("running",):
                await self.db.update_swarm(swarm_id, status="planned")
                await self._emit_swarm_event(swarm_id, "planned", {"reason": "new tasks from user feedback"})

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
        MAX_PARALLEL = 3
        sem = asyncio.Semaphore(MAX_PARALLEL)

        try:
            await self.db.update_swarm(swarm_id, status="running")
            await self._emit(swarm_id, "swarm:running", {"swarm_id": swarm_id})

            swarm = await self.db.get_swarm(swarm_id)
            workers = await self.db.get_swarm_workers(swarm_id)
            id_to_worker = {w["id"]: w for w in workers}

            completed_titles: set[str] = set()
            max_rounds = 30

            for round_no in range(max_rounds):
                tasks = await self.db.get_swarm_tasks(swarm_id)
                pending = [t for t in tasks if t["status"] == "pending"]
                if not pending:
                    break

                # Find tasks whose dependencies are all met
                ready = [
                    t for t in pending
                    if all(
                        d in completed_titles
                        for d in json.loads(t.get("depends_on", "[]"))
                    )
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
                async def _run_one(task):
                    async with sem:
                        worker = id_to_worker.get(task.get("worker_id"))
                        if not worker and workers:
                            worker = workers[task["id"] % len(workers)]
                        if not worker:
                            await self.db.update_swarm_task(
                                task["id"], status="failed", result="No worker assigned"
                            )
                            return task["title"]
                        await self._execute_task(swarm, worker, task, workers)
                        return task["title"]

                results = await asyncio.gather(*[_run_one(t) for t in ready], return_exceptions=True)
                for r in results:
                    if isinstance(r, str):
                        completed_titles.add(r)

                # Check for cancellation / pause
                current = await self.db.get_swarm(swarm_id)
                if current and current["status"] == "paused":
                    await self._emit(swarm_id, "swarm:paused_mid_run", {"swarm_id": swarm_id})
                    return

            # Synthesis step: orchestrator summarizes all results
            await self._emit(swarm_id, "swarm:synthesizing", {"swarm_id": swarm_id})
            final_result = await self._synthesize(swarm, workers)

            swarm_dir = Path(swarm["workspace_path"])
            (swarm_dir / "result.md").write_text(final_result, encoding="utf-8")

            await self.db.update_swarm(swarm_id, status="completed")
            await self._emit_swarm_event(swarm_id, "completed", {"result_preview": final_result[:500]})
            await self._emit(swarm_id, "swarm:completed", {
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
            # Build context: shared context + received messages + task description
            messages_in = await self.db.get_swarm_messages(swarm_id, to_worker_id=worker_id)
            swarm_context = self._build_worker_context(swarm, worker, task, messages_in)

            # System prompt with swarm awareness
            system_prompt = self._build_worker_system_prompt(worker, swarm, all_workers)

            config = AssistantConfig(
                name=worker["name"],
                system_prompt=system_prompt,
                max_tool_iterations=15,
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

            channel_id = f"swarm_{swarm_id}_worker_{worker_id}"
            response = await brain.process_message(
                content=swarm_context,
                user_id=f"swarm_{swarm_id}",
                channel_id=channel_id,
                channel_type="swarm",
            )

            # Save result
            worker_dir = Path(worker["workspace_path"])
            worker_dir.mkdir(parents=True, exist_ok=True)
            (worker_dir / f"task_{task_id}_result.md").write_text(
                response or "", encoding="utf-8"
            )

            result_preview = (response or "")[:200]
            await self.db.update_swarm_task(task_id, status="completed", result=response or "")
            await self.db.update_swarm_worker(worker_id, status="idle")
            # Store task result as activity message so the feed shows it
            await self.db.add_swarm_message(
                swarm_id=swarm_id,
                from_worker_id=worker_id,
                to_worker_id=None,
                content=f"**[{task['title']}]**\n\n{response or '(no output)'}",
                message_type="task_result",
            )
            await self._emit_task_event(swarm_id, task_id, "completed", {
                "task_title": task["title"], "worker_name": worker["name"],
                "result_preview": result_preview,
            })
            await self._emit_worker_event(swarm_id, worker_id, "idle", {"worker_name": worker["name"]})
            await self._emit(swarm_id, "swarm:worker_done", {
                "worker_id": worker_id, "worker_name": worker["name"],
                "task_title": task["title"], "result_preview": result_preview,
            })
            return response or ""

        except Exception as e:
            log.error("Task execution failed", task_id=task_id, error=str(e))
            await self.db.update_swarm_task(task_id, status="failed", result=str(e))
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
                "task_title": task["title"], "error": str(e),
            })
            await self._emit_worker_event(swarm_id, worker_id, "idle", {"worker_name": worker["name"]})
            await self._emit(swarm_id, "swarm:worker_error", {
                "worker_id": worker_id, "worker_name": worker["name"],
                "task_title": task["title"], "error": str(e),
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

        class _SwarmRegistry:
            def __init__(self_inner):
                self_inner._base = self.tool_registry
                # Merge base ToolDefinitions + swarm ToolDefinitions (all proper objects)
                self_inner.tools = {**self.tool_registry.tools, **swarm_tool_defs}

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

    # ─── Prompt Builders ─────────────────────────────────────────────────────

    def _build_plan_prompt(self, swarm: dict) -> str:
        ctx = swarm.get("shared_context", "")
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
- Tasks in depends_on must reference titles of earlier tasks
- Workers WILL be able to communicate with each other during execution
- Each worker should have a clear, focused role
- System prompts must include the worker's specialty and communication style"""

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
            f"You have access to swarm communication tools:\n"
            f"- `swarm_send_message`: send a message to a specific teammate\n"
            f"- `swarm_broadcast`: send a message to all teammates\n"
            f"- `swarm_read_messages`: read messages sent to you\n"
            f"Use these tools to coordinate with your team."
        )

    def _build_worker_context(
        self,
        swarm: dict,
        worker: dict,
        task: dict,
        messages_in: list[dict],
    ) -> str:
        parts = [
            f"# Task: {task['title']}\n\n{task['description']}",
        ]

        if swarm.get("shared_context"):
            parts.append(
                f"\n## Shared Project Context\n\n{swarm['shared_context']}"
            )

        if messages_in:
            msgs_formatted = "\n".join(
                f"- From {m.get('from_worker_name', 'unknown')}: {m['content']}"
                for m in messages_in
            )
            parts.append(f"\n## Messages from teammates\n\n{msgs_formatted}")

        return "\n\n".join(parts)

    # ─── Plan Parser ─────────────────────────────────────────────────────────

    def _parse_plan(self, text: str) -> dict:
        """Extract JSON plan from LLM response."""
        # Strip markdown fences if present
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.split("\n")
            # Remove first and last fence lines
            inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            stripped = "\n".join(inner)

        try:
            return json.loads(stripped)
        except Exception:
            # Try to find JSON block
            import re
            match = re.search(r"\{[\s\S]*\}", stripped)
            if match:
                try:
                    return json.loads(match.group())
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
