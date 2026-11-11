# Gmail Classifier — Inbox Summary & Daily Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an on-demand "¿Qué hay?" AI inbox summary button to the Gmail Classifier UI, and a configurable daily digest that delivers the same summary to any connected channel (Telegram today, extensible to any future channel).

**Architecture:** A new `summary.py` module generates the summary (counts by category + LLM-identified urgent emails covering today only). The UI button calls `GET /summary`. The digest cron is a second asyncio task in the plugin that emits a `channel:send` EventBus event; `AgentTelegramChannel` subscribes to it and sends proactively. Settings stored in `gmail_classifier_settings` (5 new keys). Frontend adds a "¿Qué hay?" button with inline panel and a fourth "Digest" tab in PluginSettings.

**Tech Stack:** Python/aiosqlite (backend), FastAPI, asyncio, python-telegram-bot, React/Next.js/Tailwind.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Create** | `src/openacm/plugins/gmail_classifier/summary.py` | `generate_inbox_summary()` — all summary logic |
| **Create** | `tests/unit/test_gmail_summary.py` | Unit tests for summary generation |
| **Modify** | `src/openacm/plugins/gmail_classifier/router.py` | Add `_llm_router`, `_event_bus`, `_plugin` vars; `GET /summary`; `POST /summary/test-send`; update `SettingsBody` + `PUT /settings` |
| **Modify** | `src/openacm/plugins/gmail_classifier/__init__.py` | Seed digest settings; digest cron task; wire new vars to router |
| **Modify** | `src/openacm/channels/agent_telegram_bot.py` | `AgentTelegramChannel` subscribes to `channel:send` event |
| **Modify** | `frontend/app/gmail-classifier/page.tsx` | "¿Qué hay?" button + summary panel |
| **Modify** | `frontend/app/gmail-classifier/components/PluginSettings.tsx` | "Digest" tab with all settings fields |

---

### Task 1: `summary.py` + `GET /summary` endpoint + tests

**Files:**
- Create: `src/openacm/plugins/gmail_classifier/summary.py`
- Create: `tests/unit/test_gmail_summary.py`
- Modify: `src/openacm/plugins/gmail_classifier/router.py`
- Modify: `src/openacm/plugins/gmail_classifier/__init__.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_gmail_summary.py`:

```python
"""Unit tests for Gmail Classifier inbox summary generation."""
import datetime
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_with_today_emails(db):
    """DB with Importantes + Trabajo categories and 3 emails received today."""
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description) VALUES ('Importantes', 'd')"
    )
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description) VALUES ('Trabajo', 'd')"
    )
    await db._db.commit()

    c = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Importantes'")
    importantes_id = (await c.fetchone())["id"]
    c = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Trabajo'")
    trabajo_id = (await c.fetchone())["id"]
    c = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Otros'")
    otros_id = (await c.fetchone())["id"]

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for gmail_id, sender, subject, cat_id in [
        ("gs1", "Ana Torres", "Propuesta urgente", importantes_id),
        ("gs2", "Carlos Ruiz", "Reunión jueves", trabajo_id),
        ("gs3", "Newsletter Co", "Oferta del día", otros_id),
    ]:
        await db._db.execute(
            "INSERT INTO gmail_emails "
            "(gmail_id, thread_id, subject, sender_name, sender_email, snippet, "
            " body_text, body_html, category_id, is_read, is_replied, ai_classified, "
            " manual_override, thread_last_sender_email, received_at) "
            "VALUES (?, '', ?, ?, '', '', '', '', ?, 0, 0, 1, 0, '', ?)",
            (gmail_id, subject, sender, cat_id, now_iso),
        )
    await db._db.commit()
    return db


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_no_emails_today_returns_early_message(db, mock_llm_router):
    """When no emails arrived today, returns the no-emails message without calling LLM."""
    from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
    result = await generate_inbox_summary(db, mock_llm_router)
    assert result == "No hay correos de hoy todavía."
    mock_llm_router.chat.assert_not_called()


async def test_part_a_includes_total_and_category_counts(db_with_today_emails, mock_llm_router):
    """Part A shows correct total and per-category counts."""
    mock_llm_router.chat.return_value = {
        "content": "1. Ana Torres — urgente", "tool_calls": [], "model": "mock", "usage": {}, "cost": 0
    }
    from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
    result = await generate_inbox_summary(db_with_today_emails, mock_llm_router)
    assert "3 correos" in result
    assert "📬" in result
    assert "Importantes" in result
    assert "Trabajo" in result


async def test_part_b_includes_llm_urgent_list(db_with_today_emails, mock_llm_router):
    """Part B includes the LLM's urgent-email list when LLM responds."""
    mock_llm_router.chat.return_value = {
        "content": '1. Ana Torres — "Propuesta urgente" (requiere respuesta)',
        "tool_calls": [], "model": "mock", "usage": {}, "cost": 0,
    }
    from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
    result = await generate_inbox_summary(db_with_today_emails, mock_llm_router)
    assert "🔴" in result
    assert "Ana Torres" in result


async def test_llm_timeout_returns_part_a_only(db_with_today_emails, mock_llm_router):
    """On asyncio.TimeoutError from LLM, Part A is returned with a fallback note; no crash."""
    import asyncio

    async def raise_timeout(*args, **kwargs):
        raise asyncio.TimeoutError()

    mock_llm_router.chat = raise_timeout

    from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
    result = await generate_inbox_summary(db_with_today_emails, mock_llm_router)
    assert "📬" in result          # Part A present
    assert "🔴" not in result      # Part B absent


async def test_llm_error_returns_part_a_only(db_with_today_emails, mock_llm_router):
    """On any LLM exception, Part A is returned with a fallback note; no crash."""
    async def raise_error(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    mock_llm_router.chat = raise_error

    from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
    result = await generate_inbox_summary(db_with_today_emails, mock_llm_router)
    assert "📬" in result
    assert "🔴" not in result
```

