# Security

OpenACM gives the AI real, direct access to your computer. This is a deliberate design choice — it's what makes OpenACM powerful. But it also means security needs to be taken seriously.

---

## Threat Model

OpenACM is designed to be run by you, for yourself, on your own hardware. The threat model assumes:

- **Trusted operator** (you) — you control the config, the tools, and the LLM
- **Untrusted inputs** — messages from Telegram, Discord, or WhatsApp should be treated with appropriate caution if those channels are public or shared
- **LLM mistakes** — the LLM might misinterpret a request and take an unintended action

OpenACM is **not** designed to be a multi-tenant service where untrusted users have direct access.

---

## Execution Modes

The `security.execution_mode` config setting controls how aggressively OpenACM executes tools.

### `auto` (default)
OpenACM executes all tools automatically. Blocked patterns and hardcoded restrictions still apply. Best for personal use where you trust the inputs.

### `confirmation`
Before executing `medium` or `high` risk tools, OpenACM asks for your approval. `low` risk tools always execute immediately.

| Risk Level | Confirmation Required |
|------------|----------------------|
| low | Never |
| medium | Yes (in confirmation mode) |
| high | Yes (in confirmation mode) |

### `yolo`
All tools execute without restriction (except hardcoded blocks). Use only in fully automated pipelines where you've reviewed the agent's behavior.

---

## Hardcoded Blocks (cannot be overridden)

These patterns are always blocked regardless of execution mode:

- **Privilege escalation:** `sudo su`, `runas /priv`, UAC elevation, SUID bit manipulation
- **Credential access:** `.ssh/id_rsa`, `/etc/shadow`, Windows SAM database, LSASS dump
- **Security tool bypass:** UAC dialog automation, sudo prompt interception

Even in `yolo` mode, these cannot be executed.

---

## Configurable Blocks

Add custom patterns to block in `config/default.yaml`:

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

Patterns are matched as substrings against command strings before execution.

---

## Tool Risk Levels

Every tool is annotated with a risk level:

| Level | Examples | Confirmation Required |
|-------|----------|----------------------|
| `low` | `web_search`, `read_file`, `system_info`, `search_memory`, `ha_control` | Never |
| `medium` | `write_file`, `take_screenshot`, `gmail_send` | In confirmation mode |
| `high` | `run_command`, `run_python`, `browser_agent`, `create_tool` | In confirmation mode |

---

## Sandbox

All `high` risk tools run through the `Sandbox` component, which enforces:

| Limit | Default | Config Key |
|-------|---------|------------|
| Execution timeout | 120s | `security.max_command_timeout` |
| Output size | 50KB | `security.max_output_length` |
| Environment injection | `CI=true`, stdin=`y` | Hardcoded safety net |

If a command exceeds the timeout, it's forcefully terminated. Output over the size limit is truncated.

---

## Encryption at Rest

### Conversation Messages
All conversation messages are encrypted before writing to SQLite using AES-GCM. The encryption key is stored locally at `data/.activity_key`. 

Without the key file, the database is unreadable. If you delete the key, old messages become unrecoverable.

### Activity Data
OS activity sessions (app names, window titles, process names) are encrypted with the same key.

### What is NOT encrypted
- Tool execution logs (arguments, results)
- LLM usage statistics (token counts, model names)
- Skill definitions
- Agent metadata

---

## Dashboard Authentication

The web dashboard is protected by a randomly generated token stored at `data/.dashboard_token`. On first run, the token is printed to the terminal.

The token can be:
- Stored in your browser (the dashboard saves it in localStorage)
- Passed as a Bearer header
- Passed as a `?token=` query parameter

To reset the token:
```bash
rm data/.dashboard_token
# Restart OpenACM — a new token will be generated and printed
```

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
      - 123456789   # Your Telegram user ID
      - 987654321   # Another allowed user
```

Find your Telegram user ID by messaging `@userinfobot`.

### Discord
Restrict to specific servers:

```yaml
channels:
  discord:
    enabled: true
    token: "${DISCORD_TOKEN}"
    allowed_guilds:
      - 1234567890123456789  # Your server's guild ID
```

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
| Personal laptop (just me) | `execution_mode: auto`, `host: 127.0.0.1` |
| Shared household server | `execution_mode: confirmation`, Telegram `allowed_users`, `host: 0.0.0.0` + HTTPS |
| Automated pipeline (no humans) | `execution_mode: yolo`, no external channels, localhost only |
| Public Telegram bot | `execution_mode: confirmation`, `allowed_users` strictly set, limited tool set |

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
