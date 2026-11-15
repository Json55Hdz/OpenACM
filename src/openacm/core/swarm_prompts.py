"""The prompts a swarm sends: planning, worker system prompts and per-task context."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from openacm.constants import TRUNCATE_SWARM_TASK_OUTPUT_CHARS
from openacm.utils.text import truncate

log = structlog.get_logger()


class SwarmPromptsMixin:
    """Methods of SwarmManager, kept in their own module to keep swarm_manager.py readable."""

    def _build_plan_prompt(self, swarm: dict) -> str:
        ctx = swarm.get("shared_context", "") or ""
        if len(ctx) > self._MAX_PLAN_CONTEXT_CHARS:
            ctx = ctx[: self._MAX_PLAN_CONTEXT_CHARS] + "\n\n[...context truncated for planning — workers receive full context...]"
        ctx_section = f"\n\n**Provided context files:**\n{ctx}" if ctx else ""

        answers = (swarm.get("clarification_answers") or "").strip()
        answers_section = (
            f"\n\n**Clarification Q&A — use these answers to make the plan precise:**\n{answers}"
            if answers else ""
        )

        return f"""You are a project planning AI. Design an optimal team of AI worker agents
to accomplish the following goal.{ctx_section}{answers_section}

**Goal:** {swarm["goal"]}

Return ONLY valid JSON with this exact structure:
{{
  "workers": [
    {{
      "name": "Worker Name",
      "role": "orchestrator|worker",
      "description": "One-line description of this worker's specialty",
      "system_prompt": "You are a [specialty] worker. Your owned files are: [exact list of file paths]. You MUST NOT create or edit any file outside this list. [Detailed instructions...]",
      "model": null,
      "allowed_tools": "all"
    }}
  ],
  "tasks": [
    {{
      "title": "Short unambiguous title",
      "description": "File: src/models/user.py | Action: CREATE User SQLAlchemy model (id, name, email) | Imports: none | Exports: User class used by routes/users.py | Details: use declarative base from db/base.py",
      "worker": "Worker Name",
      "depends_on": [],
      "task_type": "standard"
    }}
  ]
}}

Rules:

**Team composition**
- Include exactly ONE worker with role "orchestrator" (project lead)
- Include 2–5 specialist workers depending on complexity
- The model field can be null (use global) or a LiteLLM model string like "anthropic/claude-opus-4-6"
- Each worker owns a non-overlapping set of files — NO two workers ever write the same file
- Workers WILL be able to communicate with each other during execution

**Worker system prompts — REQUIRED content**
Every system_prompt MUST include:
  1. The worker's specialty in one sentence
  2. EXACT list of file paths they own, e.g.: "Your owned files: src/routes/users.py, src/routes/tasks.py"
  3. The rule: "You MUST NOT create or edit any file outside your ownership list. If you need something from another worker's file, read it — never rewrite it."

**Task granularity — CRITICAL**
Each task must be ATOMIC: one file, one concern. Split anything that touches more than one file. Aim for 10–20 tasks on non-trivial goals.

BAD (too broad):
  ✗ "Implement CRUD and router"        ← contains "and" between two actions
  ✗ "Set up database models and migrations"
  ✗ "Build the authentication system"

GOOD (atomic — one file, one action):
  ✓ "Create User model in src/models/user.py"
  ✓ "Add POST /api/users endpoint in src/routes/users.py"
  ✓ "Add GET /api/users/:id endpoint in src/routes/users.py"
  ✓ "Add PUT /api/users/:id endpoint in src/routes/users.py"
  ✓ "Add DELETE /api/users/:id endpoint in src/routes/users.py"
  ✓ "Create users table migration in migrations/001_users.sql"

Test: if the description contains "and" between two distinct actions → split into two tasks.

**Task descriptions — REQUIRED format**
Every description MUST be a single line using pipe-separated fields:
  "File: <exact path> | Action: CREATE|EDIT|ADD <one-line summary> | Imports: <from other workers, or none> | Exports: <what others import from this, or none> | Details: <exact content to add/change>"
Keep it on one line — no literal newlines inside the JSON string.

**Task descriptions MUST be self-contained. A worker MUST be able to execute the task by reading ONLY the target file (or zero files for CREATE tasks):**
- EDIT tasks: include the exact text/code to replace AND the exact replacement. Quote it verbatim from the context.
- ADD tasks: include the exact content to insert and the precise location (after line X, inside function Y, at the end of the array, etc.).
- CREATE tasks: include the complete structure, format, all field names, and sample values. The worker should be able to write the file without reading anything else.
- Bug-fix tasks: state the exact wrong value and the exact correct value. Never say "fix the mismatch" — say "change X to Y".
- If the context contains the relevant snippet, COPY it into the task description verbatim.