- [ ] **Step 2: Run to confirm tests fail**

```
pytest tests/unit/test_gmail_summary.py -v
```

Expected: `ModuleNotFoundError: No module named 'openacm.plugins.gmail_classifier.summary'`

- [ ] **Step 3: Create `summary.py`**

Create `src/openacm/plugins/gmail_classifier/summary.py`:

```python
"""Gmail Classifier — inbox summary generator."""
from __future__ import annotations

import asyncio
import datetime

import structlog

log = structlog.get_logger()

_NO_EMAILS_MSG = "No hay correos de hoy todavía."
_URGENT_FALLBACK = "\n\n(No se pudo identificar urgentes)"
_LLM_TIMEOUT = 20.0


async def generate_inbox_summary(db, llm_router, event_bus=None) -> str:
    """Return a formatted text summary of today's inbox.

    Part A: counts by category.
    Part B: 2-3 LLM-identified urgent emails.
    Falls back to Part A only on LLM timeout or error.
    """
    today = datetime.date.today().isoformat()  # "YYYY-MM-DD"

    # ── Part A: counts ────────────────────────────────────────────────────────
    total_cursor = await db._db.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) as unread "
        "FROM gmail_emails "
        "WHERE date(received_at, 'localtime') = ?",
        (today,),
    )
    totals = await total_cursor.fetchone()
    total = totals["total"] if totals else 0
    unread = totals["unread"] if totals else 0

    if total == 0:
        return _NO_EMAILS_MSG

    cat_cursor = await db._db.execute(
        "SELECT gc.name, COUNT(*) as cnt "
        "FROM gmail_emails ge "
        "JOIN gmail_categories gc ON ge.category_id = gc.id "
        "WHERE date(ge.received_at, 'localtime') = ? "
        "GROUP BY gc.id "
        "ORDER BY cnt DESC",
        (today,),
    )
    by_category = await cat_cursor.fetchall()
    cat_line = "  |  ".join(f"{r['name']}: {r['cnt']}" for r in by_category)

    part_a = f"📬 Resumen del inbox (hoy)\n• {total} correos — {unread} sin leer\n• {cat_line}"

    # ── Part B: LLM urgent detection ─────────────────────────────────────────
    email_cursor = await db._db.execute(
        "SELECT ge.subject, ge.sender_name, ge.received_at "
        "FROM gmail_emails ge "
        "WHERE date(ge.received_at, 'localtime') = ? "
        "ORDER BY ge.received_at DESC "
        "LIMIT 30",
        (today,),
    )
    emails = await email_cursor.fetchall()

    lines = []
    for i, e in enumerate(emails, 1):
        ts = (e["received_at"] or "")[:16]
        lines.append(
            f"{i}. De: {e['sender_name'] or 'Desconocido'} | "
            f"Asunto: {e['subject'] or '(sin asunto)'} | {ts}"
        )

    prompt = (
        "Eres un asistente que analiza correos electrónicos. "
        "Del siguiente listado de correos recibidos hoy, identifica los 2 o 3 "
        "más urgentes o importantes que requieren atención prioritaria. "
        "Para cada uno escribe UNA línea con este formato exacto:\n"
        "N. Nombre — \"Asunto\" (justificación breve de máx 8 palabras)\n\n"
        "Correos de hoy:\n" + "\n".join(lines) + "\n\n"
        "Responde SOLO con la lista numerada. Sin encabezados ni texto adicional."
    )

    try:
        result = await asyncio.wait_for(
            llm_router.chat(messages=[{"role": "user", "content": prompt}]),
            timeout=_LLM_TIMEOUT,
        )
        urgent_text = (result.get("content") or "").strip()
        part_b = f"\n\n🔴 Urgentes detectados:\n{urgent_text}" if urgent_text else _URGENT_FALLBACK
    except asyncio.TimeoutError:
        part_b = _URGENT_FALLBACK
    except Exception as exc:
        log.warning("inbox summary LLM call failed", error=str(exc))
        part_b = _URGENT_FALLBACK

    summary = part_a + part_b

    if event_bus:
        await event_bus.emit("summary:generated", {"chars": len(summary)})

    return summary
```

