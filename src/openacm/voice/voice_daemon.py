"""
VoiceDaemon — server-side always-on voice processing pipeline.

Audio pipeline: sounddevice mic → adaptive VAD → faster-whisper STT →
                wake word gate → event bus → brain → edge-tts TTS.

Modes:
  passive  — waiting for wake word; transcribes every utterance but
             only forwards to brain when assistant name is detected.
  active   — full listening; every utterance goes straight to brain.
             Returns to passive after ACTIVE_TIMEOUT seconds of silence.
  speaking — TTS playing; VAD still runs for wake-word interrupt detection.

Optional dependencies:
  pip install sounddevice faster-whisper numpy edge-tts
"""
from __future__ import annotations

import asyncio
import struct
import threading
import time
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Audio constants ────────────────────────────────────────────────────────────

SAMPLE_RATE          = 16_000   # Hz — Whisper native rate
CHUNK_DURATION       = 0.5      # seconds per read
CHUNK_SAMPLES        = int(SAMPLE_RATE * CHUNK_DURATION)
SILENCE_CHUNKS       = 2        # chunks of silence to end an utterance (~1.0 s)
MAX_CHUNKS           = 40       # max utterance length (~20 s)
ACTIVE_TIMEOUT       = 6.0      # seconds after speaking before returning to passive
MIN_VAD_THRESHOLD    = 150      # absolute floor — never go quieter than this
VAD_NOISE_MULTIPLIER = 3.5      # threshold = noise_floor × this
CALIBRATION_CHUNKS   = 4        # ~2 s of audio to measure ambient noise at startup

_ACKS = ["Un momento...", "Déjame ver...", "Entendido...", "Claro..."]


def _log(msg: str) -> None:
    print(f"[VoiceDaemon] {msg}", flush=True)


