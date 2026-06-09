# Gmail Classifier — Inbox Summary & Daily Digest

**Date:** 2026-06-09
**Status:** Approved

## Overview

Two related features sharing a common AI summary generator:

1. **"¿Qué hay?" button** — on-demand AI summary of today's inbox shown inline in the Gmail Classifier UI.
2. **Daily Digest** — scheduled delivery of the same summary to any configured channel (Telegram today, extensible to any future channel) via a channel-agnostic EventBus event.

## Summary Content

The summary always covers **today's emails** (from midnight local time to now). It contains two parts:

**Part A — Counts by category:**
```
📬 Resumen del inbox (hoy)
• 47 correos — 12 sin leer
• Importantes: 3  |  Trabajo: 8  |  Otros: 31
```

**Part B — Top 2-3 urgent emails identified by LLM:**
```
🔴 Urgentes detectados:
1. Ana Torres — "Propuesta pendiente de aprobación" (hace 2 días)
2. Carlos Ruiz — "Confirmación reunión jueves" (recibido hoy)
```

If no emails arrived today: `"No hay correos de hoy todavía."` (no LLM call made).

The LLM receives only subject + sender_name + received_at for up to 30 emails — never body text. This keeps the prompt small and fast.

## Architecture

### New file: `src/openacm/plugins/gmail_classifier/summary.py`

Single async function:

```python
async def generate_inbox_summary(db, llm_router, event_bus=None) -> str
```

Steps:
1. Query `gmail_emails` for today's emails (received_at >= midnight in the server's local timezone, compared using SQLite's `date()` with `localtime` modifier), joining `gmail_categories` for category name.
2. Compute counts: total, unread, per-category.
3. If total == 0: return the no-emails message immediately.
4. Build LLM prompt with the 30 most recent emails of the day ordered by `received_at DESC` (subject, sender_name, received_at, category). Ask for 2-3 urgent items with one-line justification each.
5. Call `llm_router.chat()` with a short timeout (20s). On timeout or error: return Part A only with a note that urgent detection failed.
6. Parse LLM response and assemble final formatted string.
7. Optionally emit `summary:generated` event on event_bus for dashboard tracing.

This function has no side effects and is safe to call concurrently.

### New endpoint: `GET /gmail-classifier/summary`

```
GET /gmail-classifier/summary
→ 200 { "summary": "...", "generated_at": "2026-06-09T08:00:00" }
→ 503 { "detail": "LLM not configured" }
```

Calls `generate_inbox_summary()`. No auth beyond existing plugin auth. No caching — each call is fresh.

### Channel-agnostic delivery: `channel:send` event

The digest cron emits a new EventBus event:

```python
await event_bus.emit("channel:send", {
    "agent_id": int,       # which agent's channel to use
    "target_id": str,      # chat_id, phone number, etc. — channel-specific
    "text": str,           # the summary text
})
```

**`TelegramChannel`** (modified): subscribes to `channel:send` on startup. When the event fires with a matching `agent_id`, calls `bot.send_message(chat_id=data["target_id"], text=data["text"])`.

Any future channel (WhatsApp, Discord, etc.) implements the same subscription pattern independently. The Gmail plugin never imports or references any specific channel class.

### Digest cron: second task in `__init__.py`

A second asyncio task (`_digest_loop`) runs alongside the existing `_cron_loop`. On startup, `_start_digest_cron()` is called if `digest_enabled == "true"` and `digest_time` is set.

`_digest_loop` logic:
1. Parse `digest_time` (HH:MM) and `digest_days` (comma-separated ISO weekday numbers, 1=Monday, 7=Sunday).
2. Calculate next fire time: find the next datetime matching the configured time and one of the configured days.
3. Sleep until that time.
4. Check that `digest_enabled` is still `"true"` (may have been toggled off while sleeping).
5. Call `generate_inbox_summary(db, llm_router)`.
6. Emit `channel:send` event with `digest_agent_id` and `digest_chat_id` from settings.
7. Repeat.

The digest cron is started/stopped independently of the processing cron. Changing digest settings via the API restarts only the digest task.

## New Settings Keys

Added to `gmail_classifier_settings`:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `digest_enabled` | `"true"/"false"` | `"false"` | Master switch |
| `digest_time` | `"HH:MM"` | `""` | Local time to send |
| `digest_days` | `"1,2,3,4,5"` | `"1,2,3,4,5"` | ISO weekday numbers |
| `digest_agent_id` | `"<int>"` | `""` | Agent whose channel sends the digest |
| `digest_chat_id` | `"<str>"` | `""` | Channel-specific destination ID |

All five keys are seeded as empty strings on first plugin start (migration).

`SettingsBody` in `router.py` gains five new optional fields. `PUT /settings` persists them and restarts the digest cron task if any digest key changed.

## Frontend

### "¿Qué hay?" button — `page.tsx`

A small button added to the toolbar row (right of the Procesar/Detener group):

```tsx
<button onClick={handleSummary} disabled={summaryLoading}>
  {summaryLoading ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
  ¿Qué hay?
</button>
```

State: `summaryLoading: bool`, `summaryText: string | null`, `summaryError: string | null`.

When `summaryText` is set, a dismissible panel appears directly below the toolbar (above the category tabs):

```tsx
{summaryText && (
  <div className="...amber/yellow border panel...">
    <pre className="whitespace-pre-wrap text-[12px]">{summaryText}</pre>
    <button onClick={() => setSummaryText(null)}>✕</button>
  </div>
)}
```

Uses `<pre>` with `whitespace-pre-wrap` to preserve the line-break formatting of the summary string.

### Digest tab — `PluginSettings.tsx`

Fourth tab **"Digest"** added alongside General, Auto-respuesta, Backup.

Fields:
- **Toggle** `digest_enabled` — "Activar digest diario"
- **Time inputs** — two `<input type="number">` fields for HH and MM (validated 0-23 / 0-59)
- **Day checkboxes** — L M X J V S D (ISO 1-7), defaults L-V
- **Agent dropdown** — `GET /agents` populates a `<select>` with agent name + id
- **Chat ID input** — free text input for the destination identifier
- **"Probar envío" button** — calls `POST /gmail-classifier/summary/test-send` which generates the summary and emits `channel:send` immediately (ignores schedule). Shows success/error inline.

All fields are disabled when `digest_enabled` is off.

### New endpoint: `POST /gmail-classifier/summary/test-send`

```
POST /gmail-classifier/summary/test-send
→ 200 { "sent": true }
→ 400 { "detail": "digest_agent_id or digest_chat_id not configured" }
→ 500 { "detail": "..." }
```

Generates summary and emits `channel:send` immediately. Does not check the schedule or `digest_enabled`. Used only for the "Probar envío" button.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| No emails today | Return no-emails message, no LLM call |
| LLM timeout (>20s) | Return Part A only + note: "No se pudo identificar urgentes" |
| LLM error | Same as timeout |
| `channel:send` emitted but no channel subscribed for that agent_id | Event fires, nothing happens (no error — channel may not be running) |
| Digest cron fires but `digest_agent_id` is empty | Log warning, skip send |
| `digest_enabled` toggled off while sleeping | Cron checks on wake, skips send and exits loop |

## Out of Scope

- Summary for date ranges other than today
- Push notification support (mobile / browser notifications)
- Per-category summary depth configuration
- Automatic channel discovery (user must know their chat_id)
- Digest history / audit log
- Multiple digest destinations (one agent + one target per plugin instance)
