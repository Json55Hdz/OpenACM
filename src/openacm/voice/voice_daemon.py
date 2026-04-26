"""
VoiceDaemon — server-side always-on voice processing pipeline.

Audio pipeline: sounddevice mic → energy VAD → faster-whisper STT →
                event bus → brain → pyttsx3/espeak server TTS.

Optional dependencies (install separately):
  pip install sounddevice faster-whisper numpy
  pip install pyttsx3   # optional, for server-side TTS playback
"""
from __future__ import annotations

import asyncio
import struct
import threading
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Audio constants ────────────────────────────────────────────────────────────

SAMPLE_RATE    = 16_000          # Hz — Whisper native rate
CHUNK_DURATION = 0.5             # seconds per read
CHUNK_SAMPLES  = int(SAMPLE_RATE * CHUNK_DURATION)
SILENCE_CHUNKS = 2               # chunks of silence to end an utterance (~1.0 s)
MAX_CHUNKS     = 40              # max utterance length in chunks (~20 s)
VAD_THRESHOLD  = 600             # RMS energy threshold (0–32 767)


def _log(msg: str) -> None:
    """Print to stdout immediately — always visible even from daemon threads."""
    print(f"[VoiceDaemon] {msg}", flush=True)


class VoiceDaemon:
    """
    Server-side always-on voice daemon.

    Lifecycle::

        daemon = VoiceDaemon(database=db, event_bus=bus, brain=brain)
        await daemon.start()   # begin listening
        await daemon.stop()    # stop listening
    """

    def __init__(self, database=None, event_bus=None, brain=None):
        self._db        = database
        self._event_bus = event_bus
        self._brain     = brain

        self._running    = False
        self._task: Optional[asyncio.Task] = None
        self._stop_evt   = threading.Event()
        self._q: asyncio.Queue[bytes | None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._device: int | str | None = None   # sounddevice device index or name

        # Public status fields (read by /api/voice/daemon/status)
        self.is_running:           bool = False
        self.current_state:        str  = "idle"
        self.last_error:           str  = ""
        self.utterances_processed: int  = 0
        self._tts_voice:           str  = "es-MX-DaliaNeural"  # set by start()

    # ── Dependency check ──────────────────────────────────────────────────────

    @staticmethod
    def check_deps() -> dict[str, bool]:
        import importlib
        importlib.invalidate_caches()
        result: dict[str, bool] = {
            "sounddevice":    False,
            "faster_whisper": False,
            "numpy":          False,
            "edge_tts":       False,
        }
        for pkg, key in [
            ("sounddevice",    "sounddevice"),
            ("faster_whisper", "faster_whisper"),
            ("numpy",          "numpy"),
            ("edge_tts",       "edge_tts"),
        ]:
            try:
                __import__(pkg)
                result[key] = True
            except Exception:
                # Catches ImportError AND OSError (e.g. libportaudio missing on Linux)
                pass
        return result

    @property
    def engine_available(self) -> bool:
        deps = self.check_deps()
        return deps["sounddevice"] and deps["faster_whisper"] and deps["numpy"]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, device: int | str | None = None) -> str:
        """Start the daemon. Returns '' on success, error message on failure."""
        _log(f"start() called — device={device!r}, already_running={self._running}")
        if self._running:
            _log("start() skipped — already running")
            return ""
        if not self.engine_available:
            missing = [k for k, v in self.check_deps().items() if not v and k != "pyttsx3"]
            self.last_error = f"Missing dependencies: pip install {' '.join(missing)}"
            _log(f"start() aborted — missing deps: {missing}")
            return self.last_error

        self._device   = device
        self._running  = True
        self.is_running = True
        self.last_error = ""
        self._stop_evt.clear()
        self._loop = asyncio.get_event_loop()
        self._q    = asyncio.Queue(maxsize=200)
        self._task = asyncio.create_task(self._run(), name="voice_daemon")
        _log(f"start() — task created, loop={self._loop!r}")
        return ""

    async def stop(self) -> None:
        _log("stop() called")
        self._running   = False
        self.is_running = False
        self.current_state = "idle"
        self._stop_evt.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _log("stop() complete")

    # ── Main async pipeline ───────────────────────────────────────────────────

    async def _run(self) -> None:
        _log("_run() task started — about to load Whisper in background thread")
        log.info("VoiceDaemon _run() started")

        # Load Whisper in thread so it doesn't block the event loop
        try:
            _log("_run() calling asyncio.to_thread(_load_whisper) ...")
            whisper = await asyncio.to_thread(self._load_whisper)
            _log("_run() Whisper model loaded OK")
            log.info("VoiceDaemon Whisper model loaded OK")
        except Exception as exc:
            self.last_error = f"Whisper load failed: {exc}"
            _log(f"_run() Whisper load FAILED: {exc}")
            log.error("VoiceDaemon Whisper load failed", error=str(exc))
            self._running   = False
            self.is_running = False
            return

        # Start mic capture in a background thread
        _log(f"_run() starting mic capture thread (device={self._device!r})")
        threading.Thread(target=self._capture_loop, daemon=True, name="voice_mic").start()

        buf: list[bytes] = []
        silence_count    = 0
        in_speech        = False

        _log("_run() entering VAD loop — emitting state=listening")
        await self._emit_state("listening")

        try:
            while self._running:
                try:
                    chunk = await asyncio.wait_for(self._q.get(), timeout=0.5)  # type: ignore[union-attr]
                except asyncio.TimeoutError:
                    if in_speech:
                        silence_count += 1
                    if in_speech and silence_count >= SILENCE_CHUNKS:
                        _log(f"_run() silence timeout flush — buf={len(buf)} chunks")
                        await self._flush(whisper, buf)
                        buf.clear()
                        silence_count = 0
                        in_speech = False
                        await self._emit_state("listening")
                    continue

                if chunk is None:  # sentinel — mic thread exited
                    _log("_run() received None sentinel from mic thread — stopping")
                    break

                has_voice = self._is_speech(chunk)

                if has_voice:
                    if not in_speech:
                        _log("_run() speech START detected")
                    in_speech     = True
                    silence_count = 0
                    buf.append(chunk)
                elif in_speech:
                    silence_count += 1
                    buf.append(chunk)  # keep trailing silence for context

                if in_speech and (silence_count >= SILENCE_CHUNKS or len(buf) >= MAX_CHUNKS):
                    _log(f"_run() speech END — flushing {len(buf)} chunks (silence={silence_count})")
                    await self._flush(whisper, buf)
                    buf.clear()
                    silence_count = 0
                    in_speech = False
                    await self._emit_state("listening")

        except asyncio.CancelledError:
            _log("_run() cancelled")
            pass
        except Exception as exc:
            self.last_error = str(exc)
            _log(f"_run() unhandled exception: {exc}")
            log.error("VoiceDaemon error", error=str(exc))
        finally:
            _log("_run() finally — cleaning up")
            self._running   = False
            self.is_running = False
            self._stop_evt.set()
            self.current_state = "idle"
            await self._emit_state("idle")
            _log("_run() exited")

    async def _flush(self, whisper, buf: list[bytes]) -> None:
        """Transcribe a collected audio buffer and emit the result."""
        if not buf:
            return
        await self._emit_state("processing")
        audio = b"".join(buf)
        _log(f"_flush() transcribing {len(audio)//2} samples ({len(audio)/16000/2:.1f}s of audio)")
        transcript = await asyncio.to_thread(self._transcribe, whisper, audio)
        if transcript:
            _log(f"_flush() transcript: {transcript!r}")
            log.info("VoiceDaemon transcript", text=transcript)
            self.utterances_processed += 1
            if self._event_bus:
                await self._event_bus.emit("voice:utterance", {
                    "text":   transcript,
                    "source": "server_daemon",
                })
        else:
            _log("_flush() transcription returned empty string")

    # ── Mic capture thread ────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        """Blocking mic capture — runs in a daemon thread."""
        import sounddevice as sd

        _log(f"_capture_loop() thread started — device={self._device!r}")

        def _cb(indata, frames, time, status):
            if status:
                _log(f"_capture_loop() sounddevice status: {status}")
            if self._stop_evt.is_set():
                raise sd.CallbackStop()
            raw = (indata[:, 0] * 32767).astype("int16").tobytes()
            if self._loop and self._q is not None:
                self._loop.call_soon_threadsafe(self._q.put_nowait, raw)

        # Try requested device first; fall back to system default on failure
        devices_to_try = [self._device, None] if self._device is not None else [None]
        for device in devices_to_try:
            try:
                _log(f"_capture_loop() opening mic — device={device!r}")
                with sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    blocksize=CHUNK_SAMPLES,
                    callback=_cb,
                    device=device,
                ):
                    _log(f"_capture_loop() mic OPEN — streaming audio (device={device!r})")
                    self._stop_evt.wait()
                    _log(f"_capture_loop() stop event set — closing mic (device={device!r})")
                return  # clean exit
            except Exception as exc:
                err = str(exc)
                _log(f"_capture_loop() mic FAILED (device={device!r}): {err}")
                log.error("VoiceDaemon mic error", device=device, error=err)
                self.last_error = err
                if device is None:
                    break  # default also failed, give up

        _log("_capture_loop() all mic attempts failed — sending sentinel")
        if self._loop and self._q is not None:
            self._loop.call_soon_threadsafe(self._q.put_nowait, None)

    # ── VAD ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _is_speech(chunk: bytes) -> bool:
        if not chunk:
            return False
        n = len(chunk) // 2
        if n == 0:
            return False
        samples = struct.unpack(f"{n}h", chunk[:n * 2])
        rms = (sum(s * s for s in samples) / n) ** 0.5
        return rms > VAD_THRESHOLD

    # ── Whisper STT ───────────────────────────────────────────────────────────

    @staticmethod
    def _load_whisper():
        _log("_load_whisper() thread: importing faster_whisper...")
        import numpy as np
        from faster_whisper import WhisperModel

        # Prefer CUDA — but run a test inference to confirm cublas/cuDNN work too
        try:
            import ctranslate2
            cuda_types = ctranslate2.get_supported_compute_types("cuda")
            if cuda_types:
                _log(f"_load_whisper() thread: CUDA detected ({cuda_types}) — loading on GPU (float16)")
                gpu_model = WhisperModel("base", device="cuda", compute_type="float16")
                # Tiny test to verify runtime libs (cublas, cudnn) are present
                _log("_load_whisper() thread: running GPU inference test...")
                test = np.zeros(1600, dtype=np.float32)
                list(gpu_model.transcribe(test, language="en")[0])
                _log("_load_whisper() thread: GPU inference OK — using GPU!")
                return gpu_model
        except Exception as exc:
            _log(f"_load_whisper() thread: GPU failed ({exc}) — falling back to CPU")

        _log("_load_whisper() thread: loading on CPU (int8)...")
        cpu_model = WhisperModel("base", device="cpu", compute_type="int8")
        _log("_load_whisper() thread: CPU model ready!")
        return cpu_model

    @staticmethod
    def _transcribe(whisper, audio_bytes: bytes) -> str:
        import numpy as np
        _log(f"_transcribe() thread: running Whisper on {len(audio_bytes)} bytes...")
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0
        try:
            segs, info = whisper.transcribe(samples, language=None, vad_filter=True, beam_size=3)
            result = " ".join(s.text for s in segs).strip()
            _log(f"_transcribe() thread: done — lang={info.language!r} prob={info.language_probability:.2f} text={result!r}")
            return result
        except Exception as exc:
            _log(f"_transcribe() thread: FAILED — {exc}")
            log.debug("Transcription failed", error=str(exc))
            return ""

    # ── Server-side TTS ───────────────────────────────────────────────────────

    async def speak(self, text: str) -> bool:
        """Speak text on the server's speakers. Returns True if spoken."""
        if not text.strip():
            return False
        _log(f"speak() called: {text!r}")
        self.current_state = "speaking"
        await self._emit_state("speaking")
        try:
            spoken = await self._tts_neural(text)
        except Exception as exc:
            _log(f"speak() TTS failed: {exc}")
            log.warning("Server TTS failed", error=str(exc))
            spoken = False
        finally:
            s = "listening" if self.is_running else "idle"
            self.current_state = s
            await self._emit_state(s)
        return spoken

    @staticmethod
    def edge_tts_available() -> bool:
        import importlib
        importlib.invalidate_caches()
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    async def _tts_neural(self, text: str) -> bool:
        """Neural TTS via edge-tts (Microsoft). No SAPI fallback — browser handles audio when edge-tts is absent."""
        import os, tempfile
        try:
            import edge_tts  # pip install edge-tts
            voice = getattr(self, "_tts_voice", "es-MX-DaliaNeural")
            _log(f"_tts_neural() edge-tts voice={voice!r}")
            communicate = edge_tts.Communicate(text, voice)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = f.name
            try:
                await communicate.save(tmp_path)
                _log(f"_tts_neural() edge-tts saved {os.path.getsize(tmp_path)} bytes — playing")
                await asyncio.to_thread(self._play_audio_file, tmp_path)
                _log("_tts_neural() edge-tts playback complete")
                return True
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        except ImportError:
            _log("_tts_neural() edge-tts not installed — browser will handle TTS. Run: pip install edge-tts")
        except Exception as exc:
            _log(f"_tts_neural() edge-tts failed: {exc}")
        return False

    @staticmethod
    def _play_audio_file(path: str) -> None:
        """Play an audio file synchronously using platform-native methods."""
        import sys
        if sys.platform == "win32":
            # Windows MCI — built-in, no extra packages, handles MP3
            import ctypes
            winmm = ctypes.windll.winmm  # type: ignore[attr-defined]
            alias = "openacm_tts"
            winmm.mciSendStringW(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
            winmm.mciSendStringW(f'play {alias} wait', None, 0, None)
            winmm.mciSendStringW(f'close {alias}', None, 0, None)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["afplay", path], check=False, timeout=120)
        else:
            import subprocess
            # Try mpg123 first (lightweight), fall back to ffplay
            for cmd in [["mpg123", "--quiet", path], ["ffplay", "-nodisp", "-autoexit", path]]:
                try:
                    subprocess.run(cmd, check=False, timeout=120)
                    return
                except FileNotFoundError:
                    continue

    @staticmethod
    def _tts_sapi(text: str) -> bool:
        """Fallback: OS text-to-speech (robotic but no extra deps)."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            return True
        except Exception:
            pass
        try:
            import subprocess, sys
            if sys.platform == "darwin":
                subprocess.run(["say", text], timeout=30, check=False)
                return True
            elif sys.platform.startswith("linux"):
                subprocess.run(["espeak", text], timeout=30, check=False)
                return True
            elif sys.platform == "win32":
                safe = text.replace('"', "'").replace('`', "'")
                subprocess.run(
                    ["powershell", "-NonInteractive", "-Command",
                     f'Add-Type -AssemblyName System.Speech;'
                     f'(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak("{safe}")'],
                    timeout=60, check=False,
                )
                return True
        except Exception:
            pass
        return False

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _emit_state(self, state: str) -> None:
        _log(f"_emit_state({state!r})")
        self.current_state = state
        if self._event_bus:
            try:
                await self._event_bus.emit("voice:daemon_state", {"state": state})
            except Exception:
                pass
