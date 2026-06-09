# Gmail Classifier Plugin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Gmail Classifier plugin that reads emails from a chosen date, uses AI to categorize them into user-defined categories, and provides a split-view UI with tab-per-category, email detail panel, and reply composer.

**Architecture:** Plugin follows the `BasePlugin` pattern (`openacm.plugins.Plugin`). A `GmailBatchProcessor` fetches emails via Gmail API, classifies them in batches using `llm_router.chat()`, and saves results to SQLite. The FastAPI router stores database/processor references as module-level singletons set by `on_start`. Frontend is Next.js App Router with tabs + split-view.

**Tech Stack:** Python/FastAPI (backend), aiosqlite (storage), Google API Python Client (Gmail), Next.js/React/TypeScript/Tailwind (frontend), lucide-react (icons), shadcn/ui patterns.

---

## File Map

### Create (backend)
- `src/openacm/plugins/gmail_classifier/__init__.py` — Plugin class + PLUGIN singleton
- `src/openacm/plugins/gmail_classifier/processor.py` — GmailBatchProcessor
- `src/openacm/plugins/gmail_classifier/router.py` — All FastAPI endpoints

### Modify (backend)
- `src/openacm/storage/database.py` — Migration 19: add 3 new tables, bump `_SCHEMA_VERSION`

### Create (frontend)
- `frontend/app/gmail-classifier/page.tsx` — Main page shell
- `frontend/app/gmail-classifier/components/CategoryTabs.tsx`
- `frontend/app/gmail-classifier/components/EmailList.tsx`
- `frontend/app/gmail-classifier/components/EmailDetail.tsx`
- `frontend/app/gmail-classifier/components/CategoryManager.tsx`
- `frontend/app/gmail-classifier/components/ProcessingProgress.tsx`
- `frontend/app/gmail-classifier/components/PluginSettings.tsx`

### Create (tests)
- `tests/unit/test_gmail_classifier.py` — All unit tests for backend

---

## Task 1: Database Migration

**Files:**
- Modify: `src/openacm/storage/database.py`
- Test: `tests/unit/test_gmail_classifier.py`

- [ ] **Step 1.1: Write failing tests for new tables**

Create `tests/unit/test_gmail_classifier.py`:

```python
"""Unit tests for Gmail Classifier plugin."""
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock


# ─── DB Migration Tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gmail_categories_table_exists(db):
    """Migration 19 creates gmail_categories table."""
    cursor = await db._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='gmail_categories'"
    )
    row = await cursor.fetchone()
    assert row is not None, "gmail_categories table should exist after initialize()"


@pytest.mark.asyncio
async def test_gmail_emails_table_exists(db):
    """Migration 19 creates gmail_emails table."""
    cursor = await db._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='gmail_emails'"
    )
    row = await cursor.fetchone()
    assert row is not None, "gmail_emails table should exist after initialize()"


@pytest.mark.asyncio
async def test_gmail_classifier_settings_table_exists(db):
    """Migration 19 creates gmail_classifier_settings table."""
    cursor = await db._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='gmail_classifier_settings'"
    )
    row = await cursor.fetchone()
    assert row is not None, "gmail_classifier_settings table should exist after initialize()"


@pytest.mark.asyncio
async def test_otros_category_inserted_on_migration(db):
    """Migration 19 seeds 'Otros' as the default fallback category."""
    cursor = await db._db.execute(
        "SELECT name FROM gmail_categories WHERE name = 'Otros'"
    )
    row = await cursor.fetchone()
    assert row is not None, "'Otros' category should be seeded by migration"
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
pytest tests/unit/test_gmail_classifier.py -v
```

Expected: FAIL — tables don't exist yet.

- [ ] **Step 1.3: Add migration 19 to `database.py`**

In `src/openacm/storage/database.py`, change `_SCHEMA_VERSION = 18` to `_SCHEMA_VERSION = 19`.

Then at the end of `_run_migrations`, before the "Save new version" block, add:

```python
        if current < 19:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS gmail_categories (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    NOT NULL UNIQUE,
                    description TEXT    NOT NULL DEFAULT '',
                    color       TEXT    NOT NULL DEFAULT '#6366f1',
                    icon        TEXT    NOT NULL DEFAULT 'Tag',
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS gmail_emails (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    gmail_id      TEXT    NOT NULL UNIQUE,
                    thread_id     TEXT    NOT NULL DEFAULT '',
                    subject       TEXT    NOT NULL DEFAULT '',
                    sender_name   TEXT    NOT NULL DEFAULT '',
                    sender_email  TEXT    NOT NULL DEFAULT '',
                    snippet       TEXT    NOT NULL DEFAULT '',
                    category_id   INTEGER REFERENCES gmail_categories(id),
                    is_read       INTEGER NOT NULL DEFAULT 0,
                    is_replied    INTEGER NOT NULL DEFAULT 0,
                    ai_classified INTEGER NOT NULL DEFAULT 0,
                    received_at   DATETIME,
                    last_synced   DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_gmail_emails_category
                    ON gmail_emails(category_id);
                CREATE INDEX IF NOT EXISTS idx_gmail_emails_received
                    ON gmail_emails(received_at);

                CREATE TABLE IF NOT EXISTS gmail_classifier_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                );
            """)
            # Seed Otros (fallback category, cannot be deleted)
            await self._db.execute(
                "INSERT OR IGNORE INTO gmail_categories (name, description, color, icon) "
                "VALUES ('Otros', 'Correos que no encajan en ninguna categoría', '#6b7280', 'Inbox')"
            )
            log.info("Migration 19: created gmail_classifier tables")
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
pytest tests/unit/test_gmail_classifier.py::test_gmail_categories_table_exists tests/unit/test_gmail_classifier.py::test_gmail_emails_table_exists tests/unit/test_gmail_classifier.py::test_gmail_classifier_settings_table_exists tests/unit/test_gmail_classifier.py::test_otros_category_inserted_on_migration -v
```

Expected: 4 PASSED.

- [ ] **Step 1.5: Commit**

```bash
git add src/openacm/storage/database.py tests/unit/test_gmail_classifier.py
git commit -m "feat: migration 19 — gmail_classifier tables"
```

---

## Task 2: Plugin Skeleton

**Files:**
- Create: `src/openacm/plugins/gmail_classifier/__init__.py`
- Test: `tests/unit/test_gmail_classifier.py`

- [ ] **Step 2.1: Write failing test for plugin nav items**

Append to `tests/unit/test_gmail_classifier.py`:

```python
# ─── Plugin Skeleton Tests ───────────────────────────────────────────────────

def test_plugin_nav_items():
    """Plugin provides a /gmail-classifier nav item."""
    from openacm.plugins.gmail_classifier import PLUGIN
    items = PLUGIN.get_nav_items()
    assert len(items) == 1
    assert items[0]["path"] == "/gmail-classifier"
    assert items[0]["icon"] == "Mail"


def test_plugin_name():
    from openacm.plugins.gmail_classifier import PLUGIN
    assert PLUGIN.name == "gmail_classifier"


def test_plugin_has_api_router():
    from openacm.plugins.gmail_classifier import PLUGIN
    router = PLUGIN.get_api_router()
    assert router is not None
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
pytest tests/unit/test_gmail_classifier.py::test_plugin_nav_items tests/unit/test_gmail_classifier.py::test_plugin_name tests/unit/test_gmail_classifier.py::test_plugin_has_api_router -v
```

Expected: FAIL — module doesn't exist.

- [ ] **Step 2.3: Create the plugin package**

Create `src/openacm/plugins/gmail_classifier/__init__.py`:

