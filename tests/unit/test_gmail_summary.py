"""Unit tests for Gmail Classifier inbox summary generation."""
import datetime
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_with_today_emails(db):
    """DB with Importantes, Trabajo, and Otros categories + 3 emails received today."""
    for name in ("Importantes", "Trabajo", "Otros"):
        await db._db.execute(
            "INSERT OR IGNORE INTO gmail_categories (name, description) VALUES (?, 'd')", (name,)
        )
    await db._db.commit()

    async def get_id(name):
        c = await db._db.execute("SELECT id FROM gmail_categories WHERE name=?", (name,))
        return (await c.fetchone())["id"]

    importantes_id = await get_id("Importantes")
    trabajo_id = await get_id("Trabajo")
    otros_id = await get_id("Otros")

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
    assert "correos" in result
    assert "📬" in result
    assert "Importantes" in result
    assert "Trabajo" in result


async def test_part_b_includes_llm_urgent_list(db_with_today_emails, mock_llm_router):
    """Part B includes the LLM urgent list when LLM responds."""
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
    assert "urgentes" in result.lower() or "No se pudo" in result


async def test_llm_error_returns_part_a_only(db_with_today_emails, mock_llm_router):
    """On any LLM exception, Part A is returned with a fallback note; no crash."""
    async def raise_error(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    mock_llm_router.chat = raise_error

    from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
    result = await generate_inbox_summary(db_with_today_emails, mock_llm_router)
    assert "📬" in result
    assert "🔴" not in result
    assert "urgentes" in result.lower() or "No se pudo" in result


async def test_llm_empty_response_returns_fallback(db_with_today_emails, mock_llm_router):
    """When LLM returns empty content, Part A shown with fallback note, no crash."""
    mock_llm_router.chat.return_value = {
        "content": "", "tool_calls": [], "model": "mock", "usage": {}, "cost": 0
    }
    from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
    result = await generate_inbox_summary(db_with_today_emails, mock_llm_router)
    assert "📬" in result
    assert "🔴" not in result
