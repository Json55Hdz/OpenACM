# Introduction to OpenACM

## What is OpenACM?

**OpenACM** (Open Automated Computer Manager) is an open-source, self-hosted Tier-1 autonomous AI agent that runs directly on your computer or server. Unlike cloud-based AI assistants, OpenACM has real, direct access to your operating system — it can execute commands, write and run code, control a browser, manage files, control smart home devices through Home Assistant, interact with your Google Workspace, run specialized agents on Telegram and WhatsApp, and much more.

OpenACM is not a chatbot. It is an **execution engine** that happens to be controlled through natural language.

---

## The Core Idea

Most AI assistants *describe* what to do. OpenACM *does it*.

```
User: "Generate a report of my disk usage and send it to my email"

❌ Traditional AI:
"You can use the `du` command to check disk usage, then use your email client..."

✅ OpenACM:
[Runs `du -sh *` to get disk usage]
[Generates a PDF report with Python + reportlab]
[Sends the email via Gmail API]
"Done! Report sent to your inbox."
```

The key difference is agency — OpenACM completes tasks end-to-end without requiring you to copy-paste code, run commands manually, or switch between applications.

---

## Key Features

### 🧠 Intelligent Decision Making
- Powered by any LLM (OpenCode Go, OpenAI, Anthropic, Gemini, xAI, OpenRouter, Ollama, any OpenAI-compatible endpoint, or a logged-in `claude`/`gemini`/`opencode` CLI — via LiteLLM)
- Multi-step agentic loops — can call multiple tools in sequence to complete complex tasks
- Automatic intent classification to select the right tools for each request
- Semantic tool selection using multilingual embeddings — sends only relevant tools to save tokens

### 🛠️ 70+ Built-in Tools
- System command execution with sandboxing
- Python kernel (persistent, with installed libraries)
- Automated browser control (Playwright/Chromium)
- File system operations and surgical code editing (`edit_file`, `grep_in_files`, `get_file_outline`, `run_linter`)
- Web search and page scraping
- Google Workspace (Gmail, Calendar, Drive, YouTube)
- Smart Home control through the Home Assistant plugin
- Screenshot capture
- UI generation (Google Stitch)
- Platform self-management: agents, flows, cron jobs, swarms, MCP servers, model and security mode

See the [Tools Reference](./05-tools-reference.md) for the full list.

### 🔌 Multi-Channel Support
Talk to your agent through:
- **Web Dashboard** — built-in browser interface with real-time streaming
- **Telegram** — message your agent from anywhere
- **Discord** — integrate into your server
- **WhatsApp** — official Meta WhatsApp Cloud API (or a legacy local bridge)
- **Console** — interactive terminal

Agents can also have their **own** Telegram bot and WhatsApp number.

### 🧩 Fully Extensible
- **Create skills** — markdown instructions that change how the agent thinks and behaves
- **Create agents** — specialized assistants with their own tools, personality, knowledge base, and Telegram/WhatsApp channels
- **Build visual flows** — node-based automations that agents call as tools, or that run from a public webhook
- **Launch swarms** — teams of AI workers that plan and execute a project in parallel
- **Connect MCP servers** — plug in any Model Context Protocol compatible server
- **Write plugins** — package tools, API routes, dashboard pages and settings in a single Python package

### 🔒 Privacy First
- 100% self-hosted — your data never leaves your machine
- Conversation messages encrypted at rest (Fernet / AES, local key in `config/activity.key`)
- Activity data (app usage) encrypted at rest
- Configurable security policies (blocked commands, execution modes)
- Three execution modes: `confirmation`, `auto`, `yolo`

### 🧠 Memory Systems
- **Short-term:** Conversation history per user/channel, auto-compacted when it reaches 60% of the model's context window
- **Long-term:** Vector database (ChromaDB) for facts, notes, and past knowledge retrieval
- **Passive learning:** LocalRouter learns your patterns to classify intents faster

---

## Philosophy

### "Do, don't describe"
OpenACM's golden rule: if there's a tool available, use it. Never describe how something could theoretically be done — just do it.

### Open and self-hosted
Your agent runs on your hardware. Your conversations, your files, your activity — all local. You control the LLM provider, the security policies, and the channels.

### Extensible by design
OpenACM is a platform, not a product. Skills, agents, flows, cron jobs, swarms and MCP servers can be added at runtime without restarting or editing source code; plugins add whole features with a restart.

### Language-agnostic
The intent classification and tool selection system is powered by multilingual embeddings (`paraphrase-multilingual-MiniLM-L12-v2`). You can talk to OpenACM in any of 50+ languages.

---

## Who is OpenACM for?

| User | Use Case |
|------|----------|
| **Developers** | Automate repetitive coding tasks, run tests, manage projects, generate boilerplate |
| **Power Users** | Control your PC with voice/text, automate workflows, manage files at scale |
| **Smart Home Enthusiasts** | Unified natural language control for IoT devices via Home Assistant |
| **Teams** | Deploy a shared agent on a server, accessible via Telegram/Discord/WhatsApp |
| **Small businesses** | Customer-facing agents on WhatsApp/Telegram with a knowledge base and WooCommerce product search |
| **AI Researchers** | Platform for experimenting with multi-tool agentic systems |
| **Content Creators** | Automate editing pipelines, generate assets, manage social media |

---

## What OpenACM Can Do Right Now

- ✅ Execute any OS command with real-time output streaming
- ✅ Write, execute, and debug Python code interactively
- ✅ Control a real browser — log in, fill forms, scrape, interact with any website
- ✅ Read, write, search, and manage files across your file system
- ✅ Search the web and retrieve up-to-date information
- ✅ Send and read emails via Gmail
- ✅ Create and manage Google Calendar events
- ✅ Upload/download files from Google Drive
- ✅ Take screenshots and analyze them
- ✅ Control smart home devices through Home Assistant (lights, climate, covers, media players, vacuums, scenes)
- ✅ Remember facts across conversations (vector memory)
- ✅ Create and manage agents, flows, cron jobs and swarms from chat
- ✅ Connect to any MCP-compatible external tool server
- ✅ Run as a Telegram bot, Discord bot, WhatsApp bot, or web interface
- ✅ Classify your Gmail inbox and draft replies (Gmail Classifier plugin)
- ✅ Expose flows as signed public webhooks
- ✅ Listen and speak through the optional voice daemon
- ✅ Detect repetitive workflows and suggest automation
- ✅ Monitor your OS activity patterns and build routines

---

## What Makes OpenACM Different

| Feature | OpenACM | Cloud AI Assistants | Local LLM UIs |
|---------|---------|---------------------|---------------|
| Real OS execution | ✅ | ❌ | ❌ |
| Self-hosted | ✅ | ❌ | ✅ |
| Multi-channel (Telegram, Discord) | ✅ | ❌ | ❌ |
| Visual flows + webhooks | ✅ | ❌ | ❌ |
| IoT / Smart Home | ✅ | Limited | ❌ |
| MCP protocol support | ✅ | Some | Some |
| Encrypted local storage | ✅ | N/A | Varies |
| Multi-agent system | ✅ | ❌ | ❌ |
| Works with any LLM | ✅ | ❌ (locked in) | ✅ |
| Activity pattern detection | ✅ | ❌ | ❌ |
| Long-term RAG memory | ✅ | ❌ | ❌ |

---

## Version

**Current:** v0.4.7 — active development (pre-1.0; breaking changes may still happen between minor versions). See the [CHANGELOG](../CHANGELOG.md).

See the [Roadmap](./18-roadmap.md) for planned features.
