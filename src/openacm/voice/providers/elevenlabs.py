"""
ElevenLabs TTS provider.
Requires an ElevenLabs API key.
"""

import os
from openacm.voice.base import TTSProvider, VoiceInfo

_VOICES = [
    VoiceInfo("21m00Tcm4TlvDq8ikWAM", "Rachel",  "en", "female"),
    VoiceInfo("AZnzlk1XvdvUeBnXmlld", "Domi",    "en", "female"),
    VoiceInfo("EXAVITQu4vr4xnSDxMaL", "Bella",   "en", "female"),
    VoiceInfo("ErXwobaYiN019PkySvjV", "Antoni",  "en", "male"),
    VoiceInfo("MF3mGyEYCl7XYWbV9V6O", "Elli",    "en", "female"),
    VoiceInfo("TxGEqnHWrfWFTfGW9XjX", "Josh",    "en", "male"),
    VoiceInfo("VR6AewLTigWG4xSOukaG", "Arnold",  "en", "male"),
    VoiceInfo("pNInz6obpgDQGcFmaJgB", "Adam",    "en", "male"),
    VoiceInfo("yoZ06aMxZJJ28mfd3POQ", "Sam",     "en", "male"),
]


class ElevenLabsProvider(TTSProvider):
    provider_id = "elevenlabs"
    display_name = "ElevenLabs"

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")

    async def synthesize(self, text: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM") -> bytes:
        import httpx
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {"xi-api-key": self._api_key, "Content-Type": "application/json"}
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r.content

    def list_voices(self) -> list[VoiceInfo]:
        return _VOICES

    def is_available(self) -> bool:
        return bool(self._api_key)

    def requires_api_key(self) -> bool:
        return True
