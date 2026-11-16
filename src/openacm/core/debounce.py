"""
Message debouncing: several messages sent in a burst are answered once.

People (and customers on WhatsApp) often send a thought as 4 short messages in 3 seconds.
Answering each one separately is noisy and wasteful. The first message of a burst waits a short
"quiet" moment; every message that arrives in the meantime is folded into it, and the whole burst
goes to the model as ONE message. A burst is capped (``max_wait_s``) so a chatty sender is
still answered.

Only the first message of a burst (the "leader") gets a reply; the others return None.

Tune with OPENACM_MESSAGE_DEBOUNCE (quiet seconds; 0 turns it off, default 1.5) and
OPENACM_MESSAGE_DEBOUNCE_MAX (default 6).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Hashable

DEFAULT_QUIET_S = 1.5
DEFAULT_MAX_WAIT_S = 6.0


def _env_seconds(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except ValueError:
        return default


@dataclass
class _Burst:
    texts: list[str]
    attachments: list[Any] = field(default_factory=list)
    wakeup: asyncio.Event = field(default_factory=asyncio.Event)


class MessageDebouncer:
    def __init__(self) -> None:
        self._bursts: dict[Hashable, _Burst] = {}

    @staticmethod
    def quiet_s() -> float:
        return _env_seconds("OPENACM_MESSAGE_DEBOUNCE", DEFAULT_QUIET_S)

    @staticmethod
    def max_wait_s() -> float:
        return _env_seconds("OPENACM_MESSAGE_DEBOUNCE_MAX", DEFAULT_MAX_WAIT_S)

    async def collect(
        self, key: Hashable, text: str, attachments: list[Any] | None = None
    ) -> tuple[str, list[Any] | None] | None:
        """The merged (text, attachments) for the leader of a burst, or None for a follower
        whose message was folded into the leader's."""
        quiet = self.quiet_s()
        if quiet <= 0:
            return text, attachments

        burst = self._bursts.get(key)
        if burst is not None:  # follower: add to the burst and wake the leader to extend the wait
            burst.texts.append(text)
            if attachments:
                burst.attachments.extend(attachments)
            burst.wakeup.set()
            return None

        burst = _Burst(texts=[text], attachments=list(attachments or []))
        self._bursts[key] = burst
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.max_wait_s()
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                burst.wakeup.clear()
                try:
                    await asyncio.wait_for(burst.wakeup.wait(), timeout=min(quiet, remaining))
                except asyncio.TimeoutError:
                    break  # quiet for long enough
        finally:
            # From here on a new message starts a new burst
            if self._bursts.get(key) is burst:
                del self._bursts[key]
        return "\n".join(t for t in burst.texts if t), (burst.attachments or None)
