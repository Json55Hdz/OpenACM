"""
Shared pytest fixtures for OpenACM test suite.

Hierarchy:
  - mock_llm_response  : minimal dict that looks like a real LLM response
  - mock_llm_router    : LLMRouter whose .chat() returns mock_llm_response
  - db                 : in-memory async SQLite database (fresh per test)
  - tool_registry      : ToolRegistry wired to db, no sandbox, no embeddings
  - brain              : Brain wired to mock_llm_router + db + tool_registry
  - app / client       : FastAPI TestClient with all globals injected
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from openacm.core.config import (
    AppConfig,
    AssistantConfig,
    LLMConfig,
    WebConfig,
    SecurityConfig,
    ChannelsConfig,
)
from openacm.core.events import EventBus
from openacm.core.llm_router import ProviderProfile
from openacm.storage.database import Database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_response(content: str = "Test response.") -> dict[str, Any]:
    """Minimal dict that brain.py expects from llm_router.chat()."""
    return {
        "content": content,
        "tool_calls": [],
        "model": "mock-model",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "cost": 0.0,
    }


def _make_app_config(**overrides) -> AppConfig:
    """Minimal AppConfig suitable for tests (no real keys, no real paths)."""
    assistant = AssistantConfig(
        name="TestACM",
        system_prompt="You are a test assistant.",
        onboarding_completed=True,
        max_context_messages=10,
        max_tool_iterations=3,
        response_timeout=5,
    )
    llm = LLMConfig(default_provider="mock", providers={})
    web = WebConfig(host="127.0.0.1", port=47821, auth_enabled=False)
    security = SecurityConfig()
    channels = ChannelsConfig()

    cfg = AppConfig(
        assistant=assistant,
        llm=llm,
        web=web,
        security=security,
        channels=channels,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def app_config() -> AppConfig:
    return _make_app_config()


@pytest.fixture
def mock_llm_router():
    """LLMRouter stub: .chat() returns a fixed response, no real API calls."""
    router = MagicMock()
    router.chat = AsyncMock(return_value=_make_llm_response())
    router.chat_stream = AsyncMock(return_value=_make_llm_response())
    router._current_provider = "mock"
    router._current_model = "mock-model"
    router.local_router = None
    router.get_provider_profile = MagicMock(return_value=ProviderProfile(
        name="mock",
        needs_tool_enforcement=False,
        tool_choice_mode="auto",
        max_tools_per_call=None,
    ))
    return router


@pytest_asyncio.fixture
async def db() -> Database:
    """Fresh in-memory SQLite database, initialized and torn down per test."""
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def tool_registry(db, event_bus, app_config):
    """ToolRegistry with no sandbox and no real embeddings."""
    from openacm.tools.registry import ToolRegistry
    from openacm.security.sandbox import Sandbox
    from openacm.security.policies import SecurityPolicy

    policy = SecurityPolicy(app_config.security)
    sandbox = Sandbox(policy, event_bus)
    registry = ToolRegistry(
        database=db,
        event_bus=event_bus,
        sandbox=sandbox,
    )
    # Skip precomputing embeddings — too slow and needs sentence-transformers loaded
    return registry


@pytest_asyncio.fixture
async def brain(app_config, mock_llm_router, db, tool_registry, event_bus):
    """Brain wired to mock LLM — no real API calls, no real model loading."""
    from openacm.core.brain import Brain
    from openacm.core.memory import MemoryManager

    memory = MemoryManager(database=db, config=app_config.assistant)
    b = Brain(
        config=app_config.assistant,
        llm_router=mock_llm_router,
        memory=memory,
        event_bus=event_bus,
        tool_registry=tool_registry,
        skill_manager=None,
    )
    return b


@pytest_asyncio.fixture
async def client(app_config, brain, db, tool_registry, event_bus):
    """
    FastAPI TestClient with all server globals injected.
    Use httpx.AsyncClient for async endpoint tests.
    """
    from httpx import AsyncClient, ASGITransport
    import openacm.web.server as server_module

    app = server_module.create_server(
        brain=brain,
        database=db,
        event_bus=event_bus,
        tool_registry=tool_registry,
        config=app_config,
        command_processor=None,
        channels=[],
        agent_bot_manager=None,
        mcp_manager=None,
        activity_watcher=None,
        cron_scheduler=None,
        swarm_manager=None,
        content_watcher=None,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
