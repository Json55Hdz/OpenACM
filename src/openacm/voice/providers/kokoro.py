"""
Kokoro provider — signals the frontend to use kokoro-js (runs in browser).
No audio is generated server-side; the frontend handles synthesis via WebGPU/WASM.
"""

from openacm.voice.base import TTSProvider, VoiceInfo

_VOICES = [
    VoiceInfo("af_heart",   "Heart",    "en-US", "female"),
    VoiceInfo("af_bella",   "Bella",    "en-US", "female"),
    VoiceInfo("af_nicole",  "Nicole",   "en-US", "female"),
    VoiceInfo("af_sarah",   "Sarah",    "en-US", "female"),
    VoiceInfo("am_adam",    "Adam",     "en-US", "male"),
    VoiceInfo("am_michael", "Michael",  "en-US", "male"),
    VoiceInfo("bf_emma",    "Emma",     "en-GB", "female"),
    VoiceInfo("bm_george",  "George",   "en-GB", "male"),
    VoiceInfo("ef_dora",    "Dora",     "es",    "female"),
    VoiceInfo("em_alex",    "Alex",     "es",    "male"),
]


class KokoroProvider(TTSProvider):
    provider_id = "kokoro"
    display_name = "Kokoro (offline, browser)"

    async def synthesize(self, text: str, voice_id: str) -> bytes:
        return b""

    def list_voices(self) -> list[VoiceInfo]:
        return _VOICES

    def is_available(self) -> bool:
        return True

    def is_browser_side(self) -> bool:
        return True