- [ ] **Step 4: Run tests to confirm they pass**

```
pytest tests/unit/test_gmail_summary.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Add `_llm_router`, `_event_bus` to `router.py` and wire `GET /summary`**

In `src/openacm/plugins/gmail_classifier/router.py`:

After the existing module-level vars (`_db`, `_processor`, `_auto_reply`, `_learning`), add:

```python
_llm_router: Any = None
_event_bus: Any = None
_plugin: Any = None  # GmailClassifierPlugin instance — used to restart digest cron
```

Add a `_require_llm` helper after the existing `_require_*` functions:

```python
def _require_llm():
    if _llm_router is None:
        raise HTTPException(status_code=503, detail="LLM no configurado")
    return _llm_router
```

Add the endpoint (place it near the stats endpoints, around line 869):

```python
# ─── Inbox Summary ────────────────────────────────────────────────────────────

@router.get("/summary")
async def get_inbox_summary():
    """Generate and return an AI summary of today's inbox."""
    import datetime
    from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
    db = _require_db()
    llm = _require_llm()
    summary = await generate_inbox_summary(db, llm, _event_bus)
    return {"summary": summary, "generated_at": datetime.datetime.now().isoformat()}
```

- [ ] **Step 6: Wire `_llm_router` and `_event_bus` in `__init__.py`**

In `src/openacm/plugins/gmail_classifier/__init__.py`, inside `on_start()` after the existing `_router_mod._processor = self._processor` lines, add:

```python
_router_mod._llm_router = llm_router
_router_mod._event_bus = event_bus
_router_mod._plugin = self
```

Also store these on the plugin instance (needed for the digest cron in Task 2):

At the top of `__init__()`, add:
```python
self._llm_router = None
self._event_bus = None
```

And in `on_start()`, before the cron section, add:
```python
self._llm_router = llm_router
self._event_bus = event_bus
```

- [ ] **Step 7: Run all Gmail tests**

```
pytest tests/unit/test_gmail_summary.py tests/unit/test_gmail_classifier.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/summary.py \
        src/openacm/plugins/gmail_classifier/router.py \
        src/openacm/plugins/gmail_classifier/__init__.py \
        tests/unit/test_gmail_summary.py
git commit -m "feat: gmail classifier — inbox summary generator + GET /summary endpoint"
```

---

### Task 2: Digest settings + cron + `SettingsBody` + `PUT /settings` restart + `POST /summary/test-send`

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/__init__.py`
- Modify: `src/openacm/plugins/gmail_classifier/router.py`

- [ ] **Step 1: Seed digest settings keys in `__init__.py`**

In `on_start()`, in the `defaults` dict (around line 120), add the five new digest keys:

