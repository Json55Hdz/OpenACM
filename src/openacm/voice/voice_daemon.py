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
import os
import struct
import tempfile
import threading
import time
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Audio constants ────────────────────────────────────────────────────────────

SAMPLE_RATE          = 16_000   # Hz — Whisper native rate
CHUNK_DURATION       = 0.5      # seconds per read
CHUNK_SAMPLES        = int(SAMPLE_RATE * CHUNK_DURATION)
SILENCE_CHUNKS       = 4        # chunks of silence to end an utterance (~2.0 s) — tolerates natural pauses
MAX_CHUNKS           = 60       # max utterance length (~30 s) — for longer dictations
IN_SPEECH_VAD_FACTOR = 0.55     # while already speaking, threshold drops to this × base — keeps the mic "open" through quiet syllables
ACTIVE_TIMEOUT       = 6.0      # seconds after speaking before returning to passive
MIN_VAD_THRESHOLD    = 100      # absolute floor — never go quieter than this
VAD_NOISE_MULTIPLIER = 2.5      # threshold = noise_floor × this
CALIBRATION_CHUNKS   = 4        # ~2 s of audio to measure ambient noise at startup
ACTIVE_VAD_FACTOR    = 0.8      # in active mode, threshold is multiplied by this (slightly more sensitive)
UTTERANCE_TIMEOUT    = 30.0     # seconds before giving up if speak() is never called
MIN_LANG_PROB        = 0.40     # discard Whisper output below this language-detection confidence
TTS_INTERRUPT_FACTOR = 3.0      # user must speak this many × measured TTS-echo RMS to interrupt TTS
WHISPER_MODEL        = "small"  # faster-whisper model size: tiny|base|small|medium|large-v3
POST_TTS_GRACE_S     = 1.2      # hard mute window right after TTS ends (room reverb dies down)
POST_TTS_SUPPRESS_S  = 5.0      # extra suppression window after grace — accept only loud input
POST_TTS_RMS_FACTOR  = 2.5      # during suppression, audio must exceed echo_rms × this to count

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

        # STT language — None = auto-detect (can hallucinate); set to "es" or "en" for reliability
        self._stt_language: str | None = None

        # Adaptive VAD
        self._vad_threshold: float = 600.0

        # TTS playback — mic is muted while speaking and for a grace period after
        self._mic_resume_after:    float = 0.0  # hard mute: drop ALL frames before this time
        self._mic_suppress_until:  float = 0.0  # soft suppress: only loud frames pass before this
        self._tts_echo_rms:        float = 0.0  # measured echo level of current TTS through speakers

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
        self._loop         = asyncio.get_running_loop()
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

                # Bi-modal VAD: harder to start speech, easier to keep it going
                # (so quiet syllables / breaths between words don't end the utterance)
                has_voice = self._is_speech(chunk, in_speech=in_speech)

                if has_voice:
                    if not in_speech:
                        in_speech = True
                        # Pause the active-mode timeout while user is speaking;
                        # it gets restarted after flush (in _handle_flush / _restore_post_speak_state).
                        if self.current_state not in ("speaking", "processing"):
                            self._cancel_active_timer()
                            if self._mode == "active" and self.current_state != "listening":
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
            transcript = await asyncio.to_thread(self._transcribe, whisper, audio, self._stt_language)
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
        transcript = await asyncio.to_thread(self._transcribe, whisper, audio, self._stt_language)

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
                # Always end up in listening + active timer so the user knows we're waiting
                # and the daemon recovers if the brain never calls speak()
                await self._emit_state("listening")
                self._start_active_timer()
            else:
                await self._emit_state("passive")
        else:
            await self._send_utterance(transcript)
            # Stay in listening so the user can chain more commands; speak() will manage
            # state transitions when the brain replies. _utterance_timeout is the safety net.
            await self._emit_state("listening")
            self._start_active_timer()

    async def _send_utterance(self, text: str) -> None:
        _log(f"_send_utterance() {text!r}")
        self.utterances_processed += 1
        if self._event_bus:
            await self._event_bus.emit("voice:utterance", {
                "text": text, "source": "server_daemon",
            })
        # Safety net: if speak() is never called (e.g. TTS skipped), restore state
        asyncio.create_task(self._utterance_timeout())

    async def _utterance_timeout(self) -> None:
        """Restore state if speak() is never called within UTTERANCE_TIMEOUT seconds."""
        await asyncio.sleep(UTTERANCE_TIMEOUT)
        if self.current_state in ("processing", "activating") and self._running:
            _log("_utterance_timeout() — speak() was not called, restoring state")
            await self._restore_post_speak_state()

    # ── Active-mode timeout ───────────────────────────────────────────────────

    def _start_active_timer(self) -> None:
        self._cancel_active_timer()
        if self._loop and self._running:
            self._active_timer = asyncio.create_task(self._active_timeout_task())

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

    @staticmethod
    def _normalize_for_match(s: str) -> str:
        """Lowercase, strip punctuation/accents, and fold common phonetic confusions
        so STT variants like 'Garbys', 'Yarvis', 'Harbys' all collapse to the same
        skeleton as 'jarvis'."""
        import unicodedata
        # Strip accents
        s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
        s = s.lower()
        # Keep only letters and spaces
        s = "".join(c if c.isalpha() or c == " " else " " for c in s)
        # Phonetic foldings — Spanish/English STT tends to confuse these
        repl = [
            ("ph", "f"), ("ck", "k"), ("qu", "k"), ("c", "k"),
            ("z", "s"), ("x", "s"), ("v", "b"), ("w", "b"),
            ("y", "i"), ("j", "i"), ("h", ""), ("g", "i"),  # j/y/g/h all sound similar in ES
        ]
        for a, b in repl:
            s = s.replace(a, b)
        return " ".join(s.split())  # collapse whitespace

    def _contains_wake_word(self, transcript: str) -> bool:
        if not self._wake_word:
            return True
        wake_norm = self._normalize_for_match(self._wake_word)
        text_norm = self._normalize_for_match(transcript)
        if not wake_norm:
            return True
        if wake_norm in text_norm:
            return True
        # Token-level fuzzy match with adaptive threshold (~30% of word length)
        max_dist = max(2, len(wake_norm) // 3)
        return any(
            self._levenshtein(w, wake_norm) <= max_dist
            for w in text_norm.split() if w
        )

    def _extract_command(self, transcript: str) -> str:
        """Return everything after the wake word. Falls back to the full transcript
        if the wake word can't be located cleanly (token boundaries don't match)."""
        if not self._wake_word:
            return transcript.strip()
        wake_norm = self._normalize_for_match(self._wake_word)
        # Walk transcript word-by-word and find the first token that matches wake word
        original_words = transcript.split()
        max_dist = max(2, len(wake_norm) // 3)
        for i, w in enumerate(original_words):
            if self._levenshtein(self._normalize_for_match(w), wake_norm) <= max_dist:
                return " ".join(original_words[i + 1:]).lstrip(" ,.;:¿?¡!").strip()
        return transcript.strip()

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
            if self.current_state == "speaking":
                # Adaptive echo cancellation: track TTS echo level, trigger interrupt
                # only when user speaks significantly louder than the reflected TTS audio.
                if not self._tts_interrupt.is_set():
                    rms = VoiceDaemon._rms(raw)
                    # Exponential moving average of the TTS echo arriving at the mic
                    if self._tts_echo_rms == 0.0:
                        self._tts_echo_rms = max(rms, 1.0)
                    else:
                        self._tts_echo_rms = self._tts_echo_rms * 0.85 + rms * 0.15
                    # Interrupt if user's voice is TTS_INTERRUPT_FACTOR × louder than echo
                    if rms > self._tts_echo_rms * TTS_INTERRUPT_FACTOR and rms > self._vad_threshold:
                        _log(f"_capture_loop() interrupt — rms={rms:.0f} echo={self._tts_echo_rms:.0f}")
                        self._tts_interrupt.set()
                return  # don't feed the normal pipeline while speaking
            now = time.monotonic()
            if now < self._mic_resume_after:
                return  # hard mute: room reverb still dying down right after TTS
            if now < self._mic_suppress_until:
                # Soft suppression: only let through audio louder than the echo we last
                # measured during TTS (× factor). This kills the trailing reverb that
                # follows the hard-mute window without losing the user's real voice.
                rms = VoiceDaemon._rms(raw)
                gate = max(self._vad_threshold, self._tts_echo_rms * POST_TTS_RMS_FACTOR)
                if rms < gate:
                    return
            q, loop = self._q, self._loop
            if q is not None and loop is not None:
                def _enqueue():
                    try:
                        q.put_nowait(raw)
                    except asyncio.QueueFull:
                        pass  # drop frame under backpressure
                loop.call_soon_threadsafe(_enqueue)

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
        q, loop = self._q, self._loop
        if q is not None and loop is not None:
            loop.call_soon_threadsafe(q.put_nowait, None)

    # ── VAD ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _rms(chunk: bytes) -> float:
        n = len(chunk) // 2
        if n == 0:
            return 0.0
        samples = struct.unpack(f"{n}h", chunk[:n * 2])
        return (sum(s * s for s in samples) / n) ** 0.5

    def _is_speech(self, chunk: bytes, in_speech: bool = False) -> bool:
        rms = self._rms(chunk)
        # Active mode is a bit more sensitive than passive
        threshold = self._vad_threshold * (ACTIVE_VAD_FACTOR if self._mode == "active" else 1.0)
        # If we're already capturing an utterance, drop the threshold further so brief
        # quiet moments (between words, breath, soft consonants) don't end the buffer.
        if in_speech:
            threshold *= IN_SPEECH_VAD_FACTOR
        return rms > threshold

    # ── Whisper STT ───────────────────────────────────────────────────────────

    @staticmethod
    def _load_whisper():
        _log(f"_load_whisper() importing faster_whisper (model={WHISPER_MODEL!r})...")
        import numpy as np
        from faster_whisper import WhisperModel

        try:
            import ctranslate2
            cuda_types = ctranslate2.get_supported_compute_types("cuda")
            if cuda_types:
                _log(f"_load_whisper() CUDA detected — loading GPU model")
                gpu_model = WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16")
                list(gpu_model.transcribe(np.zeros(1600, dtype=np.float32), language="en")[0])
                _log("_load_whisper() GPU OK!")
                return gpu_model
        except Exception as exc:
            _log(f"_load_whisper() GPU failed ({exc}) — CPU fallback")

        _log(f"_load_whisper() loading CPU model {WHISPER_MODEL!r} (int8)...")
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        _log("_load_whisper() CPU model ready!")
        return model

    @staticmethod
    def _transcribe(whisper, audio_bytes: bytes, language: str | None = None) -> str:
        import numpy as np
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0
        try:
            segs, info = whisper.transcribe(
                samples, language=language, vad_filter=True, beam_size=3,
            )
            result = " ".join(s.text for s in segs).strip()
            _log(
                f"_transcribe() lang={info.language!r} "
                f"prob={info.language_probability:.2f} → {result!r}"
            )
            if info.language_probability < MIN_LANG_PROB and language is None:
                _log(
                    f"_transcribe() discarding — low language confidence "
                    f"({info.language_probability:.2f} < {MIN_LANG_PROB})"
                )
                return ""
            return result
        except Exception as exc:
            _log(f"_transcribe() FAILED — {exc}")
            return ""

    # ── Server-side TTS ───────────────────────────────────────────────────────

    async def speak_quiet(self, text: str) -> bool:
        """Speak a short acknowledgment. Engages the AEC pipeline (state='speaking')
        during playback so the mic doesn't capture the ack, then restores the previous
        logical state and extends the post-TTS suppression window."""
        if not text.strip():
            return False
        lock = self._speak_lock
        if lock is None:
            return False
        async with lock:
            if self._tts_interrupt.is_set():
                return False
            self._tts_interrupt.clear()
            self._tts_echo_rms = 0.0
            prev_state = self.current_state
            self.current_state = "speaking"   # engages AEC branch in mic callback
            try:
                spoken = await self._tts_neural(text)
            except Exception as exc:
                _log(f"speak_quiet() failed: {exc}")
                spoken = False
            finally:
                # Restore the prior logical state, extend mute/suppress windows so the
                # tail of this ack doesn't get heard by the now-unmuted mic.
                now = time.monotonic()
                self._mic_resume_after   = max(self._mic_resume_after,   now + POST_TTS_GRACE_S)
                self._mic_suppress_until = max(self._mic_suppress_until, now + POST_TTS_GRACE_S + POST_TTS_SUPPRESS_S)
                self.current_state = prev_state
            return spoken

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
            self._tts_echo_rms = 0.0   # reset so echo calibrates fresh for this response
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
        # Two-stage post-TTS protection against the daemon hearing its own voice:
        #   1. Hard mute (POST_TTS_GRACE_S): drop ALL frames — kills initial reverb tail
        #   2. Soft suppression (POST_TTS_SUPPRESS_S): only frames louder than the
        #      TTS echo level pass through — kills trailing reverb / speaker feedback
        #      while still letting the user's actual voice through.
        now = time.monotonic()
        self._mic_resume_after   = now + POST_TTS_GRACE_S
        self._mic_suppress_until = now + POST_TTS_GRACE_S + POST_TTS_SUPPRESS_S
        # Drain any audio that accumulated in the queue during TTS (speaker feedback frames)
        if self._q is not None:
            drained = 0
            while not self._q.empty():
                try:
                    self._q.get_nowait()
                    drained += 1
                except asyncio.QueueEmpty:
                    break
            if drained:
                _log(f"_restore_post_speak_state() drained {drained} stale frames")

        # If a wake-word interrupt fired during TTS, the interrupt handler in
        # _handle_flush already set state → activating → listening. Just clear
        # the flag and exit so we don't override that transition.
        if self._tts_interrupt.is_set():
            self._tts_interrupt.clear()
            if self.current_state == "speaking":
                # Defensive fallback: shouldn't normally happen, but if interrupt fired
                # and state somehow stayed "speaking", recover to listening rather than mute forever
                self.current_state = "listening"
                await self._emit_state("listening")
                self._start_active_timer()
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
        try:
            import edge_tts
            voice = self._tts_voice
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
            _log("_tts_neural() edge-tts not installed — falling back to system TTS")
            return await asyncio.to_thread(self._tts_sapi, text)
        except Exception as exc:
            _log(f"_tts_neural() failed: {exc} — falling back to system TTS")
            return await asyncio.to_thread(self._tts_sapi, text)

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
                    proc.wait()
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
                            proc.wait()
                            break
                        time.sleep(0.05)
                    return
                except FileNotFoundError:
                    continue

    @staticmethod
    def _tts_sapi(text: str) -> bool:
        """Offline / system TTS fallback used when edge-tts is unavailable or fails."""
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
