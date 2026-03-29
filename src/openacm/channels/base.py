"""
Abstract base class for all messaging channels.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any


class BaseChannel(ABC):
    """Base class for all messaging channels."""

    # Subclasses must create this in __init__:
    #   self.ready_event = asyncio.Event()
    # and set() it once connected (or on failure, so callers don't hang).
    ready_event: asyncio.Event

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
