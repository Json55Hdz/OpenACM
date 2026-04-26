"""
Voice API routes — TTS synthesis, config, and provider management.
"""

import json
import re

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from openacm.web.state import _state

log = structlog.get_logger()

_tts_router = None


def register_routes(app: FastAPI, tts_router=None):
    global _tts_router
    _tts_router = tts_router

    # ── Assistant profile (name + gender) ─────────────────────────────────────

    @app.get("/api/config/assistant")
    async def get_assistant_profile():
        cfg = await _get_settings()
        name = ""
        if _state.config:
            name = getattr(_state.config.assistant, "name", "") or ""
        return {"name": name or "OpenACM", "gender": cfg.get("gender", "neutral")}

    @app.patch("/api/config/assistant")
    async def update_assistant_profile(body: dict):
        import yaml as _yaml
        from openacm.core.config import _find_project_root
        new_name = (body.get("name") or "").strip()[:100] or "OpenACM"
        new_gender = body.get("gender", "neutral")
        if new_gender not in ("male", "female", "neutral"):
            new_gender = "neutral"

        # Update in-memory config
        if _state.config:
            _state.config.assistant.name = new_name
        if _state.brain:
            _state.brain.config.name = new_name

        # Persist name to local.yaml
        root = _find_project_root()
        config_file = root / "config" / "local.yaml"
        data: dict = {}
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = _yaml.safe_load(f) or {}
            except Exception:
                pass
        data.setdefault("A", {})["name"] = new_name
        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                _yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            raise HTTPException(500, f"Failed to save config: {e}")

        # Persist gender + auto-voice to voice.config in DB
        _VOICE_FOR_GENDER        = {"female": "af_heart",          "male": "am_adam"}
        _SERVER_TTS_FOR_GENDER   = {"female": "es-MX-DaliaNeural", "male": "es-MX-JorgeNeural"}
        current = await _get_settings()
        current["gender"] = new_gender
        if new_gender in _VOICE_FOR_GENDER:
            current["tts_voice"] = _VOICE_FOR_GENDER[new_gender]
        if new_gender in _SERVER_TTS_FOR_GENDER:
            current["server_tts_voice"] = _SERVER_TTS_FOR_GENDER[new_gender]
        elif "server_tts_voice" not in current:
            current["server_tts_voice"] = "es-MX-DaliaNeural"
        await _save_settings(current)
        if _tts_router:
            _tts_router.invalidate_cache()
        # Apply to running daemon immediately
        daemon = getattr(_state, "voice_daemon", None)
        if daemon:
            daemon._tts_voice = current["server_tts_voice"]

        return {"name": new_name, "gender": new_gender, "tts_voice": current.get("tts_voice", "af_heart"),
                "server_tts_voice": current.get("server_tts_voice", "es-MX-DaliaNeural")}

    # ── Config ────────────────────────────────────────────────────────────────

    @app.get("/api/voice/config")
    async def get_voice_config():
        cfg = await _get_settings()
        assistant_name = ""
        if _state.config:
            assistant_name = getattr(_state.config.assistant, "name", "") or ""
        return {**cfg, "assistant_name": assistant_name}

    @app.patch("/api/voice/config")
    async def update_voice_config(body: dict):
        allowed = {"tts_provider", "tts_voice", "stt_provider", "voice_enabled", "voice_language", "api_key", "engine_mode", "mic_device", "server_tts_voice"}
        current = await _get_settings()
        for k, v in body.items():
            if k in allowed:
                current[k] = v
        await _save_settings(current)
        if _tts_router:
            _tts_router.invalidate_cache()
        return current

    # ── Providers & voices ────────────────────────────────────────────────────

    @app.get("/api/voice/providers")
    async def get_voice_providers():
        if not _tts_router:
            return []
        return _tts_router.list_providers()

    @app.get("/api/voice/voices")
    async def get_voice_voices():
        if not _tts_router:
            return []
        return await _tts_router.list_voices()

    # ── Voice Daemon — server-side mic/STT/TTS ───────────────────────────────

    @app.get("/api/voice/daemon/status")
    async def get_daemon_status():
        daemon = getattr(_state, "voice_daemon", None)
        from openacm.voice.voice_daemon import VoiceDaemon
        deps = VoiceDaemon.check_deps()
        if not daemon:
            return {
                "is_running":           False,
                "engine_available":     False,
                "current_state":        "unavailable",
                "last_error":           "Voice daemon not initialized",
                "utterances_processed": 0,
                "deps":                 deps,
            }
        return {
            "is_running":           daemon.is_running,
            "engine_available":     daemon.engine_available,
            "current_state":        daemon.current_state,
            "last_error":           daemon.last_error,
            "utterances_processed": daemon.utterances_processed,
            "deps":                 deps,
        }

    @app.post("/api/voice/daemon/start")
    async def start_daemon(body: dict = {}):
        import importlib as _importlib
        _importlib.invalidate_caches()  # pick up packages installed at runtime
        print(f"[voice/start] POST /api/voice/daemon/start — body={body!r}", flush=True)
        daemon = getattr(_state, "voice_daemon", None)
        if not daemon:
            print("[voice/start] ERROR: daemon not in _state", flush=True)
            log.warning("voice_daemon_start: daemon not initialized")
            raise HTTPException(503, "Voice daemon not initialized")
        # mic_device can be passed in body or read from saved config
        mic_device = body.get("mic_device")
        if mic_device is None:
            cfg = await _get_settings()
            raw = cfg.get("mic_device")
            print(f"[voice/start] mic_device from config: raw={raw!r}", flush=True)
            if raw not in (None, "", "default"):
                try:
                    mic_device = int(raw)
                except (ValueError, TypeError):
                    mic_device = raw
        deps = daemon.check_deps()
        print(f"[voice/start] deps={deps} engine_available={daemon.engine_available} device={mic_device!r}", flush=True)
        log.info("voice_daemon_start: deps check", deps=deps, engine_available=daemon.engine_available, device=mic_device)
        # Apply server TTS voice and wake word from config before starting
        cfg_for_tts = await _get_settings()
        daemon._tts_voice = cfg_for_tts.get("server_tts_voice", "es-MX-DaliaNeural")
        if _state.config:
            daemon._wake_word = getattr(_state.config.assistant, "name", "") or "OpenACM"
        print(f"[voice/start] wake_word={daemon._wake_word!r} server_tts_voice={daemon._tts_voice!r}", flush=True)
        print(f"[voice/start] server_tts_voice={daemon._tts_voice!r}", flush=True)
        print(f"[voice/start] calling daemon.start(device={mic_device!r}) ...", flush=True)
        error = await daemon.start(device=mic_device)
        if error:
            print(f"[voice/start] daemon.start() returned error: {error!r}", flush=True)
            log.warning("voice_daemon_start: start() returned error", error=error)
            raise HTTPException(400, error)
        print(f"[voice/start] daemon.start() OK — is_running={daemon.is_running} current_state={daemon.current_state!r}", flush=True)
        log.info("voice_daemon_start: daemon started OK", is_running=daemon.is_running)
        return {"status": "started"}

    @app.post("/api/voice/daemon/install")
    async def install_voice_deps():
        """Stream pip install output for optional voice dependencies."""
        import sys as _sys
        import asyncio as _asyncio
        from fastapi.responses import StreamingResponse as _SSE

        async def _generate():
            try:
                proc = await _asyncio.create_subprocess_exec(
                    _sys.executable, "-m", "pip", "install",
                    "sounddevice", "faster-whisper", "numpy", "edge-tts",
                    "--progress-bar", "off",
                    stdout=_asyncio.subprocess.PIPE,
                    stderr=_asyncio.subprocess.STDOUT,
                )
                async for raw in proc.stdout:  # type: ignore[union-attr]
                    line = raw.decode(errors="replace").rstrip()
                    if line:
                        yield f"data: {line}\n\n"
                await proc.wait()
                if proc.returncode == 0:
                    yield "data: __DONE__\n\n"
                else:
                    yield f"data: __ERROR__ exit code {proc.returncode}\n\n"
            except Exception as exc:
                yield f"data: __ERROR__ {exc}\n\n"

        return _SSE(
            _generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/voice/daemon/stop")
    async def stop_daemon():
        daemon = getattr(_state, "voice_daemon", None)
        if not daemon:
            raise HTTPException(503, "Voice daemon not initialized")
        await daemon.stop()
        return {"status": "stopped"}

    @app.get("/api/voice/server-tts/voices")
    async def get_server_tts_voices():
        """Return curated list of edge-tts neural voices for server-side TTS."""
        return SERVER_TTS_VOICES

    @app.get("/api/voice/devices")
    async def get_audio_devices():
        """List available audio input devices on the server machine."""
        try:
            import sounddevice as _sd
            devices = _sd.query_devices()
            default_in = _sd.default.device[0] if isinstance(_sd.default.device, (list, tuple)) else _sd.default.device
            return [
                {
                    "index":    i,
                    "name":     d["name"],
                    "channels": int(d["max_input_channels"]),
                    "default":  i == default_in,
                }
                for i, d in enumerate(devices)
                if int(d["max_input_channels"]) > 0
            ]
        except ImportError:
            return []
        except Exception:
            return []

    @app.get("/api/voice/model/status")
    async def get_model_status():
        """Check availability of server-side voice models and configured TTS provider."""
        from openacm.voice.voice_daemon import VoiceDaemon
        import os as _os
        deps = VoiceDaemon.check_deps()

        # Check if faster-whisper "base" model is already in cache
        whisper_cached = False
        if deps["faster_whisper"]:
            try:
                hf_cache = _os.path.expanduser("~/.cache/huggingface/hub")
                if _os.path.exists(hf_cache):
                    whisper_cached = any(
                        "whisper" in d.lower() and ("base" in d.lower() or "systran" in d.lower())
                        for d in _os.listdir(hf_cache)
                    )
            except Exception:
                pass

        cfg = await _get_settings()
        return {
            "stt": {
                "provider":   "faster_whisper",
                "available":  deps["faster_whisper"],
                "model":      "base",
                "downloaded": whisper_cached,
            },
            "mic":        {"available": deps["sounddevice"]},
            "server_tts": {"available": deps["edge_tts"]},
            "tts_provider": cfg.get("tts_provider", "kokoro"),
            "engine_mode":  cfg.get("engine_mode", "browser"),
        }

    # ── TTS synthesis ─────────────────────────────────────────────────────────

    class TTSRequest(BaseModel):
        text: str
        voice_id: str = ""

    @app.post("/api/voice/tts")
    async def synthesize(req: TTSRequest):
        if not _tts_router:
            raise HTTPException(503, "TTS router not available")

        text = _clean_for_tts(req.text)
        if not text.strip():
            return Response(b"", media_type="audio/mpeg")

        try:
            audio, content_type, is_browser = await _tts_router.synthesize(text)
            if is_browser:
                return {"browser_side": True, "text": text}
            return Response(audio, media_type=content_type)
        except Exception as e:
            log.error("TTS synthesis failed", error=str(e))
            raise HTTPException(500, f"TTS synthesis failed: {e}")


SERVER_TTS_VOICES = [
    {"id": "es-MX-DaliaNeural",   "label": "Dalia — ES-MX · Mujer",    "lang": "es", "gender": "female"},
    {"id": "es-MX-JorgeNeural",   "label": "Jorge — ES-MX · Hombre",   "lang": "es", "gender": "male"},
    {"id": "es-ES-ElviraNeural",  "label": "Elvira — ES-ES · Mujer",   "lang": "es", "gender": "female"},
    {"id": "es-ES-AlvaroNeural",  "label": "Álvaro — ES-ES · Hombre",  "lang": "es", "gender": "male"},
    {"id": "en-US-AriaNeural",    "label": "Aria — EN-US · Female",    "lang": "en", "gender": "female"},
    {"id": "en-US-GuyNeural",     "label": "Guy — EN-US · Male",       "lang": "en", "gender": "male"},
    {"id": "en-US-JennyNeural",   "label": "Jenny — EN-US · Female",   "lang": "en", "gender": "female"},
    {"id": "en-GB-SoniaNeural",   "label": "Sonia — EN-GB · Female",   "lang": "en", "gender": "female"},
    {"id": "en-GB-RyanNeural",    "label": "Ryan — EN-GB · Male",      "lang": "en", "gender": "male"},
]


async def _get_settings() -> dict:
    defaults = {
        "tts_provider": "kokoro",
        "tts_voice": "af_heart",
        "stt_provider": "webspeech",
        "voice_enabled": "false",
        "voice_language": "en-US",
        "api_key": "",
        "server_tts_voice": "es-MX-DaliaNeural",
    }
    if not _state.database:
        return defaults
    raw = await _state.database.get_setting("voice.config")
    if raw:
        try:
            stored = json.loads(raw)
            defaults.update(stored)
        except Exception:
            pass
    return defaults


async def _save_settings(cfg: dict):
    if not _state.database:
        return
    safe = {k: v for k, v in cfg.items() if k != "api_key" or v}
    await _state.database.set_setting("voice.config", json.dumps(safe))


def _clean_for_tts(text: str) -> str:
    """Strip markdown and code blocks before sending to TTS."""
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'[*_#~>]+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