```python
"""Gmail Classifier Plugin — AI-powered email categorization."""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from openacm.plugins import Plugin

log = structlog.get_logger()


class GmailClassifierPlugin(Plugin):
    name = "gmail_classifier"
    version = "1.0.0"
    description = "Classifies Gmail emails into user-defined categories using AI"
    author = "JsonProductions / OpenACM"

    def __init__(self):
        self._db = None
        self._processor = None
        self._cron_task: asyncio.Task | None = None

    # ── API router ─────────────────────────────────────────────

    def get_api_router(self):
        from openacm.plugins.gmail_classifier import router as _r
        return _r.router

    # ── Nav items ──────────────────────────────────────────────

    def get_nav_items(self) -> list[dict]:
        return [
            {
                "path": "/gmail-classifier",
                "label": "Gmail",
                "icon": "Mail",
                "section": "main",
            }
        ]

    # ── Lifecycle ──────────────────────────────────────────────

    async def on_start(self, *, database=None, llm_router=None, event_bus=None, **_) -> None:
        from openacm.plugins.gmail_classifier import processor as _proc_mod
        from openacm.plugins.gmail_classifier import router as _router_mod

        self._db = database

        # Seed default settings if not present
        if database:
            defaults = {
                "auto_mark_read": "false",
                "auto_apply_label": "false",
                "cron_schedule": "",
                "since_date_default": "",
            }
            for key, value in defaults.items():
                await database._db.execute(
                    "INSERT OR IGNORE INTO gmail_classifier_settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
            await database._db.commit()

        # Initialize processor and wire router
        self._processor = _proc_mod.GmailBatchProcessor(
            db=database,
            llm_router=llm_router,
            event_bus=event_bus,
        )
        _proc_mod._processor = self._processor
        _router_mod._db = database
        _router_mod._processor = self._processor

        # Start cron loop if a schedule is configured
        if database:
            cursor = await database._db.execute(
                "SELECT value FROM gmail_classifier_settings WHERE key = 'cron_schedule'"
            )
            row = await cursor.fetchone()
            schedule = row["value"] if row else ""
            if schedule:
                self._start_cron(schedule)

        log.info("GmailClassifierPlugin started")

    def _start_cron(self, schedule: str) -> None:
        if self._cron_task and not self._cron_task.done():
            self._cron_task.cancel()
        self._cron_task = asyncio.create_task(self._cron_loop(schedule))

    async def _cron_loop(self, schedule: str) -> None:
        from openacm.watchers.cron_scheduler import _next_cron_datetime
        import datetime as _dt

        while True:
            now = _dt.datetime.now(_dt.timezone.utc)
            try:
                next_run = _next_cron_datetime(schedule, now)
            except ValueError:
                log.warning("Invalid cron schedule, stopping cron loop", schedule=schedule)
                return
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(max(wait_seconds, 1))
            if self._processor:
                # Use the stored default since_date or fall back to 30 days ago
                since_date = ""
                if self._db:
                    cursor = await self._db._db.execute(
                        "SELECT value FROM gmail_classifier_settings WHERE key = 'since_date_default'"
                    )
                    row = await cursor.fetchone()
                    since_date = row["value"] if row else ""
                if not since_date:
                    since_date = (
                        _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=30)
                    ).strftime("%Y/%m/%d")
                try:
                    await self._processor.process(since_date)
                except Exception as exc:
                    log.error("Cron gmail classification failed", error=str(exc))

    async def on_stop(self) -> None:
        if self._cron_task and not self._cron_task.done():
            self._cron_task.cancel()
            try:
                await self._cron_task
            except asyncio.CancelledError:
                pass


PLUGIN = GmailClassifierPlugin()
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
pytest tests/unit/test_gmail_classifier.py::test_plugin_nav_items tests/unit/test_gmail_classifier.py::test_plugin_name tests/unit/test_gmail_classifier.py::test_plugin_has_api_router -v
```

Expected: 3 PASSED.

- [ ] **Step 2.5: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/__init__.py
git commit -m "feat: gmail_classifier plugin skeleton"
```

---

## Task 3: GmailBatchProcessor

**Files:**
- Create: `src/openacm/plugins/gmail_classifier/processor.py`
- Test: `tests/unit/test_gmail_classifier.py`

- [ ] **Step 3.1: Write failing tests for the processor**

Append to `tests/unit/test_gmail_classifier.py`:

```python
# ─── GmailBatchProcessor Tests ───────────────────────────────────────────────

@pytest.fixture
def mock_gmail_service():
    """Mocked Gmail API service."""
    svc = MagicMock()
    # messages().list().execute() returns a page of IDs
    list_result = {"messages": [{"id": "msg1"}, {"id": "msg2"}]}
    svc.users().messages().list().execute.return_value = list_result
    svc.users().messages().list_next.return_value = None

    def _make_msg(msg_id, subject, sender, sender_email, thread_id="t1", unread=True, snippet="preview"):
        return {
            "id": msg_id,
            "threadId": thread_id,
            "snippet": snippet,
            "labelIds": (["UNREAD"] if unread else []),
            "internalDate": "1748736000000",  # 2025-06-01
            "payload": {
                "headers": [
                    {"name": "Subject", "value": subject},
                    {"name": "From", "value": f"{sender} <{sender_email}>"},
                ],
            },
        }

    svc.users().messages().get().execute.side_effect = [
        _make_msg("msg1", "Asunto 1", "Ana Torres", "ana@example.com"),
        _make_msg("msg2", "Asunto 2", "Carlos Ruiz", "carlos@example.com", unread=False),
        # Thread last-message call
        _make_msg("msg2", "Asunto 2", "me@gmail.com", "me@gmail.com"),
    ]

    # threads().get() for reply detection
    svc.users().threads().get().execute.return_value = {
        "messages": [
            {"id": "msg1", "payload": {"headers": [{"name": "From", "value": "Ana Torres <ana@example.com>"}]}},
        ]
    }
    return svc


@pytest_asyncio.fixture
async def processor(db, mock_llm_router, event_bus):
    from openacm.plugins.gmail_classifier.processor import GmailBatchProcessor
    return GmailBatchProcessor(db=db, llm_router=mock_llm_router, event_bus=event_bus)


@pytest.mark.asyncio
async def test_processor_is_not_running_initially(processor):
    assert processor.is_running is False


@pytest.mark.asyncio
async def test_processor_classifies_emails(db, processor, mock_llm_router, mock_gmail_service, monkeypatch):
    """Processor fetches emails, classifies via LLM, and upserts to DB."""
    # Seed a category
    await db._db.execute(
        "INSERT INTO gmail_categories (name, description) VALUES ('Trabajo', 'Correos de trabajo')"
    )
    # Seed 'Otros'
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description, color, icon) "
        "VALUES ('Otros', 'Fallback', '#6b7280', 'Inbox')"
    )
    await db._db.commit()

    # LLM returns valid classification JSON
    mock_llm_router.chat.return_value = {
        "content": '[{"gmail_id": "msg1", "category": "Trabajo"}, {"gmail_id": "msg2", "category": "Otros"}]',
        "tool_calls": [],
        "model": "mock",
        "usage": {},
        "cost": 0.0,
    }

    # Patch _get_google_service to return mock
    monkeypatch.setattr(
        "openacm.plugins.gmail_classifier.processor._get_gmail_service",
        AsyncMock(return_value=mock_gmail_service),
    )
    # Patch authenticated user email
    monkeypatch.setattr(
        "openacm.plugins.gmail_classifier.processor._get_authenticated_email",
        AsyncMock(return_value="me@gmail.com"),
    )

    result = await processor.process("2025/06/01")

    assert result["total"] == 2
    assert result["errors"] == 0

    cursor = await db._db.execute("SELECT gmail_id, ai_classified FROM gmail_emails")
    rows = await cursor.fetchall()
    assert len(rows) == 2
    assert all(r["ai_classified"] == 1 for r in rows)


@pytest.mark.asyncio
async def test_processor_falls_back_to_otros_on_bad_llm_response(db, processor, mock_llm_router, mock_gmail_service, monkeypatch):
    """When LLM returns invalid JSON, emails are assigned to Otros."""
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description, color, icon) "
        "VALUES ('Otros', 'Fallback', '#6b7280', 'Inbox')"
    )
    await db._db.commit()

    mock_llm_router.chat.return_value = {
        "content": "Lo siento, no puedo clasificar.",  # Not valid JSON
        "tool_calls": [],
        "model": "mock",
        "usage": {},
        "cost": 0.0,
    }
    monkeypatch.setattr(
        "openacm.plugins.gmail_classifier.processor._get_gmail_service",
        AsyncMock(return_value=mock_gmail_service),
    )
    monkeypatch.setattr(
        "openacm.plugins.gmail_classifier.processor._get_authenticated_email",
        AsyncMock(return_value="me@gmail.com"),
    )

    result = await processor.process("2025/06/01")
    assert result["total"] == 2

    cursor = await db._db.execute(
        "SELECT ge.gmail_id, gc.name FROM gmail_emails ge "
        "LEFT JOIN gmail_categories gc ON ge.category_id = gc.id"
    )
    rows = await cursor.fetchall()
    assert all(r["name"] == "Otros" for r in rows)
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
pytest tests/unit/test_gmail_classifier.py::test_processor_is_not_running_initially tests/unit/test_gmail_classifier.py::test_processor_classifies_emails tests/unit/test_gmail_classifier.py::test_processor_falls_back_to_otros_on_bad_llm_response -v
```

Expected: FAIL — module doesn't exist.

- [ ] **Step 3.3: Create `processor.py`**

Create `src/openacm/plugins/gmail_classifier/processor.py`:

```python
"""Gmail batch processor — fetches emails, classifies via LLM, persists to DB."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger()

# Module-level singleton set by plugin on_start
_processor: "GmailBatchProcessor | None" = None

BATCH_SIZE = 20  # emails per LLM classification call


async def _get_gmail_service():
    """Return an authenticated Gmail API service (v1)."""
    from openacm.tools.google_services import _get_google_service
    return await _get_google_service("gmail", "v1")


async def _get_authenticated_email(service) -> str:
    """Return the authenticated user's email address."""
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


def _parse_headers(headers: list[dict]) -> dict[str, str]:
    return {h["name"]: h["value"] for h in headers}


def _parse_sender(from_header: str) -> tuple[str, str]:
    """Split 'Name <email>' into (name, email)."""
    m = re.match(r"^(.*?)\s*<([^>]+)>$", from_header.strip())
    if m:
        return m.group(1).strip().strip('"'), m.group(2).strip()
    return from_header.strip(), from_header.strip()


def _internaldate_to_iso(ms_str: str) -> str:
    try:
        ts = int(ms_str) / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


