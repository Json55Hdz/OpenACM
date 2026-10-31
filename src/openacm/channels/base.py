"""
Abstract base class for all messaging channels.
"""

import asyncio
import functools
from abc import ABC, abstractmethod
from typing import Any

from openacm.utils.text import MESSAGE_GAP_SECONDS, MESSAGE_SPLIT_MARKER, split_message_parts


class BaseChannel(ABC):
    """Base class for all messaging channels."""

    # Subclasses must create this in __init__:
    #   self.ready_event = asyncio.Event()
    # and set() it once connected (or on failure, so callers don't hang).
    ready_event: asyncio.Event

    def __init_subclass__(cls, **kwargs):
        """Make send_message of every channel deliver MESSAGE_SPLIT_MARKER parts as separate messages."""
        super().__init_subclass__(**kwargs)
        original = cls.__dict__.get("send_message")
        if original is None or getattr(original, "_splits_parts", False):
            return

        @functools.wraps(original)
        async def send_message(self, target_id, content, **kw):
            if MESSAGE_SPLIT_MARKER not in (content or ""):
                return await original(self, target_id, content, **kw)
            delivered = True
            for i, part in enumerate(split_message_parts(content)):
                if i:
                    await asyncio.sleep(MESSAGE_GAP_SECONDS)
                delivered = await original(self, target_id, part, **kw) and delivered
            return delivered

        send_message._splits_parts = True
        cls.send_message = send_message

    @property
    @abstractmethod
    def name(self) -> str:
        """Channel name (e.g., 'discord', 'telegram')."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the channel is currently connected."""
        ...

    @abstractmethod
    async def start(self):
        """Start the channel (connect to the platform)."""
        ...

    @abstractmethod
    async def stop(self):
        """Stop the channel (disconnect)."""
        ...

    @abstractmethod
    async def send_message(self, target_id: str, content: str, **kwargs) -> bool:
        """Send a message to a specific target (user/channel/group)."""
        ...
