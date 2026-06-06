# Email Auto-Reply con Aprendizaje Semántico — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar sugerencia automática de respuestas al clasificador de Gmail, con aprendizaje semántico (RAG) que mejora las sugerencias conforme el usuario edita y envía correos.

**Architecture:** Dos módulos nuevos (`AutoReplyGenerator`, `ReplyLearningManager`) en el plugin `gmail_classifier`. `AutoReplyGenerator` evalúa elegibilidad, busca ejemplos similares vía embeddings + cosine similarity, y llama al LLM. `ReplyLearningManager` guarda ejemplos aprendidos cuando el usuario envía o guarda borrador. El frontend muestra el resultado en `EmailDetail.tsx` (spinner + badge "Sugerencia IA") y los toggles en `PluginSettings.tsx`.

**Tech Stack:** Python/FastAPI (backend), aiosqlite, sentence-transformers (embeddings), numpy (cosine similarity), Gmail Drafts API, Next.js/React (frontend).

---

## File Map

| Acción | Archivo |
|---|---|
| Modify | `src/openacm/storage/database.py` — migraciones 24, 25, 26; bump `_SCHEMA_VERSION = 26` |
| Modify | `src/openacm/plugins/gmail_classifier/processor.py` — añadir `thread_last_sender_email` al fetch |
| Create | `src/openacm/plugins/gmail_classifier/auto_reply.py` |
| Create | `src/openacm/plugins/gmail_classifier/reply_learning.py` |
| Modify | `src/openacm/plugins/gmail_classifier/__init__.py` — seed settings, wire módulos |
| Modify | `src/openacm/plugins/gmail_classifier/router.py` — 6 endpoints nuevos + extender /reply |
| Modify | `frontend/app/gmail-classifier/components/EmailDetail.tsx` |
| Modify | `frontend/app/gmail-classifier/components/PluginSettings.tsx` |
| Create | `tests/unit/test_auto_reply.py` |
| Create | `tests/unit/test_reply_learning.py` |
| Create | `tests/integration/test_autoreply_flow.py` |

---

## Task 1: DB Migrations 24–26

**Files:**
- Modify: `src/openacm/storage/database.py`
- Test: `tests/unit/test_gmail_classifier.py`

- [ ] **Step 1: Bump `_SCHEMA_VERSION` y añadir las tres migraciones**

En `src/openacm/storage/database.py`:

```python
# Cambiar:
_SCHEMA_VERSION = 23
# Por:
_SCHEMA_VERSION = 26
```

Después del bloque `if current < 23:` (línea ~778), añadir:

```python
        if current < 24:
            for col, default in (
                ("thread_last_sender_email", "''"),
                ("ai_suggestion",            "''"),
            ):
                try:
                    await self._db.execute(
                        f"ALTER TABLE gmail_emails ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}"
                    )
                except Exception:
                    pass  # column already exists
            log.info("Migration 24: added thread_last_sender_email, ai_suggestion to gmail_emails")

        if current < 25:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS gmail_reply_drafts (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id       INTEGER NOT NULL UNIQUE REFERENCES gmail_emails(id),
                    gmail_draft_id TEXT    NOT NULL DEFAULT '',
                    draft_body     TEXT    NOT NULL DEFAULT '',
                    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            log.info("Migration 25: created gmail_reply_drafts table")

        if current < 26:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS gmail_reply_examples (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id         INTEGER NOT NULL REFERENCES gmail_categories(id),
                    source_email_id     INTEGER,
                    subtype_label       TEXT    NOT NULL DEFAULT '',
                    email_context       TEXT    NOT NULL DEFAULT '',
                    original_suggestion TEXT    NOT NULL DEFAULT '',
                    final_response      TEXT    NOT NULL DEFAULT '',
                    embedding           BLOB,
                    use_count           INTEGER NOT NULL DEFAULT 0,
                    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_reply_examples_category
                    ON gmail_reply_examples(category_id);
                CREATE INDEX IF NOT EXISTS idx_reply_examples_source
                    ON gmail_reply_examples(source_email_id);
            """)
            log.info("Migration 26: created gmail_reply_examples table")
```

- [ ] **Step 2: Escribir tests de migración**

Añadir al final de `tests/unit/test_gmail_classifier.py`:

```python
@pytest.mark.asyncio
async def test_migration_24_columns_exist(db):
    """Migration 24 adds thread_last_sender_email and ai_suggestion."""
    cursor = await db._db.execute("PRAGMA table_info(gmail_emails)")
    cols = {row["name"] for row in await cursor.fetchall()}
    assert "thread_last_sender_email" in cols
    assert "ai_suggestion" in cols


@pytest.mark.asyncio
async def test_migration_25_reply_drafts_table(db):
    """Migration 25 creates gmail_reply_drafts."""
    cursor = await db._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='gmail_reply_drafts'"
    )
    assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_migration_26_reply_examples_table(db):
    """Migration 26 creates gmail_reply_examples."""
    cursor = await db._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='gmail_reply_examples'"
    )
    assert await cursor.fetchone() is not None
```

- [ ] **Step 3: Correr tests de migración y verificar que pasan**

```
pytest tests/unit/test_gmail_classifier.py::test_migration_24_columns_exist tests/unit/test_gmail_classifier.py::test_migration_25_reply_drafts_table tests/unit/test_gmail_classifier.py::test_migration_26_reply_examples_table -v
```

Esperado: 3 PASSED

- [ ] **Step 4: Commit**

```bash
git add src/openacm/storage/database.py tests/unit/test_gmail_classifier.py
git commit -m "feat: DB migrations 24-26 — reply drafts, examples, thread_last_sender_email"
```

---

## Task 2: Actualizar Processor — `thread_last_sender_email`

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/processor.py`

- [ ] **Step 1: Añadir `thread_last_sender_email` al dict de email en `_fetch_details`**

En `processor.py`, dentro del bloque `try:` de `_fetch_details` (alrededor de línea 344), cambiar:

```python
                # Antes (bloque emails.append):
                emails.append({
                    "gmail_id": msg_id,
                    "thread_id": thread_id,
                    "subject": headers.get("Subject", "(sin asunto)"),
                    "sender_name": sender_name,
                    "sender_email": sender_email,
                    "snippet": msg.get("snippet", "")[:200],
                    "body_text": body_text,
                    "body_html": body_html,
                    "is_read": is_read,
                    "is_replied": is_replied,
                    "received_at": _internaldate_to_iso(msg.get("internalDate", "0")),
                })
```

Por:

```python
                emails.append({
                    "gmail_id": msg_id,
                    "thread_id": thread_id,
                    "subject": headers.get("Subject", "(sin asunto)"),
                    "sender_name": sender_name,
                    "sender_email": sender_email,
                    "snippet": msg.get("snippet", "")[:200],
                    "body_text": body_text,
                    "body_html": body_html,
                    "is_read": is_read,
                    "is_replied": is_replied,
                    "thread_last_sender_email": last_email if 'last_email' in dir() else "",
                    "received_at": _internaldate_to_iso(msg.get("internalDate", "0")),
                })
```

Nota: `last_email` ya está definida en el bloque `try:` que detecta `is_replied`. Si ese bloque falla, `last_email` no está en scope — usar `.get` pattern en su lugar. El bloque correcto queda:

```python
                is_replied = 0
                last_email = ""
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
```

Y en `emails.append`:

```python
                    "thread_last_sender_email": last_email,
```

- [ ] **Step 2: Actualizar `_upsert` para incluir `thread_last_sender_email`**

En `_upsert` (alrededor de línea 508), la query INSERT debe incluir la nueva columna:

```python
            await self._db._db.execute(
                """
                INSERT INTO gmail_emails
                    (gmail_id, thread_id, subject, sender_name, sender_email,
                     snippet, body_text, body_html, category_id, is_read, is_replied,
                     ai_classified, thread_last_sender_email, received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(gmail_id) DO UPDATE SET
                    thread_id                 = excluded.thread_id,
                    subject                   = excluded.subject,
                    sender_name               = excluded.sender_name,
                    sender_email              = excluded.sender_email,
                    snippet                   = excluded.snippet,
                    body_text                 = excluded.body_text,
                    body_html                 = excluded.body_html,
                    is_read                   = CASE WHEN manual_override=1 THEN gmail_emails.is_read ELSE excluded.is_read END,
                    is_replied                = excluded.is_replied,
                    thread_last_sender_email  = excluded.thread_last_sender_email,
                    last_synced               = CURRENT_TIMESTAMP
                """,
                (
                    email["gmail_id"], email["thread_id"], email["subject"],
                    email["sender_name"], email["sender_email"],
                    email["snippet"], email["body_text"], email["body_html"],
                    cat_id, email["is_read"], email["is_replied"],
                    email.get("thread_last_sender_email", ""),
                    email["received_at"],
                ),
            )
