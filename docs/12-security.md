# Security

OpenACM gives the AI real, direct access to your computer. This is a deliberate design choice — it's what makes OpenACM powerful. But it also means security needs to be taken seriously.

---

## Threat Model

OpenACM is designed to be run by you, for yourself, on your own hardware. The threat model assumes:

- **Trusted operator** (you) — you control the config, the tools, and the LLM
- **Untrusted inputs** — messages from Telegram, Discord, WhatsApp and agent channels should be treated with appropriate caution if those channels are public or shared
- **LLM mistakes** — the LLM might misinterpret a request and take an unintended action

OpenACM is **not** designed to be a multi-tenant service where untrusted users have direct access.

---

## Execution Modes

The `security.execution_mode` setting controls how OpenACM runs **shell commands** (the `run_command` tool). Other tools are not gated by the mode — control what an agent can do with its tool allowlist.

### `confirmation` (default)
Every command is sent to the dashboard for approval (`tool.confirmation_needed` event → approve/deny dialog, `POST /api/tool/confirm`). You can also approve a command for the rest of the session. Best default for most users.

### `auto`
Only commands whose executable (first word, e.g. `git`, `ls`, `python`) is in `security.whitelisted_commands` run — without asking. Anything else is rejected with "not in the whitelist". Blocked patterns and paths still apply.

### `yolo`
Every command runs without asking. Hardcoded blocks, blocked patterns and blocked paths still apply. Use only in fully automated pipelines where you've reviewed the agent's behavior.

The mode can be changed from the dashboard, `PATCH /api/config/security`, or the `update_security_mode` tool; it is persisted in the database and restored at startup.

---

## Hardcoded Blocks (cannot be overridden)

These patterns are always blocked regardless of execution mode (they either escalate privileges — which would hang the subprocess on a UAC/sudo prompt — or touch credential files):

- **Windows privilege escalation:** `runas`, `gsudo`, `net user … /add`, `net localgroup administrators … /add`
- **Linux/macOS privilege escalation:** `sudo -s`, `sudo -i`, `su -`, setuid/setgid `chmod` (e.g. `chmod 4755`), `chown root`
- **Credential files:** `/etc/shadow`, `/etc/passwd`

Even in `yolo` mode, these cannot be executed.

---

## Configurable Blocks

Add custom patterns to block in `config/local.yaml` (it replaces the list from `default.yaml`, so copy the entries you want to keep):

```yaml
security:
  blocked_patterns:
    - "rm -rf /"
    - "mkfs"
    - "dd if=/dev/zero of=/dev"
  blocked_paths:
    - "/etc/passwd"
    - "~/.ssh/config"
```

Patterns are matched as case-insensitive substrings against command strings before execution. Every entry of `blocked_paths` is also checked against shell commands (so `cat config/.env` is blocked when `config/` is listed) and against the paths used by file tools. The shipped defaults block OpenACM's own `config/`, `data/openacm.db`, `data/vectordb` and `data/logs`.

---

## Tool Risk Levels

Every tool is annotated with a risk level:

| Level | Examples |
|-------|----------|
| `low` | `list_directory`, `system_info`, `search_memory`, `ha_control` |
| `medium` | `read_file`, `web_search`, `take_screenshot`, `calendar_create`, `ha_call_service` |
| `high` | `run_command`, `run_python`, `write_file`, `edit_file`, `browser_agent`, `gmail_send`, `delete_agent` |

Risk levels are shown in the dashboard and in `/tools` so you can decide which tools to give each agent. The approval prompt itself is driven by the execution mode (shell commands), not by the risk level.

---

## Sandbox

Shell commands run through the `Sandbox` component, which enforces:

| Limit | Default | Config Key |
|-------|---------|------------|
| Execution timeout | 120 s built-in (the shipped `default.yaml` sets `0` = no limit) | `security.max_command_timeout` |
| Output size | 50,000 chars | `security.max_output_length` |
| Environment injection | `CI=true`, `npm_config_yes=true` | Hardcoded, so tools skip interactive prompts |

