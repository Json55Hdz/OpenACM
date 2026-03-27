# OpenACM Security Policy

## Threat Model and Security Analysis

**Last Audit:** March 2025
**Tool:** skill-security-auditor (Claude Skills)
**Verdict:** SECURE - All findings are BY DESIGN

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

OpenACM implements a security sandbox in `src/openacm/security/sandbox.py` that:
- Limits system commands to a configurable timeout
- Restricts access to sensitive directories
- Validates paths before file operations
- Logs all executions for auditing

**File:** `src/openacm/security/sandbox.py`

### 2. Secure Credential Management

All API keys and tokens are managed through:
- Environment variables (never hardcoded)
- Configuration files in `config/` (excluded from git)
- Optional encryption for persistent tokens

**Involved files:**
- `src/openacm/core/config.py` - Configuration loading
- `src/openacm/security/crypto.py` - Token management
- `src/openacm/web/server.py` - Dashboard authentication

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
- Timeout on all requests (15-30s)
- No unlimited automatic retries
- URL validation (avoids localhost/private IPs)
- All calls logged

### Environment Variable Access

**Locations:**
- `src/openacm/core/config.py`
- `src/openacm/security/crypto.py`
- `src/openacm/web/server.py`

**Description:**
API key loading via `os.environ.get()`

**Mitigation:**
- Read-only, never write
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

- Allowed: Read/write in working directory
- Allowed: Access to `data/` for persistence
- Allowed: Access to `config/` for configuration
- Blocked: No access to `~/.ssh`, `~/.aws`, system credentials
- Blocked: No modification of system files

### Network

- Allowed: Connections to documented public APIs
- Allowed: Webhooks for messaging channels
- Blocked: No port scanning
- Blocked: No connections to private IPs without authorization

---

## Automatic Auditing

To run a security audit:

```bash
# Audit source code
python .opencode/skills/skill-security-auditor/scripts/skill_security_auditor.py src/

# Audit with strict mode
python .opencode/skills/skill-security-auditor/scripts/skill_security_auditor.py src/ --strict

# JSON output for CI/CD
python .opencode/skills/skill-security-auditor/scripts/skill_security_auditor.py src/ --json
```

---

## Reporting Vulnerabilities

If you discover a security vulnerability:

1. **DO NOT open a public issue**
2. Send an email to: [your-email@example.com]
3. Include:
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
| `DASHBOARD_TOKEN` | Web authentication | Auto-generated |
| `GOOGLE_CREDENTIALS` | Google OAuth2 | Optional |

All variables are loaded via `os.environ.get()` with empty default values.

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

The execution mode is configured in `config/default.yaml`:

```yaml
security:
  execution_mode: strict  # strict | normal | permissive
  max_command_timeout: 30
  allowed_paths:
    - ./data
    - ./config
```

### 3. Dashboard Token

The token is automatically generated on first launch:
- Stored encrypted in `data/openacm.db`
- Can be rotated from the web configuration
- Configurable TTL (default: no expiration)

---

## Audit History

| Date | Tool | Result | Findings |
|------|------|--------|----------|
| 2025-03-27 | skill-security-auditor | PASS | 10/10 By Design |

---

## References

- [skill-security-auditor Documentation](.opencode/skills/skill-security-auditor/SKILL.md)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python-security.readthedocs.io/)

---

**Note:** This document is automatically updated after each security audit.

Last updated: March 2025
