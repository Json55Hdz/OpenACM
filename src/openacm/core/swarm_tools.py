"""
Swarm communication tools — injected into worker agents during swarm execution.

These tools allow workers to:
- Send messages to specific teammates (swarm_send_message)
- Broadcast to all workers (swarm_broadcast)
- Read received messages (swarm_read_messages)
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from openacm.constants import SWARM_MAX_BUG_FIX_CYCLES

log = structlog.get_logger()

EVENT_SWARM_MESSAGE = "swarm:message"


def build_swarm_tools(
    swarm_id: int,
    worker_id: int,
    all_workers: list[dict],
    database: Any,
    event_bus: Any,
) -> list:
    """
    Create a list of swarm communication tool functions bound to the given worker.
    Each function has a ``_tool_schema`` attribute for LiteLLM tool-calling.
    """
    name_to_id = {w["name"]: w["id"] for w in all_workers}
    id_to_name = {w["id"]: w["name"] for w in all_workers}
    my_name = id_to_name.get(worker_id, f"worker_{worker_id}")
    worker_names = [w["name"] for w in all_workers if w["id"] != worker_id]

    async def swarm_send_message(to_worker: str, message: str, **kwargs) -> str:
        """
        Send a message to a specific teammate in the swarm.

        Args:
            to_worker: Name of the worker to send the message to.
            message: The message content to send.
        """
        to_id = name_to_id.get(to_worker)
        if not to_id:
            return f"Worker '{to_worker}' not found. Available: {', '.join(worker_names)}"
        try:
            await database.add_swarm_message(
                swarm_id=swarm_id,
                from_worker_id=worker_id,
                to_worker_id=to_id,
                content=message,
                message_type="message",
            )
            await event_bus.emit(
                EVENT_SWARM_MESSAGE,
                {
                    "swarm_id": swarm_id,
                    "from_worker_id": worker_id,
                    "from_worker_name": my_name,
                    "to_worker_id": to_id,
                    "to_worker_name": to_worker,
                    "message": message,
                    "type": "direct",
                },
            )
            return f"Message sent to {to_worker}."
        except Exception as e:
            return f"Failed to send message: {e}"

    swarm_send_message._tool_schema = {
        "type": "function",
        "function": {
            "name": "swarm_send_message",
            "description": "Send a message to a specific teammate in the swarm.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_worker": {
                        "type": "string",
                        "description": f"Name of the worker to message. Available: {', '.join(worker_names)}",
                    },
                    "message": {
                        "type": "string",
                        "description": "The message to send.",
                    },
                },
                "required": ["to_worker", "message"],
            },
        },
    }

    async def swarm_broadcast(message: str, **kwargs) -> str:
        """
        Broadcast a message to all teammates in the swarm.

        Args:
            message: The message to broadcast to all workers.
        """
        try:
            await database.add_swarm_message(
                swarm_id=swarm_id,
                from_worker_id=worker_id,
                to_worker_id=None,  # None = broadcast
                content=message,
                message_type="broadcast",
            )
            await event_bus.emit(
                EVENT_SWARM_MESSAGE,
                {
                    "swarm_id": swarm_id,
                    "from_worker_id": worker_id,
                    "from_worker_name": my_name,
                    "to_worker_id": None,
                    "message": message,
                    "type": "broadcast",
                },
            )
            return f"Broadcast sent to all workers."
        except Exception as e:
            return f"Failed to broadcast: {e}"

    swarm_broadcast._tool_schema = {
        "type": "function",
        "function": {
            "name": "swarm_broadcast",
            "description": "Broadcast a message to all teammates in the swarm.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to broadcast to all workers.",
                    },
                },
                "required": ["message"],
            },
        },
    }

    async def swarm_read_messages(**kwargs) -> str:
        """
        Read all messages sent to you (or broadcast) in this swarm,
        including messages from the user giving feedback.
        """
        try:
            msgs = await database.get_swarm_messages(swarm_id, to_worker_id=worker_id)
            if not msgs:
                return "No messages received yet."
            lines = []
            for m in msgs:
                mtype = m.get("message_type", "message")
                from_name = m.get("from_worker_name") or "unknown"
                if mtype == "user":
                    prefix = "[USER FEEDBACK]"
                elif mtype == "broadcast":
                    prefix = f"[broadcast from {from_name}]"
                else:
                    prefix = f"[from {from_name}]"
                lines.append(f"{prefix} {m['content']}")
            return "\n".join(lines)
        except Exception as e:
            return f"Failed to read messages: {e}"

    swarm_read_messages._tool_schema = {
        "type": "function",
        "function": {
            "name": "swarm_read_messages",
            "description": "Read all messages sent to you, broadcasts, and user feedback in the swarm.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }

    async def swarm_create_task(
        title: str,
        description: str,
        assign_to: str = "",
        **kwargs,
    ) -> str:
        """
        Create a new task in the swarm. Use this to spawn additional work
        based on discoveries, user feedback, or task dependencies.

        Args:
            title: Short title for the task.
            description: Detailed description of what needs to be done.
            assign_to: Name of the worker to assign the task to (optional).
        """
        try:
            target_worker_id = name_to_id.get(assign_to.strip()) if assign_to.strip() else None
            task_id = await database.create_swarm_task(
                swarm_id=swarm_id,
                worker_id=target_worker_id,
                title=title,
                description=description,
                depends_on="[]",
            )
            await event_bus.emit(
                "swarm:task_created",
                {
                    "swarm_id": swarm_id,
                    "task_id": task_id,
                    "title": title,
                    "assign_to": assign_to or "auto",
                    "created_by": my_name,
                },
            )
            assigned = f" → assigned to {assign_to}" if assign_to else ""
            return f"Task '{title}' created (ID: {task_id}){assigned}. It will run in the next execution round."
        except Exception as e:
            return f"Failed to create task: {e}"

    swarm_create_task._tool_schema = {
        "type": "function",
        "function": {
            "name": "swarm_create_task",
            "description": (
                "Create a new task in the swarm. Use when you discover additional work is needed, "
                "receive user feedback requesting changes, or want to spawn follow-up tasks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short task title."},
                    "description": {"type": "string", "description": "Detailed description of the task."},
                    "assign_to": {
                        "type": "string",
                        "description": f"Worker name to assign to. Available: {', '.join(worker_names)}. Leave empty for auto-assign.",
                    },
                },
                "required": ["title", "description"],
            },
        },
    }

    async def swarm_ask_user(question: str, **kwargs) -> str:
        """
        Ask the user a question that requires their input before work can continue.
        The question will appear prominently in the Activity feed so the user can reply.
        Use this instead of writing questions to files.

        Args:
            question: The question to ask the user. Be specific about what you need.
        """
        try:
            await database.add_swarm_message(
                swarm_id=swarm_id,
                from_worker_id=worker_id,
                to_worker_id=None,
                content=question,
                message_type="question",
            )
            await event_bus.emit(
                "swarm:user_question",
                {
                    "swarm_id": swarm_id,
                    "from_worker_id": worker_id,
                    "from_worker_name": my_name,
                    "question": question,
                },
            )
            return "Question posted to the user in the Activity feed. End your task with TASK_STATUS: FAILED: waiting_for_user so it can be retried once the user replies."
        except Exception as e:
            return f"Failed to post question: {e}"

    swarm_ask_user._tool_schema = {
        "type": "function",
        "function": {
            "name": "swarm_ask_user",
            "description": (
                "Ask the user a question that requires their input before you can continue. "
                "The question appears in the Activity feed for the user to answer. "
                "ALWAYS use this instead of writing questions to files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user. Be specific about what information you need.",
                    },
                },
                "required": ["question"],
            },
        },
    }

    # ── QA Bug Reporting ──────────────────────────────────────────────────────

    # Track how many times each bug title has been reported to cap retry loops
    _bug_cycles: dict[str, int] = {}
    MAX_BUG_CYCLES = SWARM_MAX_BUG_FIX_CYCLES

    async def swarm_report_bug(
        title: str,
        description: str,
        severity: str = "medium",
        assign_to_fixer: str = "",
        **kwargs,
    ) -> str:
        """
        Report a bug found during QA/testing. Automatically creates:
          1. A fix task assigned to the specified fixer worker.
          2. A re-test task assigned back to you (the QA worker), which only
             runs AFTER the fix is complete.
        This creates a self-healing QA→Fix→Retest loop until all bugs pass.

        Args:
            title:           Short description of the bug.
            description:     Detailed reproduction steps and expected vs actual behavior.
            severity:        'low' | 'medium' | 'high' | 'critical'
            assign_to_fixer: Name of the worker responsible for fixing this bug.
        """
        cycle = _bug_cycles.get(title, 0) + 1
        if cycle > MAX_BUG_CYCLES:
            return (
                f"Bug '{title}' has been through {MAX_BUG_CYCLES} fix cycles with no resolution. "
                f"Escalating — please notify the user with swarm_ask_user."
            )
        _bug_cycles[title] = cycle

        fix_title = f"Fix (cycle {cycle}): {title}"
        retest_title = f"Re-test (cycle {cycle}): {title}"

        fixer_id = name_to_id.get(assign_to_fixer.strip()) if assign_to_fixer.strip() else None
        severity_label = severity.upper()

        fix_description = (
            f"**[BUG FIX — {severity_label}]** {title}\n\n"
            f"{description}\n\n"
            f"Fix the issue described above. When done, end with TASK_STATUS: COMPLETED."
        )
        retest_description = (
            f"**[QA RE-TEST — cycle {cycle}]** {title}\n\n"
            f"Re-run the original tests for this bug after '{fix_title}' is complete.\n"
            f"If the bug is fixed: TASK_STATUS: COMPLETED.\n"
            f"If it still fails: call `swarm_report_bug` again with updated details."
        )

        try:
            fix_task_id = await database.create_swarm_task(
                swarm_id=swarm_id,
                worker_id=fixer_id,
                title=fix_title,
                description=fix_description,
                depends_on="[]",
            )
            await database.create_swarm_task(
                swarm_id=swarm_id,
                worker_id=worker_id,  # back to the QA caller
                title=retest_title,
                description=retest_description,
                depends_on=json.dumps([fix_title]),
            )

            # Post a visible bug report to the Activity feed
            await database.add_swarm_message(
                swarm_id=swarm_id,
                from_worker_id=worker_id,
                to_worker_id=None,
                content=json.dumps({
                    "title": title,
                    "description": description,
                    "severity": severity,
                    "fixer": assign_to_fixer or "auto",
                    "cycle": cycle,
                    "fix_task": fix_title,
                    "retest_task": retest_title,
                }),
                message_type="bug_report",
            )
            await event_bus.emit(
                "swarm:bug_reported",
                {
                    "swarm_id": swarm_id,
                    "title": title,
                    "severity": severity,
                    "reporter": my_name,
                    "fixer": assign_to_fixer,
                    "cycle": cycle,
                },
            )
            fixer_label = assign_to_fixer or "auto-assigned"
            return (
                f"Bug '{title}' reported (cycle {cycle}/{MAX_BUG_CYCLES}, severity={severity_label}). "
                f"Created: '{fix_title}' → {fixer_label}, then '{retest_title}' → you.\n"
                f"End this task with TASK_STATUS: COMPLETED."
            )
        except Exception as e:
            return f"Failed to report bug: {e}"

    swarm_report_bug._tool_schema = {
        "type": "function",
        "function": {
            "name": "swarm_report_bug",
            "description": (
                "Report a bug found during QA/testing. "
                "Automatically schedules a fix task and a re-test task (QA loop). "
                "Use this instead of just failing the task — it keeps the swarm self-healing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short bug title (used to track cycles).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Full bug description: steps to reproduce, expected vs actual behavior.",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Bug severity level.",
                    },
                    "assign_to_fixer": {
                        "type": "string",
                        "description": (
                            f"Worker responsible for fixing. Available: {', '.join(worker_names)}. "
                            "Leave empty for auto-assignment."
                        ),
                    },
                },
                "required": ["title", "description"],
            },
        },
    }

    return [
        swarm_send_message, swarm_broadcast, swarm_read_messages,
        swarm_create_task, swarm_ask_user, swarm_report_bug,
    ]
