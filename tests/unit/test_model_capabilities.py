"""Measured model capabilities: probing, caching, picking a capable model."""
import struct
import zlib
from types import SimpleNamespace

import pytest

from openacm.core.model_capabilities import ModelCapabilities, _solid_png, _tone_wav


class FakeDB:
    def __init__(self):
        self.data = {}

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value


def _router(provider="opencode_go", model="m1", providers=None):
    return SimpleNamespace(
        current_provider=provider, current_model=model,
        config=SimpleNamespace(providers=providers if providers is not None else {
            "opencode_go": {"base_url": "https://x/v1"}, "cli_claude": {"type": "cli"},
        }),
    )


def _caps(router, answers):
    """answers: {(model, 'vision'|'audio'): str | Exception}"""
    caps = ModelCapabilities(router)
    calls = []

    async def complete(provider, model, messages, max_tokens=500, timeout=45):
        kind = "vision" if any(p.get("type") == "image_url" for p in messages[0]["content"]) else "audio"
        calls.append((provider, model, kind))
        out = answers[(model, kind)]
        if isinstance(out, Exception):
            raise out
        return out

    caps.complete = complete
    caps.calls = calls
    return caps


def test_probe_assets_are_valid_files():
    png = _solid_png((220, 20, 20))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", png[16:24]) == (96, 96)
    assert zlib.crc32(png[12:29]) & 0xFFFFFFFF == struct.unpack(">I", png[29:33])[0]
    assert _tone_wav()[:4] == b"RIFF"


async def test_probe_marks_what_the_model_really_does_and_persists():
    db = FakeDB()
    caps = _caps(_router(), {("m1", "vision"): "Red.", ("m1", "audio"): RuntimeError("this model does not support audio input")})
    await caps.load(db)
    got = await caps.probe()
    assert got["vision"] is True and got["audio"] is False
    assert caps.supports("vision") is True
    # cached: a second probe makes no requests; a fresh instance reads it from the database
    n = len(caps.calls)
    await caps.probe()
    assert len(caps.calls) == n
    again = ModelCapabilities(_router())
    await again.load(db)
    assert again.supports("vision") is True and again.supports("audio") is False


async def test_transient_error_is_unknown_not_no():
    caps = _caps(_router(), {("m1", "vision"): TimeoutError("timed out"), ("m1", "audio"): ""})
    got = await caps.probe()
    assert got["vision"] is None and got["audio"] is None
    assert caps.supports("vision") is None


async def test_wrong_answer_means_no_vision():
    caps = _caps(_router(), {("m1", "vision"): "I cannot see images.", ("m1", "audio"): "I can't hear audio."})
    got = await caps.probe()
    assert got["vision"] is False and got["audio"] is False


async def test_cli_provider_is_text_only_without_requests():
    caps = _caps(_router(provider="cli_claude", model="claude"), {})
    got = await caps.probe()
    assert got["vision"] is False and caps.calls == []


async def test_pick_prefers_current_model_then_falls_back_to_a_verified_one():
    router = _router(model="blind")
    caps = _caps(router, {
        ("blind", "vision"): "I cannot view images", ("blind", "audio"): "no",
        ("eyes", "vision"): "red", ("eyes", "audio"): "no",
    })
    assert await caps.pick("vision") is None            # nothing verified yet
    await caps.probe("opencode_go", "eyes")
    assert await caps.pick("vision") == ("opencode_go", "eyes")   # current is blind -> fallback
    router.current_model = "eyes"
    assert await caps.pick("vision") == ("opencode_go", "eyes")   # current can -> use it


def test_litellm_kwargs_per_provider(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")
    caps = ModelCapabilities(_router(providers={"opencode_go": {"base_url": "https://x/v1"}, "anthropic": {}}))
    kw = caps._litellm_kwargs("opencode_go", "qwen")
    assert kw["model"] == "openai/qwen" and kw["api_base"] == "https://x/v1" and kw["api_key"] == "k"
    assert "x-opencode-session" in kw["extra_headers"]
    assert caps._litellm_kwargs("anthropic", "claude-x")["model"] == "anthropic/claude-x"
    assert caps._litellm_kwargs("openai", "gpt-x") == {"model": "gpt-x"}
