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


async def test_local_chat_never_falls_back_to_a_remote_provider():
    providers = {"ollama": {"base_url": "http://localhost:11434/v1"}, "cloud": {"base_url": "https://api.x.com/v1"},
                 "lan": {"base_url": "http://192.168.1.20:8000/v1"}}
    router = _router(provider="ollama", model="blind", providers=providers)
    caps = _caps(router, {("blind", "vision"): "I cannot see images", ("blind", "audio"): "no",
                          ("eyes", "vision"): "red", ("eyes", "audio"): "no"})
    assert caps.is_local("ollama") and caps.is_local("lan") and not caps.is_local("cloud")
    await caps.probe("cloud", "eyes")
    assert await caps.pick("vision") is None              # image stays on the machine
    await caps.probe("lan", "eyes")
    assert await caps.pick("vision") == ("lan", "eyes")   # another local provider is fine
    router.current_provider = "cloud"
    assert (await caps.pick("vision"))[1] == "eyes"       # a remote chat may use either


async def test_removed_provider_is_not_a_fallback():
    router = _router(model="blind", providers={"opencode_go": {"base_url": "https://x/v1"}})
    caps = _caps(router, {("blind", "vision"): "cannot", ("blind", "audio"): "no"})
    caps._caps["openai::gpt-x"] = {"vision": True, "audio": False, "tested_at": 1}
    assert await caps.pick("vision") is None


async def test_audio_probe_cannot_be_passed_by_saying_yes():
    """A model that cannot hear still answers "yes" to "is there a sound?": the probe counts beeps."""
    deaf = _caps(_router(), {("m1", "vision"): "Red.", ("m1", "audio"): "Yes, there is a sound."})
    assert (await deaf.probe("p1", "m1"))["audio"] is False
    guess = _caps(_router(), {("m1", "vision"): "Red.", ("m1", "audio"): "2"})
    assert (await guess.probe("p1", "m1"))["audio"] is False
    hears = _caps(_router(), {("m1", "vision"): "Red.", ("m1", "audio"): "4"})
    assert (await hears.probe("p1", "m1"))["audio"] is True


def test_beeps_wav_is_a_valid_file():
    from openacm.core.model_capabilities import _beeps_wav
    assert _beeps_wav(4)[:4] == b"RIFF"


async def test_old_audio_yes_is_forgotten_on_load():
    from openacm.core.model_capabilities import ModelCapabilities
    import json

    class DB:
        async def get_setting(self, key):
            return json.dumps({"p::m": {"vision": True, "audio": True, "tested_at": 1}})

    caps = ModelCapabilities(_router())
    await caps.load(DB())
    assert caps._caps["p::m"]["audio"] is None and caps._caps["p::m"]["vision"] is True


async def test_pick_measures_unverified_models_on_demand():
    """After an update the old "audio yes" is forgotten; the first audio must not fail for that."""
    router = _router(providers={"opencode_go": {"base_url": "https://x/v1"}, "gemini": {}})
    caps = _caps(router, {("m1", "vision"): "Red.", ("m1", "audio"): "no",
                          ("gem", "vision"): "Red.", ("gem", "audio"): "4"})
    caps._caps["opencode_go::m1"] = {"vision": True, "audio": False, "tested_at": 1}
    caps._caps["gemini::gem"] = {"vision": True, "audio": None, "tested_at": 2}   # forgotten by the update
    assert await caps.pick("audio") == ("gemini", "gem")
    assert caps._caps["gemini::gem"]["audio"] is True                             # and it stays measured
    assert [c for c in caps.calls if c[1] == "gem"]                               # it really probed it


async def test_pick_gives_up_when_nobody_hears():
    router = _router(providers={"opencode_go": {"base_url": "https://x/v1"}, "gemini": {}})
    caps = _caps(router, {("m1", "vision"): "Red.", ("m1", "audio"): "no",
                          ("gem", "vision"): "Red.", ("gem", "audio"): "I hear nothing"})
    caps._caps["opencode_go::m1"] = {"vision": True, "audio": False, "tested_at": 1}
    caps._caps["gemini::gem"] = {"vision": True, "audio": None, "tested_at": 2}
    assert await caps.pick("audio") is None
