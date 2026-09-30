# Voice

OpenACM can talk. There are two independent pieces:

1. **Text-to-speech in the dashboard** — the browser reads the assistant's replies aloud with a selectable TTS provider.
2. **The voice daemon** — an optional, always-on, server-side pipeline: microphone → speech detection → faster-whisper transcription → wake word → agent → spoken reply. It is controlled from the **Daemon** page.

Both are optional. For deployments without audio (servers, Docker, client installs) disable the daemon entirely with:

```yaml
# config/local.yaml
features:
  voice: false
```

---

## TTS Providers (dashboard)

| Provider id | Name | Runs | Key |
|-------------|------|------|-----|
| `kokoro` | Kokoro (offline) | In the browser (`kokoro-js`, ~80 MB model download, English/Spanish voices) | — |
| `browser` | Browser built-in | Web Speech API with your OS voices | — |
| `openai` | OpenAI TTS | OpenAI API | `OPENAI_API_KEY` |
| `elevenlabs` | ElevenLabs | ElevenLabs API | `ELEVENLABS_API_KEY` |

Choose the provider, voice and language in **Configuration → Voice Interface** (or on the Daemon page). The assistant's grammatical gender (set during onboarding or via `PATCH /api/config/assistant`) picks a matching default voice.

---

## The Voice Daemon

### Requirements

The daemon runs on the machine where OpenACM runs and uses **its** microphone and speakers. It needs extra Python packages:

```bash
pip install sounddevice faster-whisper numpy edge-tts
# or use the "install" button on the Daemon page (POST /api/voice/daemon/install)
```

(`pip install -e ".[voice]"` installs `sounddevice`, `faster-whisper`, `numpy` and `pyttsx3`; add `edge-tts` for server-side speech.) At startup the console shows `Voice daemon ready (sounddevice + faster-whisper)` or lists what is missing.

### How it works

```
microphone (16 kHz) → adaptive voice-activity detection → faster-whisper ("small" model)
      → wake word? → Brain (same agent as the chat) → edge-tts speech
```

| Mode | Behavior |
|------|----------|
| `passive` | Transcribes utterances but only forwards them when the **wake word** is heard |
| `active` | Every utterance goes straight to the agent; returns to passive after ~6 s of silence |
| `speaking` | Playing the reply; saying the wake word interrupts it |

- The **wake word is the assistant's name** (`assistant.name`, e.g. "ACM" or whatever you named it during onboarding).
- The noise floor is calibrated at start; utterances end after ~2 s of silence (max ~30 s).
- Echo of its own voice is suppressed for a few seconds after speaking.
- Spoken replies use an edge-tts neural voice (`GET /api/voice/server-tts/voices`), e.g. `es-MX-DaliaNeural`.
- State changes are broadcast as `voice:daemon_state` events, which drive the animated companion on the Daemon page (with selectable skins).

### Controlling it

| Endpoint | Description |
|----------|-------------|
| `GET /api/voice/daemon/status` | Running state, mode and dependency check |
| `POST /api/voice/daemon/start` | Start (optional `{"mic_device": <index or name>}`; otherwise the saved device) |
| `POST /api/voice/daemon/stop` | Stop |
| `GET /api/voice/devices` | Audio input devices on the server |
| `GET /api/voice/model/status` | Availability of the server-side models |
| `GET/PATCH /api/voice/config` | Saved voice settings (provider, voices, microphone, STT language…) |

---

## Troubleshooting

- **"Missing dependencies: pip install …"** — install the listed packages into OpenACM's virtualenv and restart the daemon.
- **Nothing is transcribed** — check the selected microphone (`/api/voice/devices`) and that the process has microphone permission (macOS asks the first time).
- **It never reacts** — you're in passive mode: start the sentence with the assistant's name.
- **Running on a server** — there is usually no audio device; disable the daemon (`features.voice: false`) and use browser TTS only.