```

Nota: Hay que leer el `_upsert` completo actual para confirmar el ON CONFLICT SET existente antes de modificarlo, para no borrar columnas que ya están siendo actualizadas (como `manual_override`). Conservar el condicional `category_id = CASE WHEN manual_override=1 THEN ...` si ya existe.

- [ ] **Step 3: Correr tests existentes del processor para verificar que no rompimos nada**

```
pytest tests/unit/test_gmail_classifier.py -v
```

Esperado: todos PASSED

- [ ] **Step 4: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/processor.py
git commit -m "feat: track thread_last_sender_email in gmail processor upsert"
```

---

## Task 3: `auto_reply.py` — Tests primero

**Files:**
- Create: `tests/unit/test_auto_reply.py`
- Create: `src/openacm/plugins/gmail_classifier/auto_reply.py`

- [ ] **Step 1: Crear el archivo de tests con los 7 casos de elegibilidad**

Crear `tests/unit/test_auto_reply.py`:

```python
"""Unit tests for AutoReplyGenerator eligibility rules and noreply detection."""
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _seed_category(db, category_id: int = 1):
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (id, name, description, color, icon) "
        "VALUES (?, 'Test', 'desc', '#fff', 'Tag')",
        (category_id,),
    )
    await db._db.commit()


async def _seed_email(db, email_id: int = 1, **kwargs):
    defaults = {
        "gmail_id": f"gmail_{email_id}",
        "sender_email": "sender@example.com",
        "thread_last_sender_email": "sender@example.com",
        "is_replied": 0,
        "category_id": 1,
        "body_text": "Hola, quisiera información sobre mi apartamento.",
        "subject": "Consulta",
    }
    defaults.update(kwargs)
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_emails "
        "(id, gmail_id, sender_email, thread_last_sender_email, is_replied, "
        "category_id, body_text, subject) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            email_id,
            defaults["gmail_id"],
            defaults["sender_email"],
            defaults["thread_last_sender_email"],
            defaults["is_replied"],
            defaults["category_id"],
            defaults["body_text"],
            defaults["subject"],
        ),
    )
    await db._db.commit()


async def _enable_autoreply(db, category_id: int = 1):
    await db._db.execute(
        "INSERT INTO gmail_classifier_settings (key, value) VALUES ('autoreply_enabled_categories', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps([category_id]),),
    )
    await db._db.commit()


# ─── Noreply detection ────────────────────────────────────────────────────────

def test_is_noreply_detects_standard_patterns():
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    gen = AutoReplyGenerator(db=None, llm_router=None)
    assert gen._is_noreply("noreply@example.com") is True
    assert gen._is_noreply("no-reply@example.com") is True
    assert gen._is_noreply("donotreply@company.co") is True
    assert gen._is_noreply("mailer-daemon@gmail.com") is True
    assert gen._is_noreply("bounce@mail.example.com") is True
    assert gen._is_noreply("notifications@github.com") is True


def test_is_noreply_case_insensitive():
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    gen = AutoReplyGenerator(db=None, llm_router=None)
    assert gen._is_noreply("NOREPLY@EXAMPLE.COM") is True
    assert gen._is_noreply("No-Reply@Example.com") is True


def test_is_noreply_does_not_flag_real_senders():
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    gen = AutoReplyGenerator(db=None, llm_router=None)
    assert gen._is_noreply("support@example.com") is False
    assert gen._is_noreply("info@company.com") is False
    assert gen._is_noreply("jeison@gmail.com") is False


# ─── Eligibility rules ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_returns_none_when_category_not_enabled(db):
    """Returns None if category has no auto-reply toggle."""
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    await _seed_category(db)
    await _seed_email(db)
    # Do NOT call _enable_autoreply → category 1 not in enabled list
    gen = AutoReplyGenerator(db=db, llm_router=AsyncMock())
    result = await gen.generate(email_id=1)
    assert result is None


@pytest.mark.asyncio
async def test_generate_returns_none_when_is_replied(db):
    """Returns None if email already has is_replied=1."""
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    await _seed_category(db)
    await _seed_email(db, is_replied=1)
    await _enable_autoreply(db)
    gen = AutoReplyGenerator(db=db, llm_router=AsyncMock(), authed_email="me@test.com")
    result = await gen.generate(email_id=1)
    assert result is None


@pytest.mark.asyncio
async def test_generate_returns_none_when_user_is_last_sender(db):
    """Returns None if authenticated user sent the last thread message."""
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    await _seed_category(db)
    await _seed_email(db, thread_last_sender_email="me@test.com")
    await _enable_autoreply(db)
    gen = AutoReplyGenerator(db=db, llm_router=AsyncMock(), authed_email="me@test.com")
    result = await gen.generate(email_id=1)
    assert result is None


@pytest.mark.asyncio
async def test_generate_returns_none_for_noreply_sender(db):
    """Returns None if sender_email matches a noreply pattern."""
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    await _seed_category(db)
    await _seed_email(db, sender_email="noreply@example.com")
    await _enable_autoreply(db)
    gen = AutoReplyGenerator(db=db, llm_router=AsyncMock(), authed_email="me@test.com")
    result = await gen.generate(email_id=1)
    assert result is None


@pytest.mark.asyncio
async def test_generate_returns_existing_draft_without_llm_call(db):
    """If a draft exists, returns it without calling the LLM."""
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    await _seed_category(db)
    await _seed_email(db)
    await _enable_autoreply(db)
    await db._db.execute(
        "INSERT INTO gmail_reply_drafts (email_id, gmail_draft_id, draft_body) VALUES (1, 'draft_123', 'Borrador previo.')"
    )
    await db._db.commit()
    llm = AsyncMock()
    gen = AutoReplyGenerator(db=db, llm_router=llm, authed_email="me@test.com")
    result = await gen.generate(email_id=1)
    assert result == {"body": "Borrador previo.", "from_draft": True}
    llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_generate_calls_llm_and_returns_suggestion(db):
    """For an eligible email with no draft, calls LLM and returns suggestion."""
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    await _seed_category(db)
    await _seed_email(db)
    await _enable_autoreply(db)
    llm = AsyncMock()
    llm.chat.return_value = {"content": "Estimado usuario, con gusto le ayudamos."}
    gen = AutoReplyGenerator(db=db, llm_router=llm, authed_email="me@test.com")
    with patch("openacm.plugins.gmail_classifier.auto_reply.AutoReplyGenerator._get_similar_examples", return_value=[]):
        result = await gen.generate(email_id=1)
    assert result == {"body": "Estimado usuario, con gusto le ayudamos.", "from_draft": False}
    llm.chat.assert_called_once()


@pytest.mark.asyncio
async def test_generate_persists_ai_suggestion_to_db(db):
    """After generating, ai_suggestion is saved on the email row."""
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    await _seed_category(db)
    await _seed_email(db)
    await _enable_autoreply(db)
    llm = AsyncMock()
    llm.chat.return_value = {"content": "Respuesta generada."}
    gen = AutoReplyGenerator(db=db, llm_router=llm, authed_email="me@test.com")
    with patch("openacm.plugins.gmail_classifier.auto_reply.AutoReplyGenerator._get_similar_examples", return_value=[]):
        await gen.generate(email_id=1)
    cursor = await db._db.execute("SELECT ai_suggestion FROM gmail_emails WHERE id = 1")
    row = await cursor.fetchone()
    assert row["ai_suggestion"] == "Respuesta generada."
```

- [ ] **Step 2: Correr tests para verificar que fallan (módulo no existe aún)**

