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

    def conversation_ids(self, target_id: str) -> tuple[str, str] | None:
        """(user_id, channel_id) of the conversation the assistant has with this target, or None
        when the channel cannot tell. Channels override it with their own convention."""
        return None

    async def notify(self, target_id: str, content: str, **kwargs) -> bool:
        """Send something the user did not ask for just now (a plugin's notice, a scheduled
        message) and record it in their conversation, so that when they answer it the assistant
        knows what they are talking about. Use this instead of send_message for such messages."""
        sent = await self.send_message(target_id, content, **kwargs)
        ids = self.conversation_ids(str(target_id)) if sent else None
        memory = getattr(getattr(self, "brain", None), "memory", None)
        if ids and memory is not None:
            try:
                await memory.note_outgoing(ids[0], ids[1], content)
            except Exception:  # noqa: BLE001 — the message was delivered; never fail the sender
                pass
        return sent
