# OpenACM Security Policy

## Threat Model and Security Analysis

**Last Audit:** March 2025
**Tool:** skill-security-auditor (Claude Skills)
**Verdict:** SECURE - All findings are BY DESIGN

> The audit below predates many features (agents with public channels, flows, webhook connectors, plugins). For the current security model — execution modes, hardcoded blocks, authentication and public endpoints — see [Security](./12-security.md).

---

## Audit Summary

| Category | Findings | By Design | Action Required |
|----------|----------|-----------|-----------------|
| NET-EXFIL | 4 | 4 (100%) | 0 |
| CRED-HARVEST | 4 | 4 (100%) | 0 |
| OBFUSCATION | 1 | 1 (100%) | 0 |
| DEPS-RUNTIME | 1 | 1 (100%) | 0* |
| **TOTAL** | **10** | **10 (100%)** | **0** |

*Optional recommendation implemented

---

## Security Components

### 1. Execution Sandbox

OpenACM implements a security sandbox in `src/openacm/security/sandbox.py` (with policies in `security/policies.py`) that:
- Checks every shell command against hardcoded privilege-escalation blocks, `blocked_patterns` and `blocked_paths`
- Applies the execution mode (`confirmation` / `auto` whitelist / `yolo`)
- Limits system commands to a configurable timeout and output size
- Logs all tool executions for auditing

**File:** `src/openacm/security/sandbox.py`

### 2. Secure Credential Management

All API keys and tokens are managed through:
- Environment variables (never hardcoded)
- Configuration files in `config/` (excluded from git)
- Conversation and activity data encrypted at rest with a local key (`config/activity.key`)

**Involved files:**
- `src/openacm/core/config.py` - Configuration loading
- `src/openacm/security/crypto.py` - Dashboard token generation
- `src/openacm/web/routers/system.py` - Dashboard authentication middleware

### 3. Channel Isolation

Each communication channel (Discord, Telegram, WhatsApp) operates with:
- Independent processes/tasks
- Separate security contexts
- Incoming message validation

---

## Critical Findings (By Design)

### External HTTP Communication

**Locations:**
- `src/openacm/core/llm_router.py`
- `src/openacm/channels/whatsapp_channel.py`
- `src/openacm/tools/web_search.py`
- `src/openacm/web/server.py`

**Description:**
OpenACM requires HTTP communication for:
- LLM APIs (OpenAI, Anthropic, Gemini, Ollama)
- Messaging APIs (WhatsApp Business, Telegram Bot, Discord)
- Web search (DuckDuckGo)
- External services (Google APIs)

**Mitigation:**
- Timeouts on outbound requests
- Bounded automatic retries (LLM calls)
- Tool calls logged to the database

### Environment Variable Access

**Locations:**
- `src/openacm/core/config.py`
- `src/openacm/security/crypto.py`
- `src/openacm/web/server.py`

**Description:**
API key loading via `os.environ.get()`

**Mitigation:**
- Keys are read from the environment; the only writes are the ones the operator triggers (dashboard setup / wizard writing `config/.env`, and the auto-generated `DASHBOARD_TOKEN`)
- No sensitive default values
- Clear documentation of required variables
- Example in `config/.env.example`

### Base64 Processing

**Location:**
- `src/openacm/tools/python_kernel.py:144`

**Description:**
Decoding base64-encoded PNG images from the Jupyter kernel

**Mitigation:**
- Only internally generated matplotlib images
- Does not process user input directly
- Format validation before decoding

---

## Security Policies

### Code Execution

- Allowed: System commands with sandbox
- Allowed: Python execution in isolated kernel (Jupyter)
- Blocked: No `eval()` or `exec()` of user input
- Blocked: No dynamic loading of unverified code

### File Access

- Allowed: Read/write wherever the OpenACM user can, except `blocked_paths`
- Blocked by default: OpenACM's own `config/`, `data/openacm.db`, `data/vectordb`, `data/logs`, `/etc/shadow`, `/etc/passwd`, `C:\Windows\System32`
- Add more (e.g. `~/.ssh`, `~/.aws`) to `security.blocked_paths`

### Network

