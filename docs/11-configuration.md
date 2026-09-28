# Configuration

OpenACM is configured through YAML files in `config/` plus environment variables. Most settings can also be changed from the dashboard (**Configuration**) or the terminal wizard (`openacm-setup`), which write these same files.

---

## Where configuration comes from

| Source | Committed? | Purpose |
|--------|-----------|---------|
| `config/default.yaml` | Yes | Base configuration shipped with OpenACM |
| `config/local.yaml` | No (git-ignored) | Your overrides — deep-merged on top of `default.yaml`. The dashboard and wizard write here |
| `config/.env` | No (git-ignored) | API keys, tokens and secrets (loaded into the environment at startup) |
| Environment variables | — | Override `.env`; referenced from YAML with `${VAR_NAME}` |
| Database settings | — | Runtime choices persisted in SQLite: selected model, per-model params, security mode, plugin settings |

**Priority:** env vars > `config/.env` > `local.yaml` > `default.yaml` > built-in defaults. A YAML value written as `"${VAR_NAME}"` is replaced by that environment variable.

> Prefer `config/local.yaml` for your changes. `update.sh`/`update.bat` pull new versions of `default.yaml`, while `local.yaml` is never touched.

---

## Full Configuration Schema

Defaults shown are the built-in defaults; where the shipped `default.yaml` sets something different it is noted.

```yaml
assistant:
  name: "ACM"                        # Agent display name
  system_prompt: "You are ACM..."    # Base persona/instructions (default.yaml ships a longer one)
  max_context_messages: 50           # Max messages kept in the active context window
  max_tool_iterations: 20            # Max agentic loop iterations per request (default.yaml: 25)
  response_timeout: 120              # Seconds
  rag_relevance_threshold: 0.5       # Max cosine distance for automatic memory recall (0 = identical, 1 = unrelated)
  compact_ratio: 0.60                # Compact when context reaches this fraction of the model's window
  compact_keep_recent: 6             # Messages kept verbatim after compaction
  onboarding_completed: false        # Set by the onboarding flow

llm:
  default_provider: "opencode_go"    # built-in default is "ollama"; default.yaml sets opencode_go
  timeout: 0                         # Seconds to wait for any LLM response; 0 = no timeout
  model_context_overrides: {}        # e.g. {"kimi": 131072} — context window for models LiteLLM doesn't know
  providers:
    opencode_go:
      base_url: "https://opencode.ai/zen/go/v1"
      default_model: "kimi-k2.5"
    openai:
      default_model: "gpt-4o"
    anthropic:
      default_model: "claude-sonnet-4-20250514"
    gemini:
      default_model: "gemini-2.5-flash"
    xai:
      base_url: "https://api.x.ai/v1"
      default_model: "grok-4.20-0309-non-reasoning"
    openrouter:
      base_url: "https://openrouter.ai/api/v1"
      default_model: "openrouter/auto"
    ollama:
      base_url: "http://localhost:11434"
      default_model: "llama3.2"
    # CLI providers (cli_claude, cli_gemini, cli_opencode) are added automatically
    # when their binary is on PATH — see 21-cli-providers.md

security:
  execution_mode: "confirmation"     # "confirmation" | "auto" | "yolo"
  whitelisted_commands: [ls, dir, cat, git, python, pip, npm, node, ...]  # the only commands allowed in auto mode
  blocked_patterns:                  # Substrings (case-insensitive) that block a command
    - "rm -rf /"
    - "mkfs"
    - "shutdown"
  blocked_paths:                     # Paths the agent cannot touch (file tools and shell commands)
    - "/etc/shadow"
    - "config/"
    - "data/openacm.db"
    - "data/vectordb"
  max_command_timeout: 120           # Seconds; 0 = no limit (default.yaml: 0)
  max_output_length: 50000           # Max characters of command output kept

web:
  host: "127.0.0.1"                  # Bind address (use 0.0.0.0 for network/Docker access)
  port: 47821                        # Dashboard port
  auth_enabled: true

channels:
  discord:
    enabled: false
    token: ""                        # or DISCORD_TOKEN in .env
    command_prefix: "!"
    respond_to_mentions: true
    respond_to_dms: true
    allowed_guilds: []               # present in the schema, not enforced in v0.4.7

  telegram:
    enabled: false                   # auto-enabled when TELEGRAM_TOKEN is set
    token: ""                        # or TELEGRAM_TOKEN in .env
    allowed_users: []                # Empty = all users; list user IDs as strings to restrict

  whatsapp:
    enabled: false                   # auto-enabled once credentials are present
    mode: "cloud_api"                # "cloud_api" (official Meta API) | "bridge" (legacy)
    rate_limit_per_minute: 20
    access_token: ""                 # prefer WHATSAPP_ACCESS_TOKEN in .env
    phone_number_id: ""              # prefer WHATSAPP_PHONE_NUMBER_ID
    verify_token: ""                 # prefer WHATSAPP_VERIFY_TOKEN
    app_secret: ""                   # prefer WHATSAPP_APP_SECRET
    graph_api_version: "v21.0"
    bridge_url: "http://localhost:3001"   # only for mode: bridge

storage:
  database_path: "data/openacm.db"
  workspace_path: "workspace"        # Where generated files are saved
  log_conversations: true
  log_tool_executions: true

local_router:
  enabled: true                      # Enable LocalRouter (intent classification)
  observation_mode: false            # true = observe only; false = fast-path active
  confidence_threshold: 0.88         # Minimum confidence to use fast-path

resurrection_paths: []               # Folders indexed by Code Resurrection

features:                            # Heavy/optional subsystems (both default to true)
  browser_agent: true                # false = don't register the Playwright browser_agent tool
  voice: true                        # false = don't create the voice daemon at all

client_profile:                      # Restrict the dashboard for a client deployment
  active: false
  name: "Cliente"
  allowed_pages: []                  # e.g. ["/chat", "/gmail-classifier", "/swarms"]
```

