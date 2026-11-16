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
    MSG_CANCEL_PENDING,
    MSG_NOTHING_TO_CANCEL,
    MSG_FAST_OPENING,
    MSG_QUEUED_ACK,
    MSG_QUEUED_DEQUEUED,
    MSG_QUEUED_NOTIFY,
    MSG_STEER_ACK,
    MSG_STEER_NOTIFY,
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

    _CANCEL_GRACE_S = 3.0  # how long a cancel waits for the run to actually stop
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
        # Per-chat override of max_tool_iterations, set by the /steps command.
        self._step_limits: dict[tuple[str, str], int | None] = {}
        # Messages sent while a run is busy, read by the tool loop between steps.
        from openacm.core.debounce import MessageDebouncer
        self._debouncer = MessageDebouncer()
        self._channel_inbox: dict[str, list[tuple[str, str, str]]] = {}
        self._inbox_meta: dict[str, str] = {}
        self._MAX_TRACES = 20
        _lr = getattr(config, "local_router", None)
        self.local_router = LocalRouter(
            confidence_threshold=_lr.confidence_threshold if _lr else 0.88,
            # An agent talks to outside people and a swarm worker to nobody: neither may have the
            # router run host commands for a phrase (screenshots, apps, system info) on its own.
            observation_mode=(not _lr.enabled if _lr else False) or bool(getattr(config, "is_agent", False)),
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

        if getattr(self.config, "is_agent", False):
            return  # a customer's phrasing must never become a host action for everyone
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
        debounce: bool = False,
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

        is_cancel = content.strip().lower() in self._CANCEL_KEYWORDS

        # A burst of messages is answered once. Cancel words act at once, and while a run is
        # going the steering below already folds new messages into it.
        if debounce and not is_cancel and not is_transparent and not (_prev and not _prev.done()):
            merged = await self._debouncer.collect((_task_key, user_id), content, attachments)
            if merged is None:
                return ""  # folded into the first message of the burst, which gets the answer
            content, attachments = merged
            _prev = self._channel_tasks.get(_task_key)

        if _prev and not _prev.done():
            if is_cancel:
                # 1) Flag: the tool loop stops at its next check even if the hard cancel
                #    below is swallowed somewhere (executor threads, a tool catching it).
                # 2) Hard cancel of the task.
                # The task stays registered in _channel_tasks until it has REALLY ended
                # (_run_then_drain pops it): a second "cancel" must still find it, and a
                # new message must not start a second run next to a zombie one.
                # Messages the user sent while it was working are NOT dropped: they run
                # as the next turn as soon as the cancelled run has ended.
                self._cancel_flags.setdefault(_task_key, asyncio.Event()).set()
                _prev.cancel()
                try:
                    await asyncio.wait({_prev}, timeout=self._CANCEL_GRACE_S)
                except Exception:  # noqa: BLE001
                    pass
                await self.event_bus.emit(EVENT_THINKING, {
                    "status": "done",
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                })
                return MSG_CANCELLED if _prev.done() else MSG_CANCEL_PENDING
            elif not attachments and not is_transparent:
                # Steer the running turn: the tool loop reads this inbox between steps,
                # so the model gets the message as soon as the current tool finishes.
                # Anything still unread when the run ends is processed right after it.
                self._channel_inbox.setdefault(_task_key, []).append((content, user_id, channel_id))
                self._inbox_meta[_task_key] = channel_type
                await self.event_bus.emit(EVENT_THINKING, {
                    "status": "queued",
                    "message": MSG_STEER_NOTIFY,
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                })
                return MSG_STEER_ACK
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

        if is_cancel:
            # Nothing is running: do not send the bare cancel word to the LLM.
            return MSG_NOTHING_TO_CANCEL

        # No active task — give this run its OWN cancel flag (a fresh Event instead of
        # clearing the shared one, so a still-unwinding cancelled run keeps seeing its flag).
        self._cancel_flags[_task_key] = asyncio.Event()
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
            return await self._run(content, user_id, channel_id, channel_type, attachments, is_transparent)
        finally:
            # Runs on normal end AND on cancel, so waiting messages are never stranded.
            if self._channel_tasks.get(task_key) is asyncio.current_task():
                self._channel_tasks.pop(task_key, None)
                self._start_waiting(task_key, channel_type)

    def _start_waiting(self, task_key: str, channel_type: str) -> None:
        """Start the next turn from what the user sent while the previous run was busy:
        a queued message, or the steering messages the loop never got to read (grouped
        per chat)."""
        queued = self._channel_queue.pop(task_key, None)
        _left = self._channel_inbox.pop(task_key, None)
        if _left and queued:
            self._channel_inbox[task_key] = _left  # the next run's loop will read them
        elif _left:
            _c0, _u0, _ch0 = _left[0]
            _same = [c for (c, u, ch) in _left if u == _u0 and ch == _ch0]
            _rest = [m for m in _left if not (m[1] == _u0 and m[2] == _ch0)]
            if _rest:
                self._channel_inbox[task_key] = _rest
            queued = ("\n\n".join(_same), _u0, _ch0, self._inbox_meta.get(task_key, channel_type), None, False)
        if not queued:
            return
        q_content, q_user, q_channel, q_type, q_attach, q_trans = queued
        # Its own cancel flag: the previous run's flag may be set (it was cancelled).
        self._cancel_flags[task_key] = asyncio.Event()

        async def _next() -> str:
            await self.event_bus.emit(EVENT_THINKING, {
                "status": "start",
                "message": MSG_QUEUED_DEQUEUED,
                "user_id": q_user,
                "channel_id": q_channel,
                "channel_type": q_type,
            })
            return await self._run_then_drain(q_content, q_user, q_channel, q_type, q_attach, q_trans, task_key)

        self._channel_tasks[task_key] = asyncio.create_task(_next())
