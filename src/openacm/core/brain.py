"""
Brain — the central AI engine.

Receives messages, builds context, calls the LLM, processes tool calls,
and returns responses. Handles the full agentic loop with safety limits.

Implementation is split across focused mixin modules:
  brain_prompt.py     — system prompt building and RAG context injection
  brain_multimodal.py — attachment resolution (PDF, audio, images)
  brain_workflow.py   — workflow tracking and routine hints
  brain_loop.py       — agentic loop and LLM message preparation
"""

import asyncio
import json
from typing import Any

import structlog

from openacm.core.brain_loop import BrainLoopMixin
from openacm.core.brain_multimodal import BrainMultimodalMixin
from openacm.core.brain_prompt import BrainPromptMixin
from openacm.core.brain_workflow import BrainWorkflowMixin
from openacm.core.config import AssistantConfig
from openacm.core.events import (
    EVENT_MESSAGE_SENT,
    EVENT_ROUTER_LEARNED,
    EVENT_THINKING,
    EventBus,
)
from openacm.core.llm_router import LLMRouter
from openacm.core.local_router import LocalRouter
from openacm.core.memory import MemoryManager
from openacm.core.messages import (
    MSG_CANCELLED,
    MSG_FAST_OPENING,
    MSG_QUEUED_ACK,
    MSG_QUEUED_DEQUEUED,
    MSG_QUEUED_NOTIFY,
)

log = structlog.get_logger()