class GmailBatchProcessor:
    def __init__(self, db: Any, llm_router: Any, event_bus: Any):
        self._db = db
        self._llm = llm_router
        self._event_bus = event_bus
        self.is_running = False
        self._processed = 0
        self._total = 0
        self._errors = 0
        self._started_at: str | None = None

    @property
    def status(self) -> dict:
        return {
            "running": self.is_running,
            "processed": self._processed,
            "total": self._total,
            "errors": self._errors,
            "started_at": self._started_at,
        }

    async def process(self, since_date: str) -> dict:
        """Fetch, classify and persist all emails since since_date (YYYY/MM/DD)."""
        if self.is_running:
            raise RuntimeError("Processor is already running")

        self.is_running = True
        self._processed = 0
        self._total = 0
        self._errors = 0
        self._started_at = datetime.now(timezone.utc).isoformat()

        try:
            service = await _get_gmail_service()
            auth_email = await _get_authenticated_email(service)
            categories = await self._load_categories()

            # 1. Collect all message IDs
            msg_ids = await self._fetch_all_ids(service, since_date)
            self._total = len(msg_ids)
            await self._emit("gmail_classifier.progress", {"processed": 0, "total": self._total})

            # 2. Process in batches
            for i in range(0, len(msg_ids), BATCH_SIZE):
                batch_ids = msg_ids[i: i + BATCH_SIZE]
                emails = await self._fetch_details(service, batch_ids, auth_email)
                classifications = await self._classify(emails, categories)
                await self._upsert(emails, classifications, categories)
                self._processed += len(emails)
                await self._emit("gmail_classifier.progress", {
                    "processed": self._processed,
                    "total": self._total,
                })
                await asyncio.sleep(0)  # yield to event loop

            await self._emit("gmail_classifier.completed", {
                "total": self._total,
                "processed": self._processed,
                "errors": self._errors,
            })
            return {"total": self._total, "processed": self._processed, "errors": self._errors}

        except Exception as exc:
            log.error("Gmail batch processing failed", error=str(exc))
            await self._emit("gmail_classifier.error", {"message": str(exc)})
            raise
        finally:
            self.is_running = False

    # ── Internal helpers ──────────────────────────────────────

    async def _fetch_all_ids(self, service, since_date: str) -> list[str]:
        ids: list[str] = []
        query = f"after:{since_date.replace('/', '')}" if since_date else ""
        page_token = None
        while True:
            kwargs: dict = {"userId": "me", "maxResults": 500}
            if query:
                kwargs["q"] = query
            if page_token:
                kwargs["pageToken"] = page_token
            result = service.users().messages().list(**kwargs).execute()
            for m in result.get("messages", []):
                ids.append(m["id"])
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        return ids

    async def _fetch_details(self, service, ids: list[str], auth_email: str) -> list[dict]:
        emails = []
        for msg_id in ids:
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                ).execute()
                headers = _parse_headers(msg.get("payload", {}).get("headers", []))
                from_header = headers.get("From", "")
                sender_name, sender_email = _parse_sender(from_header)
                thread_id = msg.get("threadId", "")

                # Determine is_replied: check if last message in thread was from auth user
                is_replied = 0
                try:
                    thread = service.users().threads().get(
                        userId="me", id=thread_id, format="metadata",
                        metadataFields="messages/payload/headers",
                    ).execute()
                    last_msg = thread.get("messages", [{}])[-1]
                    last_from = _parse_headers(
                        last_msg.get("payload", {}).get("headers", [])
                    ).get("From", "")
                    _, last_email = _parse_sender(last_from)
                    is_replied = 1 if last_email.lower() == auth_email.lower() else 0
                except Exception:
                    pass

                is_read = 0 if "UNREAD" in msg.get("labelIds", []) else 1
                emails.append({
                    "gmail_id": msg_id,
                    "thread_id": thread_id,
                    "subject": headers.get("Subject", "(sin asunto)"),
                    "sender_name": sender_name,
                    "sender_email": sender_email,
                    "snippet": msg.get("snippet", "")[:200],
                    "is_read": is_read,
                    "is_replied": is_replied,
                    "received_at": _internaldate_to_iso(msg.get("internalDate", "0")),
                })
                await asyncio.sleep(0.05)  # Gmail API rate limiting
            except Exception as exc:
                log.warning("Failed to fetch email", gmail_id=msg_id, error=str(exc))
                self._errors += 1
        return emails

    async def _load_categories(self) -> list[dict]:
        cursor = await self._db._db.execute(
            "SELECT id, name, description FROM gmail_categories ORDER BY id"
        )
        rows = await cursor.fetchall()
        return [{"id": r["id"], "name": r["name"], "description": r["description"]} for r in rows]

    async def _classify(self, emails: list[dict], categories: list[dict]) -> dict[str, str]:
        """Call LLM to classify emails. Returns {gmail_id: category_name}."""
        if not emails or not categories:
            return {}

        cat_block = "\n".join(
            f"- {c['name']}: {c['description']}" for c in categories
            if c["name"] != "Otros"
        )
        cat_block += "\n- Otros: Usa esta cuando el correo no encaje en ninguna categoría."

        email_block = "\n".join(
            f'{i + 1}. De: {e["sender_email"]} | Asunto: {e["subject"]} | Preview: {e["snippet"]}'
            for i, e in enumerate(emails)
        )

        prompt = (
            "Eres un clasificador de correos. Clasifica cada correo en EXACTAMENTE una de estas categorías:\n"
            f"{cat_block}\n\n"
            "Devuelve SOLO un JSON array sin explicaciones:\n"
            '[{"gmail_id": "...", "category": "NombreCategoria"}, ...]\n\n'
            f"Correos a clasificar:\n{email_block}\n\n"
            "Importante: El campo gmail_id debe ser el ID exacto del correo. "
            "Si un correo no encaja en ninguna categoría, usa 'Otros'."
        )

        # Add gmail_ids so LLM can reference them
        id_block = "\n".join(
            f'{i + 1}. gmail_id={e["gmail_id"]}'
            for i, e in enumerate(emails)
        )
        full_prompt = prompt + f"\n\nIDs para referencia:\n{id_block}"

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": full_prompt}],
                temperature=0.1,
                max_tokens=1500,
            )
            content = response.get("content", "")
            # Extract JSON array from response (may have surrounding text)
            match = re.search(r"\[.*?\]", content, re.DOTALL)
            if not match:
                raise ValueError("No JSON array in LLM response")
            items = json.loads(match.group(0))
            return {item["gmail_id"]: item["category"] for item in items if "gmail_id" in item}
        except Exception as exc:
            log.warning("LLM classification failed, defaulting to Otros", error=str(exc))
            return {}

    async def _upsert(
        self,
        emails: list[dict],
        classifications: dict[str, str],
        categories: list[dict],
    ) -> None:
        cat_by_name = {c["name"]: c["id"] for c in categories}
        otros_id = cat_by_name.get("Otros")

        for email in emails:
            cat_name = classifications.get(email["gmail_id"], "Otros")
            cat_id = cat_by_name.get(cat_name, otros_id)

            await self._db._db.execute(
                """
                INSERT INTO gmail_emails
                    (gmail_id, thread_id, subject, sender_name, sender_email,
                     snippet, category_id, is_read, is_replied, ai_classified, received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(gmail_id) DO UPDATE SET
                    thread_id     = excluded.thread_id,
                    subject       = excluded.subject,
                    sender_name   = excluded.sender_name,
                    sender_email  = excluded.sender_email,
                    snippet       = excluded.snippet,
                    category_id   = excluded.category_id,
                    is_replied    = excluded.is_replied,
                    ai_classified = 1,
                    last_synced   = CURRENT_TIMESTAMP
                """,
                (
                    email["gmail_id"],
                    email["thread_id"],
                    email["subject"],
                    email["sender_name"],
                    email["sender_email"],
                    email["snippet"],
                    cat_id,
                    email["is_read"],
                    email["is_replied"],
                    email["received_at"],
                ),
            )
        await self._db._db.commit()

    async def _emit(self, event: str, data: dict) -> None:
        if self._event_bus:
            try:
                await self._event_bus.emit(event, data)
            except Exception:
                pass
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
pytest tests/unit/test_gmail_classifier.py::test_processor_is_not_running_initially tests/unit/test_gmail_classifier.py::test_processor_classifies_emails tests/unit/test_gmail_classifier.py::test_processor_falls_back_to_otros_on_bad_llm_response -v
```

Expected: 3 PASSED.

- [ ] **Step 3.5: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/processor.py
git commit -m "feat: GmailBatchProcessor with LLM classification"
```

---

## Task 4: Category & Email API Router

**Files:**
- Create: `src/openacm/plugins/gmail_classifier/router.py`
- Test: `tests/unit/test_gmail_classifier.py`

- [ ] **Step 4.1: Write failing tests for category CRUD and email endpoints**

Append to `tests/unit/test_gmail_classifier.py`:

