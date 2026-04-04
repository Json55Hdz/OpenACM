# Introduction to OpenACM

## What is OpenACM?

**OpenACM** (Open Automated Computer Manager) is an open-source, self-hosted Tier-1 autonomous AI agent that runs directly on your computer. Unlike cloud-based AI assistants, OpenACM has real, direct access to your operating system — it can execute commands, write and run code, control a browser, manage files, automate smart home devices, interact with your Google Workspace, and much more.

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
- Powered by any LLM (Ollama, OpenAI, Anthropic, Gemini, Groq, and 100+ more via LiteLLM)
- Multi-step agentic loops — can call multiple tools in sequence to complete complex tasks
- Automatic intent classification to select the right tools for each request
- Semantic tool selection using multilingual embeddings — sends only relevant tools to save tokens

### 🛠️ 42+ Built-in Tools
- System command execution with sandboxing
- Python kernel (persistent, with installed libraries)
- Automated browser control (Playwright/Chromium)
- File system operations
- Web search and page scraping
- Google Workspace (Gmail, Calendar, Drive, YouTube)
- 3D modeling via Blender Python API
- IoT/Smart Home control (Tuya, Xiaomi Mi Home, LG WebOS)
- Screenshot capture
- UI generation

### 🔌 Multi-Channel Support
Talk to your agent through:
- **Web Dashboard** — built-in browser interface with real-time streaming
- **Telegram** — message your agent from anywhere
- **Discord** — integrate into your server
- **WhatsApp** — via bridge
- **Console** — interactive terminal

### 🧩 Fully Extensible
- **Create new tools** at runtime using natural language — just ask OpenACM to make a tool
- **Create skills** — markdown instructions that change how the agent thinks and behaves
- **Create agents** — isolated instances with their own tools, personality, and Telegram bot
- **Connect MCP servers** — plug in any Model Context Protocol compatible server

### 🔒 Privacy First
- 100% self-hosted — your data never leaves your machine
- Conversation messages encrypted at rest (AES-GCM)
- Activity data (app usage) encrypted at rest
- Configurable security policies (blocked commands, execution modes)
- Three execution modes: `confirmation`, `auto`, `yolo`

### 🧠 Memory Systems
- **Short-term:** Conversation history per user/channel, auto-compacted after 25 messages
- **Long-term:** Vector database (ChromaDB) for facts, notes, and past knowledge retrieval
- **Passive learning:** LocalRouter learns your patterns to classify intents faster

---

## Philosophy

### "Do, don't describe"
OpenACM's golden rule: if there's a tool available, use it. Never describe how something could theoretically be done — just do it.

### Open and self-hosted
Your agent runs on your hardware. Your conversations, your files, your activity — all local. You control the LLM provider, the security policies, and the channels.

### Extensible by design
OpenACM is a platform, not a product. Tools, skills, agents, and MCP servers can be added without restarting or editing source code.

### Language-agnostic
The intent classification and tool selection system is powered by multilingual embeddings (`paraphrase-multilingual-MiniLM-L12-v2`). You can talk to OpenACM in any of 50+ languages.

---

## Who is OpenACM for?

| User | Use Case |
|------|----------|
| **Developers** | Automate repetitive coding tasks, run tests, manage projects, generate boilerplate |
| **Power Users** | Control your PC with voice/text, automate workflows, manage files at scale |
| **Smart Home Enthusiasts** | Unified natural language control for IoT devices |
| **Teams** | Deploy a shared agent on a server, accessible via Telegram/Discord |
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
- ✅ Control smart home devices (lights, thermostats, TVs, vacuums, blinds)
- ✅ Create 3D models and render scenes in Blender
- ✅ Remember facts across conversations (vector memory)
- ✅ Create new tools for itself at runtime
- ✅ Spawn isolated sub-agents with specialized roles
- ✅ Connect to any MCP-compatible external tool server
- ✅ Run as a Telegram bot, Discord bot, WhatsApp bot, or web interface
- ✅ Detect repetitive workflows and suggest automation
- ✅ Monitor your OS activity patterns and build routines

---

## What Makes OpenACM Different

| Feature | OpenACM | Cloud AI Assistants | Local LLM UIs |
|---------|---------|---------------------|---------------|
| Real OS execution | ✅ | ❌ | ❌ |
| Self-hosted | ✅ | ❌ | ✅ |
| Multi-channel (Telegram, Discord) | ✅ | ❌ | ❌ |
| Create tools at runtime | ✅ | ❌ | ❌ |
| IoT / Smart Home | ✅ | Limited | ❌ |
| MCP protocol support | ✅ | Some | Some |
| Encrypted local storage | ✅ | N/A | Varies |
| Multi-agent system | ✅ | ❌ | ❌ |
| Works with any LLM | ✅ | ❌ (locked in) | ✅ |
| Activity pattern detection | ✅ | ❌ | ❌ |
| Long-term RAG memory | ✅ | ❌ | ❌ |

---

## Version

**Current:** v0.1.0 — active development, not yet stable for production use.

See the [Roadmap](./18-roadmap.md) for planned features.