class Brain(BrainPromptMixin, BrainMultimodalMixin, BrainWorkflowMixin, BrainLoopMixin):
    """
    Central AI engine that processes messages through the LLM
    with tool calling support.
    """

    # Enforcement message injected for providers that need it
    _TOOL_ENFORCEMENT_MSG = (
        "You are OpenACM. You MUST respond by calling one of your tools. "
        "Do NOT describe what you would do — actually DO it using a tool call. "
        "Available tools: run_command, run_python, web_search, browser_agent, "
        "file_ops, send_file_to_chat, google_services, screenshot, system_info. "
        "If you need a Python library, install it first with run_command (pip install X) then use run_python. "
        "You CAN install packages. You CAN access the internet. You CAN create any file. "
        "NEVER say 'as a language model' or 'I cannot'. Execute the user's request NOW."
    )

    _CANCEL_KEYWORDS = {"cancel", "cancelar", "stop", "detener", "para", "parar", "abort"}

    def __init__(
        self,
        config: AssistantConfig,
        llm_router: LLMRouter,
        memory: MemoryManager,
        event_bus: EventBus,
        tool_registry: Any = None,
        skill_manager: Any = None,
    ):
        self.config = config
        self.llm_router = llm_router
        self.memory = memory
        self.event_bus = event_bus
        self.tool_registry = tool_registry
        self.skill_manager = skill_manager
        self.terminal_history: list[dict] = []
        # Tracks the active processing task per channel — used for interruption
        self._channel_tasks: dict[str, asyncio.Task] = {}
        # Queued message per channel while a task is running (one slot — latest wins)
        self._channel_queue: dict[str, tuple] = {}
        # Per-channel cancel flag: set when user cancels, checked in the tool loop
        self._cancel_flags: dict[str, asyncio.Event] = {}
        self.workflow_tracker = None  # injected by app.py
        self._pending_suggestions: dict[str, object] = {}  # key: "channel_id:user_id"
        # System prompt cache — skip get_or_create update when prompt hasn't changed
        self._system_prompt_hash: dict[str, int] = {}  # channel_key → hash
        # RAG cache — reuse results when the query is semantically similar
        self._rag_cache: dict[str, tuple[str, list[str]]] = {}  # channel_key → (query, results)
        # Last N agentic loop traces for debugging
        self._traces: list[dict] = []
        self._MAX_TRACES = 20
        _lr = getattr(config, "local_router", None)
        self.local_router = LocalRouter(
            confidence_threshold=_lr.confidence_threshold if _lr else 0.88,
            observation_mode=not _lr.enabled if _lr else False,
        )

    async def _execute_fast_path(
        self,
        intent: str,
        message: str,
        user_id: str,
        channel_id: str,
        channel_type: str,
    ) -> str | None:
        """
        Execute a simple intent directly without calling the LLM.
        Dispatches to the handler registered in fast_path.py for this intent.
        Returns the response string, or None to fall through to the LLM.
        """
        from openacm.core.fast_path import dispatch

        response = await dispatch(intent, self, message, user_id, channel_id, channel_type)
        if response is None:
            return None

        await self.memory.add_message(user_id, channel_id, "assistant", response)
        await self.event_bus.emit(EVENT_MESSAGE_SENT, {
            "content": response,
            "user_id": user_id,
            "channel_id": channel_id,
            "channel_type": channel_type,
            "tokens": 0,
        })
        await self.event_bus.emit(EVENT_THINKING, {
            "status": "done",
            "user_id": user_id,
            "channel_id": channel_id,
            "channel_type": channel_type,
        })
        log.info("Fast-path executed", intent=intent)
        return response

    async def _maybe_learn_from_tools(
        self,
        original_message: str,
        tool_calls: list[dict],
        router_task: asyncio.Task,
    ) -> None:
        """
        Passive learning: infer the user's intent from what tools the LLM called
        and teach the LocalRouter — so next time it can skip the LLM entirely.

        Only learns when:
        - The LLM called exactly one tool (unambiguous intent signal)
        - The router was uncertain (confidence below threshold)
        - We can map that tool to a known intent
        """
        from openacm.core.local_router import TOOL_TO_INTENT, RUN_COMMAND_HINTS

        if len(tool_calls) != 1:
            return  # ambiguous — multiple tools called

        try:
            router_result = await asyncio.wait_for(asyncio.shield(router_task), timeout=2.0)
        except Exception:
            router_result = None

        # Only learn if the router was uncertain (below threshold)
        if router_result and router_result.is_fast_path_eligible:
            return  # already confident, no need to learn

        tool_name = tool_calls[0]["function"]["name"]
        tool_args = tool_calls[0]["function"]["arguments"]

        # Direct tool → intent mapping
        inferred_intent = TOOL_TO_INTENT.get(tool_name)

        # run_command: check arguments for app/media hints
        if not inferred_intent and tool_name == "run_command":
            args_lower = tool_args.lower()
            for hint, intent in RUN_COMMAND_HINTS.items():
                if hint in args_lower:
                    inferred_intent = intent
                    break

        if not inferred_intent:
            return  # can't infer intent from this tool call

        # If the router already guessed right, still learn to boost confidence
        if router_result and router_result.intent != inferred_intent:
            return  # router was wrong — don't reinforce a bad pattern

        learned = await self.local_router.learn(original_message, inferred_intent)
        if learned:
            await self.event_bus.emit(EVENT_ROUTER_LEARNED, {
                "intent": inferred_intent,
                "message": original_message,
            })

        # Also learn the concrete action so fast_path can replay it later
        await self._maybe_learn_action(original_message, tool_name, tool_args, inferred_intent)

    async def _maybe_learn_action(
        self,
        phrase: str,
        tool_name: str,
        tool_args_str: str,
        intent: str,
    ) -> None:
        """
        Store a phrase → concrete tool call for direct fast-path replay.

        Safety rules (by design):
        - open_url: always learnable — opening a URL is safe and deterministic
        - run_command: only when intent == OPEN_APP — avoids learning arbitrary shell commands
        - All other tools: ignored
        """
        try:
            args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
        except Exception:
            return

        if tool_name == "open_url":
            url = args.get("url", "")
            if not url:
                return
            # Extract a readable label from the URL for the response message
            from urllib.parse import urlparse
            label = urlparse(url).netloc or url
            await self.local_router.learn_action(
                phrase, tool_name, args, intent, MSG_FAST_OPENING.format(name=label)
            )

        elif tool_name == "run_command" and intent == "OPEN_APP":
            command = args.get("command", "")
            if not command:
                return
            # Use the last token of the command as the app name (e.g. "start blender" → "Blender")
            app_name = command.strip().split()[-1].title()
            await self.local_router.learn_action(
                phrase, tool_name, args, intent, MSG_FAST_OPENING.format(name=app_name)
            )

    def _save_trace(self, trace: dict) -> None:
        """Store a completed trace, keeping only the last _MAX_TRACES entries."""
        self._traces.append(trace)
        if len(self._traces) > self._MAX_TRACES:
            self._traces = self._traces[-self._MAX_TRACES:]
        log.info(
            "Agentic loop trace",
            trace_id=trace["id"],
            outcome=trace["outcome"],
            total_elapsed_ms=trace["total_elapsed_ms"],
            iterations=len(trace["iterations"]),
            context_chars_last=[it["context_chars"] for it in trace["iterations"]],
            tool_calls_summary=[
                f"{tc['tool']}({tc['result_chars']}ch{'!trunc' if tc['truncated'] else ''})"
                for it in trace["iterations"]
                for tc in it["tool_calls"]
            ],
        )

    async def process_message(
        self,
        content: str,
        user_id: str,
        channel_id: str,
        channel_type: str = "console",
        attachments: list[str] | None = None,
        is_transparent: bool = False,
    ) -> str:
        """
        Public entry point — wraps _run() in a dedicated cancellable task.

        Behaviour when a task is already running for this channel:
        - Cancel keywords ("cancel", "stop", "cancelar", …) → cancel immediately.
        - Any other message → queue it (latest wins) and notify the user.
          The queued message is processed automatically once the current task finishes.
        """
        _task_key = f"{channel_type}:{channel_id}"
        _prev = self._channel_tasks.get(_task_key)

        if _prev and not _prev.done():
            is_cancel = content.strip().lower() in self._CANCEL_KEYWORDS
            if is_cancel:
                # Set the per-channel flag so the tool loop stops at its next check
                self._cancel_flags.setdefault(_task_key, asyncio.Event()).set()
                _prev.cancel()
                self._channel_tasks.pop(_task_key, None)
                self._channel_queue.pop(_task_key, None)
                await asyncio.sleep(0)
                await self.event_bus.emit(EVENT_THINKING, {
                    "status": "done",
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                })
                return MSG_CANCELLED
            else:
                # Queue the message — latest message wins
                self._channel_queue[_task_key] = (content, user_id, channel_id, channel_type, attachments, is_transparent)
                await self.event_bus.emit(EVENT_THINKING, {
                    "status": "queued",
                    "message": MSG_QUEUED_NOTIFY,
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                })
                return MSG_QUEUED_ACK

        # No active task — clear any stale cancel flag and run immediately
        self._cancel_flags.setdefault(_task_key, asyncio.Event()).clear()
        self._channel_queue.pop(_task_key, None)
        task = asyncio.create_task(
            self._run_then_drain(content, user_id, channel_id, channel_type, attachments, is_transparent, _task_key)
        )
        self._channel_tasks[_task_key] = task

        try:
            return await task
        except asyncio.CancelledError:
            return MSG_CANCELLED

    async def _run_then_drain(
        self,
        content: str,
        user_id: str,
        channel_id: str,
        channel_type: str,
        attachments: list[str] | None,
        is_transparent: bool,
        task_key: str,
    ) -> str:
        """Run _run(), then process any queued message afterwards."""
        try:
            result = await self._run(content, user_id, channel_id, channel_type, attachments, is_transparent)
        finally:
            self._channel_tasks.pop(task_key, None)

        # Process queued message if any
        queued = self._channel_queue.pop(task_key, None)
        if queued:
            q_content, q_user, q_channel, q_type, q_attach, q_trans = queued
            await self.event_bus.emit(EVENT_THINKING, {
                "status": "start",
                "message": MSG_QUEUED_DEQUEUED,
                "user_id": q_user,
                "channel_id": q_channel,
                "channel_type": q_type,
            })
            next_task = asyncio.create_task(
                self._run_then_drain(q_content, q_user, q_channel, q_type, q_attach, q_trans, task_key)
            )
            self._channel_tasks[task_key] = next_task
            # Don't await — let it run in background

        return result