BAD Details (worker still has to investigate):
  ✗ "Fix the narrative mismatch"
  ✗ "Add the missing steps"
  ✗ "Follow the existing pattern"
  ✗ "Update to match the schema"

GOOD Details (worker knows exactly what to write):
  ✓ "File has NARRATIVES for step-1..step-4. Add exactly 3 new entries after step-4 following this format: {{"step-5":{{"title":"...","text":"..."}},"step-6":{{...}},"step-7":{{...}}}}. Copy the structure from existing step-4 entry."
  ✓ "Replace line: const MAX = 10 with: const MAX = 50 in the config block at the top of the file."
  ✓ "Create file with these exact fields: {{id, name, email, created_at}}. Use declarative_base from db/base.py (already written by DB Worker)."

**Dependencies — decision rule**
Add task A to depends_on of task B if and only if: B needs to open or import a file that A creates or modifies.
Do NOT add a dependency just to be safe — unnecessary deps serialize work that could run in parallel.

Decision process for each task B:
  → For each file B reads or imports: who writes that file? → that task goes in B's depends_on
  → If B only writes new files that nobody wrote before: depends_on = []
  → If two tasks touch completely different files: NO dependency between them (run in parallel)

Goal: maximize parallelism. Tasks that work on separate files MUST run concurrently.

**Special tasks**
- QA/testing goals: include a dedicated QA worker using `swarm_report_bug` for every issue. QA tasks must have all implementation tasks in depends_on.
- When a QA worker is present, include a fixer worker to receive bug-fix tasks.
- ALWAYS include a final "Integration" task assigned to the orchestrator. Before writing it, enumerate ALL other task titles — every single one must appear in its depends_on. This task wires all files into the entry point.
- After planning, a shared interface CONTRACT will be auto-generated. Keep cross-worker interfaces minimal.
- Use `task_type: "debate"` only for critical architectural decisions. All implementation tasks use `task_type: "standard"`."""

    def _build_workers_prompt(self, swarm: dict) -> str:
        ctx = swarm.get("shared_context", "") or ""
        if len(ctx) > self._MAX_PLAN_CONTEXT_CHARS:
            ctx = ctx[: self._MAX_PLAN_CONTEXT_CHARS] + "\n\n[...context truncated...]"
        ctx_section = f"\n\n**Provided context files:**\n{ctx}" if ctx else ""
        answers = (swarm.get("clarification_answers") or "").strip()
        answers_section = (
            f"\n\n**Clarification Q&A:**\n{answers}" if answers else ""
        )
        return f"""You are a project planning AI. Design the optimal team of AI worker agents for this goal.{ctx_section}{answers_section}

**Goal:** {swarm["goal"]}

Return ONLY a raw JSON array — no prose, no markdown fences:
[
  {{
    "name": "Worker Name",
    "role": "orchestrator|worker",
    "description": "One-line specialty",
    "system_prompt": "You are a [specialty] worker. Your owned files: [exact list]. You MUST NOT edit files outside this list.",
    "model": null,
    "allowed_tools": "all"
  }}
]

