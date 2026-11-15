"""
Central server state — imported by tools to avoid circular imports with server.py.
"""
from __future__ import annotations

import weakref
from dataclasses import dataclass, field


@dataclass
class ServerState:
    # Core services (typed as object to avoid importing heavy core modules here)
    brain: object = None
    database: object = None
    event_bus: object = None
    tool_registry: object = None
    config: object = None
    command_processor: object = None
    channels: list = field(default_factory=list)
    agent_channel_manager: object = None
    agent_runner: object = None
    mcp_manager: object = None
    activity_watcher: object = None
    cron_scheduler: object = None
    swarm_manager: object = None
    content_watcher: object = None
    voice_daemon: object = None
    # Runtime collections
    custom_provider_ids: set = field(default_factory=set)
    onboarding_triggered_flags: dict = field(default_factory=dict)
    chat_ws_clients: set = field(default_factory=set)
    ws_clients: set = field(default_factory=set)
    ws_send_locks: weakref.WeakKeyDictionary = field(default_factory=weakref.WeakKeyDictionary)
    # Buffered response for next connecting client
    pending_chat_response: dict | None = None
    # Tool confirmation: confirm_id → asyncio.Future[bool]
    pending_confirmations: dict = field(default_factory=dict)
    session_allowed_commands: set = field(default_factory=set)
    # Per-channel persistent shell sessions
    channel_shells: dict = field(default_factory=dict)


_state = ServerState()


def shared_agent_runner():
    """The one AgentRunner the whole app uses, or None while the brain does not exist yet.

    A single runner means a single set of per-conversation locks and one inactivity tracker:
    a customer who writes through a channel and through the webhook is still answered one
    message at a time. It reuses the channels' runner when there is one.
    """
    runner = getattr(_state.agent_channel_manager, "agent_runner", None) or _state.agent_runner
    if runner is None and _state.brain is not None:
        from openacm.core.agent_runner import AgentRunner

        _state.agent_runner = runner = AgentRunner(
            llm_router=_state.brain.llm_router,
            tool_registry=_state.brain.tool_registry,
            memory=_state.brain.memory,
            event_bus=_state.brain.event_bus,
            database=_state.database,
            skill_manager=_state.brain.skill_manager,
        )
    return runner