```
pytest tests/unit/test_auto_reply.py -v
```

Esperado: `ImportError` o `ModuleNotFoundError` — FAIL en todos

- [ ] **Step 3: Crear `auto_reply.py` con `AutoReplyGenerator`**

Crear `src/openacm/plugins/gmail_classifier/auto_reply.py`:

```python
"""AutoReplyGenerator — generates AI reply suggestions for eligible emails."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

log = structlog.get_logger()

NOREPLY_PATTERNS = (
    "noreply@", "no-reply@", "donotreply@",
    "notifications@", "mailer-daemon@", "bounce@",
)


class AutoReplyGenerator:
    def __init__(self, db: Any, llm_router: Any, authed_email: str = ""):
        self._db = db
        self._llm = llm_router
        self._authed_email = authed_email

    def _is_noreply(self, sender_email: str) -> bool:
        e = (sender_email or "").lower().strip()
        return any(e.startswith(p) for p in NOREPLY_PATTERNS)

    async def _get_authed_email(self) -> str:
        if self._authed_email:
            return self._authed_email
        try:
            from openacm.plugins.gmail_classifier.processor import (
                _get_gmail_service, _get_authenticated_email,
            )
            svc = await _get_gmail_service()
            self._authed_email = await _get_authenticated_email(svc)
        except Exception:
            self._authed_email = ""
        return self._authed_email

    async def _enabled_categories(self) -> list[int]:
        if self._db is None:
            return []
        cursor = await self._db._db.execute(
            "SELECT value FROM gmail_classifier_settings "
            "WHERE key = 'autoreply_enabled_categories'"
        )
        row = await cursor.fetchone()
        if not row or not row["value"]:
            return []
        try:
            return json.loads(row["value"])
        except Exception:
            return []

    async def generate(self, email_id: int) -> dict | None:
        """Return {"body": str, "from_draft": bool} or None if not eligible."""
        cursor = await self._db._db.execute(
            "SELECT id, sender_email, thread_last_sender_email, is_replied, "
            "category_id, body_text, subject "
            "FROM gmail_emails WHERE id = ?",
            (email_id,),
        )
        email = await cursor.fetchone()
        if not email:
            return None

        enabled = await self._enabled_categories()
        if email["category_id"] not in enabled:
            return None

        if email["is_replied"]:
            return None

        authed = await self._get_authed_email()
        if authed and (email["thread_last_sender_email"] or "").lower() == authed.lower():
            return None

        if self._is_noreply(email["sender_email"]):
            return None

        draft_cursor = await self._db._db.execute(
            "SELECT draft_body FROM gmail_reply_drafts WHERE email_id = ?",
            (email_id,),
        )
        draft_row = await draft_cursor.fetchone()
        if draft_row:
            return {"body": draft_row["draft_body"], "from_draft": True}

        suggestion = await self._generate_suggestion(email_id, email)
        if suggestion:
            await self._db._db.execute(
                "UPDATE gmail_emails SET ai_suggestion = ? WHERE id = ?",
                (suggestion, email_id),
            )
            await self._db._db.commit()
            return {"body": suggestion, "from_draft": False}
        return None

    async def _generate_suggestion(self, email_id: int, email: Any) -> str | None:
        examples = await self._get_similar_examples(
            email["category_id"], email["body_text"]
        )

        cat_cursor = await self._db._db.execute(
            "SELECT name, description, context FROM gmail_categories WHERE id = ?",
            (email["category_id"],),
        )
        cat = await cat_cursor.fetchone()
        cat_name = cat["name"] if cat else ""
        cat_desc = cat["description"] if cat else ""
        cat_ctx = (cat["context"] if cat else "") or ""

        few_shot = ""
        if examples:
            parts = [
                f"Correo similar ({ex['subtype_label']}):\n"
                f"Original: {ex['email_context']}\n"
                f"Respuesta correcta: {ex['final_response']}"
                for ex in examples
            ]
            few_shot = "\n\n".join(parts) + "\n\n---\n\n"

        prompt = (
            f"Eres un asistente que redacta respuestas de correo profesionales.\n"
            f"Categoría: {cat_name} — {cat_desc}\n"
            f"{('Contexto: ' + cat_ctx + chr(10)) if cat_ctx else ''}"
            f"\n{few_shot}"
            f"Redacta una respuesta profesional para el siguiente correo. "
            f"Devuelve SOLO el cuerpo de la respuesta, sin asunto.\n\n"
            f"Asunto: {email['subject']}\n"
            f"Correo:\n{(email['body_text'] or '')[:3000]}"
        )

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}]
            )
            return (response.get("content") or "").strip() or None
        except Exception as exc:
            log.warning("AutoReply LLM call failed", error=str(exc))
            return None

    async def _get_similar_examples(
        self, category_id: int, body_text: str
    ) -> list[dict]:
        if not (body_text or "").strip():
            return []

        try:
            from openacm.core.local_router import LocalRouter
            model = LocalRouter._model
            if model is None:
                return []
        except Exception:
            return []

        try:
            import numpy as np
            loop = asyncio.get_event_loop()
            query_emb = await loop.run_in_executor(
                None,
                lambda: model.encode(
                    body_text[:2000], convert_to_numpy=True, show_progress_bar=False
                ),
            )
        except Exception as exc:
            log.warning("AutoReply embedding failed", error=str(exc))
            return []

        cursor = await self._db._db.execute(
            "SELECT subtype_label, email_context, final_response, embedding "
            "FROM gmail_reply_examples "
            "WHERE category_id = ? AND embedding IS NOT NULL",
            (category_id,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return []

        import numpy as np
        scored: list[tuple[float, dict]] = []
        for row in rows:
            try:
                stored = np.frombuffer(row["embedding"], dtype=np.float32)
                norm = np.linalg.norm(query_emb) * np.linalg.norm(stored)
                sim = float(np.dot(query_emb, stored) / (norm + 1e-9))
                scored.append((sim, dict(row)))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ex for _, ex in scored[:3]]
```

- [ ] **Step 4: Correr tests y verificar que pasan**

```
pytest tests/unit/test_auto_reply.py -v
```

Esperado: todos PASSED

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/auto_reply.py tests/unit/test_auto_reply.py
git commit -m "feat: AutoReplyGenerator — eligibility rules + RAG semantic suggestion"
```

---

## Task 4: `reply_learning.py` — Tests primero

**Files:**
- Create: `tests/unit/test_reply_learning.py`
- Create: `src/openacm/plugins/gmail_classifier/reply_learning.py`

- [ ] **Step 1: Crear tests**

Crear `tests/unit/test_reply_learning.py`:

```python
"""Unit tests for ReplyLearningManager."""
import json
import pytest
from unittest.mock import AsyncMock, patch


async def _seed_base(db):
    """Insert one category and one email."""
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (id, name, description, color, icon) "
        "VALUES (1, 'Test', 'desc', '#fff', 'Tag')"
    )
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_emails "
        "(id, gmail_id, sender_email, category_id, body_text, subject, ai_suggestion) "
        "VALUES (1, 'gid1', 'user@ex.com', 1, 'Quiero mi estado de cuenta', 'Estado de cuenta', '')"
    )
    await db._db.commit()


@pytest.mark.asyncio
async def test_learn_saves_example_when_user_modified(db):
    """If final_body differs from ai_suggestion, saves a new example."""
    from openacm.plugins.gmail_classifier.reply_learning import ReplyLearningManager
    await _seed_base(db)
    await db._db.execute(
        "UPDATE gmail_emails SET ai_suggestion = 'Respuesta genérica.' WHERE id = 1"
    )
    await db._db.commit()

    mgr = ReplyLearningManager(db=db, llm_router=AsyncMock())
    mgr._llm.chat.return_value = {"content": "solicitud de estado de cuenta"}

    with patch.object(mgr, "_generate_embedding", return_value=b"\x00" * 16):
        await mgr.learn(email_id=1, final_body="Estimado señor, para el estado de cuenta necesitamos cédula.")

    cursor = await db._db.execute("SELECT COUNT(*) as n FROM gmail_reply_examples")
    row = await cursor.fetchone()
    assert row["n"] == 1


