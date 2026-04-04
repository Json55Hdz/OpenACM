# Configuration

OpenACM is configured through `config/default.yaml` and `config/.env`. Environment variables can be referenced in the YAML using `${VAR_NAME}` syntax.

---

## Full Configuration Schema

```yaml
# config/default.yaml

assistant:
  name: "ACM"                        # Agent display name
  system_prompt: "You are ACM..."    # Custom personality/instructions
  max_context_messages: 50           # Max messages in active context window
  max_tool_iterations: 20            # Max agentic loop iterations per request
  response_timeout: 120              # Seconds before LLM call times out

llm:
  default_provider: ollama           # Active provider
  providers:
    ollama:
      base_url: "http://localhost:11434"
      default_model: "llama3.2"
    openai:
      base_url: "https://api.openai.com/v1"
      default_model: "gpt-4o"
      api_key: "${OPENAI_API_KEY}"
    anthropic:
      base_url: "https://api.anthropic.com"
      default_model: "claude-opus-4-6"
      api_key: "${ANTHROPIC_API_KEY}"
    gemini:
      base_url: "https://generativelanguage.googleapis.com"
      default_model: "gemini-2.0-flash"
      api_key: "${GEMINI_API_KEY}"

security:
  execution_mode: "auto"             # "confirmation" | "auto" | "yolo"
  whitelisted_commands: []           # Always allow these commands in confirmation mode
  blocked_patterns:                  # Regex patterns to block in commands
    - "rm -rf /"
    - "format c:"
  blocked_paths:                     # File paths the agent cannot access
    - "/etc/shadow"
    - "C:/Windows/System32/config/SAM"
  max_command_timeout: 120           # Seconds before command is killed
  max_output_length: 50000           # Max characters of command output kept

web:
  host: "127.0.0.1"                  # Bind address (use 0.0.0.0 for network access)
  port: 47821                        # Dashboard port
  auth_enabled: true                 # Require token for all endpoints

channels:
  discord:
    enabled: false
    token: "${DISCORD_TOKEN}"
    command_prefix: "!"
    respond_to_mentions: true
    respond_to_dms: true
    allowed_guilds: []               # Empty = all guilds

  telegram:
    enabled: false
    token: "${TELEGRAM_TOKEN}"
    allowed_users: []                # Empty = all users; list user IDs to restrict

  whatsapp:
    enabled: false
    bridge_url: "http://localhost:3001"
    rate_limit_per_minute: 20

storage:
  database_path: "data/openacm.db"
  workspace_path: "workspace"        # Where generated files are saved
  log_conversations: true
  log_tool_executions: true

local_router:
  enabled: true                      # Enable LocalRouter (intent classification)
  observation_mode: false            # true = observe only; false = enable fast-path
  confidence_threshold: 0.88        # Minimum confidence to use fast-path
```

---

## Environment Variables

Create `config/.env`:

```env
# ── LLM Providers ─────────────────────────────────────────────────────────────
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIzaSy...
GROQ_API_KEY=gsk_...
TOGETHER_API_KEY=...
MISTRAL_API_KEY=...

# ── Messaging Channels ─────────────────────────────────────────────────────────
TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
DISCORD_TOKEN=...

# ── Google Workspace ──────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
# (Google refresh token is stored automatically after OAuth2 flow)

# ── Optional ──────────────────────────────────────────────────────────────────
STITCH_API_KEY=...     # For Stitch UI generation tool
```

---

## Custom LLM Providers

Any OpenAI-compatible API endpoint can be added as a custom provider through the dashboard (`/config` → Custom Providers) or by editing `config/custom_providers.json` directly.

```json
[
  {
    "id": "lmstudio_abc123",
    "name": "LM Studio",
    "base_url": "http://localhost:1234/v1",
    "default_model": "local-model-identifier",
    "api_key": ""
  },
  {
    "id": "groq_custom",
    "name": "Groq (custom)",
    "base_url": "https://api.groq.com/openai/v1",
    "default_model": "llama-3.3-70b-versatile",
    "api_key": "gsk_..."
  }
]
```

Custom providers appear alongside built-in providers in model switching.

---

## MCP Server Configuration

Stored in `config/mcp_servers.json`:

```json
[
  {
    "name": "filesystem",
    "transport": "stdio",
    "command": "python",
    "args": ["-m", "mcp_filesystem", "/home/user"],
    "env": {},
    "auto_connect": true
  },
  {
    "name": "remote-api",
    "transport": "sse",
    "url": "http://localhost:8000/sse",
    "auto_connect": false
  }
]
```

---

## Security Configuration Details

### Execution Modes

**`confirmation`** — Safest. User must approve tool calls rated `medium` or `high` risk before execution.

**`auto`** — Balanced. Tools execute automatically but blocked patterns are still enforced. Good default for trusted personal use.

**`yolo`** — Maximum capability. All tools execute immediately. Useful for automated pipelines where you've reviewed what the agent will do.

### Blocked Patterns

Patterns are matched against command strings before execution. Use with caution — too-aggressive blocking can break legitimate tasks.

```yaml
security:
  blocked_patterns:
    - "rm -rf /"          # Prevent recursive root deletion
    - "dd if=/dev/zero"   # Prevent disk wipe
    - "> /dev/sda"        # Prevent raw disk write
```

### Blocked Paths

File paths the agent cannot read or write. System credential files are always blocked regardless of this setting.

```yaml
security:
  blocked_paths:
    - "/etc/passwd"
    - "C:/Users/*/AppData/Roaming/credentials"
```

---

## Web Dashboard Access

By default, the dashboard is only accessible from `localhost`. To expose it on your network:

```yaml
web:
  host: "0.0.0.0"   # Bind to all interfaces
  port: 47821
```

> ⚠️ **Warning:** Exposing OpenACM to the network gives anyone with the token full access to your computer. Use a VPN or reverse proxy with HTTPS if accessing remotely.

---

## Workspace Directory

All files generated by OpenACM (screenshots, reports, code, etc.) are saved to the workspace directory unless you specify another path.

```yaml
storage:
  workspace_path: "workspace"   # Relative to OpenACM root
```

Files in the workspace are accessible via the `/api/media/` endpoints.

---

## LocalRouter Configuration

The LocalRouter is the offline intent classifier. By default it runs in observation mode (classifying silently, never changing behavior). To enable fast-path execution (skipping the LLM for recognized simple intents):

```yaml
local_router:
  enabled: true
  observation_mode: false       # Allow fast-path execution
  confidence_threshold: 0.88   # How confident before skipping LLM
```

**Threshold guidance:**
- `0.95+` — Very conservative, rarely skips LLM. Almost no misclassifications.
- `0.88` — Default. Good balance for recognized intents like screenshots and system info.
- `0.80` — More aggressive fast-pathing. May occasionally misclassify.

---

## Agent Persona

The `system_prompt` in `assistant` config sets the base persona for the main OpenACM agent. The OpenACM identity context is always prepended, so you don't need to repeat capability descriptions. Use this for personality and domain-specific instructions:

```yaml
assistant:
  name: "Jarvis"
  system_prompt: |
    You are Jarvis, a highly capable AI assistant.
    Always respond in a professional tone.
    Prefer concise answers unless detail is specifically requested.
    When executing code, always explain what you're about to do first.
```