```python
# ─── Router Fixtures ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def router_app(db):
    """Minimal FastAPI app with the plugin router mounted."""
    from fastapi import FastAPI
    import openacm.plugins.gmail_classifier.router as router_mod
    from openacm.plugins.gmail_classifier.processor import GmailBatchProcessor

    mock_proc = MagicMock()
    mock_proc.is_running = False
    mock_proc.status = {"running": False, "processed": 0, "total": 0, "errors": 0, "started_at": None}
    mock_proc.process = AsyncMock(return_value={"total": 5, "processed": 5, "errors": 0})

    router_mod._db = db
    router_mod._processor = mock_proc

    # Seed default settings
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_classifier_settings (key, value) VALUES ('auto_mark_read', 'false')"
    )
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_classifier_settings (key, value) VALUES ('auto_apply_label', 'false')"
    )
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_classifier_settings (key, value) VALUES ('cron_schedule', '')"
    )
    await db._db.commit()

    app = FastAPI()
    app.include_router(router_mod.router)
    return app, mock_proc


@pytest_asyncio.fixture
async def api(router_app):
    from httpx import AsyncClient, ASGITransport
    app, proc = router_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, proc


# ─── Category CRUD Tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_category(api):
    client, _ = api
    resp = await client.post("/gmail-classifier/categories", json={
        "name": "Parqueaderos",
        "description": "Correos sobre parqueaderos",
        "color": "#8b5cf6",
        "icon": "Car",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Parqueaderos"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_categories(api):
    client, _ = api
    # Create one first
    await client.post("/gmail-classifier/categories", json={
        "name": "Peticiones", "description": "Desc", "color": "#3b82f6", "icon": "FileText"
    })
    resp = await client.get("/gmail-classifier/categories")
    assert resp.status_code == 200
    categories = resp.json()
    assert any(c["name"] == "Peticiones" for c in categories)


@pytest.mark.asyncio
async def test_update_category(api):
    client, _ = api
    create_resp = await client.post("/gmail-classifier/categories", json={
        "name": "Old Name", "description": "Old", "color": "#000", "icon": "Tag"
    })
    cat_id = create_resp.json()["id"]

    resp = await client.put(f"/gmail-classifier/categories/{cat_id}", json={
        "name": "New Name", "description": "New desc", "color": "#fff", "icon": "Inbox"
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_delete_category_reassigns_emails(api, db):
    client, _ = api
    # Create category and an email assigned to it
    create_resp = await client.post("/gmail-classifier/categories", json={
        "name": "ToDelete", "description": "d", "color": "#000", "icon": "Tag"
    })
    cat_id = create_resp.json()["id"]

    # Seed Otros
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description, color, icon) "
        "VALUES ('Otros', 'fallback', '#6b7280', 'Inbox')"
    )
    # Seed an email in ToDelete
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_emails (gmail_id, category_id, thread_id) VALUES ('gid1', ?, '')",
        (cat_id,)
    )
    await db._db.commit()

    resp = await client.delete(f"/gmail-classifier/categories/{cat_id}")
    assert resp.status_code == 200

    cursor = await db._db.execute(
        "SELECT gc.name FROM gmail_emails ge JOIN gmail_categories gc ON ge.category_id = gc.id WHERE ge.gmail_id = 'gid1'"
    )
    row = await cursor.fetchone()
    assert row["name"] == "Otros"


# ─── Email Endpoint Tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_emails_returns_rows(api, db):
    client, _ = api
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description, color, icon) VALUES ('Otros', 'd', '#000', 'Tag')"
    )
    cursor = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Otros'")
    otros_id = (await cursor.fetchone())["id"]
    await db._db.execute(
        "INSERT INTO gmail_emails (gmail_id, subject, sender_email, category_id, thread_id) "
        "VALUES ('abc123', 'Test Subject', 'x@y.com', ?, '')",
        (otros_id,)
    )
    await db._db.commit()

    resp = await client.get("/gmail-classifier/emails")
    assert resp.status_code == 200
    emails = resp.json()
    assert any(e["gmail_id"] == "abc123" for e in emails["items"])


@pytest.mark.asyncio
async def test_toggle_email_read(api, db):
    client, _ = api
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description, color, icon) VALUES ('Otros', 'd', '#000', 'Tag')"
    )
    cursor = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Otros'")
    otros_id = (await cursor.fetchone())["id"]
    await db._db.execute(
        "INSERT INTO gmail_emails (gmail_id, is_read, category_id, thread_id) VALUES ('gread1', 0, ?, '')",
        (otros_id,)
    )
    await db._db.commit()
    cursor = await db._db.execute("SELECT id FROM gmail_emails WHERE gmail_id='gread1'")
    email_id = (await cursor.fetchone())["id"]

    resp = await client.patch(f"/gmail-classifier/emails/{email_id}/read", json={"is_read": True})
    assert resp.status_code == 200
    assert resp.json()["is_read"] is True


@pytest.mark.asyncio
async def test_recategorize_email(api, db):
    client, _ = api
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description, color, icon) VALUES ('Otros', 'd', '#000', 'Tag')"
    )
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description, color, icon) VALUES ('Trabajo', 'd', '#000', 'Tag')"
    )
    cursor = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Otros'")
    otros_id = (await cursor.fetchone())["id"]
    cursor2 = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Trabajo'")
    trabajo_id = (await cursor2.fetchone())["id"]

    await db._db.execute(
        "INSERT INTO gmail_emails (gmail_id, category_id, thread_id) VALUES ('grecat1', ?, '')",
        (otros_id,)
    )
    await db._db.commit()
    cursor3 = await db._db.execute("SELECT id FROM gmail_emails WHERE gmail_id='grecat1'")
    email_id = (await cursor3.fetchone())["id"]

    resp = await client.patch(f"/gmail-classifier/emails/{email_id}/category", json={"category_id": trabajo_id})
    assert resp.status_code == 200
    assert resp.json()["category_id"] == trabajo_id
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
pytest tests/unit/test_gmail_classifier.py -k "category or email" -v
```

Expected: FAIL — router module doesn't exist.

- [ ] **Step 4.3: Create `router.py`**

Create `src/openacm/plugins/gmail_classifier/router.py`:

