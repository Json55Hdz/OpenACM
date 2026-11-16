"""
Model capability registry.

Every time a model is selected, OpenACM probes what it can really do (image input,
audio input) with a tiny real request, and remembers the answer. Features that need a
capability ask the registry for "a model that can do X" instead of hardcoding one:

    provider, model = await router.capabilities.pick("vision")
    text = await router.capabilities.complete(provider, model, messages)

Results are measured, not looked up in a static table: proxies and new models are often
missing from (or wrong in) such tables.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import struct
import time
import uuid
import wave
import zlib
from typing import Any

import structlog

log = structlog.get_logger()

CAPABILITIES = ("vision", "audio")
PROBE_VERSION = 2  # 2: the audio probe counts beeps instead of asking "is there a sound?"
PROBE_BEEPS = 4
SETTINGS_KEY = "llm.capabilities"
PROBE_TIMEOUT_S = 45
_NATIVE_PREFIX = {"anthropic": "anthropic", "gemini": "gemini", "openrouter": "openrouter", "xai": "xai"}

# Phrases that mean "the endpoint/model does not take this kind of input" (a definite no),
# as opposed to a transient failure (timeout, 5xx, bad key) which stays "unknown".
_UNSUPPORTED_HINTS = (
    "does not support", "doesn't support", "not support", "unsupported", "invalid content type",
    "image input", "audio input", "input_audio", "image_url", "multimodal", "modalit",
    "unknown variant", "invalid type", "expected a string", "must be a string",
)
_DENIAL_HINTS = (
    "cannot", "can't", "can not", "unable", "no audio", "not able", "don't have the ability",
    "do not have the ability", "no puedo", "no tengo", "text-based", "as a text",
)


def _solid_png(rgb: tuple[int, int, int], size: int = 96) -> bytes:
    """A solid-colour PNG built with the standard library only."""
    row = b"\x00" + bytes(rgb) * size
    raw = row * size

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _tone_wav(seconds: float = 0.6, freq: float = 440.0, rate: int = 16000) -> bytes:
    """A short sine tone as 16-bit mono WAV."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)
        ))
    return buf.getvalue()


