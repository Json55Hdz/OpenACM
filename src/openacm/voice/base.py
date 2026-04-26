"""
Abstract TTS provider — every implementation must satisfy this contract.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VoiceInfo:
    id: str
    name: str
    language: str
    gender: str = "neutral"
    preview: str = ""


class TTSProvider(ABC):
    """Base class for all TTS providers."""

    provider_id: str = ""
    display_name: str = ""

    @abstractmethod
    async def synthesize(self, text: str, voice_id: str) -> bytes:
        """Return raw audio bytes (MP3 or WAV) for the given text."""

    @abstractmethod
    def list_voices(self) -> list[VoiceInfo]:
        """Return available voices for this provider."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider can be used right now."""

    def requires_api_key(self) -> bool:
        return False

    def is_browser_side(self) -> bool:
        """True if synthesis happens in the browser (no server audio returned)."""
        return False
