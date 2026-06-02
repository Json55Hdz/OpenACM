# Gmail Classifier Plugin — Design Spec
**Date:** 2026-06-01  
**Status:** Approved

## Overview

A new OpenACM plugin that connects to the existing Gmail OAuth integration, lets the user create categories (with name, description, color, icon), and uses AI to classify emails from a chosen date onward into those categories. Emails that cannot be classified fall into "Otros". The plugin tracks thread reply status and lets the user mark emails as read/unread from a split-view UI.

---

## Goals

- Let the user define classification categories with metadata (name, description, color, icon)
- Process 100–1000 emails per run, in batches, using the active LLM via `llm_router`
- Show a tab per category (+ "Todo") with a split-view email list/detail panel
- Track thread state: if user was last to reply → "respondido"; if a new reply arrives → back to unread
- Trigger processing manually (button + date picker) and/or automatically via the system's cron scheduler
- Optionally mark emails as read in Gmail and/or apply Gmail labels — configurable per plugin settings

## Non-Goals

- Auto-replying to emails (AI-generated replies without user input)
- Composing new emails (only replying to existing threads)
- Handling attachments
- Multi-account Gmail support

---

## Architecture

### Plugin location

```
src/openacm/plugins/gmail_classifier/
├── __init__.py      ← GmailClassifierPlugin (extends BasePlugin)
├── processor.py     ← GmailBatchProcessor
└── router.py        ← FastAPI APIRouter (/api/gmail-classifier/*)

frontend/app/gmail-classifier/
└── page.tsx
    components/
    ├── CategoryTabs.tsx
    ├── EmailList.tsx
    ├── EmailDetail.tsx
    ├── CategoryManager.tsx    (create/edit/delete categories dialog)
    ├── ProcessingProgress.tsx
    └── PluginSettings.tsx
```

### Plugin registration

`GmailClassifierPlugin` registers:
- `get_nav_items()` → `{"path": "/gmail-classifier", "label": "Gmail", "icon": "Mail", "section": "main"}`
- `get_api_router()` → the FastAPI router from `router.py`
- `on_start(**ctx)` → stores `db`, `llm_router`, `event_bus`, `tool_registry` (for cron_scheduler access)

The plugin is auto-discovered via the `openacm.plugins` subpackage pattern (exposes a `PLUGIN` instance at module level).

---

## Database Schema

Three new tables added to `database.py`'s `executescript()`:

```sql
CREATE TABLE IF NOT EXISTS gmail_categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    color       TEXT NOT NULL DEFAULT '#6366f1',
    icon        TEXT NOT NULL DEFAULT 'Tag',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gmail_emails (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_id      TEXT NOT NULL UNIQUE,
    thread_id     TEXT,
    subject       TEXT,
    sender_name   TEXT,
    sender_email  TEXT,
    snippet       TEXT,
    category_id   INTEGER REFERENCES gmail_categories(id),
    is_read       INTEGER NOT NULL DEFAULT 0,
    is_replied    INTEGER NOT NULL DEFAULT 0,
    ai_classified INTEGER NOT NULL DEFAULT 0,
    received_at   DATETIME,
    last_synced   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gmail_classifier_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
```

**Default settings (inserted on first startup if not present):**

| key | default | description |
|-----|---------|-------------|
| `auto_mark_read` | `"false"` | Mark email as read in Gmail after classification |
| `auto_apply_label` | `"false"` | Apply Gmail label with category name |
| `cron_schedule` | `""` | Cron expression; empty = disabled |
| `since_date_default` | `""` | Default date pre-filled in the date picker |

When a category is deleted, all its emails are re-assigned to "Otros". The "Otros" category is auto-created by the plugin on `on_start` if it does not exist (`INSERT OR IGNORE`), cannot be deleted or renamed, and is always the last tab in the UI.

---

## GmailBatchProcessor

File: `processor.py`