@pytest.mark.asyncio
async def test_learn_is_idempotent(db):
    """Calling learn twice for the same email_id only saves one example."""
    from openacm.plugins.gmail_classifier.reply_learning import ReplyLearningManager
    await _seed_base(db)
    mgr = ReplyLearningManager(db=db, llm_router=AsyncMock())
    mgr._llm.chat.return_value = {"content": "solicitud"}

    with patch.object(mgr, "_generate_embedding", return_value=b"\x00" * 16):
        await mgr.learn(email_id=1, final_body="Respuesta uno.")
        await mgr.learn(email_id=1, final_body="Respuesta diferente.")

    cursor = await db._db.execute("SELECT COUNT(*) as n FROM gmail_reply_examples")
    row = await cursor.fetchone()
    assert row["n"] == 1


@pytest.mark.asyncio
async def test_learn_increments_use_count_when_not_modified(db):
    """If final_body == ai_suggestion, increments use_count on existing examples."""
    from openacm.plugins.gmail_classifier.reply_learning import ReplyLearningManager
    await _seed_base(db)
    await db._db.execute(
        "UPDATE gmail_emails SET ai_suggestion = 'Respuesta exacta.' WHERE id = 1"
    )
    # Pre-seed an example for this category
    await db._db.execute(
        "INSERT INTO gmail_reply_examples (category_id, subtype_label, email_context, "
        "original_suggestion, final_response, use_count) "
        "VALUES (1, 'solicitud', 'ctx', 'sug', 'Respuesta exacta.', 0)"
    )
    await db._db.commit()

    mgr = ReplyLearningManager(db=db, llm_router=AsyncMock())
    await mgr.learn(email_id=1, final_body="Respuesta exacta.")

    cursor = await db._db.execute("SELECT use_count FROM gmail_reply_examples WHERE category_id = 1")
    row = await cursor.fetchone()
    assert row["use_count"] == 1


@pytest.mark.asyncio
async def test_learn_skips_empty_final_body(db):
    """Empty final_body should not save any example."""
    from openacm.plugins.gmail_classifier.reply_learning import ReplyLearningManager
    await _seed_base(db)
    mgr = ReplyLearningManager(db=db, llm_router=AsyncMock())
    await mgr.learn(email_id=1, final_body="   ")

    cursor = await db._db.execute("SELECT COUNT(*) as n FROM gmail_reply_examples")
    row = await cursor.fetchone()
    assert row["n"] == 0


def test_text_similar_same_text():
    from openacm.plugins.gmail_classifier.reply_learning import _text_similar
    assert _text_similar("Hola mundo.", "Hola mundo.") is True


def test_text_similar_different_text():
    from openacm.plugins.gmail_classifier.reply_learning import _text_similar
    assert _text_similar(
        "Respuesta genérica del sistema.",
        "Estimado señor, para el estado de cuenta necesitamos su cédula, torre y apartamento."
    ) is False
```

- [ ] **Step 2: Correr tests para verificar que fallan**

```
pytest tests/unit/test_reply_learning.py -v
```

Esperado: `ImportError` — FAIL en todos

- [ ] **Step 3: Crear `reply_learning.py`**

Crear `src/openacm/plugins/gmail_classifier/reply_learning.py`:

```python
"""ReplyLearningManager — saves learned reply examples when user sends or drafts."""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

import structlog

log = structlog.get_logger()

_SIMILARITY_THRESHOLD = 0.95


def _text_similar(a: str, b: str, threshold: float = _SIMILARITY_THRESHOLD) -> bool:
    """True if texts are similar enough that the user didn't meaningfully edit."""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold


class ReplyLearningManager:
    def __init__(self, db: Any, llm_router: Any):
        self._db = db
        self._llm = llm_router

    async def learn(self, email_id: int, final_body: str) -> None:
        """Learn from the user's sent/drafted reply. Idempotent per email_id."""
        final_body = (final_body or "").strip()
        if not final_body:
            return

        cursor = await self._db._db.execute(
            "SELECT ai_suggestion, body_text, subject, category_id "
            "FROM gmail_emails WHERE id = ?",
            (email_id,),
        )
        email = await cursor.fetchone()
        if not email:
            return

        # Idempotency check
        dup = await self._db._db.execute(
            "SELECT id FROM gmail_reply_examples WHERE source_email_id = ?",
            (email_id,),
        )
        if await dup.fetchone():
            return

        ai_suggestion = (email["ai_suggestion"] or "").strip()

        if _text_similar(ai_suggestion, final_body):
            await self._increment_use_count(email["category_id"])
        else:
            await self._save_example(
                email_id=email_id,
                category_id=email["category_id"],
                email_context=f"Asunto: {email['subject']}\n{(email['body_text'] or '')[:1000]}",
                original_suggestion=ai_suggestion,
                final_response=final_body,
                body_text=email["body_text"] or "",
            )

    async def _save_example(
        self,
        email_id: int,
        category_id: int,
        email_context: str,
        original_suggestion: str,
        final_response: str,
        body_text: str,
    ) -> None:
        subtype = await self._classify_subtype(email_context)
        embedding_blob = await self._generate_embedding(body_text)

        await self._db._db.execute(
            "INSERT INTO gmail_reply_examples "
            "(category_id, source_email_id, subtype_label, email_context, "
            "original_suggestion, final_response, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                category_id, email_id, subtype, email_context,
                original_suggestion, final_response, embedding_blob,
            ),
        )
        await self._db._db.commit()
        log.info("AutoReply: learned new example", email_id=email_id, subtype=subtype)

    async def _classify_subtype(self, email_context: str) -> str:
        prompt = (
            "Identifica el tipo de solicitud de este correo en 3-6 palabras clave en español.\n"
            "Responde SOLO con el tipo, sin explicación.\n"
            "Ejemplos: 'solicitud de estado de cuenta', 'reclamo de pago', 'solicitud de certificado'\n\n"
            f"Correo:\n{email_context[:1000]}"
        )
        try:
            response = await self._llm.chat(messages=[{"role": "user", "content": prompt}])
            return ((response.get("content") or "").strip())[:100] or "sin clasificar"
        except Exception:
            return "sin clasificar"

    async def _generate_embedding(self, body_text: str) -> bytes | None:
        if not (body_text or "").strip():
            return None
        try:
            from openacm.core.local_router import LocalRouter
            import asyncio
            model = LocalRouter._model
            if model is None:
                return None
            loop = asyncio.get_event_loop()
            emb = await loop.run_in_executor(
                None,
                lambda: model.encode(
                    body_text[:2000], convert_to_numpy=True, show_progress_bar=False
                ),
            )
            return emb.astype("float32").tobytes()
        except Exception as exc:
            log.warning("ReplyLearning embedding failed", error=str(exc))
            return None

    async def _increment_use_count(self, category_id: int) -> None:
        """Increment use_count on all examples for the given category."""
        await self._db._db.execute(
            "UPDATE gmail_reply_examples SET use_count = use_count + 1 "
            "WHERE category_id = ?",
            (category_id,),
        )
        await self._db._db.commit()
```

- [ ] **Step 4: Correr tests y verificar que pasan**

```
pytest tests/unit/test_reply_learning.py -v
```

Esperado: todos PASSED

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/reply_learning.py tests/unit/test_reply_learning.py
git commit -m "feat: ReplyLearningManager — save examples + increment use_count + idempotency"
```

---

## Task 5: Wire Modules en Plugin + Nuevos Router Endpoints

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/__init__.py`
- Modify: `src/openacm/plugins/gmail_classifier/router.py`

- [ ] **Step 1: Añadir singletons y seed en `__init__.py`**

En `GmailClassifierPlugin.on_start()`, después de `_router_mod._processor = self._processor`, añadir:

```python
        from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
        from openacm.plugins.gmail_classifier.reply_learning import ReplyLearningManager

        auto_reply = AutoReplyGenerator(db=database, llm_router=llm_router)
        learning = ReplyLearningManager(db=database, llm_router=llm_router)
        _router_mod._auto_reply = auto_reply
        _router_mod._learning = learning