If a command exceeds the timeout, it's forcefully terminated. Output over the size limit is truncated. The sandbox is not an OS-level jail — commands run as the OpenACM user.

---

## Encryption at Rest

### Conversation Messages
All conversation messages are encrypted before writing to SQLite using Fernet (AES-128-CBC + HMAC-SHA256). The key is generated on first start and stored locally at `config/activity.key` (git-ignored).

Without the key file, the stored messages are unreadable. If you delete the key, old messages become unrecoverable — back it up together with `data/openacm.db`.

### Activity Data
OS activity sessions (app names, window titles, process names) are encrypted with the same key.

### What is NOT encrypted
- Tool execution logs (arguments, results)
- LLM usage statistics (token counts, model names)
- Skill definitions, agents, flows, knowledge base entries
- Agent channel credentials, webhook connector secrets and plugin settings (stored in SQLite; masked in API responses)
- The ChromaDB vector store (`data/vectordb/`)
- Files in `data/media/`
- `config/.env` (protect it with file permissions)

---

## Dashboard Authentication

The web dashboard and every `/api/*` route are protected by a token. On first run a random token is generated, saved as `DASHBOARD_TOKEN` in `config/.env`, and printed to the terminal. If `DASHBOARD_TOKEN` is already set, that value is used.

The token can be:
- Stored in your browser (the dashboard saves it after login)
- Passed as a Bearer header
- Passed as a `?token=` query parameter (WebSockets always use the query parameter)

Tokens are compared in constant time. If no `DASHBOARD_TOKEN` is configured, **both** the HTTP API and the WebSocket endpoints reject every request — the API is never silently open.

To reset the token, remove the `DASHBOARD_TOKEN=` line from `config/.env` (or set a new value) and restart OpenACM.