Relative `database_path` and `workspace_path` are resolved against the project root.

### The `A:` block

The onboarding flow (`save_user_profile`) and the setup wizard save your profile to `config/local.yaml` under a key named `A:` (assistant name, the generated system prompt, `onboarding_completed`, …). At load time `A:` is merged over `assistant:`, so both forms work.

---

## Environment Variables

Create `config/.env` (the setup script copies `config/.env.example`):

```env
# ── LLM Providers (pattern: <PROVIDER_ID>_API_KEY) ───────────────────────────
OPENCODE_GO_API_KEY=...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIzaSy...
XAI_API_KEY=xai-...
OPENROUTER_API_KEY=sk-or-...
# Any provider you add under llm.providers, e.g. GROQ_API_KEY=gsk_...

# ── Messaging Channels ────────────────────────────────────────────────────────
TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
DISCORD_TOKEN=...
WHATSAPP_ACCESS_TOKEN=EAAG...
WHATSAPP_PHONE_NUMBER_ID=123456789012345
WHATSAPP_VERIFY_TOKEN=any-string-you-choose
WHATSAPP_APP_SECRET=...
# WHATSAPP_MODE=cloud_api            # or bridge
# WHATSAPP_BRIDGE_URL=http://localhost:3001

# ── Web Dashboard ─────────────────────────────────────────────────────────────
DASHBOARD_TOKEN=                     # auto-generated and written here on first start

# ── Optional ──────────────────────────────────────────────────────────────────
STITCH_API_KEY=...                   # Google Stitch UI generation tool
ELEVENLABS_API_KEY=...               # ElevenLabs TTS provider
STABILITY_API_KEY=...                # image-generation mode of generate_meme
OPENACM_VERBOSE_CHANNELS=true        # send tool logs to external channels
```

Google Workspace does not use environment variables: upload the OAuth client JSON in **Configuration → Google Services** (stored as `config/google_credentials.json`; the token is saved to `config/google_token.json`). See [Gmail Setup](./GMAIL_SETUP.md).

OpenACM also sets some variables for its own components at runtime (`OPENACM_PORT`, `OPENACM_WORKSPACE`, `OPENACM_PROJECT_ROOT`) — you don't need to set them.

---

## Other files in `config/`

| File | Contents |
|------|----------|
| `custom_providers.json` | Custom OpenAI-compatible providers (see below) |
| `mcp_servers.json` | MCP server definitions |
| `activity.key` | Local encryption key for messages and activity data — back it up with the database |
| `google_credentials.json` / `google_token.json` | Google OAuth |

All of these are git-ignored.

---

## Custom LLM Providers

Any OpenAI-compatible API endpoint can be added as a custom provider through the dashboard (**Configuration → Custom Providers**) or by editing `config/custom_providers.json` directly.