class VoiceDaemon:
    """
    Server-side always-on voice daemon.

    Lifecycle::

        daemon = VoiceDaemon(database=db, event_bus=bus, brain=brain)
        daemon._wake_word = "OpenACM"
        daemon._tts_voice = "es-MX-DaliaNeural"
        await daemon.start()
        await daemon.stop()
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
        self._device: int | str | None = None

        # Wake word gate
        self._wake_word: str = ""
        self._mode: str = "passive"
        self._active_timer: Optional[asyncio.Task] = None
        self._speak_lock: Optional[asyncio.Lock] = None

        # Adaptive VAD
        self._vad_threshold: float = 600.0

        # TTS interrupt (wake word detected while speaking)
        self._tts_interrupt = threading.Event()

        # Public status fields
        self.is_running:           bool = False
        self.current_state:        str  = "idle"
        self.last_error:           str  = ""
        self.utterances_processed: int  = 0
        self._tts_voice:           str  = "es-MX-DaliaNeural"

    # ── Dependency check ──────────────────────────────────────────────────────

    @staticmethod
    def check_deps() -> dict[str, bool]:
        import importlib
        importlib.invalidate_caches()
        result: dict[str, bool] = {
            "sounddevice": False, "faster_whisper": False,
            "numpy": False, "edge_tts": False,
        }
        for pkg, key in [
            ("sounddevice", "sounddevice"), ("faster_whisper", "faster_whisper"),
            ("numpy", "numpy"), ("edge_tts", "edge_tts"),
        ]:
            try:
                __import__(pkg)
                result[key] = True
            except Exception:
                pass
        return result

    @property
    def engine_available(self) -> bool:
        deps = self.check_deps()
        return deps["sounddevice"] and deps["faster_whisper"] and deps["numpy"]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, device: int | str | None = None) -> str:
        _log(f"start() called — device={device!r}, already_running={self._running}")
        if self._running:
            return ""
        if not self.engine_available:
            missing = [k for k, v in self.check_deps().items() if not v and k != "pyttsx3"]
            self.last_error = f"Missing dependencies: pip install {' '.join(missing)}"
            return self.last_error

        self._device       = device
        self._running      = True
        self.is_running    = True
        self.last_error    = ""
        self._mode         = "passive"
        self._vad_threshold = 600.0
        self._tts_interrupt.clear()
        self._stop_evt.clear()
        self._loop         = asyncio.get_event_loop()
        self._q            = asyncio.Queue(maxsize=200)
        self._speak_lock   = asyncio.Lock()
        self._task         = asyncio.create_task(self._run(), name="voice_daemon")
        return ""

    async def stop(self) -> None:
        _log("stop() called")
        self._running    = False
        self.is_running  = False
        self.current_state = "idle"
        self._tts_interrupt.set()   # unblock any in-progress playback
        self._cancel_active_timer()
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
        _log("_run() started — loading Whisper model")
        await self._emit_state("loading_model")

        try:
            whisper = await asyncio.to_thread(self._load_whisper)
            _log("_run() Whisper loaded OK")
        except Exception as exc:
            self.last_error = f"Whisper load failed: {exc}"
            _log(f"_run() Whisper FAILED: {exc}")
            self._running = False
            self.is_running = False
            await self._emit_state("idle")
            return

        # Start mic capture thread
        _log(f"_run() starting mic (device={self._device!r})")
        threading.Thread(target=self._capture_loop, daemon=True, name="voice_mic").start()

        # ── Calibrate adaptive VAD from ambient noise (~2 s) ─────────────────
        _log(f"_run() calibrating ambient noise ({CALIBRATION_CHUNKS} chunks)...")
        calib: list[float] = []
        for _ in range(CALIBRATION_CHUNKS):
            try:
                chunk = await asyncio.wait_for(self._q.get(), timeout=1.5)  # type: ignore
                if chunk is not None:
                    calib.append(self._rms(chunk))
            except asyncio.TimeoutError:
                break
        if calib:
            noise_floor = sorted(calib)[max(0, len(calib) // 4)]  # 25th percentile
            self._vad_threshold = max(MIN_VAD_THRESHOLD, noise_floor * VAD_NOISE_MULTIPLIER)
            _log(f"_run() noise_floor={noise_floor:.0f}  vad_threshold={self._vad_threshold:.0f}")
        else:
            _log("_run() calibration timeout — using default threshold")

        # ── Main VAD loop ─────────────────────────────────────────────────────
        buf: list[bytes] = []
        silence_count    = 0
        in_speech        = False

        await self._emit_state("passive")
        _log(f"_run() VAD loop — wake_word={self._wake_word!r} threshold={self._vad_threshold:.0f}")

        try:
            while self._running:
                try:
                    chunk = await asyncio.wait_for(self._q.get(), timeout=0.5)  # type: ignore
                except asyncio.TimeoutError:
                    if in_speech:
                        silence_count += 1
                    if in_speech and silence_count >= SILENCE_CHUNKS:
                        await self._handle_flush(whisper, buf)
                        buf.clear(); silence_count = 0; in_speech = False
                    continue

                if chunk is None:
                    _log("_run() received sentinel — stopping")
                    break

                has_voice = self._is_speech(chunk)

                if has_voice:
                    if not in_speech:
                        in_speech = True
                        # Only cancel timer / emit state when not busy with TTS
                        if self.current_state not in ("speaking", "processing"):
                            self._cancel_active_timer()
                            if self._mode == "active":
                                await self._emit_state("listening")
                    silence_count = 0
                    buf.append(chunk)
                elif in_speech:
                    silence_count += 1
                    buf.append(chunk)

                if in_speech and (silence_count >= SILENCE_CHUNKS or len(buf) >= MAX_CHUNKS):
                    await self._handle_flush(whisper, buf)
                    buf.clear(); silence_count = 0; in_speech = False

        except asyncio.CancelledError:
            _log("_run() cancelled")
        except Exception as exc:
            self.last_error = str(exc)
            _log(f"_run() error: {exc}")
            log.error("VoiceDaemon error", error=str(exc))
        finally:
            _log("_run() cleaning up")
            self._cancel_active_timer()
            self._running   = False
            self.is_running = False
            self._stop_evt.set()
            self.current_state = "idle"
            await self._emit_state("idle")

    async def _handle_flush(self, whisper, buf: list[bytes]) -> None:
        """Transcribe buffer and route based on current mode / state."""
        if not buf:
            return

        if self.current_state == "speaking":
            # ── Interrupt detection: check for wake word while TTS is playing ──
            audio      = b"".join(buf)
            transcript = await asyncio.to_thread(self._transcribe, whisper, audio)
            if transcript and self._contains_wake_word(transcript):
                _log(f"_handle_flush() INTERRUPT — wake word while speaking: {transcript!r}")
                self._tts_interrupt.set()          # signal _play_audio_file to stop
                self._mode = "active"
                await self._emit_state("activating")
                await asyncio.sleep(0.35)
                await self._emit_state("listening")
            return

        if self.current_state == "processing":
            _log("_handle_flush() skipped — busy processing previous utterance")
            return

        await self._emit_state("processing")
        audio      = b"".join(buf)
        _log(f"_handle_flush() transcribing {len(audio)//2} samples ({len(audio)/16000/2:.1f}s)")
        transcript = await asyncio.to_thread(self._transcribe, whisper, audio)

        if not transcript:
            await self._emit_state("passive" if self._mode == "passive" else "listening")
            return

        _log(f"_handle_flush() transcript={transcript!r}  mode={self._mode!r}")

        if self._mode == "passive":
            if self._contains_wake_word(transcript):
                command = self._extract_command(transcript)
                _log(f"_handle_flush() wake word — command={command!r}")
                await self._emit_state("activating")
                await asyncio.sleep(0.35)
                self._mode = "active"
                if command:
                    await self._send_utterance(command)
                else:
                    await self._emit_state("listening")
            else:
                await self._emit_state("passive")
        else:
            await self._send_utterance(transcript)

    async def _send_utterance(self, text: str) -> None:
        _log(f"_send_utterance() {text!r}")
        self.utterances_processed += 1
        if self._event_bus:
            await self._event_bus.emit("voice:utterance", {
                "text": text, "source": "server_daemon",
            })

    # ── Active-mode timeout ───────────────────────────────────────────────────

    def _start_active_timer(self) -> None:
        self._cancel_active_timer()
        if self._loop and self._running:
            self._active_timer = self._loop.create_task(self._active_timeout_task())

    def _cancel_active_timer(self) -> None:
        if self._active_timer and not self._active_timer.done():
            self._active_timer.cancel()
        self._active_timer = None

    async def _active_timeout_task(self) -> None:
        try:
            await asyncio.sleep(ACTIVE_TIMEOUT)
            if self._mode == "active" and self.is_running:
                _log(f"_active_timeout_task() — {ACTIVE_TIMEOUT}s silence, returning to passive")
                self._mode = "passive"
                await self._emit_state("passive")
        except asyncio.CancelledError:
            pass

    # ── Wake word helpers ─────────────────────────────────────────────────────

    def _contains_wake_word(self, transcript: str) -> bool:
        if not self._wake_word:
            return True
        wake  = self._wake_word.lower()
        lower = transcript.lower()
        if wake in lower:
            return True
        return any(self._levenshtein(w, wake) <= 1 for w in lower.split())

    def _extract_command(self, transcript: str) -> str:
        if not self._wake_word:
            return transcript.strip()
        lower = transcript.lower()
        wake  = self._wake_word.lower()
        idx   = lower.find(wake)
        if idx == -1:
            return transcript.strip()
        return transcript[idx + len(wake):].lstrip(" ,").strip()

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        m, n = len(a), len(b)
        dp = list(range(n + 1))
        for i in range(1, m + 1):
            prev, dp[0] = dp[0], i
            for j in range(1, n + 1):
                temp  = dp[j]
                dp[j] = prev if a[i-1] == b[j-1] else 1 + min(prev, dp[j], dp[j-1])
                prev  = temp
        return dp[n]

    # ── Mic capture thread ────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        import sounddevice as sd

        _log(f"_capture_loop() started — device={self._device!r}")

        def _cb(indata, frames, t, status):
            if status:
                _log(f"_capture_loop() status: {status}")
            if self._stop_evt.is_set():
                raise sd.CallbackStop()
            raw = (indata[:, 0] * 32767).astype("int16").tobytes()
            if self._loop and self._q is not None:
                self._loop.call_soon_threadsafe(self._q.put_nowait, raw)

        devices_to_try = [self._device, None] if self._device is not None else [None]
        for device in devices_to_try:
            try:
                _log(f"_capture_loop() opening mic device={device!r}")
                with sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                    blocksize=CHUNK_SAMPLES, callback=_cb, device=device,
                ):
                    _log(f"_capture_loop() mic OPEN (device={device!r})")
                    self._stop_evt.wait()
                return
            except Exception as exc:
                _log(f"_capture_loop() mic FAILED (device={device!r}): {exc}")
                self.last_error = str(exc)
                if device is None:
                    break

        _log("_capture_loop() all attempts failed — sentinel")
        if self._loop and self._q is not None:
            self._loop.call_soon_threadsafe(self._q.put_nowait, None)

    # ── VAD ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _rms(chunk: bytes) -> float:
        n = len(chunk) // 2
        if n == 0:
            return 0.0
        samples = struct.unpack(f"{n}h", chunk[:n * 2])
        return (sum(s * s for s in samples) / n) ** 0.5

    def _is_speech(self, chunk: bytes) -> bool:
        return self._rms(chunk) > self._vad_threshold

    # ── Whisper STT ───────────────────────────────────────────────────────────

    @staticmethod
    def _load_whisper():
        _log("_load_whisper() importing faster_whisper...")
        import numpy as np
        from faster_whisper import WhisperModel

        try:
            import ctranslate2
            cuda_types = ctranslate2.get_supported_compute_types("cuda")
            if cuda_types:
                _log(f"_load_whisper() CUDA detected — loading GPU model")
                gpu_model = WhisperModel("base", device="cuda", compute_type="float16")
                list(gpu_model.transcribe(np.zeros(1600, dtype=np.float32), language="en")[0])
                _log("_load_whisper() GPU OK!")
                return gpu_model
        except Exception as exc:
            _log(f"_load_whisper() GPU failed ({exc}) — CPU fallback")

        _log("_load_whisper() loading CPU model (int8)...")
        model = WhisperModel("base", device="cpu", compute_type="int8")
        _log("_load_whisper() CPU model ready!")
        return model

    @staticmethod
    def _transcribe(whisper, audio_bytes: bytes) -> str:
        import numpy as np
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0
        try:
            segs, info = whisper.transcribe(samples, language=None, vad_filter=True, beam_size=3)
            result = " ".join(s.text for s in segs).strip()
            _log(f"_transcribe() lang={info.language!r} prob={info.language_probability:.2f} → {result!r}")
            return result
        except Exception as exc:
            _log(f"_transcribe() FAILED — {exc}")
            return ""

    # ── Server-side TTS ───────────────────────────────────────────────────────

    async def speak_quiet(self, text: str) -> bool:
        """Speak without changing daemon state (quick acknowledgments)."""
        if not text.strip():
            return False
        lock = self._speak_lock
        if lock is None:
            return False
        async with lock:
            # Abort immediately if an interrupt happened before we acquired the lock
            if self._tts_interrupt.is_set():
                return False
            self._tts_interrupt.clear()
            return await self._tts_neural(text)

    async def speak(self, text: str) -> bool:
        """Speak and update daemon state. Call speak('') to silently restore state."""
        lock = self._speak_lock
        if lock is None:
            return False
        async with lock:
            # If state already changed to listening/passive (wake word interrupt happened
            # before we acquired the lock), skip this response entirely.
            if self.current_state in ("listening", "passive"):
                _log(f"speak() skipped — interrupted before lock (state={self.current_state!r})")
                return False
            if not text.strip():
                await self._restore_post_speak_state()
                return False
            _log(f"speak() {text!r}")
            self._tts_interrupt.clear()
            self.current_state = "speaking"
            await self._emit_state("speaking")
            try:
                spoken = await self._tts_neural(text)
            except Exception as exc:
                _log(f"speak() TTS failed: {exc}")
                spoken = False
            finally:
                await self._restore_post_speak_state()
        return spoken

    async def _restore_post_speak_state(self) -> None:
        """Return to listening/passive after TTS. Skips if wake-word interrupt fired."""
        if self._tts_interrupt.is_set():
            # Interrupt handler already set the state — don't override it
            self._tts_interrupt.clear()
            return
        if not self.is_running:
            self.current_state = "idle"
            await self._emit_state("idle")
            return
        if self._mode == "active":
            self.current_state = "listening"
            await self._emit_state("listening")
            self._start_active_timer()
        else:
            self.current_state = "passive"
            await self._emit_state("passive")

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
        import os, tempfile
        try:
            import edge_tts
            voice = getattr(self, "_tts_voice", "es-MX-DaliaNeural")
            _log(f"_tts_neural() edge-tts voice={voice!r}")
            communicate = edge_tts.Communicate(text, voice)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = f.name
            try:
                await communicate.save(tmp_path)
                _log(f"_tts_neural() saved {os.path.getsize(tmp_path)} bytes — playing")
                await asyncio.to_thread(self._play_audio_file, tmp_path, self._tts_interrupt)
                _log("_tts_neural() playback complete")
                return True
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        except ImportError:
            _log("_tts_neural() edge-tts not installed — browser handles TTS")
        except Exception as exc:
            _log(f"_tts_neural() failed: {exc}")
        return False

    @staticmethod
    def _play_audio_file(path: str, stop_evt: threading.Event | None = None) -> None:
        """Play an audio file, polling stop_evt every 50 ms for interruptibility."""
        import sys
        if sys.platform == "win32":
            import ctypes
            winmm  = ctypes.windll.winmm  # type: ignore[attr-defined]
            alias  = "openacm_tts"
            buf    = ctypes.create_unicode_buffer(256)
            winmm.mciSendStringW(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
            winmm.mciSendStringW(f'play {alias}', None, 0, None)  # async — no 'wait'
            while True:
                winmm.mciSendStringW(f'status {alias} mode', buf, 256, None)
                if buf.value.lower() != "playing":
                    break
                if stop_evt and stop_evt.is_set():
                    winmm.mciSendStringW(f'stop {alias}', None, 0, None)
                    break
                time.sleep(0.05)
            winmm.mciSendStringW(f'close {alias}', None, 0, None)
        elif sys.platform == "darwin":
            import subprocess
            proc = subprocess.Popen(["afplay", path])
            while proc.poll() is None:
                if stop_evt and stop_evt.is_set():
                    proc.terminate()
                    break
                time.sleep(0.05)
        else:
            import subprocess
            for cmd in [["mpg123", "--quiet", path], ["ffplay", "-nodisp", "-autoexit", path]]:
                try:
                    proc = subprocess.Popen(cmd)
                    while proc.poll() is None:
                        if stop_evt and stop_evt.is_set():
                            proc.terminate()
                            break
                        time.sleep(0.05)
                    return
                except FileNotFoundError:
                    continue

    @staticmethod
    def _tts_sapi(text: str) -> bool:
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
