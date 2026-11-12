"""Cancellation of a running turn: Brain.process_message cancel/queue behaviour."""
import asyncio
from types import SimpleNamespace

from openacm.core.brain import Brain
from openacm.core.messages import (
    MSG_CANCEL_PENDING,
    MSG_CANCELLED,
    MSG_NOTHING_TO_CANCEL,
    MSG_STEER_ACK,
)


class _Bus:
    async def emit(self, *a, **k):
        pass


def _brain(run):
    b = Brain.__new__(Brain)
    b._channel_tasks, b._channel_queue, b._cancel_flags = {}, {}, {}
    b._channel_inbox, b._inbox_meta = {}, {}
    b.event_bus = _Bus()
    b._run = run
    return b


async def test_cancel_with_nothing_running_does_not_reach_the_llm():
    calls = []

    async def run(content, *a):
        calls.append(content)
        return "ok"

    b = _brain(run)
    assert await b.process_message("cancelar", "u", "web", "web") == MSG_NOTHING_TO_CANCEL
    assert calls == []


async def test_cancel_stops_a_running_turn_and_frees_the_channel():
    started = asyncio.Event()

    async def run(content, *a):
        started.set()
        await asyncio.sleep(30)
        return "never"

    b = _brain(run)
    first = asyncio.create_task(b.process_message("do it", "u", "web", "web"))
    await started.wait()
    assert await b.process_message("cancelar", "u", "web", "web") == MSG_CANCELLED
    assert await first == MSG_CANCELLED
    assert "web:web" not in b._channel_tasks


async def test_run_that_swallows_cancel_keeps_its_flag_when_user_sends_more():
    """A run that ignores the hard cancel must still see its cancel flag, even after the
    user sends another message (which used to clear the flag and leave a zombie run)."""
    started, seen = asyncio.Event(), {}

    async def stubborn(content, user_id, channel_id, channel_type, *a):
        flag = b._cancel_flags[f"{channel_type}:{channel_id}"]
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass  # swallows the hard cancel, like a tool running in a thread would
        await asyncio.sleep(0.2)
        seen["flag_still_set"] = flag.is_set()
        return "late"

    b = _brain(stubborn)
    b._CANCEL_GRACE_S = 0.05
    first = asyncio.create_task(b.process_message("do it", "u", "web", "web"))
    await started.wait()
    await b.process_message("cancelar", "u", "web", "web")
    # still running -> a new message waits for it, it is not started beside the zombie
    assert await b.process_message("otra cosa", "u", "web", "web") == MSG_STEER_ACK
    assert await first == "late"
    assert seen["flag_still_set"] is True  # the new message did not clear the old run's flag
    # the queued message now runs; a cancel still finds and stops it
    # (this fake run swallows the hard cancel too, so the answer is "cancelling")
    await asyncio.sleep(0.05)
    assert await b.process_message("cancelar", "u", "web", "web") == MSG_CANCEL_PENDING
    assert b._cancel_flags["web:web"].is_set()
    await asyncio.gather(*b._channel_tasks.values(), return_exceptions=True)


async def test_message_sent_mid_run_is_handed_to_the_running_loop():
    """A message sent while a run works lands in the inbox the tool loop reads between
    steps (same chat only), instead of waiting for the whole run to finish."""
    started, release = asyncio.Event(), asyncio.Event()
    got = {}

    async def run(content, user_id, channel_id, channel_type, *a):
        started.set()
        await release.wait()
        got.setdefault(user_id, b._take_inbox(f"{channel_type}:{channel_id}", user_id, channel_id))
        got.setdefault("order", []).append(content)
        return "done"

    b = _brain(run)
    first = asyncio.create_task(b.process_message("go", "chatA", "web", "web"))
    await started.wait()
    assert await b.process_message("mejor haz X", "chatA", "web", "web") == MSG_STEER_ACK
    assert await b.process_message("soy otro chat", "chatB", "web", "web") == MSG_STEER_ACK
    release.set()
    assert await first == "done"
    assert got["chatA"] == ["mejor haz X"]  # only this chat's message, read mid-run
    # the other chat's message was not injected into chatA's run: it runs as its own turn
    await asyncio.gather(*b._channel_tasks.values(), return_exceptions=True)
    assert got["order"] == ["go", "soy otro chat"]


async def test_unread_mid_run_message_becomes_the_next_turn():
    started, release, seen = asyncio.Event(), asyncio.Event(), []

    async def run(content, *a):
        seen.append(content)
        started.set()
        await release.wait()
        return "done"

    b = _brain(run)
    first = asyncio.create_task(b.process_message("go", "u", "web", "web"))
    await started.wait()
    await b.process_message("uno", "u", "web", "web")
    await b.process_message("dos", "u", "web", "web")
    release.set()
    await first
    await asyncio.gather(*b._channel_tasks.values(), return_exceptions=True)
    assert seen == ["go", "uno\n\ndos"]  # nothing lost, both delivered together