Public exceptions to the token check are listed in the [API Reference](./10-api-reference.md#authentication).

---

## Public Webhook Connectors (`/api/webhooks/*`)

Every route under `/api/` requires the dashboard token, with one deliberate exception: `POST /api/webhooks/{slug}`. Third-party services (payment providers, CRMs, form backends) can't send a dashboard token, so this prefix is exempt from `TokenAuthMiddleware` and **each connector authenticates its own requests** according to the `auth_scheme` chosen when it was created. The admin routes that manage connectors — `/api/webhook-connectors*` — are *not* exempt and still require the dashboard token.

A slug is therefore not a secret. The only thing protecting a connector is its configured scheme, so never create one with credentials you wouldn't put on the public internet. Every attempt — accepted or rejected — is written to `webhook_connector_events` with a status of `ok`, `auth_failed`, `bad_request` or `flow_error`; bodies stored on the `auth_failed` path are truncated to 8 KB. Secrets are masked as `"***"` on every API response; sending `"***"` back in a `PATCH` leaves the stored value untouched.

### The `hmac_sha256` contract

This is the scheme to prefer — it authenticates the *body*, not just the caller, so a replayed or tampered payload fails.

The sender computes:

```
signature = HMAC-SHA256(secret, "<timestamp>." + <raw body bytes>)
header value = "sha256=" + hex(signature)
```

Note that the signed message is the timestamp, a literal `.`, and the **raw** request bytes — not a re-serialized JSON object. Signing a pretty-printed or key-reordered copy of the body will not verify.

`auth_config` for this scheme:

| Key | Meaning |
|---|---|
| `secret` | Shared secret, used as the HMAC key |
| `timestamp_header` | Header carrying the Unix timestamp (seconds), e.g. `X-Timestamp` |
| `signature_header` | Header carrying `sha256=<hex>`, e.g. `X-Signature` |
| `max_skew_seconds` | Accepted clock skew in either direction (default `300`) |

A request is rejected if either header is missing, the timestamp isn't an integer, it is more than `max_skew_seconds` away from now, or the signature doesn't match. The comparison uses `hmac.compare_digest` (constant time). The other two schemes — `bearer_token` (an `Authorization: Bearer <token>` style header) and `static_header_secret` (a fixed header value) — use the same constant-time comparison but only authenticate the caller, not the payload.

Verification never raises: any malformed header, body or stored config resolves to "rejected" (`401`) and an `auth_failed` audit row, so a malformed request can't 500 the route and slip past the audit trail.

---

## Channel Security

### Telegram
By default, any Telegram user who knows your bot's username can message OpenACM. Restrict access with an allowlist:

```yaml
channels:
  telegram:
    enabled: true
    token: "${TELEGRAM_TOKEN}"
    allowed_users:
      - "123456789"   # Your Telegram user ID (as a string)
      - "987654321"   # Another allowed user
```

Find your Telegram user ID by messaging `@userinfobot`.

### Discord
The config has an `allowed_guilds` list, but v0.4.7 does not enforce it — anyone who can mention the bot or DM it can talk to OpenACM. Only invite the bot to servers you control, or leave Discord disabled.

### WhatsApp
The `/webhooks/whatsapp` endpoint is public by design (Meta must reach it). POST bodies are checked against `WHATSAPP_APP_SECRET` (`X-Hub-Signature-256`) — always set the app secret.

### Agent channels
An agent's Telegram bot / WhatsApp number is usually public. Give customer-facing agents a minimal tool allowlist — never `run_command` or `"all"`.

### Web Dashboard
The dashboard is only accessible from `localhost` by default (`host: "127.0.0.1"`). To expose it on your network, set `host: "0.0.0.0"` — but use a reverse proxy with HTTPS and keep the token secret.

---

## Network Exposure

If you expose OpenACM to the internet (via port forwarding, ngrok, etc.), be aware:

1. Anyone with the token has full control of your computer
2. Use HTTPS — never expose over plain HTTP on the public internet
3. Consider adding IP allowlisting at the reverse proxy level
4. Rotate the token regularly

Recommended reverse proxy setup with nginx:

```nginx
server {
    listen 443 ssl;
    server_name acm.yourdomain.com;
    
    ssl_certificate /etc/letsencrypt/live/acm.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/acm.yourdomain.com/privkey.pem;
    
    location / {
        proxy_pass http://127.0.0.1:47821;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

---

## Recommendations by Use Case

| Use Case | Recommended Settings |
|----------|---------------------|
| Personal laptop (just me) | `execution_mode: confirmation` (or `auto` with a curated whitelist), `host: 127.0.0.1` |
| Shared household server | `execution_mode: confirmation`, Telegram `allowed_users`, `host: 0.0.0.0` + HTTPS |
| Automated pipeline (no humans) | `execution_mode: yolo`, no external channels, localhost only |
| Public Telegram bot | `execution_mode: confirmation`, `allowed_users` strictly set, limited tool set |
| Customer-facing agent (WhatsApp/Telegram) | Agent with a minimal allowlist (or `none` + flows), `memory_mode: session_ttl` |

---

## Error Handling

API endpoints don't echo exception details (stack traces, library error messages) back to clients — agent errors return a generic message, and the details are written to the server logs (`data/logs/`). Check the logs or the **Traces** page when something fails.

---

## Dependencies

Security floors are pinned for vulnerable packages: direct dependencies in `pyproject.toml` (e.g. `litellm>=1.84.0`, `mcp>=1.28.1,<2`, `chromadb>=1.5.9`, `Pillow>=12.3.0`, `pypdf>=6.16.1`, `cryptography>=50`) and transitive ones through `[tool.uv] constraint-dependencies`. Keep them current with `update.sh` / `openacm update`, which re-syncs dependencies.

---

## Audit Log

Every tool execution is logged to the database with:
- Timestamp
- User and channel that triggered it
- Tool name and arguments
- Result (truncated to 5KB)
- Success/failure flag
- Execution time in milliseconds

View this log in the dashboard under **Tools → Execution Log**, or query via `GET /api/tools/executions`.
