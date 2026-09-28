# LLM Providers

OpenACM uses **LiteLLM** as a unified LLM interface, supporting 100+ providers. All providers are accessed through the same internal API regardless of who hosts them.

---

## How providers are configured

- **Provider settings** (`base_url`, `default_model`) live under `llm.providers` in `config/default.yaml`; put your changes in `config/local.yaml`, which overrides it and is not touched by updates.
- **API keys** are always read from environment variables named **`<PROVIDER_ID>_API_KEY`** (uppercase) — e.g. `OPENAI_API_KEY`, `OPENCODE_GO_API_KEY`. Put them in `config/.env`, or enter them in the onboarding wizard / **Configuration**, which writes `config/.env` for you. An `api_key` field inside the YAML is not used.
- **`llm.default_provider`** selects the provider used at startup. Once you pick a model in the dashboard (or with `/model`), that choice is persisted in the database and restored on restart.

---

## Built-in Providers

These providers are preconfigured in `config/default.yaml`:

| Provider id | Default model | Base URL | API key env var |
|-------------|---------------|----------|-----------------|
| `opencode_go` (default) | `kimi-k2.5` | `https://opencode.ai/zen/go/v1` | `OPENCODE_GO_API_KEY` |
| `openai` | `gpt-4o` | LiteLLM default | `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-4-20250514` | LiteLLM default | `ANTHROPIC_API_KEY` |
| `gemini` | `gemini-2.5-flash` | LiteLLM default | `GEMINI_API_KEY` |
| `xai` | `grok-4.20-0309-non-reasoning` | `https://api.x.ai/v1` | `XAI_API_KEY` |
| `openrouter` | `openrouter/auto` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| `ollama` | `llama3.2` | `http://localhost:11434` | — |

### Ollama (Local)
Run models 100% locally. No API key. No internet. No cost.

```yaml
# config/local.yaml
llm:
  default_provider: ollama
  providers:
    ollama:
      base_url: "http://localhost:11434"
      default_model: "llama3.2"
```

Ollama is called through its OpenAI-compatible `/v1` endpoint. `GET /api/ollama/status` reports whether Ollama is running and which models are installed.

**Recommended models for OpenACM:**
| Model | Size | Best for |
|-------|------|----------|
| `llama3.2` | 2GB | Fast general purpose |
| `llama3.1:8b` | 5GB | Better reasoning |
| `llama3.3:70b` | 40GB | Best quality local |
| `qwen2.5-coder` | 4GB | Code tasks |
| `mistral` | 4GB | Instruction following |
| `deepseek-r1` | 7GB+ | Complex reasoning |

Install models: `ollama pull llama3.2`

---

### OpenAI

```yaml
llm:
  default_provider: openai
  providers:
    openai:
      default_model: "gpt-4o"
```
```env
OPENAI_API_KEY=sk-...
```

---

### Anthropic (Claude)

```yaml
llm:
  default_provider: anthropic
  providers:
    anthropic:
      default_model: "claude-sonnet-4-20250514"
```
```env
ANTHROPIC_API_KEY=sk-ant-...
```

---

### Google Gemini

```yaml
llm:
  default_provider: gemini
  providers:
    gemini:
      default_model: "gemini-2.5-flash"
```
```env
GEMINI_API_KEY=AIza...
```

---

### OpenCode Go, xAI, OpenRouter

These are OpenAI-compatible endpoints preconfigured with a `base_url`. Just add the key (`OPENCODE_GO_API_KEY`, `XAI_API_KEY`, `OPENROUTER_API_KEY`) and select the provider. For OpenCode Go, OpenACM sends a per-conversation `x-opencode-session` header.

---

### Any other LiteLLM provider

Add an entry with a `base_url` for any OpenAI-compatible API (Groq, Together, Mistral, DeepSeek…), and the matching `<ID>_API_KEY`:

```yaml
llm:
  providers:
    groq:
      base_url: "https://api.groq.com/openai/v1"
      default_model: "llama-3.3-70b-versatile"
```
```env
GROQ_API_KEY=gsk_...
```

---

## Custom Providers (OpenAI-Compatible)

Any server that speaks the OpenAI API can be added as a custom provider from the dashboard, with its key stored alongside it. This includes:
- **LM Studio** (local model server)
- **vLLM** (self-hosted high-performance inference)
- **LocalAI** (local model server)
- **Kobold.cpp** (local GGUF model runner)
- **Perplexity AI**
- **DeepSeek API**
- **Fireworks AI**

