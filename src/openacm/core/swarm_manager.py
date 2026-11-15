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
from openacm.core.swarm_parsing import SwarmParsingMixin
from openacm.core.swarm_prompts import SwarmPromptsMixin
from openacm.utils.text import truncate

log = structlog.get_logger()

# Event names for real-time updates
EVENT_SWARM_UPDATED = "swarm:updated"
EVENT_SWARM_WORKER_STATUS = "swarm:worker_status"
EVENT_SWARM_MESSAGE = "swarm:message"
EVENT_SWARM_TASK_UPDATED = "swarm:task_updated"


class SwarmManager(SwarmParsingMixin, SwarmPromptsMixin):
    """Manages swarm lifecycle: planning, execution, and worker coordination."""

    def __init__(self, database, llm_router, tool_registry, memory, event_bus, skill_manager=None):
        self.db = database
        self.llm_router = llm_router
        self.tool_registry = tool_registry
        self.skill_manager = skill_manager
        self.memory = memory
        self.event_bus = event_bus
        # Running swarm tasks keyed by swarm_id
        self._running: dict[int, asyncio.Task] = {}
        # Retry counters: swarm_id → {task_id → retries_used}
        # Persists across auto-restarts so a task can't retry infinitely across runs.
        self._task_retries: dict[int, dict[int, int]] = {}
        self._llm_semaphores: dict[int, asyncio.Semaphore] = {}  # kept for legacy cleanup only
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
        working_path: str = "",
    ) -> dict[str, Any]:
        """
        Create a new draft swarm.

        file_contents: list of {"filename": ..., "content": ...} dicts already read.
        """
        swarm_id = await self.db.create_swarm(name, goal, global_model)
        swarm_dir = self._swarm_dir(swarm_id, name)
        swarm_dir.mkdir(parents=True, exist_ok=True)
        (swarm_dir / "workers").mkdir(exist_ok=True)
        (swarm_dir / "context").mkdir(exist_ok=True)

        shared_context = ""
        context_files: list[str] = []

        _TEXT_EXTENSIONS = {
            ".txt", ".md", ".rst", ".csv", ".json", ".yaml", ".yml",
            ".toml", ".ini", ".cfg", ".xml", ".html", ".htm",
            ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp",
            ".h", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".bat",
            ".sql", ".r", ".kt", ".swift",
        }
        if file_contents:
            manifest_lines: list[str] = []
            for f in file_contents:
                fname = f.get("filename", "file")
                raw: bytes = f.get("raw") or f.get("content", "").encode()
                fpath = swarm_dir / "context" / fname
                ext = Path(fname).suffix.lower()
                is_text = ext in _TEXT_EXTENSIONS

                if is_text:
                    text = raw.decode("utf-8", errors="replace")
                    fpath.write_text(text, encoding="utf-8")
                    size_label = f"{len(text):,} chars"
                else:
                    fpath.write_bytes(raw)
                    size_label = f"{len(raw):,} bytes"

                context_files.append(fname)
                manifest_lines.append(f"- {fpath} ({size_label})")

            shared_context = "Uploaded files:\n" + "\n".join(manifest_lines)

        await self.db.update_swarm(
            swarm_id,
            workspace_path=str(swarm_dir),
            shared_context=shared_context,
            context_files=json.dumps(context_files),
            working_path=working_path,
        )

        swarm = await self.db.get_swarm(swarm_id)
        await self._emit_swarm_event(swarm_id, "created")
        return swarm

    async def check_reuse_compatibility(
        self,
        swarm_id: int,
        new_goal: str,
    ) -> dict:
        """
        Ask the LLM whether the existing worker team is suitable for a new goal.
        Returns {"compatible": bool, "reason": str, "suggestion": str}.
        """
        swarm = await self.db.get_swarm(swarm_id)
        if not swarm:
            raise ValueError(f"Swarm {swarm_id} not found")

        workers = await self.db.get_swarm_workers(swarm_id)
        if not workers:
            return {"compatible": True, "reason": "No workers yet — any goal is fine.", "suggestion": ""}

        worker_summary = "\n".join(
            f"- {w['name']} ({w['role']}): {w['description']}"
            for w in workers
        )

        prompt = (
            f"An existing AI agent swarm was designed for this original goal:\n"
            f"{swarm['goal']}\n\n"
            f"Its worker team:\n{worker_summary}\n\n"
            f"The user wants to reuse this exact team (same workers, same system prompts) "
            f"for a new goal:\n{new_goal}\n\n"
            "Assess whether the existing team is well-suited for the new goal.\n\n"
            "Consider INCOMPATIBLE if the new goal requires fundamentally different skills "
            "(e.g., the team was built for coding but now the goal is graphic design), "
            "references very different domains, or would produce clearly worse results "
            "than a purpose-built team. Minor goal variations are fine — only flag truly "
            "mismatched cases.\n\n"
            "Respond with ONLY a JSON object, no prose:\n"
            '{"compatible": true/false, "reason": "one sentence", '
            '"suggestion": "what the user should do instead if incompatible, empty string if compatible"}'
        )

        try:
            result = await self.llm_router.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=256,
                model_override=swarm.get("global_model") or None,
            )
            content = (result.get("content") or "").strip()
            import re as _re
            match = _re.search(r"\{.*\}", content, _re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                return {
                    "compatible": bool(parsed.get("compatible", True)),
                    "reason": str(parsed.get("reason", "")),
                    "suggestion": str(parsed.get("suggestion", "")),
                }
        except Exception as exc:
            log.warning("Reuse compatibility check failed — assuming compatible",
                        swarm_id=swarm_id, error=str(exc))

        return {"compatible": True, "reason": "", "suggestion": ""}

    async def reset_swarm(
        self,
        swarm_id: int,
        goal: str | None = None,
        file_contents: list[dict[str, str]] | None = None,
        working_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Reset a swarm for re-use without re-planning.

        Keeps all workers and task definitions intact — only resets task results
        back to pending so the same team runs again with new context/files.
        """
        swarm = await self.db.get_swarm(swarm_id)
        if not swarm:
            raise ValueError(f"Swarm {swarm_id} not found")

        if swarm["status"] == "running":
            await self.stop_swarm(swarm_id)

        # Reset tasks to pending + workers to idle + clear activity feed
        await self.db.reset_swarm_tasks(swarm_id)
        await self.db.clear_swarm_messages(swarm_id)

        updates: dict = {"status": "planned"}
        if goal is not None:
            updates["goal"] = goal
        if working_path is not None:
            updates["working_path"] = working_path

        # Replace context files if new ones were uploaded
        if file_contents is not None:
            swarm_dir = Path(swarm["workspace_path"])
            context_dir = swarm_dir / "context"
            import shutil as _shutil
            if context_dir.exists():
                _shutil.rmtree(context_dir)
            context_dir.mkdir(parents=True, exist_ok=True)

            parts: list[str] = []
            ctx_files: list[str] = []
            for f in file_contents:
                fname = f.get("filename", "file")
                content = f.get("content", "")
                (context_dir / fname).write_text(content, encoding="utf-8", errors="replace")
                ctx_files.append(fname)
                parts.append(f"### {fname}\n{content}")
            updates["shared_context"] = "\n\n".join(parts)
            updates["context_files"] = json.dumps(ctx_files)

        await self.db.update_swarm(swarm_id, **updates)
        await self._emit_swarm_event(swarm_id, "planned")
        return await self.db.get_swarm(swarm_id)

    async def clarify_swarm(self, swarm_id: int) -> list[str]:
        """
        Review the swarm's goal + context and generate clarifying questions.
        Sets status to 'clarifying', stores questions in DB, returns question list.
        Call this right after create_swarm, before plan_swarm.
        """
        swarm = await self.db.get_swarm(swarm_id)
        if not swarm:
            raise ValueError(f"Swarm {swarm_id} not found")

        await self.db.update_swarm(swarm_id, status="clarifying")
        await self._emit_swarm_event(swarm_id, "clarifying")

        ctx = (swarm.get("shared_context") or "").strip()
        if len(ctx) > self._MAX_CONTEXT_CHARS:
            ctx = ctx[: self._MAX_CONTEXT_CHARS] + "\n[...truncated...]"
        ctx_section = f"\n\nPROVIDED CONTEXT AND DOCUMENTS:\n{ctx}" if ctx else "\n\nNo context files were provided."

        prompt = (
            f"You are about to coordinate a team of AI agents to accomplish the following goal.\n\n"
            f"GOAL:\n{swarm['goal']}"
            f"{ctx_section}\n\n"
            "---\n\n"
            "Before designing the team and task plan, you MUST identify every gap and ambiguity "
            "that would force a worker to guess or make an assumption. Your job is to surface those "
            "gaps NOW, before any work starts, so the plan is precise.\n\n"
            "You MUST ask about ALL of the following that apply:\n"
            "- Tech stack: language version, framework, libraries, package manager (never assume)\n"
            "- Project structure: where files should live, naming conventions, existing patterns to follow\n"
            "- Scope boundaries: what is IN scope vs explicitly OUT of scope\n"
            "- Integration: does this connect to existing code? If so, what are the interfaces?\n"
            "- Output / deliverable: exact format, what files, where they go, how they are run\n"
            "- Quality bar: error handling depth, test coverage, type annotations, linting rules\n"
            "- Ambiguities: any requirement where two different developers might make different decisions\n"
            "- Missing information: anything not provided that a worker would need to look up or invent\n\n"
            "Rules:\n"
            "- When in doubt, ASK — it is always better to ask than to have workers guess wrong\n"
            "- Do NOT skip a question just because an answer seems 'obvious' — obvious things are often wrong\n"
            "- Aim for 5–10 questions; fewer only if the goal is extremely simple and well-specified\n"
            "- Each question must be specific and actionable, not vague\n\n"
            "Respond with ONLY a JSON array of question strings — no prose, no markdown wrapper:\n"
            '["Question 1?", "Question 2?", ...]'
        )

        questions: list[str] = []
        try:
            result = await self.llm_router.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=1024,
                model_override=swarm.get("global_model") or None,
            )
            content = (result.get("content") or "").strip()
            import re as _re
            match = _re.search(r"\[.*?\]", content, _re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, list):
                    questions = [str(q).strip() for q in parsed if str(q).strip()]
        except Exception as exc:
            log.warning("Clarification LLM call failed — proceeding without questions",
                        swarm_id=swarm_id, error=str(exc))

        await self.db.update_swarm(swarm_id, clarification_questions=json.dumps(questions))
        await self._emit(swarm_id, "swarm:clarifying", {
            "swarm_id": swarm_id,
            "question_count": len(questions),
        })
        return questions

    async def plan_swarm(self, swarm_id: int) -> dict[str, Any]:
        """
        Use the LLM to design the worker team and initial task plan for this swarm.
        Returns the updated swarm with workers created.
        """
        swarm = await self.db.get_swarm(swarm_id)
        if not swarm:
            raise ValueError(f"Swarm {swarm_id} not found")

        # Clear any existing workers/tasks from a previous plan before re-planning
        await self.db.clear_swarm_plan(swarm_id)
        await self.db.update_swarm(swarm_id, status="planning")
        await self._emit_swarm_event(swarm_id, "planning")

        plan_prompt = self._build_plan_prompt(swarm)

        try:
            # Stream the plan. If the JSON is truncated at the token limit, ask the model
            # to continue exactly from where it stopped and append the continuation.
            def _plan_is_valid(p: dict) -> bool:
                """A plan needs at least 2 workers (orchestrator + 1 specialist) and 1 task."""
                return len(p.get("workers", [])) >= 2 and len(p.get("tasks", [])) >= 1

            messages: list[dict] = [{"role": "user", "content": plan_prompt}]
            plan_text = ""
            plan: dict | None = None
            MAX_CONTINUATIONS = 3

            for attempt in range(MAX_CONTINUATIONS + 1):
                chunk_text = ""
                async for _chunk in self.llm_router.chat_stream(
                    messages=messages,
                    temperature=0.4,
                    max_tokens=4096,
                    model_override=swarm.get("global_model") or None,
                ):
                    chunk_text += _chunk
                    await self.event_bus.emit("swarm:planning_thought", {
                        "swarm_id": swarm_id,
                        "chunk": _chunk,
                        "accumulated": plan_text + chunk_text,
                    })
                plan_text += chunk_text

                # Try to parse and validate
                try:
                    candidate = self._parse_plan(plan_text)
                    if _plan_is_valid(candidate):
                        plan = candidate
                        break
                    # Parsed fine but incomplete (e.g. only orchestrator, no tasks) —
                    # ask the model to complete the plan
                    if attempt < MAX_CONTINUATIONS:
                        log.debug("Plan incomplete, requesting completion",
                                  swarm_id=swarm_id, attempt=attempt + 1,
                                  workers=len(candidate.get("workers", [])),
                                  tasks=len(candidate.get("tasks", [])))
                        messages = [
                            {"role": "user", "content": plan_prompt},
                            {"role": "assistant", "content": plan_text},
                            {"role": "user", "content": (
                                "Your plan is incomplete. You defined workers but are missing "
                                "the full team and/or all tasks. Continue the JSON exactly from "
                                "where you stopped — do not repeat what you already wrote."
                            )},
                        ]
                        continue
                except ValueError:
                    pass

                # JSON truncated — ask for continuation
                if attempt < MAX_CONTINUATIONS and self._json_is_truncated(plan_text):
                    log.debug("Plan JSON truncated, requesting continuation",
                              swarm_id=swarm_id, attempt=attempt + 1)
                    messages = [
                        {"role": "user", "content": plan_prompt},
                        {"role": "assistant", "content": plan_text},
                        {"role": "user", "content": "Continue exactly from where you stopped. Do not repeat anything already written."},
                    ]
                else:
                    break

            if plan is None:
                log.warning("Plan could not be parsed after continuations, using minimal fallback",
                            swarm_id=swarm_id, preview=plan_text[:300])
                plan = {
                    "workers": [{"name": "General Worker", "role": "worker",
                                 "description": "General purpose worker",
                                 "system_prompt": "You are a helpful AI assistant. Complete the given task.",
                                 "model": None, "allowed_tools": "all"}],
                    "tasks": [{"title": "Main Task",
                               "description": swarm.get("goal", "Complete the project goal."),
                               "worker": "General Worker", "depends_on": []}],
                }

            log.info("Swarm plan built", swarm_id=swarm_id,
                     workers=len(plan.get("workers", [])), tasks=len(plan.get("tasks", [])))

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
            import re as _re
            wname = _re.sub(r'[^a-z0-9_-]', '_', w.get("name", "worker").lower())
            wname = _re.sub(r'_+', '_', wname).strip('_') or "worker"
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
                task_type=t.get("task_type", "standard"),
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
                f"Project goal: {swarm['goal']}\n"
                f"Swarm workspace: {str(Path(swarm['workspace_path']))}\n\n"
                f"Work completed so far:\n{results_summary}\n\n"
                f"Currently pending tasks: {pending_summary}\n\n"
                f"**The user says:**\n\n{user_message}\n\n"
                f"---\n"
                f"Read the user's message and respond appropriately. You know this project inside out.\n"
                f"- If the user is asking about the project, answer them directly and concisely.\n"
                f"- If the user wants changes or new work, use `swarm_create_task` to delegate to the right worker.\n"
                f"- Use `list_directory` or `read_file` only if you need a specific detail you don't already have.\n\n"
                f"Available tools: `read_file`, `list_directory`, `swarm_create_task`, `swarm_broadcast`, `swarm_send_message`, `swarm_ask_user`.\n"
                f"You do NOT have run_command or write_file — delegate execution to workers."
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
            brain._swarm_id = swarm_id
            brain._swarm_worker_name = orchestrator.get("name", "orchestrator")
            if model_override:
                _orig = brain.llm_router.chat
                async def _patched(*a, **kw):
                    kw.setdefault("model_override", model_override)
                    return await _orig(*a, **kw)
                brain.llm_router.chat = _patched

            import time as _time_mod
            _swarm_slug = self._safe_slug(swarm.get("name", str(swarm_id)))
            _orch_slug = self._safe_slug(orchestrator.get("name", "orchestrator"))
            _react_channel = f"{_swarm_slug}__{_orch_slug}__react_{int(_time_mod.time())}"
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
        # Whatever was in flight died with the cancel: put it back so a restart picks it up
        # instead of leaving tasks "running" and workers "busy" forever.
        for t in await self.db.get_swarm_tasks(swarm_id):
            if t["status"] == "running":
                await self.db.update_swarm_task(t["id"], status="pending", result="[Stopped — will resume]")
        for w in await self.db.get_swarm_workers(swarm_id):
            if w["status"] == "busy":
                await self.db.update_swarm_worker(w["id"], status="idle")
        await self.db.update_swarm(swarm_id, status="paused")
        await self._emit_swarm_event(swarm_id, "paused")

    # ─── Execution Engine ─────────────────────────────────────────────────────

    async def _swarm_watchdog(self, swarm_id: int, stop_event: asyncio.Event) -> None:
        """
        Runs in parallel with _run_swarm. Emits a heartbeat every 60 s so the UI
        knows the swarm is alive even when workers are mid-LLM-call and silent.
        """
        while True:
            try:
                await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=60.0)
                break  # stop_event fired — swarm finished or was cancelled
            except asyncio.TimeoutError:
                pass
            if stop_event.is_set():
                break
            try:
                tasks = await self.db.get_swarm_tasks(swarm_id)
                by_status: dict[str, int] = {}
                for t in tasks:
                    by_status[t["status"]] = by_status.get(t["status"], 0) + 1
                await self._emit(swarm_id, "swarm:heartbeat", {
                    "swarm_id": swarm_id,
                    "task_counts": by_status,
                    "running_tasks": [t["title"] for t in tasks if t["status"] == "running"],
                })
            except Exception as e:
                log.debug("Watchdog heartbeat failed", swarm_id=swarm_id, error=str(e))

    async def _run_swarm(self, swarm_id: int) -> None:
        """
        Main execution loop.

        Tasks with no pending dependencies are executed IN PARALLEL (up to
        MAX_PARALLEL workers at a time to avoid SQLite lock contention).
        Each worker runs in its own isolated workspace / memory namespace.
        Events are emitted for every state change so the UI can react in real time.
        """
        sem = asyncio.Semaphore(SWARM_MAX_PARALLEL_WORKERS)
        _watchdog_stop = asyncio.Event()
        _watchdog_task = asyncio.ensure_future(self._swarm_watchdog(swarm_id, _watchdog_stop))

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
            # Dynamic cap: at least 60 rounds, or 3× the task count so deep
            # dependency chains never exhaust the loop before finishing.
            max_rounds = max(60, len(all_tasks_now) * 3)
            MAX_TASK_RETRIES = SWARM_MAX_TASK_RETRIES
            # Use persistent retry counts so retries survive auto-restarts
            if swarm_id not in self._task_retries:
                self._task_retries[swarm_id] = {}
            retry_counts = self._task_retries[swarm_id]
            # Stall detector: abort early if two consecutive rounds produce zero progress
            _consecutive_stall = 0

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
                            # Prefer role-based match over arbitrary modulo assignment
                            task_text = (
                                (task.get("title") or "") + " " + (task.get("description") or "")
                            ).lower()
                            for w in _ws:
                                role = (w.get("role") or "").lower()
                                if role and role != "orchestrator" and role in task_text:
                                    worker = w
                                    break
                            if not worker:
                                non_orch = [w for w in _ws if (w.get("role") or "") != "orchestrator"]
                                worker = non_orch[0] if non_orch else _ws[0]
                        if not worker:
                            await self.db.update_swarm_task(
                                task["id"], status="failed", result="No worker assigned"
                            )
                            return None
                        if task.get("task_type") == "debate":
                            result_status = await self._execute_debate_task(_sw, task, _aw)
                        else:
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
                                # `task` was read before this attempt ran: take what the attempt wrote
                                _latest = await self.db.get_swarm_task(task["id"])
                                prev_result = (_latest or {}).get("result") or ""
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
                newly_completed = 0
                for r in results:
                    if isinstance(r, str):
                        completed_titles.add(r)
                        newly_completed += 1

                # Stall detection: two consecutive rounds with zero progress → abort
                if newly_completed == 0:
                    _consecutive_stall += 1
                    if _consecutive_stall >= 2:
                        log.warning(
                            "Swarm stalled — no progress in 2 consecutive rounds, aborting loop",
                            swarm_id=swarm_id, round=round_no,
                        )
                        await self._emit(swarm_id, "swarm:stalled", {
                            "swarm_id": swarm_id, "round": round_no, "reason": "no_progress",
                        })
                        break
                else:
                    _consecutive_stall = 0

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
        finally:
            _watchdog_stop.set()
            _watchdog_task.cancel()

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
                _noise_prefixes = ("[Retry ", "[Rate ", "[Network ", "[Skipped", "[Reset:")
                if prev_result and not any(prev_result.startswith(p) for p in _noise_prefixes):
                    task_status_prev, fail_reason_prev = self._parse_task_status(prev_result)
                    retry_history.append({"result": prev_result, "fail_reason": fail_reason_prev or "Task did not complete"})
                # Also grab accumulated history stored in task metadata key
                import json as _rjson
                stored = task.get("retry_history_json") or "[]"
                extra = _rjson.loads(stored) if stored != "[]" else []
                retry_history = extra + retry_history
            except Exception as e:
                log.warning("Could not read a task's retry history; the worker retries without it", error=str(e))

            # Build context: shared contract + dependency outputs + messages + task description
            messages_in = await self.db.get_swarm_messages(swarm_id, to_worker_id=worker_id)
            messages_in = messages_in[-20:]  # cap to last 20 to avoid context overflow
            team_updates = await self.db.get_swarm_team_updates(swarm_id, limit=20)
            swarm_context = self._build_worker_context(
                swarm, worker, task, messages_in, dep_outputs,
                retry_history=retry_history or None,
                team_updates=team_updates or None,
            )

            # System prompt with swarm awareness
            skills_prompt = ""
            if self.skill_manager:
                skills_prompt = await self.skill_manager.get_active_skills_prompt_for_worker(worker["id"])
            system_prompt = self._build_worker_system_prompt(worker, swarm, all_workers, skills_prompt)

            config = AssistantConfig(
                name=worker["name"],
                system_prompt=system_prompt,
                max_tool_iterations=25,
                onboarding_completed=True,
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
            brain._swarm_id = swarm_id
            brain._swarm_worker_name = worker.get("name", "")

            # If a model override is set, patch the router call
            if model_override:
                _orig_chat = brain.llm_router.chat

                async def _patched_chat(*args, **kwargs):
                    kwargs.setdefault("model_override", model_override)
                    return await _orig_chat(*args, **kwargs)

                brain.llm_router.chat = _patched_chat

            # One stable channel per worker across all its tasks.
            # No task_id in channel_id so the worker keeps its full history.
            swarm_slug = self._safe_slug(swarm.get("name", str(swarm_id)))
            worker_slug = self._safe_slug(worker.get("name", str(worker_id)))
            user_id_str = f"swarm_{swarm_id}"
            channel_id = f"{swarm_slug}__{worker_slug}"

            # Pin workspace for this task channel: use swarm's working_path if set,
            # otherwise use the swarm's own workspace directory (NOT the global workspace).
            swarm_record = await self.db.get_swarm(swarm_id)
            task_working_path = (swarm_record or {}).get("working_path", "").strip()
            if not task_working_path:
                task_working_path = str(Path(swarm["workspace_path"]))
            brain.memory.set_conversation_workspace(
                user_id_str, channel_id, task_working_path
            )

            # 10-minute hard timeout per task — prevents infinite hangs.
            # Parallelism is controlled by the outer semaphore in _run_swarm;
            # a nested LLM semaphore here caused deadlocks (3 workers holding outer
            # slots while all waiting on a max-2 inner sem).
            try:
                response = await asyncio.wait_for(
                    brain.process_message(
                        content=swarm_context,
                        user_id=user_id_str,
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

            # If brain swallowed a RateLimitError and returned it as text, requeue instead of failing
            resp_text = response or ""
            if "RateLimitError" in resp_text or ("rate limit" in resp_text.lower() and "429" in resp_text):
                import re as _re
                wait_match = _re.search(r"try again in (\d+(?:\.\d+)?)s", resp_text, _re.IGNORECASE)
                wait_secs = float(wait_match.group(1)) + 1.0 if wait_match else 15.0
                log.warning("Task response contains RateLimitError — requeueing",
                            task_id=task_id, task_title=task["title"], wait_secs=wait_secs)
                await self.db.update_swarm_task(task_id, status="pending",
                                                result=f"[Rate limited — requeued after {wait_secs:.0f}s]")
                await self.db.update_swarm_worker(worker_id, status="idle")
                await self._emit_task_event(swarm_id, task_id, "pending", {
                    "task_title": task["title"], "reason": "rate_limited",
                })
                await asyncio.sleep(wait_secs)
                return "rate_limited"

            # Determine actual task status from the worker's explicit marker
            task_status, fail_reason = self._parse_task_status(resp_text)

            result_preview = resp_text[:200]
            await self.db.update_swarm_task(task_id, status=task_status, result=resp_text)
            await self.db.update_swarm_worker(worker_id, status="idle")

            # Store task result as activity message so the feed shows it
            if task_status == "completed":
                msg_type = "task_result"
                msg_content = f"**[{task['title']}]**\n\n{resp_text or '(no output)'}"
            elif task_status == "waiting":
                msg_type = "task_waiting"
                msg_content = f"**[{task['title']}]** waiting for user input."
            else:
                msg_type = "task_failed"
                msg_content = f"**[{task['title']}] FAILED:** {fail_reason}\n\n{resp_text}"

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
            return "failed"  # so the retry / cascade logic in _run_swarm actually runs

    async def _execute_debate_task(
        self,
        swarm: dict,
        task: dict,
        all_workers: list[dict],
    ) -> str:
        """
        Run a debate task: two workers tackle the same problem from opposing perspectives,
        then an LLM judge synthesizes the best solution from both.
        Returns the canonical task status string ("completed" / "failed").
        """
        from openacm.core.config import AssistantConfig
        from openacm.core.brain import Brain

        swarm_id = swarm["id"]
        task_id = task["id"]

        await self.db.update_swarm_task(task_id, status="running")
        await self._emit_task_event(swarm_id, task_id, "running", {
            "task_title": task["title"], "mode": "debate",
        })

        debaters = [w for w in all_workers if (w.get("role") or "") != "orchestrator"][:2]
        if len(debaters) < 2:
            debaters = (debaters * 2)[:2]
        if not debaters:
            debaters = all_workers[:2]

        perspectives = [
            "Prioritize reliability, simplicity, and correctness. Prefer proven patterns.",
            "Prioritize performance, elegance, and innovation. Prefer modern approaches.",
        ]

        async def _run_debater(worker: dict, perspective: str) -> str:
            dep_outputs: list[tuple[str, str]] = []
            try:
                dep_titles = json.loads(task.get("depends_on") or "[]")
                if dep_titles:
                    all_tasks = await self.db.get_swarm_tasks(swarm_id)
                    done_map = {t["title"]: t for t in all_tasks if t["status"] == "completed"}
                    for dt in dep_titles:
                        if dt in done_map and done_map[dt].get("result"):
                            dep_outputs.append((dt, done_map[dt]["result"]))
            except Exception as e:
                log.warning("Could not load the outputs of the tasks this one depends on; the worker runs without them", error=str(e))

            messages_in = (await self.db.get_swarm_messages(swarm_id, to_worker_id=worker["id"]))[-10:]
            context = self._build_worker_context(swarm, worker, task, messages_in, dep_outputs or None)
            context += f"\n\n**Debate perspective — adopt this lens for your solution:** {perspective}"

            worker_skills_prompt = ""
            if self.skill_manager:
                worker_skills_prompt = await self.skill_manager.get_active_skills_prompt_for_worker(worker["id"])

            config = AssistantConfig(
                name=worker["name"],
                system_prompt=self._build_worker_system_prompt(worker, swarm, all_workers, worker_skills_prompt),
                max_tool_iterations=20,
                onboarding_completed=True,
            )
            brain = Brain(
                config=config,
                llm_router=self.llm_router,
                memory=self.memory,
                event_bus=self.event_bus,
                tool_registry=self._build_worker_tool_registry(swarm_id, worker["id"], all_workers, worker),
            )
            brain._swarm_id = swarm_id
            brain._swarm_worker_name = worker.get("name", "")
            _sw_slug = self._safe_slug(swarm.get("name", str(swarm_id)))
            _w_slug = self._safe_slug(worker.get("name", str(worker["id"])))
            channel_id = f"{_sw_slug}__{_w_slug}"
            _uid = f"swarm_{swarm_id}"
            brain.memory.set_conversation_workspace(
                _uid, channel_id,
                (swarm.get("working_path") or "").strip() or str(Path(swarm["workspace_path"]))
            )
            try:
                return await asyncio.wait_for(
                    brain.process_message(content=context, user_id=_uid,
                                          channel_id=channel_id, channel_type="swarm"),
                    timeout=300.0,
                ) or ""
            except Exception as e:
                return f"Debater error: {e}"

        responses = await asyncio.gather(
            _run_debater(debaters[0], perspectives[0]),
            _run_debater(debaters[1], perspectives[1]),
        )

        judge_prompt = (
            f"Two agents approached the same task from different angles. "
            f"Synthesize the definitively best solution.\n\n"
            f"**Task:** {task['title']}\n{task['description']}\n\n"
            f"**Approach A (reliability-focused):**\n{responses[0][:3000]}\n\n"
            f"**Approach B (innovation-focused):**\n{responses[1][:3000]}\n\n"
            f"Write the final solution, taking the strongest elements from both. "
            f"Produce real, runnable output — not a summary of the debate. "
            f"End with exactly: TASK_STATUS: COMPLETED"
        )

        try:
            synthesis_resp = await self.llm_router.chat(
                messages=[{"role": "user", "content": judge_prompt}],
                temperature=0.2,
                max_tokens=4096,
                model_override=swarm.get("global_model") or None,
            )
            result = synthesis_resp.get("content") or "".join(responses)
        except Exception:
            result = responses[0] + "\n\nTASK_STATUS: COMPLETED"

        await self.db.update_swarm_task(task_id, status="completed", result=result)
        await self._emit_task_event(swarm_id, task_id, "completed", {
            "task_title": task["title"], "mode": "debate",
        })
        return "completed"

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
            swarm_manager=self,
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
                        # An unreadable allow-list must not become "every tool"
                        log.warning("Worker allowed_tools is not valid JSON — no outside tools", value=str(allowed)[:80])
                        base_tools = []

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
            swarm_manager=self,
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
    # Planning only needs enough context to understand the project — workers get the full context
    _MAX_PLAN_CONTEXT_CHARS = 30_000


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


    # ─── Plan Parser ─────────────────────────────────────────────────────────


    # ─── Helpers ─────────────────────────────────────────────────────────────


    def _swarm_dir(self, swarm_id: int, name: str = "") -> Path:
        workspace = Path(os.environ.get("OPENACM_WORKSPACE", "workspace"))
        folder = f"{self._safe_slug(name)}_{swarm_id}" if name else str(swarm_id)
        return workspace / "swarms" / folder

    async def _emit(self, swarm_id: int, event_type: str, payload: dict):
        """Emit any swarm-related event.  All events carry swarm_id for filtering."""
        payload.setdefault("swarm_id", swarm_id)
        payload["_ts"] = datetime.now(timezone.utc).isoformat()
        try:
            await self.event_bus.emit(event_type, payload)
        except Exception as e:
            log.warning("A swarm event could not be delivered to its listeners", error=str(e))

    # Convenience wrappers kept for readability
    async def _emit_swarm_event(self, swarm_id: int, status: str, extra: dict | None = None):
        await self._emit(swarm_id, EVENT_SWARM_UPDATED, {"status": status, **(extra or {})})

    async def _emit_worker_event(self, swarm_id: int, worker_id: int, status: str, extra: dict | None = None):
        await self._emit(swarm_id, EVENT_SWARM_WORKER_STATUS, {"worker_id": worker_id, "status": status, **(extra or {})})

    async def _emit_task_event(self, swarm_id: int, task_id: int, status: str, extra: dict | None = None):
        await self._emit(swarm_id, EVENT_SWARM_TASK_UPDATED, {"task_id": task_id, "status": status, **(extra or {})})