```python
class GmailBatchProcessor:
    BATCH_SIZE = 20  # emails per LLM call

    async def process(self, since_date: str) -> dict:
        ...
```

### Processing flow

1. **Fetch message IDs** — Call Gmail API `messages.list` with query `after:{since_date}`. Paginate until all IDs are collected (Gmail returns max 500 per page).
2. **Fetch details** — For each batch of `BATCH_SIZE` IDs, call `messages.get` to retrieve `subject`, `from`, `snippet`, `threadId`, `internalDate`.
3. **Determine thread reply status** — For threads not yet in DB, fetch the thread's last message sender. If it matches the authenticated user's email → `is_replied=1`.
4. **Rate limiting** — Gmail API allows ~250 quota units/second. Fetching message details costs 5 units/message. For 1000 emails, add `asyncio.sleep(0.05)` between individual `messages.get` calls to stay under quota. Alternatively, use Gmail API batch HTTP requests (up to 100 requests per batch HTTP call) to reduce round trips.
5. **Classify with LLM** — Build a prompt listing all user categories (name + description) and the batch of emails (index, sender, subject, snippet). Ask LLM to return a JSON array `[{gmail_id, category_name}]`. Fallback to "Otros" for any email not matched or on LLM error.
5. **Upsert** — Insert or update `gmail_emails` rows. New emails get `is_read=0`; existing emails only update `category_id` and `ai_classified`.
6. **Optional Gmail actions** — If `auto_mark_read=true`, call `messages.modify` to remove `UNREAD` label. If `auto_apply_label=true`, ensure Gmail label exists for the category and apply it.
7. **Yield control** — Call `asyncio.sleep(0)` between batches to not block the event loop.
8. **Emit events** — Emit `gmail_classifier.progress {processed, total}` after each batch, `gmail_classifier.completed {total, by_category}` at the end.

### Thread re-open logic (on subsequent syncs)

For emails already in DB (`is_replied=1`), check if the thread now has messages newer than `last_synced` from a sender that is not the authenticated user. If yes → set `is_read=0`, `is_replied=0`, update `last_synced`.

### Classification prompt template

```
You are an email classifier. Classify each email into exactly one of these categories:
{categories_block}
- Otros: Use this when the email does not fit any category above.

Return ONLY a JSON array, no explanation:
[{"gmail_id": "...", "category": "CategoryName"}, ...]

Emails to classify:
{emails_block}
```

---

## API Endpoints

All routes are prefixed `/api/gmail-classifier`.

### Categories

| Method | Path | Description |
|--------|------|-------------|
| GET | `/categories` | List all categories (includes email count) |
| POST | `/categories` | Create category `{name, description, color, icon}` |
| PUT | `/categories/{id}` | Update category |
| DELETE | `/categories/{id}` | Delete category; reassign emails to Otros |

### Emails

| Method | Path | Description |
|--------|------|-------------|
| GET | `/emails` | List emails. Query params: `category_id`, `is_read`, `page`, `per_page` (default 50) |
| PATCH | `/emails/{id}/read` | Toggle `is_read` for one email |
| PATCH | `/emails/{id}/category` | Manually recategorize `{category_id}` |
| POST | `/emails/{id}/reply` | Send reply `{body: str}`; sets `is_replied=1`, `is_read=1` on success |

### Processing

| Method | Path | Description |
|--------|------|-------------|
| POST | `/process` | Start batch `{since_date: "YYYY-MM-DD"}`. Returns 409 if already running. |
| GET | `/process/status` | `{running: bool, processed: int, total: int, started_at: str}` |

### Settings & Cron

| Method | Path | Description |
|--------|------|-------------|
| GET | `/settings` | Get all plugin settings as `{key: value}` |
| PUT | `/settings` | Update one or more settings |
| POST | `/cron` | Set cron schedule `{schedule: "0 * * * *"}` |
| DELETE | `/cron` | Disable cron (sets schedule to `""`) |

