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

async def test_generate_returns_none_when_category_not_enabled(db):
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    await _seed_category(db)
    await _seed_email(db)
    # Do NOT call _enable_autoreply → category 1 not in enabled list
    gen = AutoReplyGenerator(db=db, llm_router=AsyncMock())
    result = await gen.generate(email_id=1)
    assert result is None


async def test_generate_returns_none_when_is_replied(db):
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    await _seed_category(db)
    await _seed_email(db, is_replied=1)
    await _enable_autoreply(db)
    gen = AutoReplyGenerator(db=db, llm_router=AsyncMock(), authed_email="me@test.com")
    result = await gen.generate(email_id=1)
    assert result is None


async def test_generate_returns_none_when_user_is_last_sender(db):
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    await _seed_category(db)
    await _seed_email(db, thread_last_sender_email="me@test.com")
    await _enable_autoreply(db)
    gen = AutoReplyGenerator(db=db, llm_router=AsyncMock(), authed_email="me@test.com")
    result = await gen.generate(email_id=1)
    assert result is None


async def test_generate_returns_none_for_noreply_sender(db):
    from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
    await _seed_category(db)
    await _seed_email(db, sender_email="noreply@example.com")
    await _enable_autoreply(db)
    gen = AutoReplyGenerator(db=db, llm_router=AsyncMock(), authed_email="me@test.com")
    result = await gen.generate(email_id=1)
    assert result is None


async def test_generate_returns_existing_draft_without_llm_call(db):
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


async def test_generate_calls_llm_and_returns_suggestion(db):
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


async def test_generate_persists_ai_suggestion_to_db(db):
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
