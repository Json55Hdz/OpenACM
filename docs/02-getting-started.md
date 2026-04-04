# Getting Started

## Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Windows 10, macOS 12, Ubuntu 20.04 | Windows 11, macOS 14, Ubuntu 22.04 |
| Python | 3.11+ | 3.12 |
| RAM | 4 GB | 8 GB (16 GB with local LLM) |
| Storage | 2 GB | 5 GB (more for local models) |
| Node.js | 18+ | 20+ |
| GPU | Not required | Optional (for local LLM acceleration) |

---

## Installation (Recommended — Scripts)

OpenACM ships with setup and run scripts that handle everything automatically.

### 1. Clone the repository

```bash
git clone https://github.com/Json55Hdz/OpenACM.git
cd OpenACM
```

### 2. Run the setup script

The setup script creates the virtual environment, installs all Python dependencies, and builds the frontend in one step.

**Windows:**
```
setup.bat
```

**macOS / Linux:**
```bash
chmod +x setup.sh
./setup.sh
```

### 3. Start OpenACM

From now on, every time you want to run OpenACM:

**Windows:**
```
run.bat
```

**macOS / Linux:**
```bash
./run.sh
```

That's it. Open your browser at `http://127.0.0.1:47821`.

> **No config needed upfront.** The onboarding wizard will guide you through choosing your LLM provider, entering API keys, and setting up channels — all from the browser.

---

## First Run: Dashboard Setup

1. Open `http://127.0.0.1:47821` in your browser
2. Enter the **Dashboard Token** shown in the terminal
3. The **Onboarding Wizard** guides you through:
   - Choosing your LLM provider and model
   - Setting up optional channels (Telegram, Discord)
   - Configuring optional integrations (Google, IoT)

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

  🧠 LLM: ollama (llama3.2)
  🖥️  Web: http://127.0.0.1:47821
  🔒 Security: auto mode
  📱 Channels: Console · Web

  🔑 Dashboard Token:
  acm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
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

---

## Quick LLM Configuration

### Ollama (local, no API key needed)

1. Install [Ollama](https://ollama.com)
2. Pull a model: `ollama pull llama3.2`
3. In `config/default.yaml`:

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
llm:
  default_provider: openai
  providers:
    openai:
      default_model: "gpt-4o"
      api_key: "${OPENAI_API_KEY}"
```

### Anthropic (Claude)

```yaml
llm:
  default_provider: anthropic
  providers:
    anthropic:
      default_model: "claude-opus-4-6"
      api_key: "${ANTHROPIC_API_KEY}"
```

---

## Slash Commands

Available in both web chat and the terminal console:

| Command | Description |
|---------|-------------|
| `/new` | Start a fresh conversation |
| `/clear` | Same as `/new` |
| `/model <name>` | Switch LLM model mid-conversation |
| `/stats` | Show token usage and request counts |
| `/export` | Export conversation as text file |
| `/help` | Show available commands |

---

## Directory Structure

```
OpenACM/
├── setup.bat / setup.sh      # One-time setup script
├── run.bat / run.sh           # Start OpenACM
├── config/
│   ├── default.yaml           # Main configuration file
│   ├── .env                   # API keys and secrets
│   ├── custom_providers.json  # Custom LLM endpoints
│   └── mcp_servers.json       # MCP server configurations
├── data/
│   ├── openacm.db             # SQLite database (conversations, tools, skills)
│   ├── vectordb/              # ChromaDB vector storage (long-term memory)
│   └── router_learned.json    # LocalRouter learned examples
├── docs/                      # This documentation
├── frontend/                  # Next.js web dashboard source
├── skills/                    # Skill markdown files
│   ├── agents/
│   ├── custom/
│   └── development/
├── src/openacm/               # Python source
│   ├── app.py                 # Main orchestrator
│   ├── core/                  # Brain, memory, LLM router, config
│   ├── channels/              # Discord, Telegram, WhatsApp
│   ├── tools/                 # All built-in tools
│   ├── security/              # Sandbox, policies, encryption
│   ├── storage/               # SQLite database layer
│   ├── web/                   # FastAPI server + static frontend
│   └── watchers/              # OS activity monitor
└── workspace/                 # Default directory for generated files
```

---

## Updating OpenACM

```bash
git pull
```

Then re-run the setup script to update dependencies and rebuild the frontend:

**Windows:** `setup.bat`  
**macOS / Linux:** `./setup.sh`

The database schema is automatically migrated on startup.

---

## Manual Installation (Advanced)

If you prefer to install without the scripts, or need to customize the setup:

### 1. Create a Python virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 2. Install Python dependencies

```bash
pip install -e ".[all]"
```

Or install only what you need:

```bash
pip install -e ".[core]"       # Core only (no RAG, no IoT)
pip install -e ".[rag]"        # + ChromaDB vector memory
pip install -e ".[browser]"    # + Playwright browser automation
pip install -e ".[google]"     # + Google Workspace APIs
pip install -e ".[iot]"        # + IoT/Smart Home
pip install -e ".[blender]"    # + Blender Python integration
```

### 3. Build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

### 4. Run

```bash
python -m openacm
```

---

## Troubleshooting

### "Web dashboard fails to load"
- Make sure the frontend was built (`npm run build` in `frontend/`) — `setup.bat`/`setup.sh` does this automatically
- Check that port 47821 is not in use: `netstat -ano | findstr 47821`

### "LLM connection failed"
- For Ollama: verify it's running with `ollama list`
- For cloud providers: check your API key in `config/.env`
- Verify `config/default.yaml` has the correct `base_url`

### "Tool execution blocked"
- Review `security.execution_mode` in `config/default.yaml`
- Check `security.blocked_patterns` — you may have blocked too aggressively

### "Sentence-transformers model not downloading"
- The `paraphrase-multilingual-MiniLM-L12-v2` model (~470MB) downloads on first use
- Requires internet access on first run; subsequent runs are fully offline
- Cached at `~/.cache/huggingface/hub/`
