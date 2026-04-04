# Roadmap

OpenACM is actively developed. This document describes what's planned, what's in progress, and the long-term vision.

**Current version:** v0.1.0 — functional but not yet stable for production use.

---

## Recently Shipped (v0.1.0)

- ✅ Core agentic loop with multi-tool support
- ✅ 42+ built-in tools (system, file, web, Google, Blender, IoT, browser)
- ✅ Web dashboard (Next.js) with real-time streaming
- ✅ Telegram, Discord, WhatsApp channel support
- ✅ Multi-agent system with isolated tool access
- ✅ Skills system (markdown behavior instructions)
- ✅ Runtime tool creation (`create_tool`)
- ✅ MCP server integration (stdio + SSE)
- ✅ LocalRouter (offline intent classifier, multilingual)
- ✅ RAG / vector memory (ChromaDB)
- ✅ Conversation compaction (auto-summarization)
- ✅ Semantic tool selection (multilingual embeddings)
- ✅ Conversation encryption at rest (AES-GCM)
- ✅ Activity watcher (OS app usage monitoring)
- ✅ Routine detection and automation
- ✅ Workflow tracker (suggests automation for repeated patterns)
- ✅ Custom LLM provider support (OpenAI-compatible endpoints)
- ✅ Dashboard: stats, charts, model switching, debug traces

---

## Short-term (v0.2.0)

### Voice Input/Output
- Whisper integration for speech-to-text in the web chat
- TTS output option (ElevenLabs, OpenAI TTS, local Coqui)
- Voice-only Telegram mode

### Scheduled Tasks / Cron
- Schedule recurring tasks ("every morning at 8am, summarize my emails")
- Cron-like syntax from natural language
- Task history and result storage

### Smarter Fast-Path
- More intent categories (file operations, web search patterns)
- Per-user learned fast paths (personalized to each channel)
- Fast-path for common IoT commands (reduces ~800ms LLM overhead)

### Better Tool Results in Context
- Structured tool result display in chat (tables, code blocks, collapsible sections)
- Large tool outputs stored in RAG instead of full context

### Plugin System
- Community-contributed tool packs installable via pip
- `openacm install tool-pack-weather`
- Plugin registry

---

## Medium-term (v0.3.0)

### Multi-Modal Improvements
- Vision: analyze images, screenshots, documents in-conversation
- Audio transcription of uploaded audio/video files
- PDF and document parsing (already partially implemented)

### Web Automation Improvements
- Persistent browser session (don't restart Playwright on every call)
- Browser profiles (saved login sessions for common sites)
- Record-and-replay for browser workflows

### Advanced Agent Features
- Agent-to-agent communication (main agent delegates to sub-agents)
- Agent marketplace / template library
- Agent health monitoring dashboard
- Webhooks for agent events

### Knowledge Management
- File upload to RAG (index documents, PDFs, codebases)
- Structured knowledge bases (named collections, namespaced search)
- Knowledge graph visualization

### Better IoT
- Matter protocol support
- Home Assistant integration (replacing individual device APIs)
- Unified device discovery UI
- Scenes and automation rules

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
- Webhook triggers from external systems
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
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all,dev]"
cd frontend && npm install && cd ..
```

**Code style:**
- Python: `ruff` for linting, `black` for formatting
- TypeScript: `eslint` + `prettier`
- All new tools must have risk levels and categories annotated
- New API endpoints must be documented in `docs/10-api-reference.md`

---

## Versioning

OpenACM follows semantic versioning:

- `0.x.y` — Pre-stable. Breaking changes may occur between minor versions.
- `1.0.0` — First stable release. Breaking changes only in major versions.

The database schema is automatically migrated on startup. Config format changes are documented in release notes.