```python
"""Gmail Classifier — FastAPI router for all API endpoints."""
from __future__ import annotations

import asyncio
import base64
import re
from email.mime.text import MIMEText
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = structlog.get_logger()

router = APIRouter(prefix="/gmail-classifier", tags=["gmail-classifier"])

# Set by GmailClassifierPlugin.on_start()
_db: Any = None
_processor: Any = None


def _require_db():
    if _db is None:
        raise HTTPException(status_code=503, detail="Gmail Classifier not initialized")
    return _db


def _require_processor():
    if _processor is None:
        raise HTTPException(status_code=503, detail="Gmail Classifier processor not initialized")
    return _processor


# ─── Pydantic models ─────────────────────────────────────────────────────────

class CategoryBody(BaseModel):
    name: str
    description: str = ""
    color: str = "#6366f1"
    icon: str = "Tag"


class ReadToggle(BaseModel):
    is_read: bool


class RecategorizeBody(BaseModel):
    category_id: int


class ProcessBody(BaseModel):
    since_date: str  # YYYY/MM/DD


class ReplyBody(BaseModel):
    body: str


class SettingsBody(BaseModel):
    auto_mark_read: str | None = None
    auto_apply_label: str | None = None
    cron_schedule: str | None = None
    since_date_default: str | None = None


class CronBody(BaseModel):
    schedule: str


# ─── Categories ──────────────────────────────────────────────────────────────

@router.get("/categories")
async def list_categories():
    db = _require_db()
    cursor = await db._db.execute(
        "SELECT gc.id, gc.name, gc.description, gc.color, gc.icon, "
        "COUNT(ge.id) as email_count "
        "FROM gmail_categories gc "
        "LEFT JOIN gmail_emails ge ON ge.category_id = gc.id "
        "GROUP BY gc.id ORDER BY gc.id"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@router.post("/categories")
async def create_category(body: CategoryBody):
    db = _require_db()
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    try:
        cursor = await db._db.execute(
            "INSERT INTO gmail_categories (name, description, color, icon) VALUES (?, ?, ?, ?)",
            (body.name.strip(), body.description, body.color, body.icon),
        )
        await db._db.commit()
        row_cursor = await db._db.execute(
            "SELECT * FROM gmail_categories WHERE id = ?", (cursor.lastrowid,)
        )
        row = await row_cursor.fetchone()
        return dict(row)
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(status_code=409, detail="Category name already exists")
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/categories/{cat_id}")
async def update_category(cat_id: int, body: CategoryBody):
    db = _require_db()
    cursor = await db._db.execute("SELECT id FROM gmail_categories WHERE id = ?", (cat_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Category not found")
    await db._db.execute(
        "UPDATE gmail_categories SET name=?, description=?, color=?, icon=? WHERE id=?",
        (body.name.strip(), body.description, body.color, body.icon, cat_id),
    )
    await db._db.commit()
    cursor2 = await db._db.execute("SELECT * FROM gmail_categories WHERE id = ?", (cat_id,))
    return dict(await cursor2.fetchone())


@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: int):
    db = _require_db()
    cursor = await db._db.execute("SELECT name FROM gmail_categories WHERE id = ?", (cat_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Category not found")
    if row["name"] == "Otros":
        raise HTTPException(status_code=400, detail="Cannot delete the Otros category")

    # Reassign emails to Otros
    otros_cursor = await db._db.execute(
        "SELECT id FROM gmail_categories WHERE name = 'Otros'"
    )
    otros = await otros_cursor.fetchone()
    if otros:
        await db._db.execute(
            "UPDATE gmail_emails SET category_id = ? WHERE category_id = ?",
            (otros["id"], cat_id),
        )
    await db._db.execute("DELETE FROM gmail_categories WHERE id = ?", (cat_id,))
    await db._db.commit()
    return {"deleted": True, "id": cat_id}


# ─── Emails ───────────────────────────────────────────────────────────────────

@router.get("/emails")
async def list_emails(
    category_id: int | None = None,
    is_read: int | None = None,
    page: int = 1,
    per_page: int = 50,
):
    db = _require_db()
    conditions = []
    params: list = []

    if category_id is not None:
        conditions.append("ge.category_id = ?")
        params.append(category_id)
    if is_read is not None:
        conditions.append("ge.is_read = ?")
        params.append(is_read)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * per_page

    count_cursor = await db._db.execute(
        f"SELECT COUNT(*) as total FROM gmail_emails ge {where}", params
    )
    total = (await count_cursor.fetchone())["total"]

    cursor = await db._db.execute(
        f"""
        SELECT ge.*, gc.name as category_name, gc.color as category_color, gc.icon as category_icon
        FROM gmail_emails ge
        LEFT JOIN gmail_categories gc ON ge.category_id = gc.id
        {where}
        ORDER BY ge.received_at DESC
        LIMIT ? OFFSET ?
        """,
        params + [per_page, offset],
    )
    rows = await cursor.fetchall()
    return {"items": [dict(r) for r in rows], "total": total, "page": page, "per_page": per_page}


@router.patch("/emails/{email_id}/read")
async def toggle_read(email_id: int, body: ReadToggle):
    db = _require_db()
    cursor = await db._db.execute("SELECT id FROM gmail_emails WHERE id = ?", (email_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Email not found")
    await db._db.execute(
        "UPDATE gmail_emails SET is_read = ? WHERE id = ?",
        (1 if body.is_read else 0, email_id),
    )
    await db._db.commit()
    row_cursor = await db._db.execute("SELECT * FROM gmail_emails WHERE id = ?", (email_id,))
    row = dict(await row_cursor.fetchone())
    row["is_read"] = bool(row["is_read"])
    return row


@router.patch("/emails/{email_id}/category")
async def recategorize(email_id: int, body: RecategorizeBody):
    db = _require_db()
    cursor = await db._db.execute("SELECT id FROM gmail_emails WHERE id = ?", (email_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Email not found")
    cat_cursor = await db._db.execute("SELECT id FROM gmail_categories WHERE id = ?", (body.category_id,))
    if not await cat_cursor.fetchone():
        raise HTTPException(status_code=404, detail="Category not found")
    await db._db.execute(
        "UPDATE gmail_emails SET category_id = ? WHERE id = ?",
        (body.category_id, email_id),
    )
    await db._db.commit()
    row_cursor = await db._db.execute("SELECT * FROM gmail_emails WHERE id = ?", (email_id,))
    return dict(await row_cursor.fetchone())


@router.post("/emails/{email_id}/reply")
async def reply_email(email_id: int, body: ReplyBody):
    db = _require_db()
    cursor = await db._db.execute(
        "SELECT gmail_id, subject, sender_email FROM gmail_emails WHERE id = ?", (email_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Email not found")

    try:
        from openacm.tools.google_services import _get_google_service
        service = await _get_google_service("gmail", "v1")

        subject = row["subject"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        message = MIMEText(body.body)
        message["to"] = row["sender_email"]
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()

        # Mark as replied and read
        await db._db.execute(
            "UPDATE gmail_emails SET is_replied = 1, is_read = 1 WHERE id = ?", (email_id,)
        )
        await db._db.commit()
        return {"success": True, "to": row["sender_email"]}

    except Exception as exc:
        log.error("Failed to send reply", email_id=email_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to send reply: {exc}")


# ─── Processing ───────────────────────────────────────────────────────────────

@router.post("/process")
async def start_process(body: ProcessBody):
    proc = _require_processor()
    if proc.is_running:
        raise HTTPException(status_code=409, detail="Processing already in progress")
    asyncio.create_task(proc.process(body.since_date))
    return {"started": True, "since_date": body.since_date}


@router.get("/process/status")
async def process_status():
    proc = _require_processor()
    return proc.status


# ─── Settings ─────────────────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings():
    db = _require_db()
    cursor = await db._db.execute("SELECT key, value FROM gmail_classifier_settings")
    rows = await cursor.fetchall()
    return {r["key"]: r["value"] for r in rows}


@router.put("/settings")
async def update_settings(body: SettingsBody):
    db = _require_db()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    for key, value in updates.items():
        await db._db.execute(
            "INSERT INTO gmail_classifier_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    await db._db.commit()
    cursor = await db._db.execute("SELECT key, value FROM gmail_classifier_settings")
    rows = await cursor.fetchall()
    return {r["key"]: r["value"] for r in rows}


# ─── Cron ─────────────────────────────────────────────────────────────────────

@router.post("/cron")
async def set_cron(body: CronBody):
    db = _require_db()
    if body.schedule:
        fields = body.schedule.strip().split()
        shortcuts = {"@hourly", "@daily", "@midnight", "@weekly", "@monthly"}
        if body.schedule.strip() not in shortcuts and len(fields) != 5:
            raise HTTPException(status_code=400, detail="Invalid cron expression (need 5 fields)")

    await db._db.execute(
        "INSERT INTO gmail_classifier_settings (key, value) VALUES ('cron_schedule', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (body.schedule,),
    )
    await db._db.commit()

    # Restart cron loop in plugin
    from openacm.plugins.gmail_classifier import PLUGIN
    if body.schedule:
        PLUGIN._start_cron(body.schedule)
    else:
        if PLUGIN._cron_task and not PLUGIN._cron_task.done():
            PLUGIN._cron_task.cancel()

    return {"cron_schedule": body.schedule}


@router.delete("/cron")
async def delete_cron():
    db = _require_db()
    await db._db.execute(
        "INSERT INTO gmail_classifier_settings (key, value) VALUES ('cron_schedule', '') "
        "ON CONFLICT(key) DO UPDATE SET value = ''"
    )
    await db._db.commit()
    from openacm.plugins.gmail_classifier import PLUGIN
    if PLUGIN._cron_task and not PLUGIN._cron_task.done():
        PLUGIN._cron_task.cancel()
    return {"cron_schedule": ""}
```

- [ ] **Step 4.4: Run all router tests**

```bash
pytest tests/unit/test_gmail_classifier.py -v
```

Expected: All PASSED.

- [ ] **Step 4.5: Run full test suite to check for regressions**

```bash
pytest --tb=short -q
```

Expected: All existing tests still pass.

- [ ] **Step 4.6: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/router.py
git commit -m "feat: gmail_classifier API router — categories, emails, process, settings"
```

---

## Task 5: Frontend — Main Page Shell

**Files:**
- Create: `frontend/app/gmail-classifier/page.tsx`
- Create: `frontend/app/gmail-classifier/components/ProcessingProgress.tsx`

- [ ] **Step 5.1: Create ProcessingProgress component**

Create `frontend/app/gmail-classifier/components/ProcessingProgress.tsx`:

```tsx
"use client";

interface ProcessingProgressProps {
  processed: number;
  total: number;
  running: boolean;
}