---

## Frontend UI

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ Gmail Classifier              [⚙ Config]  [▶ Procesar desde: ──] │
├─────────────────────────────────────────────────────────────────┤
│ [Todo] [● Parqueaderos 12] [● Peticiones 5] [● Otros 3] [+ Cat.] │
├──────────────────────────┬──────────────────────────────────────┤
│  ● Juan García           │  De: juan@example.com               │
│    Consulta parqueadero  │  Asunto: Consulta parqueadero...    │
│    12 May · Parqueaderos │  Fecha: 12 Mayo 2024                │
│                          │  ─────────────────────────────────  │
│  ○ Ana Torres            │  [Cuerpo completo del correo]       │
│    Petición radicado 001 │                                     │
│    10 May · Peticiones   │  Categoría: [Parqueaderos ▾]        │
│                          │  [Marcar leído] [Marcar no leído]   │
│  ● noreply@proveedor.com │                                     │
│    Factura Mayo 2024     │                                     │
│    08 May · Otros        │                                     │
└──────────────────────────┴──────────────────────────────────────┘
```

- `●` = no leído (bold font weight), `○` = leído
- Tab badges show unread count per category
- Processing in progress shows a progress bar below the toolbar with `{n} / {total} correos clasificados`
- Color dot in each tab matches the category's configured color
- "Otros" category is always the last tab and cannot be deleted

### CategoryManager dialog

Fields: name (text), description (textarea), color (color picker with preset palette), icon (grid of lucide-react icons filtered by search).

### Email reply composer (in detail panel)

Below the email body, the detail panel includes a reply composer:

```
┌──────────────────────────────────────────────┐
│ Responder a: juan@example.com                │
│ ┌────────────────────────────────────────┐   │
│ │ Escribe tu respuesta...                │   │
│ │                                        │   │
│ └────────────────────────────────────────┘   │
│              [Enviar respuesta]              │
└──────────────────────────────────────────────┘
```

- "Responder" pre-fills `To:` with the original sender and the thread's `References`/`In-Reply-To` headers so Gmail threads it correctly
- On send success: email's `is_replied=1`, `is_read=1` updated locally; a success toast appears
- On send error: error toast with the error message; email state unchanged
- Uses the existing `gmail_send` tool from `google_services.py` internally, called directly from `router.py` (not through Brain)

**New API endpoint added:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/emails/{id}/reply` | Send reply `{body: str}`. Returns `{success: bool}`. Sets `is_replied=1` and `is_read=1` on success. |

### PluginSettings modal

- Toggle: Marcar como leído en Gmail tras clasificar (`auto_mark_read`)
- Toggle: Aplicar etiqueta en Gmail (`auto_apply_label`)
- Input: Cron expression (`cron_schedule`) with human-readable preview ("Cada hora", "Cada día a las 8am", etc.)

---

## Error Handling

- **Gmail auth expired** — `processor.py` catches `google.auth.exceptions.RefreshError` and emits `gmail_classifier.auth_error`. Frontend shows banner asking user to reconnect.
- **LLM error on batch** — That batch's emails are saved with `category_id = Otros.id`, `ai_classified=0`. Processing continues with next batch.
- **Duplicate run** — `POST /process` returns HTTP 409 if `processor.is_running == True`.
- **Category deletion** — Emails are reassigned to Otros before deleting the category row.

---

## Testing

- Unit tests for `GmailBatchProcessor` with mocked Gmail API and mocked `llm_router`
- Unit tests for category CRUD endpoints
- Unit tests for email read-toggle and recategorize endpoints
- Integration test: full process run with 3 categories and 5 mock emails, verify correct category assignments
- Thread tracking test: simulate new reply arriving after initial sync, verify `is_read=0` reset

Tests live in `tests/unit/test_gmail_classifier.py` following the existing `conftest.py` fixture pattern.
