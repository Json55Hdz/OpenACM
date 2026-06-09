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

    # Patch _get_gmail_service to return mock
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


# ─── Router Fixtures ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def router_app(db):
    """Minimal FastAPI app with the plugin router mounted."""
    from fastapi import FastAPI
    import openacm.plugins.gmail_classifier.router as router_mod

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
    cursor2 = await db._db.execute("SELECT id FROM gmail_emails WHERE gmail_id='gread1'")
    email_id = (await cursor2.fetchone())["id"]

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


# ─── _upsert force flag ───────────────────────────────────────────────────────

@pytest.fixture
async def processor_with_categories(db, mock_llm_router, event_bus):
    """Processor with 'Importantes' and 'Otros' categories seeded."""
    from openacm.plugins.gmail_classifier.processor import GmailBatchProcessor
    # Seed categories
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description) VALUES (?, ?)",
        ("Importantes", "Alta prioridad"),
    )
    await db._db.commit()
    return GmailBatchProcessor(db=db, llm_router=mock_llm_router, event_bus=event_bus)


async def test_upsert_force_true_overrides_manual_override(db, processor_with_categories):
    """force=True rewrites category and clears manual_override even when manual_override=1."""
    proc = processor_with_categories

    # Load the two category IDs
    c1 = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Importantes'")
    importantes_id = (await c1.fetchone())["id"]
    c2 = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Otros'")
    otros_id = (await c2.fetchone())["id"]

    # Pre-insert an email with manual_override=1 pointing to 'Otros'
    await db._db.execute(
        "INSERT INTO gmail_emails "
        "(gmail_id, thread_id, subject, sender_name, sender_email, snippet, "
        " body_text, body_html, category_id, is_read, is_replied, ai_classified, "
        " manual_override, thread_last_sender_email, received_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 1, ?, datetime('now'))",
        ("gid1", "tid1", "Asunto", "Sender", "s@x.com", "preview",
         "body", "", otros_id, ""),
    )
    await db._db.commit()

    email = {
        "gmail_id": "gid1", "thread_id": "tid1", "subject": "Asunto",
        "sender_name": "Sender", "sender_email": "s@x.com",
        "snippet": "preview", "body_text": "body", "body_html": "",
        "is_read": 0, "is_replied": 0, "thread_last_sender_email": "",
        "received_at": "2026-06-09T00:00:00+00:00",
    }
    categories = await proc._load_categories()
    classifications = {"gid1": "Importantes"}

    await proc._upsert([email], classifications, categories, force=True)

    cursor = await db._db.execute(
        "SELECT category_id, manual_override, ai_classified FROM gmail_emails WHERE gmail_id='gid1'"
    )
    row = await cursor.fetchone()
    assert row["category_id"] == importantes_id
    assert row["manual_override"] == 0
    assert row["ai_classified"] == 1


async def test_upsert_force_false_preserves_manual_override(db, processor_with_categories):
    """force=False (default) preserves manual_override=1 and keeps old category."""
    proc = processor_with_categories

    c1 = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Importantes'")
    importantes_id = (await c1.fetchone())["id"]
    c2 = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Otros'")
    otros_id = (await c2.fetchone())["id"]

    # Pre-insert with manual_override=1 pointing to 'Otros'
    await db._db.execute(
        "INSERT INTO gmail_emails "
        "(gmail_id, thread_id, subject, sender_name, sender_email, snippet, "
        " body_text, body_html, category_id, is_read, is_replied, ai_classified, "
        " manual_override, thread_last_sender_email, received_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 1, ?, datetime('now'))",
        ("gid2", "tid2", "Asunto", "Sender", "s@x.com", "preview",
         "body", "", otros_id, ""),
    )
    await db._db.commit()

    email = {
        "gmail_id": "gid2", "thread_id": "tid2", "subject": "Asunto",
        "sender_name": "Sender", "sender_email": "s@x.com",
        "snippet": "preview", "body_text": "body", "body_html": "",
        "is_read": 0, "is_replied": 0, "thread_last_sender_email": "",
        "received_at": "2026-06-09T00:00:00+00:00",
    }
    categories = await proc._load_categories()
    classifications = {"gid2": "Importantes"}

    # force=False — manual_override should be preserved
    await proc._upsert([email], classifications, categories, force=False)

    cursor = await db._db.execute(
        "SELECT category_id, manual_override FROM gmail_emails WHERE gmail_id='gid2'"
    )
    row = await cursor.fetchone()
    assert row["category_id"] == otros_id   # unchanged — manual override kept
    assert row["manual_override"] == 1