### Via Dashboard
Go to **Configuration** → **Custom Providers** → **Add Provider**. The provider id is derived from the name (snake_case).

### Via `config/custom_providers.json`
```json
[
  {
    "id": "lm_studio",
    "name": "LM Studio",
    "base_url": "http://localhost:1234/v1",
    "default_model": "lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF",
    "api_key": ""
  },
  {
    "id": "deepseek",
    "name": "DeepSeek",
    "base_url": "https://api.deepseek.com/v1",
    "default_model": "deepseek-chat",
    "api_key": "sk-..."
  }
]
```

On startup each custom provider is injected into the live config and its `api_key` is exported as `<ID>_API_KEY`. The file is git-ignored because it may contain keys.

---

## CLI Providers

If the `claude`, `gemini` or `opencode` CLI is installed and logged in, OpenACM auto-detects it at startup and adds `cli_claude` / `cli_gemini` / `cli_opencode` as providers — no API key needed. See [CLI Providers](./21-cli-providers.md).

---

## Switching Models

### Mid-Conversation (Chat)
```
You> /model anthropic/claude-sonnet-4-6
You> /model ollama/llama3.2
You> /model my_custom_provider/my-model
```

A `provider/model` string also switches the provider. The agent can do the same with the `switch_llm_model` tool.

### Via Dashboard
Go to **Configuration** → **Model** → pick a provider and model (`GET /api/config/available_models` lists the models the current provider exposes).

### Via API
```bash
curl -X POST http://localhost:47821/api/config/model \
  -H "Authorization: Bearer <dashboard-token>" \
  -H "Content-Type: application/json" \
  -d '{"provider": "ollama", "model": "llama3.2"}'
```

The selected model is persisted — it survives restarts.

---

## Per-model Parameters

`temperature`, `max_tokens` and `top_p` can be saved per provider + model from the dashboard or via `PATCH /api/config/model-params` (`{"provider": "...", "model": "...", "temperature": 0.3}`). They are persisted in the database.

---

## Context Window Overrides

OpenACM sizes compaction and truncation from each model's context window, as reported by LiteLLM (128K is assumed when unknown). For models LiteLLM doesn't know, set it yourself:

```yaml
llm:
  model_context_overrides:
    kimi: 131072         # substring of the model name → tokens
    deepseek-r1: 65536
```

---

## Timeouts and Retries

- `llm.timeout` — seconds to wait for any LLM response (`0` = no timeout, the default)
- Transient failures (5xx, dropped connections) and **HTTP 429 rate limits** are retried with exponential backoff and jitter; a `Retry-After` header is honored

---

## Provider Profiles

Some providers have quirks that OpenACM handles automatically:

| Provider | Quirk | How OpenACM handles it |
|----------|-------|----------------------|
| Gemini | Strict message format; tool limits | Message normalization, max 15 tools per call |
| Ollama / local models | Weak native tool calling | Tool-use enforcement message, max 10 tools per call |
| OpenCode Go | Proxy fails with `tool_choice="required"` | Always `auto`, no enforcement |
| Unknown / custom | — | Conservative defaults (enforcement on, max 15 tools) |
| Thinking models (DeepSeek R1, Kimi) | Emit reasoning tokens / `<think>` tags | Tags stripped from the answer; reasoning streamed to the dashboard and stripped from old context |

---

## Token Usage Tracking

All LLM calls are logged to the database with:
- Model and provider
- Prompt tokens, completion tokens, total tokens
- Estimated cost (from LiteLLM's pricing table; 0 when unknown)
- Elapsed milliseconds

View in the dashboard: **Dashboard** (tokens over time, totals) or `/stats` in chat.

---

## Choosing a Provider

| Priority | Recommendation |
|----------|---------------|
| Privacy first | Ollama (local) |
| Best quality | Anthropic Claude or OpenAI GPT-4o-class models |
| Low cost, good tool use | OpenCode Go (Kimi) or Gemini Flash |
| No API billing | A CLI provider using your existing subscription |
| Code tasks | Claude, GPT, or Ollama `qwen2.5-coder` |
| Reasoning | DeepSeek R1 or OpenAI o-series |

See also [LLM Pricing Reference](./LLM_PRICING_REFERENCE.md).