```python
defaults = {
    "auto_mark_read": "false",
    "auto_apply_label": "false",
    "cron_schedule": "",
    "since_date_default": "",
    "autoreply_enabled_categories": "[]",
    "autoreply_model": "",
    "autoreply_timeout_seconds": "60",
    # Digest
    "digest_enabled": "false",
    "digest_time": "",
    "digest_days": "1,2,3,4,5",
    "digest_agent_id": "",
    "digest_chat_id": "",
}
```

- [ ] **Step 2: Add `_digest_task` to `__init__()` and `_start_digest_cron()` + `_digest_loop()` methods**

In `GmailClassifierPlugin.__init__()`, add:
```python
self._digest_task: asyncio.Task | None = None
```

After the existing `_start_cron()` and `_cron_loop()` methods, add:

```python
def _start_digest_cron(self) -> None:
    if self._digest_task and not self._digest_task.done():
        self._digest_task.cancel()
    self._digest_task = asyncio.create_task(self._digest_loop())

async def _digest_loop(self) -> None:
    import datetime as _dt

    log.info("Gmail digest loop started")
    while True:
        cursor = await self._db._db.execute(
            "SELECT key, value FROM gmail_classifier_settings "
            "WHERE key IN ('digest_enabled','digest_time','digest_days','digest_agent_id','digest_chat_id')"
        )
        cfg = {r["key"]: r["value"] for r in await cursor.fetchall()}

        if cfg.get("digest_enabled") != "true":
            log.info("Gmail digest disabled, stopping loop")
            return

        digest_time = cfg.get("digest_time", "")
        if not digest_time or ":" not in digest_time:
            log.warning("Gmail digest: invalid digest_time, stopping", digest_time=digest_time)
            return

        try:
            hh, mm = int(digest_time.split(":")[0]), int(digest_time.split(":")[1])
        except (ValueError, IndexError):
            log.warning("Gmail digest: cannot parse digest_time", value=digest_time)
            return

        try:
            digest_days = {int(d.strip()) for d in cfg.get("digest_days", "1,2,3,4,5").split(",") if d.strip()}
        except ValueError:
            digest_days = {1, 2, 3, 4, 5}

        # Find next fire time (ISO isoweekday: 1=Mon, 7=Sun)
        now = _dt.datetime.now()
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= now:
            candidate += _dt.timedelta(days=1)
        for _ in range(7):
            if candidate.isoweekday() in digest_days:
                break
            candidate += _dt.timedelta(days=1)

        wait_seconds = (candidate - now).total_seconds()
        if wait_seconds <= 0:
            await asyncio.sleep(60)
            continue

        log.info("Gmail digest next run", next_run=str(candidate), wait_seconds=round(wait_seconds))
        await asyncio.sleep(wait_seconds)

        # Re-read enabled flag after sleep (may have been toggled off)
        cursor2 = await self._db._db.execute(
            "SELECT value FROM gmail_classifier_settings WHERE key = 'digest_enabled'"
        )
        row2 = await cursor2.fetchone()
        if not row2 or row2["value"] != "true":
            log.info("Gmail digest disabled after sleep, skipping and stopping")
            return

        # Re-read agent config (may have changed)
        cursor3 = await self._db._db.execute(
            "SELECT key, value FROM gmail_classifier_settings "
            "WHERE key IN ('digest_agent_id','digest_chat_id')"
        )
        send_cfg = {r["key"]: r["value"] for r in await cursor3.fetchall()}
        agent_id_str = send_cfg.get("digest_agent_id", "")
        chat_id = send_cfg.get("digest_chat_id", "")

        if not agent_id_str or not chat_id:
            log.warning("Gmail digest: agent_id or chat_id not configured, skipping send")
        else:
            try:
                from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
                summary = await generate_inbox_summary(self._db, self._llm_router, self._event_bus)
                await self._event_bus.emit("channel:send", {
                    "agent_id": int(agent_id_str),
                    "target_id": chat_id,
                    "text": summary,
                })
                log.info("Gmail digest sent", agent_id=agent_id_str)
            except Exception as exc:
                log.error("Gmail digest send failed", error=str(exc))
```

- [ ] **Step 3: Start digest cron in `on_start()` and cancel in `on_stop()`**

In `on_start()`, after the existing cron start block, add:

```python
        # Start digest loop if configured
        cursor_d = await database._db.execute(
            "SELECT value FROM gmail_classifier_settings WHERE key = 'digest_enabled'"
        )
        row_d = await cursor_d.fetchone()
        if row_d and row_d["value"] == "true":
            self._start_digest_cron()
```

In `on_stop()`, after cancelling `_cron_task`, add the same pattern for `_digest_task`:

```python
        if self._digest_task and not self._digest_task.done():
            self._digest_task.cancel()
            try:
                await self._digest_task
            except asyncio.CancelledError:
                pass
```

- [ ] **Step 4: Update `SettingsBody` in `router.py` and `PUT /settings` restart logic**

In `router.py`, update `SettingsBody`:

```python
class SettingsBody(BaseModel):
    auto_mark_read: str | None = None
    auto_apply_label: str | None = None
    cron_schedule: str | None = None
    since_date_default: str | None = None
    autoreply_enabled_categories: str | None = None
    autoreply_model: str | None = None
    autoreply_timeout_seconds: int | None = None
    digest_enabled: str | None = None
    digest_time: str | None = None
    digest_days: str | None = None
    digest_agent_id: str | None = None
    digest_chat_id: str | None = None
```

In `update_settings()`, after the existing retroactive-apply block (around line 700), add:

```python
    _DIGEST_KEYS = {"digest_enabled", "digest_time", "digest_days", "digest_agent_id", "digest_chat_id"}
    if any(k in updates for k in _DIGEST_KEYS) and _plugin:
        _plugin._start_digest_cron()
```

- [ ] **Step 5: Add `POST /summary/test-send` endpoint to `router.py`**

After the `GET /summary` endpoint added in Task 1, add:

```python
@router.post("/summary/test-send")
async def test_send_digest():
    """Generate the summary and emit channel:send immediately (for testing config)."""
    db = _require_db()
    llm = _require_llm()
    if _event_bus is None:
        raise HTTPException(status_code=503, detail="Event bus no disponible")

    cursor = await db._db.execute(
        "SELECT key, value FROM gmail_classifier_settings "
        "WHERE key IN ('digest_agent_id', 'digest_chat_id')"
    )
    cfg = {r["key"]: r["value"] for r in await cursor.fetchall()}
    agent_id_str = cfg.get("digest_agent_id", "")
    chat_id = cfg.get("digest_chat_id", "")

    if not agent_id_str or not chat_id:
        raise HTTPException(
            status_code=400,
            detail="digest_agent_id o digest_chat_id no configurado",
        )
    try:
        agent_id = int(agent_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="digest_agent_id inválido")

    from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
    summary = await generate_inbox_summary(db, llm, _event_bus)
    await _event_bus.emit("channel:send", {
        "agent_id": agent_id,
        "target_id": chat_id,
        "text": summary,
    })
    return {"sent": True}
```

- [ ] **Step 6: Run tests**

```
pytest tests/unit/test_gmail_classifier.py tests/unit/test_gmail_summary.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/__init__.py \
        src/openacm/plugins/gmail_classifier/router.py
git commit -m "feat: gmail classifier — digest cron, 5 new settings keys, test-send endpoint"
```

---

### Task 3: `channel:send` event in `AgentTelegramChannel`

**Files:**
- Modify: `src/openacm/channels/agent_telegram_bot.py`

- [ ] **Step 1: Override `start()` and `stop()` in `AgentTelegramChannel` to subscribe/unsubscribe**

In `src/openacm/channels/agent_telegram_bot.py`, inside `AgentTelegramChannel`, add after `_on_message_sent`:

```python
    async def start(self):
        await super().start()
        # Subscribe to proactive send events — fired by Gmail digest cron and other plugins
        self.event_bus.on("channel:send", self._handle_channel_send)

    async def stop(self):
        try:
            self.event_bus.off("channel:send", self._handle_channel_send)
        except Exception:
            pass
        await super().stop()

    async def _handle_channel_send(self, event_type: str, data: dict):
        """Deliver a proactive message to the configured chat if this agent owns it."""
        if data.get("agent_id") != self.brain.agent["id"]:
            return
        target_id = str(data.get("target_id", ""))
        text = str(data.get("text", ""))
        if target_id and text:
            await self.send_message(target_id, text)
```

