"""
TTSRouter — picks the right provider based on the active config.
Providers are instantiated lazily and cached.
"""

import json
import structlog
from openacm.voice.base import TTSProvider, VoiceInfo
from openacm.voice.providers import BrowserProvider, KokoroProvider, OpenAITTSProvider, ElevenLabsProvider

log = structlog.get_logger()

_ALL_PROVIDERS: dict[str, type[TTSProvider]] = {
    "browser":    BrowserProvider,
    "kokoro":     KokoroProvider,
    "openai":     OpenAITTSProvider,
    "elevenlabs": ElevenLabsProvider,
}

_PROVIDER_META = [
    {
        "id": "kokoro",
        "name": "Kokoro (offline)",
        "description": "High-quality neural TTS running 100% in your browser. ~80MB download, no API key needed.",
        "requires_key": False,
        "offline": True,
        "languages": ["en", "es"],
    },
    {
        "id": "browser",
        "name": "Browser built-in",
        "description": "Uses your OS voices via Web Speech API. Zero setup, always available.",
        "requires_key": False,
        "offline": True,
        "languages": ["any"],
    },
    {
        "id": "openai",
        "name": "OpenAI TTS",
        "description": "Premium neural voices via OpenAI API. Requires an API key.",
        "requires_key": True,
        "offline": False,
        "languages": ["en", "es", "multilingual"],
    },
    {
        "id": "elevenlabs",
        "name": "ElevenLabs",
        "description": "Ultra-realistic voices. Requires an ElevenLabs API key.",
        "requires_key": True,
        "offline": False,
        "languages": ["en", "es", "multilingual"],
    },
]


class TTSRouter:
    def __init__(self, database=None):
        self._db = database
        self._cache: dict[str, TTSProvider] = {}

    async def _get_voice_settings(self) -> dict:
        defaults = {
            "tts_provider": "kokoro",
            "tts_voice": "af_heart",
            "stt_provider": "webspeech",
            "voice_enabled": "false",
            "voice_language": "en-US",
        }
        if not self._db:
            return defaults
        raw = await self._db.get_setting("voice.config")
        if raw:
            try:
                stored = json.loads(raw)
                defaults.update(stored)
            except Exception:
                pass
        return defaults

    async def get_active_provider(self) -> TTSProvider:
        cfg = await self._get_voice_settings()
        provider_id = cfg.get("tts_provider", "kokoro")
        return self._build_provider(provider_id, cfg)

    def _build_provider(self, provider_id: str, cfg: dict) -> TTSProvider:
        if provider_id in self._cache:
            return self._cache[provider_id]

        cls = _ALL_PROVIDERS.get(provider_id, KokoroProvider)
        api_key = cfg.get("api_key", "")
        try:
            if provider_id in ("openai", "elevenlabs"):
                instance = cls(api_key=api_key)
            else:
                instance = cls()
        except Exception:
            instance = BrowserProvider()

        self._cache[provider_id] = instance
        return instance

    def invalidate_cache(self):
        self._cache.clear()

    async def synthesize(self, text: str) -> tuple[bytes, str, bool]:
        """Returns (audio_bytes, content_type, is_browser_side)."""
        cfg = await self._get_voice_settings()
        provider = await self.get_active_provider()
        voice_id = cfg.get("tts_voice", "af_heart")

        if provider.is_browser_side():
            return b"", "audio/mpeg", True

        audio = await provider.synthesize(text, voice_id)
        return audio, "audio/mpeg", False

    def list_providers(self) -> list[dict]:
        return _PROVIDER_META

    async def list_voices(self) -> list[dict]:
        provider = await self.get_active_provider()
        return [
            {"id": v.id, "name": v.name, "language": v.language, "gender": v.gender}
            for v in provider.list_voices()
        ]