Rules:
- Exactly 1 orchestrator + 2–5 specialist workers
- Each worker owns a non-overlapping set of files — no two workers ever write the same file
- system_prompt max 100 words; MUST include: specialty, exact owned file paths, no-edit-outside rule
- model can be null or a LiteLLM string like "anthropic/claude-opus-4-6\""""

    def _build_tasks_prompt(self, swarm: dict, workers: list[dict]) -> str:
        worker_names = [w.get("name", "") for w in workers]
        workers_summary = "\n".join(
            f'- {w.get("name")} ({w.get("role")}): {w.get("description", "")}'
            for w in workers
        )
        return f"""You are a project planning AI. Given the worker team below, generate the complete task plan.

**Goal:** {swarm["goal"]}

**Team:**
{workers_summary}

Valid worker names (use exactly): {json.dumps(worker_names)}

Return ONLY a raw JSON array of tasks — no prose, no markdown fences:
[
  {{
    "title": "Short unambiguous title",
    "description": "File: <exact path> | Action: CREATE|EDIT|ADD <summary> | Imports: <or none> | Exports: <or none> | Details: <notes>",
    "worker": "<exact worker name from list above>",
    "depends_on": [],
    "task_type": "standard"
  }}
]

Rules:
- Each task is ATOMIC: one file, one action. If it says "and" between two actions → split it.
- Aim for 10–20 tasks on non-trivial goals
- depends_on: list task titles that must complete before this one (only real file dependencies)
- Maximize parallelism — tasks on separate files have NO dependency
- ALWAYS include a final "Integration" task assigned to the orchestrator with ALL other task titles in depends_on
- ALWAYS include a "Documentation" task assigned to the orchestrator, depends_on ALL other task titles (including Integration). This task must produce a `README.md` in the workspace root covering: what was built, the architecture/structure, how to install/run it, how to use it, and any important decisions made. This is mandatory — every swarm must leave complete documentation.
- QA tasks (if needed) must depend on all implementation tasks
- task_type: "debate" only for critical architectural decisions; everything else is "standard\""""

    def _build_worker_system_prompt(
        self, worker: dict, swarm: dict, all_workers: list[dict], skills_prompt: str = ""
    ) -> str:
        teammates = [
            f"- {w['name']}: {w.get('description', w.get('role', 'worker'))}"
            for w in all_workers
            if w["id"] != worker["id"]
        ]
        team_section = "\n".join(teammates) if teammates else "None"

        import platform as _platform
        os_hint = (
            "You are running on **Windows**. "
            "Use `list_directory` / `read_file` / `write_file` for all file operations — "
            "NEVER `ls`, `pwd`, or Unix paths. "
            "When you must use `run_command`, use Windows syntax (backslashes, `dir`, `type`, etc.)."
            if _platform.system() == "Windows"
            else "You are running on Linux/macOS. Use standard shell commands."
        )

        shared_ws = (swarm.get("working_path") or "").strip() or worker["workspace_path"]

        base_prompt = worker["system_prompt"]
        if skills_prompt:
            base_prompt = f"{base_prompt}\n\n{skills_prompt}"

        return (
            f"{base_prompt}\n\n"
            f"---\n"
            f"**Swarm context:**\n"
            f"Project goal: {swarm['goal']}\n"
            f"Your role: {worker.get('role', 'worker')}\n"
            f"Shared project workspace (ALL team output goes here): `{shared_ws}`\n\n"
            f"**⚠️ FILE OPERATIONS — READ THIS FIRST:**\n"
            f"{os_hint}\n"
            f"- **One shared workspace for the whole team:** `{shared_ws}`\n"
            f"  Every worker reads and writes project files HERE — not in personal subdirectories.\n"
            f"  Example: `write_file(\"{shared_ws}/app/main.py\", content)`\n"
            f"- **Modify existing files with `edit_file`, not `write_file`.**\n"
            f"  `edit_file(path, old_string, new_string)` replaces only the changed section.\n"
            f"  Only use `write_file` when creating a file that does NOT exist yet.\n"
            f"  Rewriting an entire file that a teammate already created will destroy their work.\n"
            f"- Use `read_file` and `list_directory` for reading — NOT shell commands.\n"
            f"- NEVER use `cd`, `ls`, `pwd`, or try to navigate. Start writing files immediately.\n\n"
            f"**Your teammates:**\n{team_section}\n\n"
            f"**Swarm communication tools:**\n"
            f"- `swarm_send_message`: send a message to a specific teammate\n"
            f"- `swarm_broadcast`: send a message to all teammates\n"
            f"- `swarm_read_messages`: read messages sent to you or from the user\n"
            f"- `swarm_ask_user`: post a question to the user in the Activity feed (they will reply as a message)\n"
            f"- `swarm_create_task`: create a new task for yourself or a teammate\n"
            f"- `swarm_report_bug`: (QA workers) report a bug — auto-creates a fix task + re-test task\n"
            f"- `swarm_post_update`: post a progress update to the **team bulletin board** (all workers see it)\n"
            f"- `swarm_store_knowledge`: store a key fact/decision so ALL teammates can find it\n"
            f"- `swarm_query_knowledge`: search facts stored by any worker before starting your task\n"
            f"- `swarm_spawn_subswarm`: spawn a child swarm for a complex sub-goal (blocks, returns synthesis)\n\n"
            f"**IMPORTANT RULES:**\n"
            f"- **Trust your tools.** Tool results are accurate. If read_file returns content, that IS the file's content.\n"
            f"  Do NOT re-read the same file to verify — read each file ONCE, then act on the result.\n"
            f"- **Bias to action, not verification.** If you have enough information to write a file, write it.\n"
            f"  Imperfect working code is better than perfect paralysis. You can fix errors on retry.\n"
            f"- **Teammate failures are not your problem.** If a teammate had issues, read their outputs anyway\n"
            f"  and do your best with what exists. Do not let their failure stop you from creating your files.\n"
            f"- **Read the CONTRACT first**: your task context includes a SHARED INTERFACE CONTRACT.\n"
            f"  Follow it exactly — do not invent your own event names, data formats, DOM IDs, or import paths.\n"
            f"- **File ownership**: only write to the files your role owns per the contract.\n"
            f"  To use another worker's module, import it — do NOT rewrite it.\n"
            f"- **Read dependency outputs**: your context includes the full output of tasks you depend on.\n"
            f"  Read them carefully and build on the actual code/files produced, not assumptions.\n"
            f"- If you need information from the user, call `swarm_ask_user` — NEVER write questions to files.\n"
            f"- Do NOT create README or question files just to ask the user something.\n"
            f"- If blocked waiting for user input, use `swarm_ask_user` then end with TASK_STATUS: FAILED: waiting_for_user\n"
            f"- Call `swarm_read_messages` ONLY if your task is blocked waiting for a user reply or a teammate's answer — not as a routine step.\n"
            f"- Call `swarm_query_knowledge` ONLY when your task requires knowing a teammate's API, file format, or schema that isn't already in your task context.\n"
            f"- **Call `swarm_post_update` when you finish significant work** (e.g. 'Finished DB schema at db/schema.sql', 'API: POST /items returns {{id, name}}') so teammates stay informed.\n"
            f"- **Call `swarm_store_knowledge` after every key decision** (API shape, file path, DB schema, pattern used) so teammates don't have to guess.\n\n"
            f"**MATCH YOUR EFFORT TO YOUR TASK SCOPE:**\n"
            f"- **Single-file edit**: your task names a file and describes a specific change → read that file ONCE (if you need the current content), apply the edit, done. Do NOT explore the codebase, query knowledge, or read other files.\n"
            f"- **New file**: your task asks you to create a file → write it directly. Do NOT read the whole project first.\n"
            f"- **Integration task**: your task says to wire multiple files together → use `read_file` on the specific files listed in your task, then write the wiring. Do NOT read files not mentioned.\n"
            f"- **Documentation task**: survey the workspace with `list_directory` and `read_file` only on files you'll document, then write `README.md`.\n"
            f"- **QA/testing**: call `swarm_report_bug` ONCE PER BUG — ONE bug, ONE file, ONE call. NEVER create a broad 'Bug Fixing' task. Workflow: find bug in file X → `swarm_report_bug` (provide FILE/WRONG/CORRECT/REASON in description) → find next bug → `swarm_report_bug` → ... → TASK_STATUS: COMPLETED. Do NOT bundle bugs. Do NOT attempt fixes in files you don't own.\n"
            f"- **Orchestrator/auditor**: when finding problems (missing imports, broken wiring), call `swarm_create_task` immediately — do not just note the problem.\n\n"
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
        team_updates: list[dict] | None = None,
    ) -> str:
        shared_ws = (swarm.get("working_path") or "").strip()
        ws_reminder = (
            f"\n> **Shared workspace:** `{shared_ws}`  "
            f"Write ALL output files here. Use `edit_file` to modify existing files, "
            f"`write_file` only for new files."
        ) if shared_ws else ""

        parts = [
            f"# Task: {task['title']}{ws_reminder}\n\n{task['description']}",
        ]

        # ── Team Bulletin Board ───────────────────────────────────────────────
        # Recent updates posted by teammates via swarm_post_update.
        # Read these to know what's been done and avoid duplicating work.
        if team_updates:
            lines = []
            for u in team_updates:
                who = u.get("from_worker_name") or "unknown"
                lines.append(f"- [{who}] {u['content']}")
            parts.append(
                f"\n## Team Bulletin Board\n"
                f"Recent updates from your teammates:\n" + "\n".join(lines) + "\n\n"
                f"Post your own updates with `swarm_post_update` when you finish significant work."
            )

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
                f"### Output of: {title}\n\n{self._smart_truncate_output(output, TRUNCATE_SWARM_TASK_OUTPUT_CHARS)}"
                for title, output in dep_outputs
            )
            parts.append(
                f"\n## Output from Tasks You Depend On\n"
                f"Read these carefully — your task builds on this work.\n\n"
                f"{dep_section}"
            )

        # ── 3. Shared Project Context (uploaded files) ────────────────────────
        # Only show a compact file manifest — workers read files on demand.
        # Never inline full content here: workers reuse the same channel across
        # tasks, so injecting content each time wastes tokens unnecessarily.
        _ctx_files = json.loads(swarm.get("context_files") or "[]")
        if _ctx_files:
            _ws = swarm.get("workspace_path", "")
            _ctx_dir = Path(_ws) / "context" if _ws else Path("context")
            _flist = "\n".join(f"- {_ctx_dir / fn}" for fn in _ctx_files)
            parts.append(
                f"\n## Project Files\n\nUploaded files available — use `read_file` to access:\n{_flist}"
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
