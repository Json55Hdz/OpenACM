"""
Internal event bus for OpenACM.

Lightweight pub/sub system for decoupling components.
Used for real-time updates (e.g., new message → dashboard WebSocket).
"""

import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine

import structlog

log = structlog.get_logger()

# Event type constants
EVENT_MESSAGE_RECEIVED = "message.received"
EVENT_MESSAGE_SENT = "message.sent"
EVENT_THINKING = "message.thinking"  # Bot está procesando/pensando
EVENT_TOOL_CALLED = "tool.called"
EVENT_TOOL_RESULT = "tool.result"
EVENT_TOOL_CONFIRMATION = "tool.confirmation_needed"
EVENT_LLM_REQUEST = "llm.request"
EVENT_LLM_RESPONSE = "llm.response"
EVENT_LLM_STREAM_CHUNK = "llm.stream_chunk"
EVENT_CHANNEL_CONNECTED = "channel.connected"
EVENT_CHANNEL_DISCONNECTED = "channel.disconnected"
EVENT_TOOL_OUTPUT_STREAM = "tool.output_stream"  # real-time chunk from a running tool
EVENT_ERROR = "error"
EVENT_ROUTER_LEARNED = "router.learned"  # LocalRouter saved a new example


class EventBus:
    """Simple async event bus for internal communication."""

    def __init__(self):
        self._handlers: dict[str, list[Callable[..., Coroutine]]] = defaultdict(list)
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

    def on(self, event_type: str, handler: Callable[..., Coroutine]):
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)

    def off(self, event_type: str, handler: Callable[..., Coroutine]):
        """Remove a handler."""
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    async def emit(self, event_type: str, data: dict[str, Any] | None = None):
        """
        Emit an event. All registered handlers are called concurrently.
        Errors in handlers are logged but don't propagate.
        """
        data = data or {}
        handlers = self._handlers.get(event_type, [])

        if not handlers:
            return

        tasks = []
        for handler in handlers:
            tasks.append(self._safe_call(handler, event_type, data))

        if tasks:
            await asyncio.gather(*tasks)

    async def _safe_call(self, handler: Callable, event_type: str, data: dict[str, Any]):
        """Call a handler safely, catching and logging errors."""
        try:
            await handler(event_type, data)
        except Exception as e:
            log.error(
                "Event handler error",
                event_type=event_type,
                handler=handler.__name__,
                error=str(e),
            )
