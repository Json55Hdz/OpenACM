"""Integration tests for the email auto-reply suggest → draft → learn flow."""
import struct
import json
import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch

from openacm.plugins.gmail_classifier.auto_reply import AutoReplyGenerator
from openacm.plugins.gmail_classifier.reply_learning import ReplyLearningManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_embedding(value: float = 0.5) -> bytes:
    """Create a simple 3-float embedding as bytes (float32)."""
    import struct
    return struct.pack("3f", value, value, value)


def _make_np_embedding(value: float = 0.5):
    """Create a 3-element numpy float32 array for use as a mock model output."""
    return np.array([value, value, value], dtype=np.float32)


def _llm_response(text: str) -> dict:
    """Minimal LLM response dict matching what auto_reply.py and reply_learning.py expect."""
    return {"content": text, "tool_calls": [], "model": "mock", "usage": {}, "cost": 0.0}


# ---------------------------------------------------------------------------
# Helper seeds (use the conftest `db` fixture which runs full migrations)
# ---------------------------------------------------------------------------

async def _seed_category(db, cat_id: int = 1, name: str = "Soporte"):
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (id, name, color) VALUES (?, ?, '#ff0000')",
        (cat_id, name),
    )
    await db._db.commit()


async def _enable_autoreply(db, category_ids: list[int] = None):
    if category_ids is None:
        category_ids = [1]
    await db._db.execute(
        "INSERT INTO gmail_classifier_settings (key, value) VALUES "
        "('autoreply_enabled_categories', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(category_ids),),
    )
    await db._db.commit()


async def _seed_email(db, email_id: int = 1, **kwargs):
    defaults = dict(
        gmail_id=f"msg{email_id}",
        subject="Help needed",
        sender_email="client@company.com",
        body_text="I need help with my account.",
        category_id=1,
        is_replied=0,
        thread_last_sender_email="client@company.com",
        ai_suggestion="",
    )
    defaults.update(kwargs)
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_emails "
        "(id, gmail_id, subject, sender_email, body_text, category_id, "
        "is_replied, thread_last_sender_email, ai_suggestion) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            email_id,
            defaults["gmail_id"],
            defaults["subject"],
            defaults["sender_email"],
            defaults["body_text"],
            defaults["category_id"],
            defaults["is_replied"],
            defaults["thread_last_sender_email"],
            defaults["ai_suggestion"],
        ),
    )
    await db._db.commit()


# ---------------------------------------------------------------------------
# Test 1 — Full flow: suggest → user edits → draft → example learned
# ---------------------------------------------------------------------------

async def test_full_suggest_edit_draft_learns(db):
    """Full flow: email arrives, LLM generates suggestion, user edits and saves, example is stored."""
    await _seed_category(db)
    await _enable_autoreply(db)
    await _seed_email(db, email_id=1)

    llm_router = MagicMock()
    llm_router.chat = AsyncMock(
        return_value=_llm_response("Thank you for reaching out. I'll help you with your account.")
    )

    # Patch LocalRouter._model so _get_similar_examples returns [] early
    # (model is None → returns [] → no few-shot injection needed here)
    with patch("openacm.core.local_router.LocalRouter") as mock_lr_cls:
        mock_lr_cls._model = None  # triggers early return in _get_similar_examples

        gen = AutoReplyGenerator(db=db, llm_router=llm_router, authed_email="me@company.com")
        result = await gen.generate(email_id=1)

    assert result is not None
    assert "body" in result
    assert result["from_draft"] is False
    assert len(result["body"]) > 0

    # Verify ai_suggestion was persisted to the DB
    cursor = await db._db.execute("SELECT ai_suggestion FROM gmail_emails WHERE id = 1")
    row = await cursor.fetchone()
    assert row["ai_suggestion"] != ""

    # User edits and saves — the edited text differs from the AI suggestion
    learning = ReplyLearningManager(db=db, llm_router=llm_router)
    user_edited_body = "Thank you for contacting us! Our team will review your account within 24 hours."

    with patch.object(learning, "_classify_subtype", new=AsyncMock(return_value="account inquiry")), \
         patch.object(learning, "_generate_embedding", new=AsyncMock(return_value=_make_embedding(0.5))):
        await learning.learn(email_id=1, final_body=user_edited_body)

    # Verify the example was saved
    cursor = await db._db.execute("SELECT * FROM gmail_reply_examples WHERE category_id = 1")
    example = await cursor.fetchone()
    assert example is not None
    assert example["final_response"] == user_edited_body
    assert example["subtype_label"] == "account inquiry"
    assert example["source_email_id"] == 1