```

Y en el bloque de `defaults` del seed de settings, añadir las dos nuevas keys:

```python
            defaults = {
                "auto_mark_read": "false",
                "auto_apply_label": "false",
                "cron_schedule": "",
                "since_date_default": "",
                "autoreply_enabled_categories": "[]",
                "autoreply_model": "",
            }
```

- [ ] **Step 2: Añadir singletons y Pydantic models en `router.py`**

Al inicio de `router.py`, después de `_processor: Any = None`, añadir:

```python
_auto_reply: Any = None
_learning: Any = None
```

Añadir helpers:

```python
def _require_auto_reply():
    if _auto_reply is None:
        raise HTTPException(status_code=503, detail="AutoReply not initialized")
    return _auto_reply

def _require_learning():
    if _learning is None:
        raise HTTPException(status_code=503, detail="ReplyLearning not initialized")
    return _learning
```

Extender `SettingsBody` para incluir las nuevas keys. Buscar la clase existente y añadir los campos:

```python
class SettingsBody(BaseModel):
    auto_mark_read: str | None = None
    auto_apply_label: str | None = None
    cron_schedule: str | None = None
    since_date_default: str | None = None
    autoreply_enabled_categories: str | None = None  # ← nuevo (JSON array string)
    autoreply_model: str | None = None               # ← nuevo
```

Añadir también los nuevos Pydantic models después de `SettingsBody`:

```python
class DraftBody(BaseModel):
    body: str

class ReplyExampleUpdate(BaseModel):
    subtype_label: str | None = None
    final_response: str | None = None
```

- [ ] **Step 3: Añadir los 6 nuevos endpoints en `router.py`**

Añadir después del endpoint `reply_email` existente:

```python
# ─── Auto-reply ───────────────────────────────────────────────────────────────

@router.get("/emails/{email_id}/suggest-reply")
async def suggest_reply(email_id: int):
    gen = _require_auto_reply()
    result = await gen.generate(email_id=email_id)
    if result is None:
        return {"eligible": False}
    return {"eligible": True, **result}


