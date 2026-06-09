# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (dev)
uv pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/unit/test_brain.py

# Run a single test by name
pytest tests/unit/test_brain.py::TestBrainInit::test_local_router_created

# Run the app
python -m openacm
# or
uv run openacm
```

Tests use `asyncio_mode = "auto"` — all async test functions run without `@pytest.mark.asyncio`.

## Architecture

### Startup sequence (`app.py`)
`OpenACM.run()` boots in order: config → database → security/LLM/memory → tools → channels → watchers/schedulers → web server → console loop. Each subsystem is wired together by `app.py`; it is the only place where cross-cutting dependencies are assembled.

### The agentic loop (`core/brain.py`)
`Brain.process_message()` is the main entry point for every user message:
1. **LocalRouter** classifies intent in ~5ms — if confidence is above threshold it runs a fast-path handler and skips the LLM entirely.
2. Otherwise the **agentic loop** runs: build system prompt → inject RAG context + skills → call LLM → execute tool calls → loop until no more tool calls or `max_tool_iterations` is hit.
3. Each iteration is fully traced (`_traces`) and accessible via `/api/traces`.

### Tool system (`tools/`)
Tools are registered with the `@tool` decorator. The decorator adds a `ToolDefinition` to a global list in `tools/base.py`. At startup `ToolRegistry` imports each tool module (triggering the decorator) then builds semantic embeddings over all tool descriptions for cosine-similarity selection.

Tool functions always receive `_brain=None` as a kwarg. Use `_brain.tool_registry` to access shared managers (`cron_scheduler`, `swarm_manager`, `mcp_manager`, `app_config`).

### Events (`core/events.py`)
`EventBus` is a simple async pub/sub. Emit events for anything the dashboard needs to see in real-time (tool calls, LLM responses, thinking status). The WebSocket handler in `web/server.py` subscribes to all events and forwards them to connected clients.

### Memory (`core/memory.py`)
`MemoryManager` owns conversation history in an in-memory cache backed by SQLite. It needs `llm_router` and `event_bus` to run auto-compaction — pass them in the constructor, not after the fact.

### Strings (`core/messages.py`)
All user-facing strings and LLM prompts live here as constants. Never hardcode them in engine files.

### Intent keywords (`tools/intent_keywords.py`)
The keyword fallback dict for tool selection lives here, separate from `ToolRegistry` logic. Add or edit keywords only in this file.

## Key conventions

- All tool functions are `async` and end with `**kwargs` to absorb unknown params.
- `_brain` is always the last positional-style kwarg; tools pull their dependencies from `_brain.tool_registry`.
- `ToolRegistry` is the dependency container for tools — not module-level globals.
- The `conftest.py` fixtures wire everything with mocks; use them instead of instantiating classes directly in tests.
- `pytest-asyncio` is configured in `auto` mode — no need to mark individual async tests.