# ---------------------------------------------------------------------------
# Test 2 — Existing draft returned without LLM call
# ---------------------------------------------------------------------------

async def test_existing_draft_returned_without_llm(db):
    """If a draft already exists for an email, generate() returns it without calling the LLM."""
    await _seed_category(db)
    await _enable_autoreply(db)
    await _seed_email(
        db, email_id=1,
        gmail_id="msg2",
        subject="Follow up",
        body_text="Still waiting for response.",
    )

    # Insert existing draft
    await db._db.execute(
        "INSERT INTO gmail_reply_drafts (email_id, gmail_draft_id, draft_body) "
        "VALUES (1, 'draft_abc123', 'We are working on your case.')"
    )
    await db._db.commit()

    llm_router = MagicMock()
    llm_router.chat = AsyncMock(return_value=_llm_response("NEW SUGGESTION"))  # Must NOT be called

    gen = AutoReplyGenerator(db=db, llm_router=llm_router, authed_email="me@company.com")
    result = await gen.generate(email_id=1)

    assert result is not None
    assert result["from_draft"] is True
    assert result["body"] == "We are working on your case."
    # LLM was NOT called — draft short-circuits before _generate_suggestion
    llm_router.chat.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 3 — Few-shot examples injected into LLM prompt
# ---------------------------------------------------------------------------

async def test_few_shot_examples_injected_into_prompt(db):
    """When similar examples exist, they are included in the LLM prompt."""
    await _seed_category(db)
    await _enable_autoreply(db)
    await _seed_email(
        db, email_id=1,
        gmail_id="msg3",
        subject="Account issue",
        body_text="My account is locked.",
    )

    # Insert a learned example with a real float32 embedding
    embedding = _make_embedding(0.9)
    await db._db.execute(
        "INSERT INTO gmail_reply_examples "
        "(category_id, subtype_label, email_context, original_suggestion, "
        "final_response, embedding, use_count) "
        "VALUES (1, 'account locked', 'Account is locked request', 'orig suggestion', "
        "'Your account has been unlocked.', ?, 3)",
        (embedding,),
    )
    await db._db.commit()

    captured_prompts: list[str] = []

    async def mock_chat(messages, **kwargs):
        for msg in messages:
            if isinstance(msg, dict):
                captured_prompts.append(msg.get("content", ""))
        return _llm_response("Here is the suggested response for the locked account.")

    llm_router = MagicMock()
    llm_router.chat = AsyncMock(side_effect=mock_chat)

    # Patch LocalRouter._model with a real numpy-returning encode so cosine sim works
    mock_model = MagicMock()
    mock_model.encode.return_value = _make_np_embedding(0.9)

    with patch("openacm.core.local_router.LocalRouter") as mock_lr_cls:
        mock_lr_cls._model = mock_model

        gen = AutoReplyGenerator(db=db, llm_router=llm_router, authed_email="me@company.com")
        result = await gen.generate(email_id=1)

    assert result is not None

    # The prompt must include the few-shot example's content
    all_prompt_text = " ".join(captured_prompts)
    assert "unlocked" in all_prompt_text or "account locked" in all_prompt_text


# ---------------------------------------------------------------------------
# Test 4 — Idempotency: learning the same email twice creates only one example
# ---------------------------------------------------------------------------

async def test_learning_idempotent_for_same_email(db):
    """Calling learn() twice for the same email_id only creates one example."""
    await _seed_category(db)
    await _seed_email(
        db, email_id=1,
        gmail_id="msg4",
        subject="Test",
        sender_email="a@b.com",
        thread_last_sender_email="a@b.com",
        body_text="body text",
        ai_suggestion="original ai suggestion",
    )

    llm_router = MagicMock()
    llm_router.chat = AsyncMock(return_value=_llm_response("subtype"))

    learning = ReplyLearningManager(db=db, llm_router=llm_router)
    final_body = "A different response than the AI suggestion."

    with patch.object(learning, "_classify_subtype", new=AsyncMock(return_value="test subtype")), \
         patch.object(learning, "_generate_embedding", new=AsyncMock(return_value=_make_embedding())):
        await learning.learn(email_id=1, final_body=final_body)
        await learning.learn(email_id=1, final_body=final_body)  # Second call — idempotent

    cursor = await db._db.execute("SELECT COUNT(*) as cnt FROM gmail_reply_examples")
    row = await cursor.fetchone()
    assert row["cnt"] == 1  # Only one example, not two