@router.post("/emails/{email_id}/draft")
async def save_draft(email_id: int, body: DraftBody):
    db = _require_db()
    learning = _require_learning()

    cursor = await db._db.execute(
        "SELECT gmail_id, subject, sender_email FROM gmail_emails WHERE id = ?", (email_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Email not found")

    try:
        from openacm.tools.google_services import _get_google_service
        import base64
        from email.mime.text import MIMEText
        service = await _get_google_service("gmail", "v1")

        subject = row["subject"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        message = MIMEText(body.body)
        message["to"] = row["sender_email"]
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        existing = await db._db.execute(
            "SELECT gmail_draft_id FROM gmail_reply_drafts WHERE email_id = ?", (email_id,)
        )
        existing_row = await existing.fetchone()

        if existing_row and existing_row["gmail_draft_id"]:
            draft = service.users().drafts().update(
                userId="me",
                id=existing_row["gmail_draft_id"],
                body={"message": {"raw": raw}},
            ).execute()
        else:
            draft = service.users().drafts().create(
                userId="me", body={"message": {"raw": raw}}
            ).execute()

        draft_id = draft.get("id", "")
        await db._db.execute(
            "INSERT INTO gmail_reply_drafts (email_id, gmail_draft_id, draft_body) "
            "VALUES (?, ?, ?) ON CONFLICT(email_id) DO UPDATE SET "
            "gmail_draft_id = excluded.gmail_draft_id, "
            "draft_body = excluded.draft_body, "
            "updated_at = CURRENT_TIMESTAMP",
            (email_id, draft_id, body.body),
        )
        await db._db.commit()
        await learning.learn(email_id=email_id, final_body=body.body)
        return {"success": True, "draft_id": draft_id}

    except Exception as exc:
        log.error("Failed to save draft", email_id=email_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to save draft: {exc}")


@router.delete("/emails/{email_id}/draft")
async def delete_draft(email_id: int):
    db = _require_db()
    cursor = await db._db.execute(
        "SELECT gmail_draft_id FROM gmail_reply_drafts WHERE email_id = ?", (email_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No draft found for this email")

    try:
        from openacm.tools.google_services import _get_google_service
        service = await _get_google_service("gmail", "v1")
        if row["gmail_draft_id"]:
            service.users().drafts().delete(
                userId="me", id=row["gmail_draft_id"]
            ).execute()
    except Exception as exc:
        log.warning("Failed to delete Gmail draft", error=str(exc))

    await db._db.execute("DELETE FROM gmail_reply_drafts WHERE email_id = ?", (email_id,))
    await db._db.commit()
    return {"deleted": True}


# ─── Reply examples ──────────────────────────────────────────────────────────

@router.get("/reply-examples")
async def list_reply_examples(category_id: int | None = None):
    db = _require_db()
    if category_id is not None:
        cursor = await db._db.execute(
            "SELECT id, category_id, subtype_label, email_context, "
            "final_response, use_count, created_at "
            "FROM gmail_reply_examples WHERE category_id = ? ORDER BY use_count DESC",
            (category_id,),
        )
    else:
        cursor = await db._db.execute(
            "SELECT id, category_id, subtype_label, email_context, "
            "final_response, use_count, created_at "
            "FROM gmail_reply_examples ORDER BY use_count DESC"
        )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@router.put("/reply-examples/{example_id}")
async def update_reply_example(example_id: int, body: ReplyExampleUpdate):
    db = _require_db()
    cursor = await db._db.execute(
        "SELECT id FROM gmail_reply_examples WHERE id = ?", (example_id,)
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Example not found")

    updates: list[str] = []
    params: list = []
    if body.subtype_label is not None:
        updates.append("subtype_label = ?")
        params.append(body.subtype_label)
    if body.final_response is not None:
        updates.append("final_response = ?")
        params.append(body.final_response)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(example_id)
    await db._db.execute(
        f"UPDATE gmail_reply_examples SET {', '.join(updates)} WHERE id = ?", params
    )
    await db._db.commit()
    cursor2 = await db._db.execute(
        "SELECT id, category_id, subtype_label, email_context, final_response, use_count "
        "FROM gmail_reply_examples WHERE id = ?", (example_id,)
    )
    return dict(await cursor2.fetchone())


@router.delete("/reply-examples/{example_id}")
async def delete_reply_example(example_id: int):
    db = _require_db()
    cursor = await db._db.execute(
        "SELECT id FROM gmail_reply_examples WHERE id = ?", (example_id,)
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Example not found")
    await db._db.execute("DELETE FROM gmail_reply_examples WHERE id = ?", (example_id,))
    await db._db.commit()
    return {"deleted": True, "id": example_id}
```

- [ ] **Step 4: Extender `reply_email` para disparar aprendizaje**

En el endpoint existente `reply_email`, después de `await db._db.commit()`, añadir:

```python
        try:
            if _learning:
                await _learning.learn(email_id=email_id, final_body=body.body)
        except Exception as exc:
            log.warning("AutoReply learning failed on send", error=str(exc))
```

- [ ] **Step 5: Correr todos los tests**

```
pytest tests/ -v --tb=short
```

Esperado: todos PASSED

- [ ] **Step 6: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/__init__.py src/openacm/plugins/gmail_classifier/router.py
git commit -m "feat: wire AutoReply + Learning into plugin; add 6 new router endpoints"
```

---

## Task 6: Frontend — `EmailDetail.tsx`

**Files:**
- Modify: `frontend/app/gmail-classifier/components/EmailDetail.tsx`

La lógica de auto-sugerencia requiere saber si la categoría actual tiene auto-reply habilitado. Esto llega desde el padre (`page.tsx`). La interfaz `Email` y `Category` ya existen.

- [ ] **Step 1: Actualizar `EmailDetailProps` e `Email` interface**

En `EmailDetail.tsx`, actualizar la interfaz `Email` para incluir el nuevo campo, y `EmailDetailProps` para recibir las categorías habilitadas:

```typescript
interface Email {
  id: number;
  gmail_id: string;
  thread_id: string;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
  body_text: string;
  body_html: string;
  category_id: number;
  is_read: number;
  is_replied: number;
  received_at: string;
}

interface EmailDetailProps {
  email: Email | null;
  categories: Category[];
  autoReplyCategoryIds: number[];        // ← nuevo
  token: string;                          // ← nuevo (para llamadas a API)
  onReadToggle: (emailId: number, isRead: boolean) => void;
  onRecategorize: (emailId: number, categoryId: number) => void;
  onReply: (emailId: number, body: string) => Promise<boolean>;
}
```

- [ ] **Step 2: Añadir estado de auto-sugerencia al componente**

Dentro de `EmailDetail`, añadir los nuevos estados después de los existentes:

```typescript
  // Auto-reply suggestion state
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const [suggestionLoading, setSuggestionLoading] = useState(false);
  const [suggestionError, setSuggestionError] = useState('');
  const [fromDraft, setFromDraft] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [draftSaved, setDraftSaved] = useState(false);
```

- [ ] **Step 3: Añadir `useEffect` que dispara la sugerencia al abrir un correo**

Añadir después de los estados, antes del `if (!email)` render:

```typescript
  const API = '/api/gmail-classifier';
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  // Trigger auto-suggestion when a new eligible email is selected
  useEffect(() => {
    setSuggestion(null);
    setSuggestionError('');
    setFromDraft(false);
    setDraftSaved(false);
    setReplyText('');

    if (!email || email.is_replied) return;
    if (!autoReplyCategoryIds.includes(email.category_id)) return;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);

    setSuggestionLoading(true);
    fetch(`${API}/emails/${email.id}/suggest-reply`, { headers, signal: controller.signal })
      .then(r => r.json())
      .then(data => {
        if (data.eligible && data.body) {
          setSuggestion(data.body);
          setReplyText(data.body);
          setFromDraft(data.from_draft ?? false);
          setReplyOpen(true);
        }
      })
      .catch(err => {
        if (err.name !== 'AbortError') {
          setSuggestionError('No se pudo generar sugerencia');
        }
      })
      .finally(() => {
        setSuggestionLoading(false);
        clearTimeout(timeout);
      });

    return () => { controller.abort(); clearTimeout(timeout); };
  }, [email?.id]); // eslint-disable-line react-hooks/exhaustive-deps
```

- [ ] **Step 4: Añadir handler para "Guardar como borrador"**

```typescript
  const handleSaveDraft = async () => {
    if (!replyText.trim()) return;
    setSavingDraft(true);
    try {
      const res = await fetch(`${API}/emails/${email!.id}/draft`, {
        method: 'POST', headers, body: JSON.stringify({ body: replyText.trim() }),
      });
      if (!res.ok) throw new Error(await res.text());
      setDraftSaved(true);
      setFromDraft(true);
      setTimeout(() => setDraftSaved(false), 4000);
    } catch {
      setReplyError('Error al guardar borrador.');
    } finally {
      setSavingDraft(false);
    }
  };
```

- [ ] **Step 5: Actualizar la sección de reply composer en el render**

En el JSX, dentro de la sección `{/* ── Reply Composer ── */}` (o donde esté el textarea de reply), reemplazar el area de composer existente. Busca el bloque que contiene `replyOpen` y el `textarea` — reemplazar todo ese bloque por:

```tsx
      {/* ── Reply Composer ────────────────────────────────── */}
      <div className="px-6 py-3 border-t border-[var(--acm-border)] flex-shrink-0">
        {!replyOpen ? (
          <button
            onClick={() => setReplyOpen(true)}
            className="btn-secondary text-[12px] flex items-center gap-1.5"
          >
            <CornerUpLeft size={13} /> Responder
          </button>
        ) : (
          <div className="space-y-2">
            {/* Header row */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-[12px] font-medium text-[var(--acm-fg-2)]">Respuesta</span>
                {suggestionLoading && (
                  <span className="text-[11px] text-[var(--acm-fg-4)] flex items-center gap-1">
                    <span className="inline-block w-3 h-3 border-2 border-[var(--acm-accent)] border-t-transparent rounded-full animate-spin" />
                    Generando respuesta...
                  </span>
                )}
                {suggestion && !suggestionLoading && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--acm-accent)]/15 text-[var(--acm-accent)] font-medium">
                    {fromDraft ? 'Borrador guardado' : 'Sugerencia IA ✦'}
                  </span>
                )}
                {suggestionError && (
                  <span className="text-[11px] text-[var(--acm-fg-4)]">{suggestionError}</span>
                )}
              </div>
              <button onClick={() => setReplyOpen(false)} className="text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors">
                <ChevronUp size={14} />
              </button>
            </div>

            {/* Textarea */}
            <textarea
              value={replyText}
              onChange={e => setReplyText(e.target.value)}
              placeholder="Escribe tu respuesta..."
              rows={6}
              className="w-full bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] px-3 py-2 text-[13px] text-[var(--acm-fg)] placeholder:text-[var(--acm-fg-4)] outline-none focus:border-[var(--acm-accent)] resize-none acm-scroll transition-colors"
            />

            {/* Action buttons */}
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={handleSendReply}
                disabled={sending || !replyText.trim()}
                className="btn-primary text-[12px] disabled:opacity-50"
              >
                {sending ? 'Enviando...' : 'Enviar'}
              </button>
              <button
                onClick={handleSaveDraft}
                disabled={savingDraft || !replyText.trim()}
                className="btn-secondary text-[12px] disabled:opacity-50"
              >
                {savingDraft ? 'Guardando...' : draftSaved ? '✓ Borrador guardado' : 'Guardar como borrador'}
              </button>
              {replySuccess && (
                <span className="text-[12px] text-green-500">Enviado correctamente</span>
              )}
              {replyError && (
                <span className="text-[12px] text-red-400">{replyError}</span>
              )}
            </div>
          </div>
        )}
      </div>
```

- [ ] **Step 6: Actualizar `page.tsx` para pasar `autoReplyCategoryIds` y `token` a `EmailDetail`**

En `frontend/app/gmail-classifier/page.tsx`, buscar donde se renderiza `<EmailDetail` y añadir las nuevas props. Primero, añadir estado de settings con `autoreply_enabled_categories`:

En el componente `GmailClassifierPage`, añadir estado:
```typescript
const [autoReplyCategoryIds, setAutoReplyCategoryIds] = useState<number[]>([]);
```

En el `useEffect` que carga settings (o crear uno nuevo), añadir fetch de la configuración:
```typescript
  useEffect(() => {
    if (!token) return;
    fetch('/api/gmail-classifier/settings', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(data => {
        try {
          setAutoReplyCategoryIds(JSON.parse(data.autoreply_enabled_categories || '[]'));
        } catch { /* ignore */ }
      });
  }, [token]);
```

En el JSX donde se renderiza `<EmailDetail`:
```tsx
<EmailDetail
  email={selectedEmail}
  categories={categories}
  autoReplyCategoryIds={autoReplyCategoryIds}
  token={token}
  onReadToggle={handleReadToggle}
  onRecategorize={handleRecategorize}
  onReply={handleReply}
/>
```

- [ ] **Step 7: Verificar que el frontend compila sin errores de TypeScript**

```
cd frontend && npx tsc --noEmit
```

Esperado: 0 errores

- [ ] **Step 8: Commit**

```bash
git add frontend/app/gmail-classifier/components/EmailDetail.tsx frontend/app/gmail-classifier/page.tsx
git commit -m "feat: EmailDetail auto-suggest UX — spinner, IA badge, save-draft button"
```

---

## Task 7: Frontend — `PluginSettings.tsx` (Pestaña Auto-respuesta)

**Files:**
- Modify: `frontend/app/gmail-classifier/components/PluginSettings.tsx`

- [ ] **Step 1: Añadir estado para categorías, toggles de auto-reply, y ejemplos aprendidos**

En `PluginSettings`, añadir imports y estados:

```typescript
import { useState, useEffect } from 'react';
import { X, Trash2, Pencil, Check } from 'lucide-react';

// Añadir a los estados existentes:
const [activeTab, setActiveTab] = useState<'general' | 'autoreply'>('general');
const [categories, setCategories] = useState<{ id: number; name: string; color: string }[]>([]);
const [autoReplyIds, setAutoReplyIds] = useState<number[]>([]);
const [savingAutoReply, setSavingAutoReply] = useState(false);
const [examples, setExamples] = useState<{
  id: number; category_id: number; subtype_label: string;
  email_context: string; final_response: string; use_count: number;
}[]>([]);
const [examplesLoading, setExamplesLoading] = useState(false);
const [filterCatId, setFilterCatId] = useState<number | null>(null);
const [editingId, setEditingId] = useState<number | null>(null);
const [editSubtype, setEditSubtype] = useState('');
const [editResponse, setEditResponse] = useState('');
```

- [ ] **Step 2: Añadir `useEffect` para cargar categorías, autoreply settings, y ejemplos**

```typescript
  useEffect(() => {
    if (!token) return;
    // Load categories
    fetch(`${API}/categories`, { headers })
      .then(r => r.json())
      .then(setCategories);
    // Load autoreply settings
    fetch(`${API}/settings`, { headers })
      .then(r => r.json())
      .then(data => {
        try {
          setAutoReplyIds(JSON.parse(data.autoreply_enabled_categories || '[]'));
        } catch { /* ignore */ }
      });
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadExamples = () => {
    setExamplesLoading(true);
    const url = filterCatId
      ? `${API}/reply-examples?category_id=${filterCatId}`
      : `${API}/reply-examples`;
    fetch(url, { headers })
      .then(r => r.json())
      .then(setExamples)
      .finally(() => setExamplesLoading(false));
  };

  useEffect(() => {
    if (activeTab === 'autoreply') loadExamples();
  }, [activeTab, filterCatId]); // eslint-disable-line react-hooks/exhaustive-deps
```

- [ ] **Step 3: Añadir handlers de toggle y gestión de ejemplos**

```typescript
  const toggleAutoReply = async (catId: number, enabled: boolean) => {
    const next = enabled
      ? [...autoReplyIds, catId]
      : autoReplyIds.filter(id => id !== catId);
    setAutoReplyIds(next);
    setSavingAutoReply(true);
    await fetch(`${API}/settings`, {
      method: 'PUT', headers,
      body: JSON.stringify({ autoreply_enabled_categories: JSON.stringify(next) }),
    });
    setSavingAutoReply(false);
  };

  const deleteExample = async (id: number) => {
    await fetch(`${API}/reply-examples/${id}`, { method: 'DELETE', headers });
    setExamples(ex => ex.filter(e => e.id !== id));
  };

  const startEdit = (ex: typeof examples[0]) => {
    setEditingId(ex.id);
    setEditSubtype(ex.subtype_label);
    setEditResponse(ex.final_response);
  };

  const saveEdit = async (id: number) => {
    await fetch(`${API}/reply-examples/${id}`, {
      method: 'PUT', headers,
      body: JSON.stringify({ subtype_label: editSubtype, final_response: editResponse }),
    });
    setExamples(ex => ex.map(e =>
      e.id === id ? { ...e, subtype_label: editSubtype, final_response: editResponse } : e
    ));
    setEditingId(null);
  };
```

- [ ] **Step 4: Actualizar el JSX para añadir tabs y la pestaña Auto-respuesta**

Reemplazar el `return (` del componente para añadir tabs en la parte superior del modal:

```tsx
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--acm-card)] rounded-[var(--acm-radius)] border border-[var(--acm-border)] w-full max-w-2xl max-h-[85vh] flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-4 pb-0 flex-shrink-0">
          <div className="flex items-center gap-4">
            <h2 className="text-[14px] font-semibold text-[var(--acm-fg)]">Configuración del plugin</h2>
            <div className="flex gap-1">
              {(['general', 'autoreply'] as const).map(tab => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`text-[12px] px-3 py-1 rounded-[var(--acm-radius)] transition-colors ${
                    activeTab === tab
                      ? 'bg-[var(--acm-accent)]/15 text-[var(--acm-accent)]'
                      : 'text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)]'
                  }`}
                >
                  {tab === 'general' ? 'General' : 'Auto-respuesta'}
                </button>
              ))}
            </div>
          </div>
          <button onClick={onClose} className="text-[var(--acm-fg-4)] hover:text-[var(--acm-fg)] transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="overflow-y-auto acm-scroll flex-1 px-5 py-4">
          {activeTab === 'general' ? (
            /* ── Contenido existente de la pestaña General ── */
            /* (Mover aquí todo el JSX actual del return, desde el primer div de settings hasta el final, sin el header) */
            <>{/* existing settings content here */}</>
          ) : (
            /* ── Pestaña Auto-respuesta ── */
            <div className="space-y-6">

              {/* Activación por categoría */}
              <div>
                <h3 className="text-[13px] font-medium text-[var(--acm-fg)] mb-3">
                  Activación por categoría
                  {savingAutoReply && <span className="text-[11px] text-[var(--acm-fg-4)] ml-2">Guardando...</span>}
                </h3>
                <div className="space-y-2">
                  {categories.filter(c => c.name !== 'Otros').map(cat => (
                    <label key={cat.id} className="flex items-center justify-between p-3 rounded-[var(--acm-radius)] bg-[var(--acm-elev)] cursor-pointer hover:bg-[var(--acm-border)]/30 transition-colors">
                      <div className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: cat.color }} />
                        <span className="text-[13px] text-[var(--acm-fg)]">{cat.name}</span>
                      </div>
                      <input
                        type="checkbox"
                        checked={autoReplyIds.includes(cat.id)}
                        onChange={e => toggleAutoReply(cat.id, e.target.checked)}
                        className="accent-[var(--acm-accent)] w-4 h-4"
                      />
                    </label>
                  ))}
                </div>
              </div>

              {/* Ejemplos aprendidos */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-[13px] font-medium text-[var(--acm-fg)]">Ejemplos aprendidos</h3>
                  <select
                    value={filterCatId ?? ''}
                    onChange={e => setFilterCatId(e.target.value ? Number(e.target.value) : null)}
                    className="bg-[var(--acm-card)] border border-[var(--acm-border)] text-[var(--acm-fg-2)] text-[11px] rounded-[var(--acm-radius)] px-2 py-1 outline-none"
                  >
                    <option value="">Todas las categorías</option>
                    {categories.map(c => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>

                {examplesLoading ? (
                  <p className="text-[12px] text-[var(--acm-fg-4)]">Cargando...</p>
                ) : examples.length === 0 ? (
                  <p className="text-[12px] text-[var(--acm-fg-4)] italic">
                    No hay ejemplos aún. Se aprenden automáticamente cuando envías o guardas borradores.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {examples.map(ex => {
                      const catName = categories.find(c => c.id === ex.category_id)?.name ?? '';
                      return (
                        <div key={ex.id} className="p-3 rounded-[var(--acm-radius)] bg-[var(--acm-elev)] border border-[var(--acm-border)]">
                          {editingId === ex.id ? (
                            <div className="space-y-2">
                              <input
                                value={editSubtype}
                                onChange={e => setEditSubtype(e.target.value)}
                                className="w-full bg-[var(--acm-card)] border border-[var(--acm-border)] rounded px-2 py-1 text-[12px] outline-none focus:border-[var(--acm-accent)]"
                                placeholder="Subtipo"
                              />
                              <textarea
                                value={editResponse}
                                onChange={e => setEditResponse(e.target.value)}
                                rows={3}
                                className="w-full bg-[var(--acm-card)] border border-[var(--acm-border)] rounded px-2 py-1 text-[12px] outline-none focus:border-[var(--acm-accent)] resize-none"
                              />
                              <div className="flex gap-2">
                                <button onClick={() => saveEdit(ex.id)} className="btn-primary text-[11px] flex items-center gap-1"><Check size={12} /> Guardar</button>
                                <button onClick={() => setEditingId(null)} className="btn-secondary text-[11px]">Cancelar</button>
                              </div>
                            </div>
                          ) : (
                            <>
                              <div className="flex items-start justify-between gap-2 mb-1">
                                <div>
                                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--acm-accent)]/10 text-[var(--acm-accent)] mr-1.5">{catName}</span>
                                  <span className="text-[11px] font-medium text-[var(--acm-fg-2)]">{ex.subtype_label}</span>
                                  <span className="text-[10px] text-[var(--acm-fg-4)] ml-2">{ex.use_count} usos</span>
                                </div>
                                <div className="flex gap-1 flex-shrink-0">
                                  <button onClick={() => startEdit(ex)} className="text-[var(--acm-fg-4)] hover:text-[var(--acm-accent)] transition-colors p-1"><Pencil size={12} /></button>
                                  <button onClick={() => deleteExample(ex.id)} className="text-[var(--acm-fg-4)] hover:text-red-400 transition-colors p-1"><Trash2 size={12} /></button>
                                </div>
                              </div>
                              <p className="text-[11px] text-[var(--acm-fg-3)] line-clamp-2">{ex.final_response}</p>
                            </>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
```

**Nota importante:** El JSX existente del tab "General" debe moverse dentro del bloque `activeTab === 'general'`. Lee el archivo actual completo antes de editar para asegurarte de no perder el contenido existente.

- [ ] **Step 5: Verificar que el frontend compila**

```
cd frontend && npx tsc --noEmit
```

Esperado: 0 errores

- [ ] **Step 6: Commit**

```bash
git add frontend/app/gmail-classifier/components/PluginSettings.tsx
git commit -m "feat: PluginSettings — Auto-respuesta tab with category toggles and examples manager"
```

---

## Task 8: Integration Tests

**Files:**
- Create: `tests/integration/test_autoreply_flow.py`

- [ ] **Step 1: Crear el directorio si no existe**

```
mkdir -p tests/integration
```

Crear `tests/integration/__init__.py` vacío si no existe.

- [ ] **Step 2: Crear `test_autoreply_flow.py`**

Crear `tests/integration/test_autoreply_flow.py`:

```python
"""Integration tests for the auto-reply flow: suggest → draft → learn."""
import json
import pytest
from unittest.mock import AsyncMock, patch


async def _seed(db):
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (id, name, description, color, icon) "
        "VALUES (1, 'Legales', 'Correos legales', '#8b5cf6', 'Landmark')"
    )
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_emails "
        "(id, gmail_id, sender_email, thread_last_sender_email, is_replied, "
        "category_id, body_text, subject, ai_suggestion) "
        "VALUES (1, 'gid1', 'usuario@example.com', 'usuario@example.com', 0, "
        "1, 'Por favor envíenme el estado de cuenta de mi apartamento.', 'Estado de cuenta', '')"
    )
    await db._db.execute(
        "INSERT INTO gmail_classifier_settings (key, value) "
        "VALUES ('autoreply_enabled_categories', '[1]') "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    )
    await db._db.commit()


@pytest.mark.asyncio
async def test_full_flow_suggest_edit_draft_learns(db):
    """
    Full flow: suggest-reply → user edits → save-draft → example is saved.
    """
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    from openacm.plugins.gmail_classifier.reply_learning import ReplyLearningManager

    await _seed(db)

    llm = AsyncMock()
    llm.chat.return_value = {"content": "Estimado cliente, con gusto le ayudamos."}

    gen = AutoReplyGenerator(db=db, llm_router=llm, authed_email="agent@company.com")

    with patch.object(gen, "_get_similar_examples", return_value=[]):
        result = await gen.generate(email_id=1)

    assert result is not None
    assert result["from_draft"] is False
    assert "Estimado" in result["body"]

    # Verify ai_suggestion was persisted
    cursor = await db._db.execute("SELECT ai_suggestion FROM gmail_emails WHERE id = 1")
    row = await cursor.fetchone()
    assert row["ai_suggestion"] == "Estimado cliente, con gusto le ayudamos."

    # User edits and saves draft
    edited_reply = (
        "Estimado señor, para poder enviarle el estado de cuenta de su apartamento "
        "necesitamos: número de cédula, torre y número de apartamento. Saludos."
    )

    learn_llm = AsyncMock()
    learn_llm.chat.return_value = {"content": "solicitud de estado de cuenta"}
    mgr = ReplyLearningManager(db=db, llm_router=learn_llm)

    with patch.object(mgr, "_generate_embedding", return_value=b"\x00" * 16):
        await mgr.learn(email_id=1, final_body=edited_reply)

    # Example should be saved
    cursor = await db._db.execute("SELECT * FROM gmail_reply_examples WHERE category_id = 1")
    ex = await cursor.fetchone()
    assert ex is not None
    assert ex["final_response"] == edited_reply
    assert ex["subtype_label"] == "solicitud de estado de cuenta"
    assert ex["source_email_id"] == 1


@pytest.mark.asyncio
async def test_existing_draft_returned_without_llm_call(db):
    """If a draft exists, suggest-reply returns it without calling the LLM."""
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator

    await _seed(db)
    await db._db.execute(
        "INSERT INTO gmail_reply_drafts (email_id, gmail_draft_id, draft_body) "
        "VALUES (1, 'draft_abc', 'Borrador guardado previamente.')"
    )
    await db._db.commit()

    llm = AsyncMock()
    gen = AutoReplyGenerator(db=db, llm_router=llm, authed_email="agent@company.com")
    result = await gen.generate(email_id=1)

    assert result == {"body": "Borrador guardado previamente.", "from_draft": True}
    llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_second_suggest_with_example_uses_few_shot(db):
    """After learning an example, the next suggestion includes it as few-shot."""
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    import numpy as np

    await _seed(db)

    # Pre-seed an example with a known embedding
    dummy_emb = np.ones(384, dtype=np.float32)
    await db._db.execute(
        "INSERT INTO gmail_reply_examples "
        "(category_id, subtype_label, email_context, original_suggestion, final_response, embedding) "
        "VALUES (1, 'solicitud de estado de cuenta', 'Asunto: Estado de cuenta', '', "
        "'Necesitamos cédula, torre y apartamento.', ?)",
        (dummy_emb.tobytes(),),
    )
    await db._db.commit()

    llm = AsyncMock()
    llm.chat.return_value = {"content": "Respuesta con few-shot."}
    gen = AutoReplyGenerator(db=db, llm_router=llm, authed_email="agent@company.com")

    # Mock the model to return a similar vector
    mock_model = type("M", (), {
        "encode": lambda self, text, **kw: dummy_emb
    })()

    with patch("openacm.plugins.gmail_classifier.auto_reply.LocalRouter") as lr_mock:
        lr_mock._model = mock_model
        result = await gen.generate(email_id=1)

    assert result is not None
    # The prompt passed to LLM should contain the few-shot example
    prompt_sent = llm.chat.call_args[1]["messages"][0]["content"]
    assert "Necesitamos cédula" in prompt_sent
```

- [ ] **Step 3: Correr integration tests**

```
pytest tests/integration/test_autoreply_flow.py -v
```

Esperado: 3 PASSED

- [ ] **Step 4: Correr toda la suite**

```
pytest tests/ -v --tb=short
```

Esperado: todos PASSED

- [ ] **Step 5: Commit final**

```bash
git add tests/integration/test_autoreply_flow.py tests/integration/__init__.py
git commit -m "test: integration tests for auto-reply flow — suggest, draft, learn, few-shot"
```

---

## Checklist de spec coverage

- [x] Reglas de elegibilidad (5 condiciones) → Task 3 tests + AutoReplyGenerator
- [x] Timeout 30s frontend → Task 6 `AbortController` + `setTimeout(30000)`
- [x] Gmail Drafts API → Task 5 `save_draft` endpoint
- [x] No regenerar si draft existe → Task 3 + Task 8 test
- [x] Aprendizaje solo en Send/Draft → Task 4 (extender /reply) + Task 5 (draft endpoint)
- [x] Idempotency por email_id → Task 4 tests + `source_email_id` index
- [x] Diff usuario → guardar ejemplo → Task 4 `ReplyLearningManager`
- [x] No diff → incrementar use_count → Task 4 tests
- [x] RAG semántico top-3 → Task 3 `_get_similar_examples`
- [x] ai_suggestion persistido → Task 3 test + implementación
- [x] Gestión de ejemplos UI → Task 7 PluginSettings tab
- [x] Toggles por categoría off by default → Task 7 + seeded `[]`
- [x] Patrones noreply case-insensitive → Task 3 tests
- [x] thread_last_sender_email sincronizado en cada sync → Task 2 processor