`send_message(target_id, content)` already exists on `TelegramChannel` (line 136 of telegram_channel.py) — it calls `bot.send_message(chat_id=int(target_id), text=content, parse_mode="Markdown")`.

- [ ] **Step 2: Verify the module imports cleanly**

```
python -c "from openacm.channels.agent_telegram_bot import AgentTelegramChannel; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/openacm/channels/agent_telegram_bot.py
git commit -m "feat: AgentTelegramChannel subscribes to channel:send for proactive digest delivery"
```

---

### Task 4: Frontend — "¿Qué hay?" button + summary panel in `page.tsx`

**Files:**
- Modify: `frontend/app/gmail-classifier/page.tsx`

- [ ] **Step 1: Add state and handler**

In `page.tsx`, find the existing state declarations (the block with `useState` calls). Add these three after the existing state:

```tsx
const [summaryLoading, setSummaryLoading] = useState(false);
const [summaryText, setSummaryText] = useState<string | null>(null);
const [summaryError, setSummaryError] = useState<string | null>(null);
```

Add the handler function alongside the other handlers (e.g., near `handleProcess`):

```tsx
const handleSummary = async () => {
  setSummaryLoading(true);
  setSummaryError(null);
  setSummaryText(null);
  try {
    const res = await fetch(`${API}/summary`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`Error ${res.status}`);
    const data = await res.json();
    setSummaryText(data.summary);
  } catch (err: any) {
    setSummaryError(err.message || 'Error generando resumen');
  } finally {
    setSummaryLoading(false);
  }
};
```

- [ ] **Step 2: Add "¿Qué hay?" button to toolbar**

Find the toolbar row that contains the Procesar/Detener button. Add the "¿Qué hay?" button immediately before or after that button group. Check that `Sparkles` and `Loader2` are imported from `lucide-react`; if not, add them to the existing lucide import line.

```tsx
<button
  onClick={handleSummary}
  disabled={summaryLoading}
  className="btn-secondary text-[12px] py-[7px] px-3 flex items-center gap-1"
>
  {summaryLoading
    ? <Loader2 size={13} className="animate-spin" />
    : <Sparkles size={13} />}
  ¿Qué hay?
</button>
```

- [ ] **Step 3: Add summary panel below toolbar (above category tabs)**

Find the location in the JSX right after the toolbar `<div>` and right before the category tabs / email list container. Insert:

```tsx
{/* Inbox summary panel */}
{summaryText && (
  <div className="mx-4 mb-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 flex items-start gap-2">
    <pre className="flex-1 whitespace-pre-wrap text-[12px] text-amber-200/90 font-sans">
      {summaryText}
    </pre>
    <button
      onClick={() => setSummaryText(null)}
      className="text-amber-400/60 hover:text-amber-300 text-[14px] leading-none mt-0.5"
    >
      ✕
    </button>
  </div>
)}
{summaryError && (
  <p className="mx-4 mb-2 text-[11px] text-red-400">{summaryError}</p>
)}
```

- [ ] **Step 4: TypeScript check**

```
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/gmail-classifier/page.tsx
git commit -m "feat: gmail classifier — ¿Qué hay? summary button + inline panel"
```

---

### Task 5: Frontend — Digest tab in `PluginSettings.tsx`

**Files:**
- Modify: `frontend/app/gmail-classifier/components/PluginSettings.tsx`

- [ ] **Step 1: Extend `MainTab` type and add Digest tab entry**

Find:
```tsx
type MainTab = 'general' | 'auto-respuesta' | 'backup';
```

Replace with:
```tsx
type MainTab = 'general' | 'auto-respuesta' | 'backup' | 'digest';
```

Find the `TABS` array (or the tabs JSX). Add the Digest entry:
```tsx
{ id: 'digest' as MainTab, label: 'Digest' }
```

- [ ] **Step 2: Add digest state variables**

Inside `PluginSettings`, after the existing `settings` state, add:

```tsx
// Digest tab state
const [digestEnabled, setDigestEnabled] = useState(false);
const [digestHH, setDigestHH] = useState('08');
const [digestMM, setDigestMM] = useState('00');
const [digestDays, setDigestDays] = useState<number[]>([1, 2, 3, 4, 5]);
const [digestAgentId, setDigestAgentId] = useState('');
const [digestChatId, setDigestChatId] = useState('');
const [agents, setAgents] = useState<{ id: number; name: string }[]>([]);
const [testSending, setTestSending] = useState(false);
const [testResult, setTestResult] = useState<string | null>(null);
const [testError, setTestError] = useState<string | null>(null);
```

