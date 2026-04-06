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

    return [swarm_send_message, swarm_broadcast, swarm_read_messages, swarm_create_task]
