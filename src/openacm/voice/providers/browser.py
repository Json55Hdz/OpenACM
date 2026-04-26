"""
Browser SpeechSynthesis provider — synthesis happens client-side.
Server returns an empty 200 as a signal; the frontend does the actual speaking.
"""

from openacm.voice.base import TTSProvider, VoiceInfo


class BrowserProvider(TTSProvider):
    provider_id = "browser"
    display_name = "Browser (built-in)"

    async def synthesize(self, text: str, voice_id: str) -> bytes:
        return b""

    def list_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(id="default", name="System Default", language="auto"),
        ]

    def is_available(self) -> bool:
        return True

    def is_browser_side(self) -> bool:
        return True
