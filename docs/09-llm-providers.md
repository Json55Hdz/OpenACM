# LLM Providers

OpenACM uses **LiteLLM** as a unified LLM interface, supporting 100+ providers. All providers are accessed through the same internal API regardless of who hosts them.

---

## Built-in Providers

### Ollama (Local)
Run models 100% locally. No API key. No internet. No cost.

```yaml
llm:
  default_provider: ollama
  providers:
    ollama:
      base_url: "http://localhost:11434"
      default_model: "llama3.2"
```

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
  providers:
    openai:
      base_url: "https://api.openai.com/v1"
      default_model: "gpt-4o"
      api_key: "${OPENAI_API_KEY}"
```

**Available models:** `gpt-4o`, `gpt-4o-mini`, `o1`, `o1-mini`, `o3-mini`

---

### Anthropic (Claude)

```yaml
llm:
  providers:
    anthropic:
      base_url: "https://api.anthropic.com"
      default_model: "claude-opus-4-6"
      api_key: "${ANTHROPIC_API_KEY}"
```

**Available models:** `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`

---

### Google Gemini

```yaml
llm:
  providers:
    gemini:
      base_url: "https://generativelanguage.googleapis.com"
      default_model: "gemini-2.0-flash"
      api_key: "${GEMINI_API_KEY}"
```

**Available models:** `gemini-2.0-flash`, `gemini-1.5-pro`, `gemini-1.5-flash`

---

### Groq (Fast Inference)

```yaml
llm:
  providers:
    groq:
      base_url: "https://api.groq.com/openai/v1"
      default_model: "llama-3.3-70b-versatile"
      api_key: "${GROQ_API_KEY}"
```

Groq provides extremely fast inference (~500 tokens/second). Excellent for real-time applications.

---

### Together AI

```yaml
llm:
  providers:
    together:
      base_url: "https://api.together.xyz/v1"
      default_model: "meta-llama/Llama-3-70b-chat-hf"
      api_key: "${TOGETHER_API_KEY}"
```

---

### Mistral

```yaml
llm:
  providers:
    mistral:
      base_url: "https://api.mistral.ai/v1"
      default_model: "mistral-large-latest"
      api_key: "${MISTRAL_API_KEY}"
```

---

## Custom Providers (OpenAI-Compatible)

Any server that speaks the OpenAI API can be added as a custom provider. This includes:
- **LM Studio** (local model server)
- **vLLM** (self-hosted high-performance inference)
- **LocalAI** (local model server)
- **Kobold.cpp** (local GGUF model runner)
- **Perplexity AI**
- **DeepSeek API**
- **Fireworks AI**

### Via Dashboard
Go to **Config** → **Custom Providers** → **Add Provider**.

### Via `config/custom_providers.json`
```json
[
  {
    "id": "lmstudio_001",
    "name": "LM Studio",
    "base_url": "http://localhost:1234/v1",
    "default_model": "lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF",
    "api_key": ""
  },
  {
    "id": "deepseek_api",
    "name": "DeepSeek",
    "base_url": "https://api.deepseek.com/v1",
    "default_model": "deepseek-chat",
    "api_key": "sk-..."
  }
]
```

---

## Switching Models

### Mid-Conversation (Chat)
```
You> /model anthropic/claude-opus-4-6
You> /model ollama/llama3.2
You> /model my_custom_provider/my-model
```

### Via Dashboard
Go to **Config** → **Current Model** → select from dropdown.

### Via API
```bash
curl -X POST http://localhost:47821/api/config/model \
  -H "Authorization: Bearer acm_xxx" \
  -H "Content-Type: application/json" \
  -d '{"provider": "ollama", "model": "llama3.2"}'
```

The selected model is persisted — it survives restarts.

---

## Provider Profiles

Some providers have quirks that OpenACM handles automatically:

| Provider | Quirk | How OpenACM handles it |
|----------|-------|----------------------|
| Gemini | Strict message format (no adjacent same-role messages) | Message reordering |
| Some local models | Don't support native tool calling | Text-based tool enforcement |
| Groq | Tool count limits | Automatic capping |
| Thinking models (DeepSeek R1, Kimi) | Emit reasoning tokens | Stored but stripped from old context |

---

## Token Usage Tracking

All LLM calls are logged to the database with:
- Model and provider
- Prompt tokens, completion tokens, total tokens
- Elapsed milliseconds

View in the dashboard: **Dashboard** → **Activity Chart** (tokens over time) or **Stats** (totals).

---

## Choosing a Provider

| Priority | Recommendation |
|----------|---------------|
| Privacy first | Ollama (local) |
| Best quality | Anthropic Claude Opus or OpenAI GPT-4o |
| Fastest responses | Groq |
| Lowest cost | Ollama (free) or Gemini Flash |
| Best tool use | OpenAI GPT-4o or Anthropic Claude |
| Code tasks | Ollama qwen2.5-coder or OpenAI o3-mini |
| Reasoning | DeepSeek R1 or OpenAI o1 |