- Allowed: Connections to the LLM providers, channels and integrations you configure
- Public inbound endpoints: `/webhooks/whatsapp` (signature-checked) and `/api/webhooks/{slug}` (per-connector auth); everything else under `/api/` requires the dashboard token
- The agent's network access is otherwise that of the OpenACM process — use execution modes, tool allowlists and host firewalls to restrict it

---

## Automatic Auditing

To run a security audit:

```bash
# Audit source code
python skills/skill_security_auditor.py src/

# Audit with strict mode
python skills/skill_security_auditor.py src/ --strict

# JSON output for CI/CD
python skills/skill_security_auditor.py src/ --json
```

---

## Reporting Vulnerabilities

If you discover a security vulnerability:

1. **DO NOT open a public issue**
2. Send an email to: [jeisondh55@gmail.com]
4. Include:
   - Detailed description
   - Steps to reproduce
   - Potential impact
   - Mitigation suggestions (optional)

**Expected response time:** 48-72 hours

---

## Sensitive Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `OPENAI_API_KEY` | OpenAI API | Optional |
| `ANTHROPIC_API_KEY` | Anthropic API | Optional |
| `GEMINI_API_KEY` | Google Gemini API | Optional |
| `DISCORD_TOKEN` | Discord Bot | Optional |
| `TELEGRAM_TOKEN` | Telegram Bot | Optional |
| `XAI_API_KEY`, `OPENROUTER_API_KEY`, `OPENCODE_GO_API_KEY` | Other built-in LLM providers | Optional |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | WhatsApp Cloud API | Optional |
| `STITCH_API_KEY`, `ELEVENLABS_API_KEY` | Google Stitch, ElevenLabs TTS | Optional |
| `DASHBOARD_TOKEN` | Web authentication | Auto-generated on first start |

Google OAuth2 credentials are files, not variables: `config/google_credentials.json` and `config/google_token.json`.

All variables are loaded via `os.environ.get()` with empty default values, from `config/.env` or the process environment.

---

## Best Practices for Users

### 1. API Key Protection

```bash
# Correct - Use .env file
export OPENAI_API_KEY="sk-..."
export DISCORD_TOKEN="..."

# Never commit the .env file
# It's included in .gitignore
```

### 2. Security Sandbox

The execution mode is configured in `config/default.yaml` / `config/local.yaml` (or from the dashboard):

```yaml
security:
  execution_mode: confirmation   # confirmation | auto | yolo
  max_command_timeout: 120       # seconds, 0 = no limit
  whitelisted_commands: [ls, git, python]   # used by auto mode
  blocked_paths:
    - config/
    - ~/.ssh
```

### 3. Keep dependencies updated

`pyproject.toml` pins security floors for direct dependencies (e.g. `litellm>=1.84.0`, `mcp>=1.28.1,<2`, `chromadb>=1.5.9`, `Pillow>=12.3.0`, `pypdf>=6.16.1`, `cryptography>=50`) and for vulnerable transitive packages via `[tool.uv] constraint-dependencies`. Run `./update.sh` (or `openacm update`) regularly.

### 4. Dashboard Token

The token is automatically generated on first launch:
- Stored as `DASHBOARD_TOKEN` in `config/.env` (plain text — protect the file with `chmod 600`)
- Rotate it by changing/removing that line (or with `openacm-setup` → Dashboard Token) and restarting
- It does not expire
- It is compared in constant time; with no token configured, both the HTTP API and the WebSockets reject every request

---

## Audit History

| Date | Tool | Result | Findings |
|------|------|--------|----------|
| 2025-03-27 | skill-security-auditor | PASS | 10/10 By Design |
| 2026-09-28 | Dependabot + CodeQL review | Fixed | Vulnerable dependencies bumped (see below); SPA path traversal guard tightened; exception details no longer returned to clients; ReDoS in the TTS markdown cleaner fixed; constant-time token comparison; WebSockets reject connections when no `DASHBOARD_TOKEN` is set |

---

## References

- [skill-security-auditor Documentation](../skills/SKILL.md)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python-security.readthedocs.io/)

---

**Note:** This document is automatically updated after each security audit.

Last updated: September 2026