def _beeps_wav(count: int = 4, rate: int = 16000) -> bytes:
    """`count` short beeps separated by silence, as 16-bit mono WAV.

    The audio probe asks HOW MANY beeps there are: a model that cannot hear has to guess the
    number, whereas a plain "is there a sound? yes/no" is passed by any model that says "yes".
    """
    buf = io.BytesIO()
    beep = [int(12000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(int(0.25 * rate))]
    gap = [0] * int(0.3 * rate)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        samples: list[int] = list(gap)
        for _ in range(count):
            samples += beep + gap
        w.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return buf.getvalue()


def _looks_unsupported(error: str) -> bool:
    e = error.lower()
    return any(h in e for h in _UNSUPPORTED_HINTS)


class ModelCapabilities:
    """Measured capabilities per (provider, model), cached and persisted."""

    def __init__(self, router: Any):
        self.router = router
        self._caps: dict[str, dict[str, Any]] = {}
        self._probing: dict[str, asyncio.Task] = {}
        self._database: Any = None

    # ── storage ──────────────────────────────────────────────────────────────

    @staticmethod
    def key(provider: str, model: str) -> str:
        return f"{provider}::{model}"

    async def load(self, database: Any) -> None:
        self._database = database
        try:
            raw = await database.get_setting(SETTINGS_KEY)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if not isinstance(v, dict):
                            continue
                        if v.get("v") != PROBE_VERSION and v.get("audio") is True:
                            # Measured with the old yes/no question, which a deaf model passes by
                            # guessing: forget the "yes" and measure again with the beep count.
                            v = {**v, "audio": None}
                        self._caps[k] = v
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load model capabilities", error=str(exc))

    async def _save(self) -> None:
        if not self._database:
            return
        try:
            await self._database.set_setting(SETTINGS_KEY, json.dumps(self._caps))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not persist model capabilities", error=str(exc))

    # ── queries ──────────────────────────────────────────────────────────────

    def _current(self) -> tuple[str, str]:
        return self.router.current_provider, self.router.current_model

    def get(self, provider: str | None = None, model: str | None = None) -> dict[str, Any]:
        """Known capabilities ({} if never probed). Values: True, False or None (unknown)."""
        cp, cm = self._current()
        return dict(self._caps.get(self.key(provider or cp, model or cm), {}))

    def supports(self, capability: str, provider: str | None = None, model: str | None = None) -> bool | None:
        """True/False if measured, None if unknown (never probed or probe inconclusive)."""
        return self.get(provider, model).get(capability)

    def describe(self, provider: str | None = None, model: str | None = None) -> str:
        caps = self.get(provider, model)
        if not caps:
            return "capabilities: not tested yet"
        mark = {True: "yes", False: "no", None: "unknown"}
        return "capabilities: " + ", ".join(f"{c} {mark[caps.get(c)]}" for c in CAPABILITIES)

    def _is_cli(self, provider: str) -> bool:
        cfg = (getattr(self.router.config, "providers", {}) or {}).get(provider)
        return isinstance(cfg, dict) and cfg.get("type") == "cli"

    def is_local(self, provider: str) -> bool:
        """True when the provider runs on this machine / private network."""
        cfg = (getattr(self.router.config, "providers", {}) or {}).get(provider)
        base = (cfg.get("base_url") if isinstance(cfg, dict) else "") or ""
        if not base:
            return provider == "ollama"
        host = base.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0].strip("[]").lower()
        if host in ("localhost", "::1", "host.docker.internal") or host.endswith(".local"):
            return True
        try:
            import ipaddress
            ip = ipaddress.ip_address(host)
            return ip.is_loopback or ip.is_private
        except ValueError:
            return False

    async def pick(self, capability: str) -> tuple[str, str] | None:
        """A (provider, model) able to do `capability`: the current model if it can,
        otherwise the most recently verified one. Probes the current model if unknown."""
        cp, cm = self._current()
        known = self.supports(capability)
        if known is None and not self._is_cli(cp):
            await self.probe(cp, cm)
            known = self.supports(capability)
        if known:
            return cp, cm
        # Falling back means the content goes to ANOTHER provider than the chat's. Only
        # providers still in the config qualify, and a chat running on a local model never
        # falls back to a remote one: what the user kept on their machine stays there.
        providers = getattr(self.router.config, "providers", {}) or {}
        keep_local = self.is_local(cp)
        best: tuple[float, str, str] | None = None
        for k, caps in self._caps.items():
            if caps.get(capability) is not True or "::" not in k:
                continue
            p, m = k.split("::", 1)
            if p not in providers:
                continue  # provider was removed from the config
            if keep_local and not self.is_local(p):
                continue
            t = float(caps.get("tested_at") or 0)
            if best is None or t > best[0]:
                best = (t, p, m)
        return (best[1], best[2]) if best else None

    # ── raw completion against any configured provider ───────────────────────

    def _litellm_kwargs(self, provider: str, model: str) -> dict[str, Any]:
        cfg = (getattr(self.router.config, "providers", {}) or {}).get(provider) or {}
        base = cfg.get("base_url") if isinstance(cfg, dict) else None
        kwargs: dict[str, Any] = {}
        if provider in _NATIVE_PREFIX and not base:
            prefix = _NATIVE_PREFIX[provider]
            kwargs["model"] = model if model.startswith(prefix + "/") else f"{prefix}/{model}"
        elif provider == "openai" and not base:
            kwargs["model"] = model
        elif base:
            # OpenAI-compatible endpoint (ollama, opencode_go, xai with base_url, custom...)
            kwargs["model"] = model if model.startswith("openai/") else f"openai/{model}"
            kwargs["api_base"] = base
            kwargs["api_key"] = os.environ.get(f"{provider.upper()}_API_KEY", "") or "none"
        else:
            kwargs["model"] = model
        if provider == "opencode_go":
            kwargs["extra_headers"] = {"x-opencode-session": f"openacm-cap-{uuid.uuid4()}"}
        return kwargs

    async def complete(self, provider: str, model: str, messages: list[dict[str, Any]],
                       max_tokens: int = 500, timeout: float = PROBE_TIMEOUT_S) -> str:
        """One plain completion on a specific provider/model (no tools, no history).
        Raises on failure. CLI providers are not supported (they take text only)."""
        if self._is_cli(provider):
            raise RuntimeError(f"provider '{provider}' is a CLI provider and only takes text")
        import litellm

        resp = await litellm.acompletion(
            messages=messages, max_tokens=max_tokens, temperature=0, timeout=timeout,
            **self._litellm_kwargs(provider, model),
        )
        return (resp.choices[0].message.content or "").strip()

    # ── probing ──────────────────────────────────────────────────────────────

    async def _probe_one(self, provider: str, model: str, content: list[dict[str, Any]],
                         accept) -> tuple[bool | None, str]:
        """Returns (verdict, note). verdict None = inconclusive (not cached as a 'no')."""
        try:
            answer = await self.complete(provider, model, [{"role": "user", "content": content}], max_tokens=300)
        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {exc}"
            # The endpoint rejected the REQUEST SHAPE (HTTP 400/415/422): it does not take
            # this kind of input. Timeouts, 5xx, auth and rate limits stay "unknown".
            rejected = type(exc).__name__ in (
                "BadRequestError", "UnprocessableEntityError", "UnsupportedParamsError",
            ) or getattr(exc, "status_code", None) in (400, 415, 422)
            return (False if rejected or _looks_unsupported(msg) else None), msg[:200]
        if not answer:
            return None, "empty answer"
        return accept(answer.lower()), answer[:120]

    async def probe(self, provider: str | None = None, model: str | None = None,
                    force: bool = False) -> dict[str, Any]:
        """Measure what (provider, model) accepts. Cached unless force=True."""
        cp, cm = self._current()
        provider, model = provider or cp, model or cm
        k = self.key(provider, model)
        if not force and k in self._caps and all(self._caps[k].get(c) is not None for c in CAPABILITIES):
            return dict(self._caps[k])
        if self._is_cli(provider):
            result: dict[str, Any] = {"vision": False, "audio": False, "note": "CLI provider: text only"}
        else:
            png = base64.b64encode(_solid_png((220, 20, 20))).decode()
            wav = base64.b64encode(_beeps_wav(PROBE_BEEPS)).decode()
            (vision, vnote), (audio, anote) = await asyncio.gather(
                self._probe_one(provider, model, [
                    {"type": "text", "text": "What is the colour of this image? Answer with one word."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}},
                ], lambda a: any(w in a for w in ("red", "rojo", "crimson", "scarlet"))),
                self._probe_one(provider, model, [
                    {"type": "text", "text": "How many separate beeps are in this audio? Answer with a single digit."},
                    {"type": "input_audio", "input_audio": {"data": wav, "format": "wav"}},
                ], lambda a: (not any(d in a for d in _DENIAL_HINTS))
                and any(w in a for w in (str(PROBE_BEEPS), "four", "cuatro"))),
            )
            result = {"vision": vision, "audio": audio, "note": f"vision: {vnote} | audio: {anote}"}
        result["tested_at"] = time.time()
        result["v"] = PROBE_VERSION
        self._caps[k] = result
        await self._save()
        log.info("Model capabilities probed", provider=provider, model=model,
                 vision=result.get("vision"), audio=result.get("audio"))
        return dict(result)

    def schedule_probe(self, provider: str | None = None, model: str | None = None) -> None:
        """Probe in the background (called whenever a model is selected). Never raises."""
        try:
            cp, cm = self._current()
            provider, model = provider or cp, model or cm
            k = self.key(provider, model)
            if k in self._caps and all(self._caps[k].get(c) is not None for c in CAPABILITIES):
                return
            running = self._probing.get(k)
            if running and not running.done():
                return
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop yet (startup); it is probed on first use via pick()
        except Exception:  # noqa: BLE001
            return

        async def _run() -> None:
            try:
                await self.probe(provider, model)
            except Exception as exc:  # noqa: BLE001
                log.warning("Capability probe failed", provider=provider, model=model, error=str(exc))

        self._probing[k] = loop.create_task(_run())
