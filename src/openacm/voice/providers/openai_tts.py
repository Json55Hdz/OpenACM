"""
OpenAI TTS provider — uses the OpenAI audio/speech endpoint.
Requires OPENAI_API_KEY in the environment or passed via settings.
"""

import os
from openacm.voice.base import TTSProvider, VoiceInfo

_VOICES = [
    VoiceInfo("alloy",   "Alloy",   "en", "neutral"),
    VoiceInfo("echo",    "Echo",    "en", "male"),
    VoiceInfo("fable",   "Fable",   "en", "male"),
    VoiceInfo("onyx",    "Onyx",    "en", "male"),
    VoiceInfo("nova",    "Nova",    "en", "female"),
    VoiceInfo("shimmer", "Shimmer", "en", "female"),
]


class OpenAITTSProvider(TTSProvider):
    provider_id = "openai"
    display_name = "OpenAI TTS"

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    async def synthesize(self, text: str, voice_id: str = "nova") -> bytes:
        import httpx
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": "tts-1", "input": text, "voice": voice_id, "response_format": "mp3"}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post("https://api.openai.com/v1/audio/speech", json=payload, headers=headers)
            r.raise_for_status()
            return r.content

    def list_voices(self) -> list[VoiceInfo]:
        return _VOICES

    def is_available(self) -> bool:
        return bool(self._api_key)

    def requires_api_key(self) -> bool:
        return True
