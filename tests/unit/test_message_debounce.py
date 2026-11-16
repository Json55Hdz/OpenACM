"""A burst of messages is answered once."""
import asyncio

import pytest

from openacm.core.debounce import MessageDebouncer


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setenv("OPENACM_MESSAGE_DEBOUNCE", "0.05")
    monkeypatch.setenv("OPENACM_MESSAGE_DEBOUNCE_MAX", "0.5")


async def test_a_burst_becomes_one_message_for_the_first_sender():
    d = MessageDebouncer()
    results = await asyncio.gather(
        d.collect("k", "hola"),
        _later(d, 0.01, "como"),
        _later(d, 0.02, "estas"),
    )
    assert results[0] == ("hola\ncomo\nestas", None)
    assert results[1] is None and results[2] is None


async def _later(d, delay, text):
    await asyncio.sleep(delay)
    return await d.collect("k", text)


async def test_a_message_after_the_quiet_moment_starts_a_new_burst():
    d = MessageDebouncer()
    first = await d.collect("k", "uno")
    second = await d.collect("k", "dos")
    assert first == ("uno", None) and second == ("dos", None)


async def test_different_conversations_do_not_mix():
    d = MessageDebouncer()
    a, b = await asyncio.gather(d.collect("a", "x"), d.collect("b", "y"))
    assert a == ("x", None) and b == ("y", None)


async def test_attachments_are_merged():
    d = MessageDebouncer()
    lead, follow = await asyncio.gather(d.collect("k", "mira", ["a.png"]), _later_att(d))
    assert lead == ("mira\nesto", ["a.png", "b.png"]) and follow is None


async def _later_att(d):
    await asyncio.sleep(0.01)
    return await d.collect("k", "esto", ["b.png"])


async def test_a_constant_stream_is_still_answered_at_the_max_wait(monkeypatch):
    monkeypatch.setenv("OPENACM_MESSAGE_DEBOUNCE", "0.2")
    monkeypatch.setenv("OPENACM_MESSAGE_DEBOUNCE_MAX", "0.3")
    d = MessageDebouncer()
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    leader = asyncio.create_task(d.collect("k", "m"))

    async def chatter():  # a message every 0.1 s keeps resetting the quiet timer
        for i in range(10):
            await asyncio.sleep(0.1)
            asyncio.create_task(d.collect("k", f"m{i}"))

    asyncio.create_task(chatter())
    await leader
    assert loop.time() - t0 < 0.6  # answered at the cap, not after the chatter ends


async def test_zero_turns_it_off(monkeypatch):
    monkeypatch.setenv("OPENACM_MESSAGE_DEBOUNCE", "0")
    d = MessageDebouncer()
    assert await d.collect("k", "a") == ("a", None)
    assert await d.collect("k", "b") == ("b", None)
