# Roadmap

OpenACM is actively developed. This document describes what's planned, what's in progress, and the long-term vision.

**Current version:** v0.4.7 — functional, pre-1.0 (breaking changes may still happen between minor versions). See the [CHANGELOG](../CHANGELOG.md) for release notes.

---

## Shipped

### Foundations (v0.1)
- ✅ Core agentic loop with multi-tool support
- ✅ Built-in tools (system, file, web, Google, browser, Python kernel)
- ✅ Web dashboard (Next.js) with real-time updates
- ✅ Telegram, Discord, WhatsApp channel support
- ✅ Skills system (markdown behavior instructions)
- ✅ MCP server integration (stdio, SSE, streamable HTTP)
- ✅ LocalRouter (offline intent classifier, multilingual)
- ✅ RAG / vector memory (ChromaDB)
- ✅ Conversation compaction (auto-summarization)
- ✅ Semantic tool selection (multilingual embeddings)
- ✅ Conversation encryption at rest
- ✅ Activity watcher, routine detection and workflow tracker
- ✅ Custom LLM provider support (OpenAI-compatible endpoints) and CLI providers
- ✅ Dashboard: stats, charts, model switching, debug traces
- ✅ Cron scheduler with visual management UI and LLM tools
- ✅ Per-channel PTY terminal (xterm.js + pywinpty/pty)
- ✅ Cancel button — abort any in-progress AI request from the chat UI

### Since then (v0.2 – v0.4.7)
- ✅ Multi-agent **swarms** with planning, peer messaging, shared knowledge and templates
- ✅ **Plugin system** (built-in + pip entry points) with settings forms and embedded plugin dashboards
- ✅ **Home Assistant** plugin (replacing per-vendor IoT integrations), **Gmail Classifier** and **Content Automation** plugins
- ✅ **Voice**: always-on voice daemon (faster-whisper STT, wake word, TTS) and in-browser Kokoro TTS
- ✅ **Agents 2.0**: knowledge base, per-agent Telegram/WhatsApp channels, private skills, memory TTL policy, customer names, inactivity follow-ups, chat grouping
- ✅ **Visual flows** with an Unreal-style node editor, data pins, variables, loops, WooCommerce node, JSON import/export and an AI chat builder
- ✅ **Webhook connectors**: public, signed webhooks (HMAC / bearer / static header) that run a flow, with audit log
- ✅ Official **WhatsApp Cloud API** channel
- ✅ Surgical **code-editing tools** (`edit_file`, `grep_in_files`, `get_file_outline`, `run_linter`)
- ✅ Persistent browser session for the browser agent
- ✅ Terminal setup wizard (`openacm-setup`) and console manager (`openacm-manage`)
- ✅ Docker image, versioned GHCR releases, `features` toggles and `client_profile` for client deployments
- ✅ LLM 429 rate-limit retries with backoff

---

## Short-term

### Smarter Fast-Path
- More intent categories (file operations, web search patterns)
- Per-user learned fast paths (personalized to each channel)
- Fast-path for common IoT commands (reduces ~800ms LLM overhead)

### Better Tool Results in Context
- Structured tool result display in chat (tables, code blocks, collapsible sections)
- Large tool outputs stored in RAG instead of full context

### Plugin ecosystem
- Community-contributed plugins installable via pip (the entry-point mechanism already exists)
- Plugin registry

### Voice
- Voice-only Telegram mode

---

## Medium-term

### Web Automation Improvements
- Browser profiles (saved login sessions for common sites)
- Record-and-replay for browser workflows

### Advanced Agent Features
- Agent marketplace / template library
- Agent health monitoring dashboard
- More flow node types and connection types beyond WooCommerce

### Knowledge Management
- File upload to the global RAG (index documents, PDFs, codebases)
- Structured knowledge bases (named collections, namespaced search)
- Knowledge graph visualization

### Better IoT
- Matter protocol support
- Automation rules built from the dashboard

---

## Long-term Vision

### OpenACM Cloud (Optional)
- Hosted option for users who don't want to self-host
- Data stays encrypted and user-controlled
- Agent sharing marketplace

### OpenACM Mobile
- iOS and Android native apps
- Voice-first interface
- Push notifications from agents
- Location-aware context

### Autonomous Operation Mode
- Proactive agent — acts without being asked based on detected patterns
- "Morning briefing" routine that runs automatically
- Anomaly detection ("your disk is 90% full, want me to clean it?")

### Multi-Computer Support
- Connect multiple machines to one OpenACM instance
- Execute tools on specific machines by name
- Aggregate activity data across devices

### OpenACM for Teams
- Multi-user support with per-user permissions
- Shared agents and skills
- Team knowledge base (shared RAG)
- Audit log with user attribution

### Developer Platform
- OpenACM SDK for building tool packs
- REST API for embedding OpenACM in other applications
- Zapier/Make.com integration

---

## Contributing

OpenACM is open source and contributions are welcome.

**Where to start:**
- Check open issues on GitHub for `good first issue` labels
- Tool contributions — if you've built a useful tool, submit it
- Translations — help localize the dashboard
- Documentation improvements

**Development setup:**
```bash
git clone https://github.com/Json55Hdz/OpenACM.git
cd OpenACM
uv venv --seed && source .venv/bin/activate
uv pip install -e ".[dev]"
cd frontend && npm install && cd ..
pytest
```

**Code style:**
- Python: `ruff` (line length 100, Python 3.12 target)
- TypeScript: `eslint` (`npm run lint` in `frontend/`)
- All new tools must have risk levels and categories annotated
- New API endpoints must be documented in `docs/10-api-reference.md`

---

## Versioning

OpenACM follows semantic versioning:

- `0.x.y` — Pre-stable. Breaking changes may occur between minor versions.
- `1.0.0` — First stable release. Breaking changes only in major versions.

The database schema is automatically migrated on startup. Config format changes are documented in release notes.
