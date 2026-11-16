"""Audio attachments are transcribed by a model that really takes audio, no Whisper needed."""
from openacm.core.brain_multimodal import BrainMultimodalMixin


class _Caps:
    def __init__(self, target):
        self.target, self.sent = target, None

    async def pick(self, capability):
        assert capability == "audio"
        return self.target

    async def complete(self, provider, model, messages, **kw):
        self.sent = (provider, model, messages)
        return "hola, esto es una prueba"


class _Host(BrainMultimodalMixin):
    def __init__(self, caps):
        self.llm_router = type("R", (), {"capabilities": caps})()


async def test_audio_goes_to_a_capable_model():
    caps = _Caps(("gemini", "gemini-4-hydrogen"))
    out = await _Host(caps)._transcribe_audio(b"RIFFxxxx", ".wav")
    assert out == "hola, esto es una prueba"
    part = caps.sent[2][0]["content"][1]
    assert part["type"] == "input_audio" and part["input_audio"]["format"] == "wav"


async def test_without_a_capable_model_it_falls_back(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    caps = _Caps(None)
    await _Host(caps)._transcribe_audio(b"not audio", ".wav")
    assert caps.sent is None  # nothing was sent to a model; Whisper/MarkItDown fallbacks took over
