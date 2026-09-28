# OpenACM Documentation

> Official documentation for **OpenACM — Open Automated Computer Manager**

---

## Table of Contents

| Document | Description |
|----------|-------------|
| [Introduction](./01-introduction.md) | What is OpenACM, vision, philosophy, key differentiators |
| [Getting Started](./02-getting-started.md) | Installation, setup, first run, updating |
| [Architecture](./03-architecture.md) | System design, components, data flow |
| [Core Concepts](./04-core-concepts.md) | Brain, memory, tools, skills, agents |
| [Tools Reference](./05-tools-reference.md) | Every built-in tool, parameters, examples |
| [Skills System](./06-skills-system.md) | What skills are, creating them, built-in library |
| [Agents](./07-agents.md) | Agents, channels, knowledge base, memory policy, flows |
| [Channels](./08-channels.md) | Web, Console, Telegram, Discord, WhatsApp |
| [LLM Providers](./09-llm-providers.md) | Supported providers, model switching, custom endpoints |
| [API Reference](./10-api-reference.md) | REST endpoints + WebSocket protocols |
| [Configuration](./11-configuration.md) | Full config schema, `local.yaml`, environment variables |
| [Security](./12-security.md) | Execution modes, sandbox, encryption, public webhooks |
| [MCP Integration](./13-mcp.md) | Model Context Protocol server setup |
| [Memory & RAG](./14-memory-rag.md) | Short-term memory, compaction, long-term vector memory |
| [Activity & Routines](./15-activity-routines.md) | OS activity watcher, pattern detection, automation |
| [Dashboard](./16-dashboard.md) | Web UI guide, all pages |
| [Extending OpenACM](./17-extending.md) | Creating tools, skills, custom channels, MCP servers |
| [Roadmap](./18-roadmap.md) | What has shipped and what's coming next |
| [Cron Scheduler](./19-cron-scheduler.md) | Background job scheduler — recurring tasks, cron expressions, API |
| [Token Optimization](./20-token-optimization.md) | Multi-layer token reduction system — local router, semantic tools, output compressor, compaction |
| [CLI Providers](./21-cli-providers.md) | Connect via CLI binaries (claude, gemini, opencode) — no API key required |
| [Swarms](./22-swarms.md) | Multi-agent swarms, parallel workers, peer messaging |
| [Code Resurrection](./23-code-resurrection.md) | Background code indexer — RAG over your own projects |
| [Plugins](./24-plugins.md) | Plugin system — tools, routes, nav items, settings, lifecycle |
| [Third-Party Integrations](./25-third-party-integrations.md) | MarkItDown, Chonkie, Docling, Instructor — curated MIT libraries |
| [Dev Mode Plugin Plan](./26-dev-mode-plugin-plan.md) | Design plan (not implemented) for a developer-tools plugin |
| [CLI Setup Wizard](./27-cli-setup.md) | `openacm-setup` and `openacm-manage` terminal tools |
| [Agent Flows](./28-agent-flows.md) | Visual flow editor, node types, templates, testing, AI flow builder |
| [Webhook Connectors](./29-webhook-connectors.md) | Public signed webhooks that run a flow |
| [Voice](./30-voice.md) | Voice daemon (STT/TTS), TTS providers, wake word |
| [Gmail Classifier](./31-gmail-classifier.md) | Built-in plugin: AI email categorization, replies, digests |
| [Docker](./32-docker.md) | Running OpenACM in Docker and versioned client images |

### Guides

| Document | Description |
|----------|-------------|
| [Deploy on a VPS](./DEPLOY_VPS.md) | Ubuntu VPS deployment with Nginx Proxy Manager + systemd (Spanish) |
| [WhatsApp Setup](./WHATSAPP_SETUP.md) | Official Meta WhatsApp Cloud API setup (Spanish) |
| [Gmail Setup](./GMAIL_SETUP.md) | Google Cloud OAuth credentials for Gmail/Calendar/Drive (Spanish) |
| [Home Assistant Setup](./HOME_ASSISTANT_SETUP.md) | Home Assistant plugin setup (Spanish) |
| [Skills & Tools Guide](./SKILLS_TOOLS_GUIDE.md) | File structure for skills and tools |
| [Troubleshooting](./TROUBLESHOOTING.md) | Common problems and fixes |
| [LLM Pricing Reference](./LLM_PRICING_REFERENCE.md) | Cost reference for the Gmail Classifier workload (Spanish) |
| [Integration Roadmap](./ROADMAP_INTEGRATION.md) | Long-term architectural plans (Spanish) |
| [Security Policy](./SECURITY.md) | Security policy and vulnerability reporting |
| [Contributing](./CONTRIBUTING.md) | How to contribute and release |

---

## Quick Links

- **GitHub:** [github.com/Json55Hdz/OpenACM](https://github.com/Json55Hdz/OpenACM)
- **npm CLI:** [`open-acm`](https://www.npmjs.com/package/open-acm)
- **License:** MIT
- **Version:** 0.4.7

---

*OpenACM is an open-source, self-hosted autonomous AI agent that runs on your computer or server.*
