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

    with patch.object(mgr, "_generate_embedding", new=AsyncMock(return_value=b"\x00" * 16)):
        await mgr.learn(email_id=1, final_body="Estimado señor, para el estado de cuenta necesitamos cédula.")

    cursor = await db._db.execute("SELECT COUNT(*) as n FROM gmail_reply_examples")
    row = await cursor.fetchone()
    assert row["n"] == 1


async def test_learn_is_idempotent(db):
    """Calling learn twice for the same email_id only saves one example."""
    from openacm.plugins.gmail_classifier.reply_learning import ReplyLearningManager
    await _seed_base(db)
    mgr = ReplyLearningManager(db=db, llm_router=AsyncMock())
    mgr._llm.chat.return_value = {"content": "solicitud"}

    with patch.object(mgr, "_generate_embedding", new=AsyncMock(return_value=b"\x00" * 16)):
        await mgr.learn(email_id=1, final_body="Respuesta uno.")
        await mgr.learn(email_id=1, final_body="Respuesta diferente.")

    cursor = await db._db.execute("SELECT COUNT(*) as n FROM gmail_reply_examples")
    row = await cursor.fetchone()
    assert row["n"] == 1


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
