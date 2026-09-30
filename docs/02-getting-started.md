# Getting Started

## Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Windows 10, macOS 12, Ubuntu 22.04 | Windows 11, macOS 14, Ubuntu 24.04 |
| Python | 3.12+ | 3.12+ |
| RAM | 8 GB (Windows) / 3 GB (Linux VPS) | 8-16 GB (16+ GB with local LLMs) |
| CPU | 2 cores / vCPUs | 3+ cores (smooth concurrency) |
| Storage | 5 GB | 20 GB+ |
| Node.js | 20+ | 20+ |
| GPU | Not required | Optional (for local LLM acceleration) |

> OpenACM itself uses about **1.8 GB of RAM** at runtime (FastAPI + dashboard + the embedding models used by RAG and the local router). Windows needs more headroom because the OS alone uses ~4 GB at idle.

The setup scripts install what is missing: [`uv`](https://docs.astral.sh/uv/), Python 3.12 (through `uv`), Node.js 20 (via nvm, Homebrew or apt on macOS/Linux), the Python dependencies and Playwright's Chromium.

---

## Installation (Recommended — npm CLI)

Requires Node.js 18+ and git.

```bash
npm i -g open-acm
openacm install   # clones the repo into ~/OpenACM and runs the full setup
openacm start
```

Or without a global install: `npx open-acm install` / `npx open-acm start`.

| Command | Description |
|---------|-------------|
| `openacm install` | Clone and set up OpenACM (first time; offers `update` if already installed) |
| `openacm start` | Start OpenACM |
| `openacm stop` | Stop a running instance |
| `openacm status` | Check if OpenACM is running |
| `openacm update` | Pull latest + sync deps + rebuild frontend |
| `openacm repair` | Reinstall Python dependencies (no git pull) |
| `openacm uninstall` | Delete the installation directory |

Set `OPENACM_DIR=/custom/path` to use a different installation directory.

---

## Installation (One-Liner)

No need to clone the repo manually. Run this from anywhere:

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/Json55Hdz/OpenACM/main/install.sh | bash
```

**Windows (PowerShell as Administrator):**
```powershell
iwr -useb https://raw.githubusercontent.com/Json55Hdz/OpenACM/main/install.ps1 | iex
```

This clones the repo to `~/OpenACM` (or pulls if it already exists), runs the full setup, and offers to launch OpenACM when done.

> To install to a custom path, set `OPENACM_DIR` first:  
> `OPENACM_DIR=/opt/openacm curl -fsSL ... | bash`

---

## Installation (Manual — Already have git)

If you prefer to clone yourself:

### 1. Clone the repository

```bash
git clone https://github.com/Json55Hdz/OpenACM.git
cd OpenACM
```

### 2. Run setup

**Windows:**
```
setup.bat
```
(`setup.bat` asks for administrator rights — some Windows setups block the `uv` or Playwright installs otherwise.)

**macOS / Linux:**
```bash
chmod +x setup.sh run.sh update.sh acm.sh
./setup.sh
```

The setup script creates `.venv`, installs the Python package (`uv pip install -e .`), installs Playwright's Chromium, creates `config/.env` from `config/.env.example`, and offers to start OpenACM. When it starts, open your browser at `http://127.0.0.1:47821`.

---

## The `acm` Script

Inside the repository, `acm.bat` (Windows) and `acm.sh` (macOS/Linux) are a single entry point for the other scripts:

| Command | Description |
|---------|-------------|
| `acm install` | First-time setup |
| `acm start` | Start OpenACM |
| `acm stop` | Stop the instance listening on port 47821 |
| `acm status` | Check if OpenACM is running |
| `acm update` | Pull latest + sync deps + rebuild frontend |
| `acm repair` | Reinstall Python deps without pulling git |

**Windows:** `acm start`  
**macOS / Linux:** `./acm.sh start`

> **No config needed upfront.** The onboarding wizard in the browser guides you through choosing your LLM provider and entering API keys. Prefer the terminal? Run `openacm-setup --guided` (see [CLI Setup Wizard](./27-cli-setup.md)).

---

## First Run: Dashboard Setup

1. Open `http://127.0.0.1:47821` in your browser
2. Enter the **Dashboard Token** shown in the terminal. It is generated on the first start and saved as `DASHBOARD_TOKEN` in `config/.env`, so it stays the same across restarts.
3. The **Onboarding Wizard** guides you through:
   - Choosing your LLM provider and model
   - Setting up optional channels (Telegram, WhatsApp)
   - Configuring optional integrations (Google)
4. In the first chat, the assistant asks for your name, what to call it, and how it should behave, then saves your profile (`save_user_profile`).

On first launch you'll see something like:

```
   ____                      ___   ______ __  ___
  / __ \____  ___  ____     /   | / ____//  |/  /
 / / / / __ \/ _ \/ __ \   / /| |/ /    / /|_/ /
/ /_/ / /_/ /  __/ / / /  / ___ / /___ / /  / /
\____/ .___/\___/_/ /_/  /_/  |_\____//_/  /_/
    /_/

[████████████████████] 100% • Starting web dashboard  3.2s

✅ OpenACM is running!

  🧠 LLM: opencode_go (kimi-k2.5)
  🖥️  Web: http://127.0.0.1:47821
  🔒 Security: confirmation mode
  📱 Channels: Console · Web

  🔑 Dashboard Token:
  <your token>
```

---

## First Conversation

Type in the web chat or directly in the terminal console:

```
You> What can you do?
You> Take a screenshot and tell me what's on my screen
You> What's my disk usage?
You> Search for the latest news about AI agents
You> Create a Python script that renames all .txt files in my Downloads folder to lowercase
```

In the default `confirmation` security mode, every shell command the agent wants to run is shown to you for approval first. See [Security](./12-security.md).

---

## Quick LLM Configuration

The easiest way is the dashboard (**Configuration → Model**) or the onboarding wizard. To do it by hand, put your overrides in `config/local.yaml` (not committed, survives updates) and API keys in `config/.env`. API keys are always read from environment variables named `<PROVIDER_ID>_API_KEY`.

### Ollama (local, no API key needed)

1. Install [Ollama](https://ollama.com)
2. Pull a model: `ollama pull llama3.2`
3. In `config/local.yaml`:

```yaml
llm:
  default_provider: ollama
  providers:
    ollama:
      base_url: "http://localhost:11434"
      default_model: "llama3.2"
```

### OpenAI

```yaml
# config/local.yaml
llm:
  default_provider: openai
  providers:
    openai:
      default_model: "gpt-4o"
```
```env
# config/.env
OPENAI_API_KEY=sk-...
```

### Anthropic (Claude)

```yaml
# config/local.yaml
llm:
  default_provider: anthropic
  providers:
    anthropic:
      default_model: "claude-sonnet-4-20250514"
```
```env
# config/.env
ANTHROPIC_API_KEY=sk-ant-...
```

See [LLM Providers](./09-llm-providers.md) for every provider, custom endpoints and CLI providers.

---

## Slash Commands

Available in the web chat, the terminal console, and external channels:

| Command | Description |
|---------|-------------|
| `/new` | Start a fresh conversation |
| `/clear` | Same as `/new` |
| `/reset` | Emergency reset — wipes this conversation's memory to fix a broken LLM state |
| `/compact` | Summarize the conversation now to free context |
| `/model <name>` | Switch LLM model mid-conversation |
| `/stats` | Show token usage and request counts |
| `/export` | Export conversation as text |
| `/workspace [path\|clear]` | Show, pin, or clear the working directory for this conversation |
| `/help` | Show available commands |

The terminal console also has `/models`, `/tools` and `/config`.

---

## Directory Structure

```
OpenACM/
├── install.ps1 / install.sh   # Bootstrap: clone + setup (run from anywhere)
├── acm.bat / acm.sh           # Unified script: install/update/start/stop/status/repair
├── setup.bat / setup.sh       # One-time setup script
├── update.bat / update.sh     # Pull + sync deps + rebuild frontend
├── run.bat / run.sh           # Start OpenACM (rebuilds the frontend if Node is available)
├── bin/openacm.js             # npm CLI (`open-acm` package)
├── scripts/                   # The real implementations of the scripts above (.sh / .ps1)
├── config/
│   ├── default.yaml           # Base configuration (committed)
│   ├── local.yaml             # Your overrides (not committed)
│   ├── .env                   # API keys, tokens and secrets (not committed)
│   ├── .env.example           # Template for .env
│   ├── activity.key           # Local encryption key (not committed)
│   ├── custom_providers.json  # Custom LLM endpoints
│   ├── mcp_servers.json       # MCP server configurations
│   └── google_credentials.json / google_token.json   # Google OAuth (optional)
├── data/
│   ├── openacm.db             # SQLite database (conversations, agents, flows, cron, swarms…)
│   ├── vectordb/              # ChromaDB vector storage (long-term memory)
│   ├── media/                 # Uploaded and generated files served at /api/media
│   ├── logs/                  # Log files
│   └── router_learned.json    # LocalRouter learned examples
├── docker/                    # Dockerfile + docker-compose.yml
├── docs/                      # This documentation
├── frontend/                  # Next.js web dashboard source
├── skills/                    # Skill markdown files
├── src/openacm/               # Python source
│   ├── app.py                 # Main orchestrator
│   ├── core/                  # Brain, memory, LLM router, config, flows, swarms
│   ├── channels/              # Discord, Telegram, WhatsApp (+ per-agent channels)
│   ├── tools/                 # All built-in tools
│   ├── plugins/               # Built-in plugins
│   ├── security/              # Sandbox, policies, crypto
│   ├── storage/               # SQLite database layer
│   ├── voice/                 # Voice daemon + TTS providers
│   ├── cli/                   # openacm-setup / openacm-manage
│   ├── web/                   # FastAPI server + static frontend
│   └── watchers/              # Activity monitor, cron scheduler, code resurrection
└── workspace/                 # Default directory for generated files
```

---

## Updating OpenACM

**npm CLI:** `openacm update`

**Windows:**
```
acm update
```
or
```
update.bat
```

**macOS / Linux:**
```bash
./acm.sh update
```
or
```bash
./update.sh
```

This updates the code (`git pull --ff-only`, temporarily stashing local changes; if the folder is not a git checkout it downloads the latest tarball from GitHub instead), syncs Python dependencies, and rebuilds the frontend. `config/.env`, `config/local.yaml`, `data/` and `.venv/` are preserved. The database schema is automatically migrated on startup.

---

## Docker

```bash
# Tell OpenACM to listen on all interfaces, on the port the compose file publishes
cat > config/local.yaml <<'EOF'
web:
  host: 0.0.0.0
  port: 8080
EOF

docker compose -f docker/docker-compose.yml up -d --build
docker logs openacm   # first start prints the dashboard token
```

Then open `http://localhost:8080`. `data/` and `config/` are mounted from the host. See [Docker](./32-docker.md).

---

## Manual Installation (Advanced)

If you prefer to install without the scripts, or need to customize the setup:

### 1. Create a Python virtual environment

```bash
python3.12 -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

(or `uv venv --seed` if you use `uv`)

### 2. Install Python dependencies

```bash
pip install -e .
playwright install chromium
```

All core features (RAG, browser agent, Google APIs, MCP, document parsing) are regular dependencies. The only optional extras are:

```bash
pip install -e ".[voice]"   # sounddevice, faster-whisper, numpy, pyttsx3 for the voice daemon
pip install -e ".[dev]"     # pytest, pytest-asyncio, pytest-mock, ruff
```

### 3. Build the frontend

```bash
cd frontend
npm install
npm run deploy   # next build + copy frontend/dist into src/openacm/web/static
cd ..
```

### 4. Run

```bash
python -m openacm
# or, with the package installed:
openacm
```

---

## Troubleshooting

### "Web dashboard fails to load"
- Make sure the frontend was built and copied to `src/openacm/web/static/` (`npm run deploy` in `frontend/`) — `setup`, `run` and `update` scripts do this automatically when Node.js is available
- Check that port 47821 is not in use: `netstat -ano | findstr 47821` (Windows) or `lsof -i :47821` (macOS/Linux)

### "LLM connection failed"
- For Ollama: verify it's running with `ollama list`
- For cloud providers: check your `<PROVIDER>_API_KEY` in `config/.env`
- Verify the provider's `base_url` in `config/default.yaml` / `config/local.yaml`

### "Tool execution blocked"
- Review `security.execution_mode` (in `auto` mode only whitelisted commands run)
- Check `security.blocked_patterns` and `security.blocked_paths` — you may have blocked too aggressively

### "Sentence-transformers model not downloading"
- The `paraphrase-multilingual-MiniLM-L12-v2` model (local router + tool selection) and `all-MiniLM-L6-v2` (RAG) download on first use
- Requires internet access on first run; subsequent runs are fully offline
- Cached at `~/.cache/huggingface/hub/`

More in [Troubleshooting](./TROUBLESHOOTING.md).