- [ ] **Step 3: Load settings and agents in `useEffect`**

Find the existing `useEffect` that loads settings. Inside it, after loading existing settings into state, also populate digest state:

```tsx
// Populate digest state from settings
setDigestEnabled(data.digest_enabled === 'true');
const [hh = '08', mm = '00'] = (data.digest_time || '08:00').split(':');
setDigestHH(hh.padStart(2, '0'));
setDigestMM(mm.padStart(2, '0'));
const days = (data.digest_days || '1,2,3,4,5')
  .split(',').map(Number).filter(Boolean);
setDigestDays(days);
setDigestAgentId(data.digest_agent_id || '');
setDigestChatId(data.digest_chat_id || '');
```

Also load agents (can be in a separate `useEffect` or the same one):

```tsx
// Load agents for digest dropdown
fetch('/api/agents', { headers: { Authorization: `Bearer ${token}` } })
  .then(r => r.json())
  .then((list: any[]) => setAgents(list.map(a => ({ id: a.id, name: a.name }))))
  .catch(() => {});
```

- [ ] **Step 4: Add `handleSaveDigest` function**

```tsx
const handleSaveDigest = async () => {
  const digestTime = `${digestHH.padStart(2,'0')}:${digestMM.padStart(2,'0')}`;
  const digestDaysStr = digestDays.sort((a,b)=>a-b).join(',');
  await fetch(`${API}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      digest_enabled: digestEnabled ? 'true' : 'false',
      digest_time: digestTime,
      digest_days: digestDaysStr,
      digest_agent_id: digestAgentId,
      digest_chat_id: digestChatId,
    }),
  });
};
```

- [ ] **Step 5: Add `handleTestSend` function**

```tsx
const handleTestSend = async () => {
  setTestSending(true);
  setTestResult(null);
  setTestError(null);
  // Save current values first so test uses latest config
  await handleSaveDigest();
  try {
    const res = await fetch(`${API}/summary/test-send`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `Error ${res.status}`);
    }
    setTestResult('✓ Mensaje enviado correctamente');
  } catch (err: any) {
    setTestError(err.message || 'Error al enviar');
  } finally {
    setTestSending(false);
  }
};
```

- [ ] **Step 6: Add `toggleDigestDay` helper**

```tsx
const toggleDigestDay = (day: number) => {
  setDigestDays(prev =>
    prev.includes(day) ? prev.filter(d => d !== day) : [...prev, day]
  );
};
```

- [ ] **Step 7: Render the Digest tab content**

In the tab content section (the `{activeTab === 'backup' && (...)}` block), add after it:

```tsx
{activeTab === 'digest' && (
  <div className="space-y-5">

    {/* Master toggle */}
    <div className="flex items-center gap-3">
      <input
        id="digest-enabled"
        type="checkbox"
        checked={digestEnabled}
        onChange={e => setDigestEnabled(e.target.checked)}
        className="w-4 h-4 accent-[var(--acm-accent)]"
      />
      <label htmlFor="digest-enabled" className="text-[13px] text-[var(--acm-fg-2)]">
        Activar digest diario
      </label>
    </div>

    <fieldset disabled={!digestEnabled} className="space-y-4 disabled:opacity-40">

      {/* Time */}
      <div>
        <p className="text-[11px] text-[var(--acm-fg-4)] mb-1">Hora de envío</p>
        <div className="flex items-center gap-1">
          <input
            type="number" min={0} max={23}
            value={digestHH}
            onChange={e => setDigestHH(String(e.target.valueAsNumber).padStart(2,'0'))}
            className="w-14 rounded border border-[var(--acm-border)] bg-[var(--acm-bg-2)] px-2 py-1 text-[12px] text-center"
          />
          <span className="text-[var(--acm-fg-3)]">:</span>
          <input
            type="number" min={0} max={59} step={5}
            value={digestMM}
            onChange={e => setDigestMM(String(e.target.valueAsNumber).padStart(2,'0'))}
            className="w-14 rounded border border-[var(--acm-border)] bg-[var(--acm-bg-2)] px-2 py-1 text-[12px] text-center"
          />
        </div>
      </div>

      {/* Days */}
      <div>
        <p className="text-[11px] text-[var(--acm-fg-4)] mb-1">Días</p>
        <div className="flex gap-1">
          {(['L','M','X','J','V','S','D'] as const).map((label, i) => {
            const dayNum = i + 1; // ISO: 1=Mon … 7=Sun
            const active = digestDays.includes(dayNum);
            return (
              <button
                key={dayNum}
                type="button"
                onClick={() => toggleDigestDay(dayNum)}
                className={`w-8 h-8 rounded text-[11px] font-medium border transition-colors ${
                  active
                    ? 'bg-[var(--acm-accent)] border-[var(--acm-accent)] text-white'
                    : 'border-[var(--acm-border)] text-[var(--acm-fg-3)] hover:border-[var(--acm-accent)]'
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Agent */}
      <div>
        <p className="text-[11px] text-[var(--acm-fg-4)] mb-1">Agente notificador</p>
        <select
          value={digestAgentId}
          onChange={e => setDigestAgentId(e.target.value)}
          className="w-full rounded border border-[var(--acm-border)] bg-[var(--acm-bg-2)] px-2 py-1 text-[12px] text-[var(--acm-fg-2)]"
        >
          <option value="">— Selecciona un agente —</option>
          {agents.map(a => (
            <option key={a.id} value={String(a.id)}>{a.name}</option>
          ))}
        </select>
      </div>

      {/* Chat ID */}
      <div>
        <p className="text-[11px] text-[var(--acm-fg-4)] mb-1">Chat ID / Destino</p>
        <input
          type="text"
          value={digestChatId}
          onChange={e => setDigestChatId(e.target.value)}
          placeholder="ej. 123456789"
          className="w-full rounded border border-[var(--acm-border)] bg-[var(--acm-bg-2)] px-2 py-1 text-[12px] text-[var(--acm-fg-2)]"
        />
        <p className="text-[10px] text-[var(--acm-fg-4)] mt-1">
          Para Telegram: abre una conversación con tu bot y mira la URL o usa @userinfobot.
        </p>
      </div>

      {/* Save + Test */}
      <div className="flex items-center gap-3 pt-1">
        <button onClick={handleSaveDigest} className="btn-primary text-[12px] py-[6px] px-3">
          Guardar digest
        </button>
        <button
          onClick={handleTestSend}
          disabled={testSending || !digestAgentId || !digestChatId}
          className="btn-secondary text-[12px] py-[6px] px-3 disabled:opacity-40"
        >
          {testSending ? 'Enviando…' : 'Probar envío'}
        </button>
      </div>

      {testResult && <p className="text-[11px] text-green-400">{testResult}</p>}
      {testError  && <p className="text-[11px] text-red-400">{testError}</p>}

    </fieldset>
  </div>
)}
```

- [ ] **Step 8: TypeScript check**

```
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/app/gmail-classifier/components/PluginSettings.tsx
git commit -m "feat: gmail classifier — Digest tab in PluginSettings with schedule, agent, test-send"
```

---

### Task 6: Full verification

- [ ] **Step 1: Run all Gmail-related tests**

```
pytest tests/unit/test_gmail_classifier.py tests/unit/test_gmail_summary.py tests/unit/test_gmail_backup.py tests/unit/test_gmail_stats.py -v
```

Expected: all pass.

- [ ] **Step 2: TypeScript check**

```
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Confirm `channel:send` wiring**

```
python -c "
import inspect
from openacm.channels.agent_telegram_bot import AgentTelegramChannel
src = inspect.getsource(AgentTelegramChannel)
assert 'channel:send' in src, 'channel:send subscription missing'
assert '_handle_channel_send' in src, 'handler missing'
print('OK — channel:send wired in AgentTelegramChannel')
"
```

Expected: `OK — channel:send wired in AgentTelegramChannel`

- [ ] **Step 4: Confirm digest cron method exists**

```
python -c "
from openacm.plugins.gmail_classifier import GmailClassifierPlugin
p = GmailClassifierPlugin()
assert hasattr(p, '_start_digest_cron')
assert hasattr(p, '_digest_loop')
assert hasattr(p, '_digest_task')
print('OK — digest cron on plugin instance')
"
```

Expected: `OK — digest cron on plugin instance`
