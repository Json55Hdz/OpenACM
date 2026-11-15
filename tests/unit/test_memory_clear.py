"""/clear and /reset must really forget the conversation, not just the cached copy."""

import pytest
import pytest_asyncio

from openacm.core.memory import MemoryManager


@pytest_asyncio.fixture
async def memory(db, app_config):
    return MemoryManager(database=db, config=app_config.assistant)


async def test_clear_removes_history_for_good(memory):
    await memory.add_message("u1", "c1", "user", "hola, me llamo Ana")
    await memory.add_message("u1", "c1", "assistant", "hola Ana")
    assert any("Ana" in str(m.get("content")) for m in await memory.get_messages("u1", "c1"))

    await memory.clear("u1", "c1")

    after = await memory.get_messages("u1", "c1")
    assert not any("Ana" in str(m.get("content")) for m in after)


async def test_clear_leaves_other_conversations_alone(memory):
    await memory.add_message("u1", "c1", "user", "uno")
    await memory.add_message("u2", "c2", "user", "dos")
    await memory.clear("u1", "c1")
    assert any("dos" in str(m.get("content")) for m in await memory.get_messages("u2", "c2"))


async def test_clear_resets_compaction_state(memory):
    key = memory._key("u1", "c1")
    memory._needs_compact.add(key)
    memory._compact_baseline[key] = 999
    await memory.clear("u1", "c1")
    assert key not in memory._needs_compact and key not in memory._compact_baseline