```json
[
  {
    "id": "lm_studio",
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

Stored in `config/mcp_servers.json` (managed by the **MCP** page):

```json
{
  "servers": [
    {
      "name": "filesystem",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
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
}
```

See [MCP Integration](./13-mcp.md).

---

## Security Configuration Details

### Execution Modes

The execution mode applies to shell commands run through `run_command`.

**`confirmation`** (default) — Safest. Every command is shown in the dashboard for approval before it runs.

**`auto`** — Only commands whose executable is listed in `whitelisted_commands` run; anything else is rejected. Blocked patterns and paths are still enforced.

**`yolo`** — Every command runs immediately (hardcoded blocks, blocked patterns and blocked paths still apply). Useful for automated pipelines where you've reviewed what the agent will do.

The mode can be changed at runtime from the dashboard, with `PATCH /api/config/security`, or with the `update_security_mode` tool; the choice is persisted in the database and restored on restart.

### Blocked Patterns

Patterns are matched as case-insensitive substrings against command strings before execution. Use with caution — too-aggressive blocking can break legitimate tasks (note that the shipped list includes short words such as `format` and `shutdown`).

```yaml
security:
  blocked_patterns:
    - "rm -rf /"          # Prevent recursive root deletion
    - "dd if=/dev"        # Prevent disk wipe
    - "mkfs"
```

### Blocked Paths

Paths the agent cannot read or write with file tools, and that may not appear in shell commands. The shipped defaults also protect OpenACM's own `config/` folder, database and vector store.

```yaml
security:
  blocked_paths:
    - "/etc/passwd"
    - "C:/Users/me/AppData/Roaming/credentials"
```

---

## Web Dashboard Access

By default, the dashboard is only accessible from `localhost`. To expose it on your network:

```yaml
web:
  host: "0.0.0.0"   # Bind to all interfaces
  port: 47821
```

> ⚠️ **Warning:** Exposing OpenACM to the network gives anyone with the token full access to your computer. Use a VPN or reverse proxy with HTTPS if accessing remotely. See [Deploy on a VPS](./DEPLOY_VPS.md).

---

## Workspace Directory

All files generated by OpenACM (reports, code, etc.) are saved to the workspace directory unless another path is given. Each conversation can pin its own working directory with `/workspace <path>`.

```yaml
storage:
  workspace_path: "workspace"   # Relative to OpenACM root
```

Files sent to the chat are copied to `data/media/` and served via `/api/media/`.

---

## LocalRouter Configuration

The LocalRouter is the offline intent classifier. By default fast-path execution is **on** (`observation_mode: false`): recognized simple intents above the threshold skip the LLM. Set `observation_mode: true` to only classify silently.

```yaml
local_router:
  enabled: true
  observation_mode: false       # Allow fast-path execution
  confidence_threshold: 0.88    # How confident before skipping LLM
```

It can also be toggled at runtime from **Configuration → Local Intent Router** (`POST /api/config/local_router`).

**Threshold guidance:**
- `0.95+` — Very conservative, rarely skips LLM. Almost no misclassifications.
- `0.88` — Default. Good balance for recognized intents like screenshots and system info.
- `0.80` — More aggressive fast-pathing. May occasionally misclassify.

---

## Memory & Compaction

```yaml
assistant:
  rag_relevance_threshold: 0.5   # lower = stricter automatic memory recall
  compact_ratio: 0.60            # compact at 60% of the model's context window
  compact_keep_recent: 6
llm:
  model_context_overrides:
    kimi: 131072
```

Both RAG and compaction settings are editable in **Configuration → Memory & RAG** and are saved to `config/local.yaml`. See [Memory & RAG](./14-memory-rag.md).

---

## Client Deployments: `features` and `client_profile`

For deployments that ship OpenACM to a client, two blocks (added to `config/local.yaml`, then restart) trim the product down:

```yaml
features:
  browser_agent: false   # skip the Playwright-based browser_agent tool
  voice: false           # don't start the voice daemon (STT/TTS) at all

client_profile:
  active: true
  name: "Conjunto Residencial Los Pinos"
  allowed_pages:
    - /chat
    - /gmail-classifier
    - /swarms
```

With `client_profile.active: true`, only the listed pages are shown in the sidebar and reachable in the dashboard (`GET /api/config/client-profile`). Remove the block to lift the restriction. See [Docker](./32-docker.md#versioned-client-images) for versioned client images.

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

The name and prompt can also be edited in **Configuration → Assistant Identity**.
