# Webhook Connectors

A **webhook connector** gives one of your [flows](./28-agent-flows.md) a public URL, so a third-party service — a payment provider, a CRM, a form backend, another server — can trigger it with an HTTP POST:

```
POST https://<your-openacm>/api/webhooks/{slug}
```

The connector authenticates the request with its own scheme (third parties can't send your dashboard token), runs the flow synchronously with the request's headers and body, and answers with the flow's result. Every attempt is written to an audit log.

---

## Creating a Connector

Connectors are created through the API (the **Connectors** page in the dashboard lists them, turns them on/off, and shows their activity):

```bash
curl -X POST http://localhost:47821/api/webhook-connectors \
  -H "Authorization: Bearer <dashboard-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "payments",
    "name": "Payment notifications",
    "auth_scheme": "hmac_sha256",
    "auth_config": {
      "secret": "a-long-random-secret",
      "timestamp_header": "X-Timestamp",
      "signature_header": "X-Signature",
      "max_skew_seconds": 300
    },
    "flow_id": 7,
    "dedupe_header": "X-Event-Id"
  }'
```

| Field | Required | Meaning |
|-------|----------|---------|
| `slug` | ✅ | Public URL segment — must be unique (`409` otherwise). It is **not** a secret |
| `name` | ✅ | Display name |
| `auth_scheme` | ✅ | `hmac_sha256`, `bearer_token` or `static_header_secret` |
| `auth_config` | ✅ | Scheme settings (see below) |
| `flow_id` | ✅ | The flow to run (any agent's flow) |
| `dedupe_header` | — | Header carrying a unique event id; a repeated id that already succeeded returns the stored result instead of running the flow again |

Secrets are masked as `"***"` in every response; sending `"***"` back in a `PATCH` keeps the stored value.

---

## Authentication Schemes

### `hmac_sha256` (recommended)

Authenticates the **body**, not just the caller, so tampered or replayed payloads fail.

```
signature    = HMAC-SHA256(secret, "<timestamp>." + <raw body bytes>)
header value = "sha256=" + hex(signature)
```

| `auth_config` key | Meaning |
|---|---|
| `secret` | Shared secret used as the HMAC key |
| `timestamp_header` | Header carrying the Unix timestamp (seconds) |
| `signature_header` | Header carrying `sha256=<hex>` |
| `max_skew_seconds` | Accepted clock skew in either direction (default `300`) |

Sign the **raw** request bytes — not a re-serialized JSON object.

**Sender example (Python):**
```python
import hashlib, hmac, json, time, httpx

body = json.dumps({"order_id": 123, "status": "paid"}).encode()
ts = str(int(time.time()))
sig = hmac.new(b"a-long-random-secret", ts.encode() + b"." + body, hashlib.sha256).hexdigest()

httpx.post(
    "https://acm.example.com/api/webhooks/payments",
    content=body,
    headers={"Content-Type": "application/json", "X-Timestamp": ts,
             "X-Signature": f"sha256={sig}", "X-Event-Id": "evt_001"},
)
```

### `bearer_token`

| `auth_config` key | Meaning |
|---|---|
| `token` | Expected token |
| `header_name` | Header to read (default `Authorization`); its value must be `Bearer <token>` |

### `static_header_secret`

| `auth_config` key | Meaning |
|---|---|
| `header_name` | Header to read |
| `secret` | Expected value |

All comparisons are constant-time. `bearer_token` and `static_header_secret` authenticate the caller only, not the payload.

---

## What the Flow Receives

The flow is run with two parameters:

| Parameter | Content |
|-----------|---------|
| `headers` | The request headers (object) |
| `body` | The parsed JSON body (object; `{}` for an empty body) |

Use templates such as `{{body.order_id}}` or `{{body.customer.email}}` in the flow's nodes (declaring `body` / `headers` as Start parameters documents them and lets you test the flow with sample data). The End node's text is returned to the caller.

> WooCommerce nodes need the per-agent connection lookup, which webhook-triggered runs don't have in v0.4.7 — use HTTP nodes in connector flows.

---

## Responses

| Status | When | Body |
|--------|------|------|
| `200` | Flow ran (or duplicate of a successful event) | `{"result": "<End node text>"}` |
| `400` | Body is not valid JSON | `{"error": "Invalid JSON body"}` |
| `401` | Authentication failed (any reason) | `{"error": "Invalid credentials"}` |
| `404` | Unknown slug or connector disabled | — |
| `500` | The configured flow is missing or structurally invalid | generic detail (reasons only in the audit log) |
| `502` | The flow failed at runtime (e.g. an HTTP node errored) | `{"error": "<flow error>"}` |

The flow runs inline, within the request.

---

## Audit Log

Every attempt is stored in `webhook_connector_events` with status `ok`, `auth_failed`, `bad_request` or `flow_error`, the body (truncated to 8 KB for failed-auth attempts), the result or error, and the duration. View it on the **Connectors** page or with:

```bash
curl http://localhost:47821/api/webhook-connectors/1/events \
  -H "Authorization: Bearer <dashboard-token>"
# → {"events": [...], "stats": {...}}
```

---

## Admin API

| Endpoint | Description |
|----------|-------------|
| `GET /api/webhook-connectors` | List |
| `GET /api/webhook-connectors/{id}` | Get one |
| `POST /api/webhook-connectors` | Create |
| `PATCH /api/webhook-connectors/{id}` | Update any field (e.g. `{"enabled": 0}`) |
| `DELETE /api/webhook-connectors/{id}` | Delete |
| `GET /api/webhook-connectors/{id}/events` | Audit log + stats |

The admin routes require the dashboard token; only `POST /api/webhooks/{slug}` is public. See also [Security → Public Webhook Connectors](./12-security.md#public-webhook-connectors-apiwebhooks).

---

## Exposing it to the Internet

The third party must reach `https://<your-domain>/api/webhooks/{slug}`. Put OpenACM behind a reverse proxy with HTTPS (see [Deploy on a VPS](./DEPLOY_VPS.md)) or a tunnel (e.g. Cloudflare Tunnel, as in [WhatsApp Setup](./WHATSAPP_SETUP.md)). If you only want to expose webhooks, configure the proxy to forward just `/api/webhooks/` paths.