export function ProcessingProgress({ processed, total, running }: ProcessingProgressProps) {
  if (!running && total === 0) return null;

  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-2 flex items-center gap-3">
      <div className="flex-1">
        <div className="flex justify-between text-xs text-blue-700 mb-1">
          <span>{running ? "Clasificando correos..." : "Clasificación completada"}</span>
          <span>{processed} / {total} correos</span>
        </div>
        <div className="w-full bg-blue-200 rounded-full h-1.5">
          <div
            className="bg-blue-600 h-1.5 rounded-full transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      {!running && (
        <span className="text-green-600 text-sm font-medium">✓ Listo</span>
      )}
    </div>
  );
}
```

- [ ] **Step 5.2: Create main page shell**

Create `frontend/app/gmail-classifier/page.tsx`:

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { Mail, RefreshCw, Settings } from "lucide-react";
import { CategoryTabs } from "./components/CategoryTabs";
import { EmailList } from "./components/EmailList";
import { EmailDetail } from "./components/EmailDetail";
import { CategoryManager } from "./components/CategoryManager";
import { ProcessingProgress } from "./components/ProcessingProgress";
import { PluginSettings } from "./components/PluginSettings";

const API = "/api/gmail-classifier";

interface Category {
  id: number;
  name: string;
  description: string;
  color: string;
  icon: string;
  email_count: number;
}

interface Email {
  id: number;
  gmail_id: string;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
  category_id: number;
  category_name: string;
  category_color: string;
  category_icon: string;
  is_read: number;
  is_replied: number;
  received_at: string;
}

interface ProcessStatus {
  running: boolean;
  processed: number;
  total: number;
  errors: number;
  started_at: string | null;
}

export default function GmailClassifierPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [emails, setEmails] = useState<Email[]>([]);
  const [totalEmails, setTotalEmails] = useState(0);
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
  const [selectedEmail, setSelectedEmail] = useState<Email | null>(null);
  const [processStatus, setProcessStatus] = useState<ProcessStatus>({
    running: false, processed: 0, total: 0, errors: 0, started_at: null,
  });
  const [sinceDate, setSinceDate] = useState("");
  const [showCategoryManager, setShowCategoryManager] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [page, setPage] = useState(1);

  const fetchCategories = useCallback(async () => {
    const res = await fetch(`${API}/categories`);
    if (res.ok) setCategories(await res.json());
  }, []);

  const fetchEmails = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page), per_page: "50" });
    if (selectedCategoryId !== null) params.set("category_id", String(selectedCategoryId));
    const res = await fetch(`${API}/emails?${params}`);
    if (res.ok) {
      const data = await res.json();
      setEmails(data.items);
      setTotalEmails(data.total);
    }
  }, [selectedCategoryId, page]);

  const fetchStatus = useCallback(async () => {
    const res = await fetch(`${API}/process/status`);
    if (res.ok) {
      const status: ProcessStatus = await res.json();
      setProcessStatus(status);
      if (status.running) {
        setTimeout(fetchStatus, 1500);
      } else if (status.total > 0) {
        fetchEmails();
        fetchCategories();
      }
    }
  }, [fetchEmails, fetchCategories]);

  useEffect(() => {
    fetchCategories();
    fetchEmails();
    fetchStatus();
  }, [fetchCategories, fetchEmails, fetchStatus]);

  useEffect(() => {
    fetchEmails();
  }, [fetchEmails]);

  const handleProcess = async () => {
    if (!sinceDate) {
      alert("Selecciona una fecha de inicio");
      return;
    }
    const formatted = sinceDate.replace(/-/g, "/");
    const res = await fetch(`${API}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ since_date: formatted }),
    });
    if (res.ok) {
      setProcessStatus({ running: true, processed: 0, total: 0, errors: 0, started_at: new Date().toISOString() });
      setTimeout(fetchStatus, 1000);
    } else {
      const err = await res.json();
      alert(err.detail || "Error al iniciar el proceso");
    }
  };

  const handleEmailRead = async (emailId: number, isRead: boolean) => {
    await fetch(`${API}/emails/${emailId}/read`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_read: isRead }),
    });
    setEmails(prev => prev.map(e => e.id === emailId ? { ...e, is_read: isRead ? 1 : 0 } : e));
    if (selectedEmail?.id === emailId) {
      setSelectedEmail(prev => prev ? { ...prev, is_read: isRead ? 1 : 0 } : null);
    }
  };

  const handleRecategorize = async (emailId: number, categoryId: number) => {
    const res = await fetch(`${API}/emails/${emailId}/category`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category_id: categoryId }),
    });
    if (res.ok) {
      fetchEmails();
      fetchCategories();
    }
  };

  const handleReply = async (emailId: number, body: string) => {
    const res = await fetch(`${API}/emails/${emailId}/reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    });
    if (res.ok) {
      setEmails(prev => prev.map(e => e.id === emailId ? { ...e, is_replied: 1, is_read: 1 } : e));
      if (selectedEmail?.id === emailId) {
        setSelectedEmail(prev => prev ? { ...prev, is_replied: 1, is_read: 1 } : null);
      }
      return true;
    }
    return false;
  };

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-3 border-b bg-gray-50">
        <Mail className="text-blue-600" size={20} />
        <h1 className="font-semibold text-gray-800 text-lg">Gmail Classifier</h1>
        <div className="flex-1" />

        <input
          type="date"
          value={sinceDate}
          onChange={e => setSinceDate(e.target.value)}
          className="text-sm border rounded px-2 py-1 text-gray-700"
        />
        <button
          onClick={handleProcess}
          disabled={processStatus.running}
          className="flex items-center gap-1.5 bg-blue-600 text-white text-sm px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <RefreshCw size={14} className={processStatus.running ? "animate-spin" : ""} />
          {processStatus.running ? "Procesando..." : "Procesar"}
        </button>
        <button
          onClick={() => setShowSettings(true)}
          className="p-1.5 rounded hover:bg-gray-200 text-gray-600"
        >
          <Settings size={16} />
        </button>
      </div>

      {/* Progress bar */}
      {(processStatus.running || processStatus.total > 0) && (
        <div className="px-4 py-2 border-b">
          <ProcessingProgress
            running={processStatus.running}
            processed={processStatus.processed}
            total={processStatus.total}
          />
        </div>
      )}

      {/* Category tabs */}
      <CategoryTabs
        categories={categories}
        selectedId={selectedCategoryId}
        onSelect={id => { setSelectedCategoryId(id); setPage(1); setSelectedEmail(null); }}
        onManage={() => setShowCategoryManager(true)}
      />

      {/* Split view */}
      <div className="flex flex-1 min-h-0">
        <EmailList
          emails={emails}
          selectedId={selectedEmail?.id ?? null}
          onSelect={email => {
            setSelectedEmail(email);
            if (!email.is_read) handleEmailRead(email.id, true);
          }}
        />
        <EmailDetail
          email={selectedEmail}
          categories={categories}
          onReadToggle={handleEmailRead}
          onRecategorize={handleRecategorize}
          onReply={handleReply}
        />
      </div>

      {/* Modals */}
      {showCategoryManager && (
        <CategoryManager
          categories={categories}
          onClose={() => setShowCategoryManager(false)}
          onSaved={() => { fetchCategories(); fetchEmails(); }}
        />
      )}
      {showSettings && (
        <PluginSettings onClose={() => setShowSettings(false)} />
      )}
    </div>
  );
}
```

- [ ] **Step 5.3: Commit**

```bash
git add frontend/app/gmail-classifier/
git commit -m "feat: gmail-classifier page shell and ProcessingProgress component"
```

---

## Task 6: Frontend — CategoryTabs & EmailList

**Files:**
- Create: `frontend/app/gmail-classifier/components/CategoryTabs.tsx`
- Create: `frontend/app/gmail-classifier/components/EmailList.tsx`

- [ ] **Step 6.1: Create CategoryTabs**

Create `frontend/app/gmail-classifier/components/CategoryTabs.tsx`:

```tsx
"use client";

import * as Icons from "lucide-react";
import { Plus } from "lucide-react";

interface Category {
  id: number;
  name: string;
  color: string;
  icon: string;
  email_count: number;
}

interface CategoryTabsProps {
  categories: Category[];
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  onManage: () => void;
}

function CategoryIcon({ iconName, color }: { iconName: string; color: string }) {
  const LucideIcon = (Icons as any)[iconName] ?? Icons.Tag;
  return <LucideIcon size={14} style={{ color }} />;
}

export function CategoryTabs({ categories, selectedId, onSelect, onManage }: CategoryTabsProps) {
  const unreadAll = categories.reduce((sum, c) => sum + c.email_count, 0);

  return (
    <div className="flex items-center gap-1 px-4 py-2 border-b overflow-x-auto bg-white">
      {/* Todo tab */}
      <button
        onClick={() => onSelect(null)}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm whitespace-nowrap transition-colors ${
          selectedId === null
            ? "bg-gray-900 text-white"
            : "text-gray-600 hover:bg-gray-100"
        }`}
      >
        Todo
        {unreadAll > 0 && (
          <span className="bg-gray-500 text-white text-xs px-1.5 rounded-full">{unreadAll}</span>
        )}
      </button>

      {/* Category tabs */}
      {categories.map(cat => (
        <button
          key={cat.id}
          onClick={() => onSelect(cat.id)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm whitespace-nowrap transition-colors ${
            selectedId === cat.id
              ? "text-white"
              : "text-gray-600 hover:bg-gray-100"
          }`}
          style={selectedId === cat.id ? { backgroundColor: cat.color } : undefined}
        >
          <CategoryIcon iconName={cat.icon} color={selectedId === cat.id ? "white" : cat.color} />
          {cat.name}
          {cat.email_count > 0 && (
            <span
              className="text-xs px-1.5 rounded-full"
              style={{
                backgroundColor: selectedId === cat.id ? "rgba(255,255,255,0.3)" : `${cat.color}22`,
                color: selectedId === cat.id ? "white" : cat.color,
              }}
            >
              {cat.email_count}
            </span>
          )}
        </button>
      ))}

      {/* Add category */}
      <button
        onClick={onManage}
        className="flex items-center gap-1 px-2 py-1.5 rounded-full text-sm text-gray-500 hover:bg-gray-100 whitespace-nowrap"
      >
        <Plus size={14} />
        Nueva
      </button>
    </div>
  );
}
```

- [ ] **Step 6.2: Create EmailList**

Create `frontend/app/gmail-classifier/components/EmailList.tsx`:

```tsx
"use client";

import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";

interface Email {
  id: number;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
  category_name: string;
  category_color: string;
  is_read: number;
  is_replied: number;
  received_at: string;
}

interface EmailListProps {
  emails: Email[];
  selectedId: number | null;
  onSelect: (email: Email) => void;
}

function timeAgo(dateStr: string): string {
  try {
    return formatDistanceToNow(new Date(dateStr), { addSuffix: true, locale: es });
  } catch {
    return "";
  }
}

export function EmailList({ emails, selectedId, onSelect }: EmailListProps) {
  if (emails.length === 0) {
    return (
      <div className="w-80 flex-shrink-0 border-r flex items-center justify-center text-gray-400 text-sm">
        No hay correos
      </div>
    );
  }

  return (
    <div className="w-80 flex-shrink-0 border-r overflow-y-auto">
      {emails.map(email => (
        <button
          key={email.id}
          onClick={() => onSelect(email)}
          className={`w-full text-left px-4 py-3 border-b hover:bg-gray-50 transition-colors ${
            selectedId === email.id ? "bg-blue-50 border-l-2 border-l-blue-500" : ""
          }`}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              {/* Unread indicator */}
              <div
                className={`w-2 h-2 rounded-full flex-shrink-0 mt-1 ${
                  email.is_read ? "bg-transparent" : "bg-blue-500"
                }`}
              />
              <div className="min-w-0">
                <p
                  className={`text-sm truncate ${email.is_read ? "text-gray-600" : "text-gray-900 font-semibold"}`}
                >
                  {email.sender_name || email.sender_email}
                </p>
                <p
                  className={`text-sm truncate ${email.is_read ? "text-gray-500" : "text-gray-800 font-medium"}`}
                >
                  {email.subject}
                </p>
                <p className="text-xs text-gray-400 truncate">{email.snippet}</p>
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between mt-1 pl-4">
            <span
              className="text-xs px-2 py-0.5 rounded-full"
              style={{ backgroundColor: `${email.category_color}22`, color: email.category_color }}
            >
              {email.category_name}
            </span>
            <span className="text-xs text-gray-400">{timeAgo(email.received_at)}</span>
          </div>
          {email.is_replied === 1 && (
            <p className="text-xs text-green-600 pl-4 mt-0.5">↩ Respondido</p>
          )}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 6.3: Commit**

```bash
git add frontend/app/gmail-classifier/components/CategoryTabs.tsx frontend/app/gmail-classifier/components/EmailList.tsx
git commit -m "feat: CategoryTabs and EmailList components"
```

---

## Task 7: Frontend — EmailDetail & CategoryManager & PluginSettings

**Files:**
- Create: `frontend/app/gmail-classifier/components/EmailDetail.tsx`
- Create: `frontend/app/gmail-classifier/components/CategoryManager.tsx`
- Create: `frontend/app/gmail-classifier/components/PluginSettings.tsx`

- [ ] **Step 7.1: Create EmailDetail**

Create `frontend/app/gmail-classifier/components/EmailDetail.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Mail, MailOpen, ChevronDown } from "lucide-react";

interface Email {
  id: number;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
  category_id: number;
  is_read: number;
  is_replied: number;
  received_at: string;
}

interface Category {
  id: number;
  name: string;
  color: string;
}

interface EmailDetailProps {
  email: Email | null;
  categories: Category[];
  onReadToggle: (emailId: number, isRead: boolean) => void;
  onRecategorize: (emailId: number, categoryId: number) => void;
  onReply: (emailId: number, body: string) => Promise<boolean>;
}

export function EmailDetail({ email, categories, onReadToggle, onRecategorize, onReply }: EmailDetailProps) {
  const [replyText, setReplyText] = useState("");
  const [sending, setSending] = useState(false);
  const [replySuccess, setReplySuccess] = useState(false);

  if (!email) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
        Selecciona un correo para ver el detalle
      </div>
    );
  }

  const handleSendReply = async () => {
    if (!replyText.trim()) return;
    setSending(true);
    const ok = await onReply(email.id, replyText.trim());
    setSending(false);
    if (ok) {
      setReplyText("");
      setReplySuccess(true);
      setTimeout(() => setReplySuccess(false), 3000);
    }
  };

  const formattedDate = email.received_at
    ? new Date(email.received_at).toLocaleString("es-CO", {
        day: "2-digit", month: "long", year: "numeric",
        hour: "2-digit", minute: "2-digit",
      })
    : "";

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b bg-white">
        <h2 className="font-semibold text-gray-900 text-lg leading-tight">{email.subject}</h2>
        <div className="flex items-center gap-4 mt-2 text-sm text-gray-500">
          <span>De: <span className="text-gray-700">{email.sender_name || email.sender_email}</span></span>
          <span>&lt;{email.sender_email}&gt;</span>
          <span className="ml-auto">{formattedDate}</span>
        </div>
      </div>

      {/* Body / snippet */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <p className="text-gray-700 text-sm leading-relaxed whitespace-pre-wrap">{email.snippet}</p>
      </div>

      {/* Controls */}
      <div className="px-6 py-3 border-t bg-gray-50 flex items-center gap-3 flex-wrap">
        {/* Category selector */}
        <div className="relative">
          <select
            value={email.category_id}
            onChange={e => onRecategorize(email.id, Number(e.target.value))}
            className="text-sm border rounded px-2 py-1.5 pr-6 text-gray-700 bg-white appearance-none"
          >
            {categories.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <ChevronDown size={12} className="absolute right-2 top-2.5 text-gray-400 pointer-events-none" />
        </div>

        {/* Read toggle */}
        {email.is_read ? (
          <button
            onClick={() => onReadToggle(email.id, false)}
            className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-blue-600 px-2 py-1.5 rounded hover:bg-blue-50"
          >
            <Mail size={14} /> Marcar no leído
          </button>
        ) : (
          <button
            onClick={() => onReadToggle(email.id, true)}
            className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-green-600 px-2 py-1.5 rounded hover:bg-green-50"
          >
            <MailOpen size={14} /> Marcar leído
          </button>
        )}

        {email.is_replied === 1 && (
          <span className="text-xs text-green-600 bg-green-50 px-2 py-1 rounded">↩ Respondido</span>
        )}
      </div>

      {/* Reply composer */}
      <div className="px-6 py-4 border-t bg-white">
        <p className="text-xs text-gray-500 mb-2">Responder a: {email.sender_email}</p>
        <textarea
          value={replyText}
          onChange={e => setReplyText(e.target.value)}
          placeholder="Escribe tu respuesta..."
          rows={4}
          className="w-full border rounded px-3 py-2 text-sm text-gray-700 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <div className="flex items-center justify-between mt-2">
          {replySuccess && (
            <span className="text-sm text-green-600">✓ Respuesta enviada</span>
          )}
          <div className="ml-auto">
            <button
              onClick={handleSendReply}
              disabled={sending || !replyText.trim()}
              className="bg-blue-600 text-white text-sm px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {sending ? "Enviando..." : "Enviar respuesta"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 7.2: Create CategoryManager**

Create `frontend/app/gmail-classifier/components/CategoryManager.tsx`:

```tsx
"use client";

import { useState, useEffect } from "react";
import { X, Plus, Trash2, Edit2, Check } from "lucide-react";

const API = "/api/gmail-classifier";

const PRESET_COLORS = [
  "#6366f1", "#3b82f6", "#10b981", "#f59e0b",
  "#ef4444", "#8b5cf6", "#ec4899", "#6b7280",
];

const PRESET_ICONS = [
  "Tag", "Mail", "Car", "FileText", "Inbox",
  "Briefcase", "Home", "Star", "Bell", "Users",
  "ShoppingCart", "Calendar", "Map", "Truck", "Landmark",
];

interface Category {
  id: number;
  name: string;
  description: string;
  color: string;
  icon: string;
}

interface CategoryManagerProps {
  categories: Category[];
  onClose: () => void;
  onSaved: () => void;
}

export function CategoryManager({ categories, onClose, onSaved }: CategoryManagerProps) {
  const [editingId, setEditingId] = useState<number | "new" | null>(null);
  const [form, setForm] = useState({ name: "", description: "", color: "#6366f1", icon: "Tag" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const startNew = () => {
    setForm({ name: "", description: "", color: "#6366f1", icon: "Tag" });
    setEditingId("new");
    setError("");
  };

  const startEdit = (cat: Category) => {
    setForm({ name: cat.name, description: cat.description, color: cat.color, icon: cat.icon });
    setEditingId(cat.id);
    setError("");
  };

  const handleSave = async () => {
    if (!form.name.trim()) { setError("El nombre es requerido"); return; }
    setSaving(true);
    setError("");
    try {
      const url = editingId === "new" ? `${API}/categories` : `${API}/categories/${editingId}`;
      const method = editingId === "new" ? "POST" : "PUT";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const e = await res.json();
        setError(e.detail || "Error al guardar");
        return;
      }
      onSaved();
      setEditingId(null);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("¿Eliminar esta categoría? Los correos pasarán a 'Otros'.")) return;
    await fetch(`${API}/categories/${id}`, { method: "DELETE" });
    onSaved();
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="font-semibold text-gray-900">Gestionar Categorías</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded">
            <X size={18} />
          </button>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-2">
          {categories.map(cat => (
            <div key={cat.id} className="border rounded-lg overflow-hidden">
              {editingId === cat.id ? (
                <CategoryForm
                  form={form}
                  onChange={setForm}
                  onSave={handleSave}
                  onCancel={() => setEditingId(null)}
                  saving={saving}
                  error={error}
                />
              ) : (
                <div className="flex items-center gap-3 px-4 py-3">
                  <div className="w-3 h-3 rounded-full" style={{ backgroundColor: cat.color }} />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm text-gray-800">{cat.name}</p>
                    <p className="text-xs text-gray-500 truncate">{cat.description}</p>
                  </div>
                  {cat.name !== "Otros" && (
                    <div className="flex gap-1">
                      <button onClick={() => startEdit(cat)} className="p-1.5 hover:bg-gray-100 rounded text-gray-400 hover:text-gray-700">
                        <Edit2 size={14} />
                      </button>
                      <button onClick={() => handleDelete(cat.id)} className="p-1.5 hover:bg-red-50 rounded text-gray-400 hover:text-red-600">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {editingId === "new" && (
            <div className="border rounded-lg overflow-hidden">
              <CategoryForm
                form={form}
                onChange={setForm}
                onSave={handleSave}
                onCancel={() => setEditingId(null)}
                saving={saving}
                error={error}
              />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t">
          <button
            onClick={startNew}
            disabled={editingId !== null}
            className="flex items-center gap-2 text-sm text-blue-600 hover:text-blue-800 disabled:opacity-40"
          >
            <Plus size={16} /> Agregar categoría
          </button>
        </div>
      </div>
    </div>
  );
}

function CategoryForm({
  form,
  onChange,
  onSave,
  onCancel,
  saving,
  error,
}: {
  form: { name: string; description: string; color: string; icon: string };
  onChange: (f: any) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  error: string;
}) {
  const PRESET_COLORS = [
    "#6366f1", "#3b82f6", "#10b981", "#f59e0b",
    "#ef4444", "#8b5cf6", "#ec4899", "#6b7280",
  ];
  const PRESET_ICONS = [
    "Tag", "Mail", "Car", "FileText", "Inbox",
    "Briefcase", "Home", "Star", "Bell", "Users",
  ];

  return (
    <div className="px-4 py-3 space-y-3">
      <input
        className="w-full border rounded px-3 py-2 text-sm"
        placeholder="Nombre de la categoría"
        value={form.name}
        onChange={e => onChange({ ...form, name: e.target.value })}
      />
      <textarea
        className="w-full border rounded px-3 py-2 text-sm resize-none"
        placeholder="Descripción (ayuda a la IA a clasificar)"
        rows={2}
        value={form.description}
        onChange={e => onChange({ ...form, description: e.target.value })}
      />
      <div>
        <p className="text-xs text-gray-500 mb-1">Color</p>
        <div className="flex gap-2 flex-wrap">
          {PRESET_COLORS.map(c => (
            <button
              key={c}
              onClick={() => onChange({ ...form, color: c })}
              className={`w-6 h-6 rounded-full border-2 ${form.color === c ? "border-gray-900" : "border-transparent"}`}
              style={{ backgroundColor: c }}
            />
          ))}
        </div>
      </div>
      <div>
        <p className="text-xs text-gray-500 mb-1">Icono</p>
        <div className="flex gap-2 flex-wrap">
          {PRESET_ICONS.map(icon => (
            <button
              key={icon}
              onClick={() => onChange({ ...form, icon })}
              className={`px-2 py-1 text-xs border rounded ${form.icon === icon ? "bg-gray-900 text-white" : "hover:bg-gray-100"}`}
            >
              {icon}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="flex gap-2">
        <button
          onClick={onSave}
          disabled={saving}
          className="bg-blue-600 text-white text-sm px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Guardando..." : "Guardar"}
        </button>
        <button onClick={onCancel} className="text-sm text-gray-600 px-3 py-1.5 rounded hover:bg-gray-100">
          Cancelar
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 7.3: Create PluginSettings**

Create `frontend/app/gmail-classifier/components/PluginSettings.tsx`:

```tsx
"use client";

import { useState, useEffect } from "react";
import { X } from "lucide-react";

const API = "/api/gmail-classifier";

interface PluginSettingsProps {
  onClose: () => void;
}

function describeCron(expr: string): string {
  if (!expr) return "Desactivado";
  const map: Record<string, string> = {
    "@hourly": "Cada hora",
    "@daily": "Cada día a medianoche",
    "@midnight": "Cada día a medianoche",
    "@weekly": "Cada semana",
    "@monthly": "Cada mes",
    "0 * * * *": "Cada hora",
    "0 8 * * *": "Cada día a las 8:00am",
    "0 0 * * *": "Cada día a medianoche",
    "*/30 * * * *": "Cada 30 minutos",
  };
  return map[expr.trim()] ?? `Expresión: ${expr}`;
}

export function PluginSettings({ onClose }: PluginSettingsProps) {
  const [settings, setSettings] = useState({
    auto_mark_read: "false",
    auto_apply_label: "false",
    cron_schedule: "",
    since_date_default: "",
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`${API}/settings`)
      .then(r => r.json())
      .then(data => setSettings(s => ({ ...s, ...data })));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    const res = await fetch(`${API}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });

    if (res.ok && settings.cron_schedule) {
      await fetch(`${API}/cron`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schedule: settings.cron_schedule }),
      });
    } else if (res.ok && !settings.cron_schedule) {
      await fetch(`${API}/cron`, { method: "DELETE" });
    }

    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="font-semibold text-gray-900">Configuración del Plugin</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded">
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-5">
          {/* Auto mark read */}
          <label className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-800">Marcar como leído en Gmail</p>
              <p className="text-xs text-gray-500">Tras clasificar, se marca el correo como leído en Gmail</p>
            </div>
            <input
              type="checkbox"
              checked={settings.auto_mark_read === "true"}
              onChange={e => setSettings(s => ({ ...s, auto_mark_read: e.target.checked ? "true" : "false" }))}
              className="w-4 h-4"
            />
          </label>

          {/* Auto apply label */}
          <label className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-800">Aplicar etiqueta en Gmail</p>
              <p className="text-xs text-gray-500">Crea y aplica una etiqueta con el nombre de la categoría</p>
            </div>
            <input
              type="checkbox"
              checked={settings.auto_apply_label === "true"}
              onChange={e => setSettings(s => ({ ...s, auto_apply_label: e.target.checked ? "true" : "false" }))}
              className="w-4 h-4"
            />
          </label>

          {/* Default since date */}
          <div>
            <p className="text-sm font-medium text-gray-800 mb-1">Fecha de inicio por defecto</p>
            <input
              type="date"
              value={settings.since_date_default}
              onChange={e => setSettings(s => ({ ...s, since_date_default: e.target.value }))}
              className="w-full border rounded px-3 py-2 text-sm"
            />
          </div>

          {/* Cron schedule */}
          <div>
            <p className="text-sm font-medium text-gray-800 mb-1">Ejecución automática (cron)</p>
            <input
              type="text"
              placeholder="Ej: 0 8 * * * (vacío = desactivado)"
              value={settings.cron_schedule}
              onChange={e => setSettings(s => ({ ...s, cron_schedule: e.target.value }))}
              className="w-full border rounded px-3 py-2 text-sm"
            />
            <p className="text-xs text-gray-500 mt-1">{describeCron(settings.cron_schedule)}</p>
            <div className="flex gap-2 mt-2 flex-wrap">
              {[
                { label: "Cada hora", value: "0 * * * *" },
                { label: "8am diario", value: "0 8 * * *" },
                { label: "Desactivar", value: "" },
              ].map(preset => (
                <button
                  key={preset.label}
                  onClick={() => setSettings(s => ({ ...s, cron_schedule: preset.value }))}
                  className="text-xs px-2 py-1 border rounded hover:bg-gray-100"
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="px-6 py-4 border-t flex justify-end gap-3">
          <button onClick={onClose} className="text-sm text-gray-600 px-3 py-2 hover:bg-gray-100 rounded">
            Cancelar
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="bg-blue-600 text-white text-sm px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Guardando..." : saved ? "✓ Guardado" : "Guardar"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 7.4: Check for missing `date-fns` dependency**

```bash
cd frontend && cat package.json | grep date-fns
```

If `date-fns` is not listed, install it:

```bash
cd frontend && npm install date-fns
```

- [ ] **Step 7.5: Commit**

```bash
git add frontend/app/gmail-classifier/components/
git commit -m "feat: EmailDetail, CategoryManager, PluginSettings components"
```

---

## Task 8: Final Check & Integration

- [ ] **Step 8.1: Run all backend tests**

```bash
pytest tests/unit/test_gmail_classifier.py -v
```

Expected: All PASSED.

- [ ] **Step 8.2: Run full test suite**

```bash
pytest --tb=short -q
```

Expected: No new failures.

- [ ] **Step 8.3: Verify plugin is auto-discovered**

The plugin at `src/openacm/plugins/gmail_classifier/__init__.py` exposes a `PLUGIN = GmailClassifierPlugin()` instance. The `PluginManager.load_builtin_plugins()` iterates `pkgutil.iter_modules` over the plugins directory and loads any subpackage that exposes a `PLUGIN` attribute. No extra registration is needed.

- [ ] **Step 8.4: Verify frontend compiles**

```bash
cd frontend && npm run build 2>&1 | tail -30
```

Fix any TypeScript errors reported.

- [ ] **Step 8.5: Final commit**

```bash
git add -A
git commit -m "feat: Gmail Classifier plugin — complete implementation"
```

---

## Self-Review Against Spec

| Spec requirement | Covered by |
|---|---|
| Create categories with name + description | Task 3 router + Task 5 CategoryManager |
| Category color + icon | DB schema + CategoryManager form |
| AI reads emails from a chosen date | GmailBatchProcessor.process() + `/process` endpoint |
| AI classifies into categories | `_classify()` method with LLM + JSON parsing |
| Fallback to "Otros" | `_upsert()` uses `otros_id` as default; Otros seeded in migration |
| Tab per category + "Todo" tab | CategoryTabs component |
| Split view (list + detail panel) | EmailList + EmailDetail side-by-side in page.tsx |
| Mark as read / unread | `/emails/{id}/read` + UI buttons in EmailDetail |
| Thread tracking (is_replied) | `_fetch_details()` checks last thread sender |
| Reply from detail panel | EmailDetail reply composer + `/emails/{id}/reply` |
| Recategorize from detail panel | Category dropdown in EmailDetail |
| Manual trigger (button + date) | Toolbar in page.tsx + `/process` POST |
| Auto cron trigger | `GmailClassifierPlugin._cron_loop()` + `/cron` endpoints |
| Plugin settings (mark read, apply label, cron) | PluginSettings modal + `/settings` endpoints |
| Plugin auto-discovered | `PLUGIN` singleton + `load_builtin_plugins()` pattern |
| Progress in real-time | `ProcessingProgress` + status polling |
