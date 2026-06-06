# tests/unit/test_gmail_stats.py
"""Unit tests for gmail_classifier stats aggregation."""
import pytest
from openacm.plugins.gmail_classifier.stats import compute_stats


async def _seed_category(db, cat_id: int = 1, name: str = "X", color: str = "#fff"):
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (id, name, color) VALUES (?, ?, ?)",
        (cat_id, name, color),
    )
    await db._db.commit()


async def _seed_emails(db, emails: list[dict]):
    """Insert minimal email rows."""
    for e in emails:
        await db._db.execute(
            "INSERT INTO gmail_emails "
            "(gmail_id, subject, sender_email, sender_name, body_text, category_id, "
            "is_read, is_replied, ai_classified, received_at, ai_suggestion) "
            "VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)",
            (
                e["gmail_id"],
                e.get("subject", "S"),
                e.get("sender_email", "a@b.com"),
                e.get("sender_name", "A"),
                e.get("category_id", 1),
                e.get("is_read", 0),
                e.get("is_replied", 0),
                e.get("ai_classified", 0),
                e.get("received_at", "2026-06-05 10:00:00"),
                e.get("ai_suggestion", ""),
            ),
        )
    await db._db.commit()


async def test_total_emails_in_range(db):
    """Only emails within the date range are counted."""
    await _seed_category(db)
    await _seed_emails(db, [
        {"gmail_id": "m1", "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m2", "received_at": "2026-06-10 10:00:00"},
        {"gmail_id": "m3", "received_at": "2026-05-01 10:00:00"},  # outside range
    ])
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    assert result["period"]["total_emails"] == 2


async def test_volume_by_day_groups_correctly(db):
    """Emails on the same day are grouped into one entry."""
    await _seed_category(db)
    await _seed_emails(db, [
        {"gmail_id": "m1", "received_at": "2026-06-05 08:00:00"},
        {"gmail_id": "m2", "received_at": "2026-06-05 17:00:00"},
        {"gmail_id": "m3", "received_at": "2026-06-06 10:00:00"},
    ])
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    assert len(result["volume_by_day"]) == 2
    assert result["volume_by_day"][0] == {"date": "2026-06-05", "count": 2}
    assert result["volume_by_day"][1] == {"date": "2026-06-06", "count": 1}


async def test_reply_rate(db):
    """reply_rate.rate = replied / total."""
    await _seed_category(db)
    await _seed_emails(db, [
        {"gmail_id": "m1", "is_replied": 1, "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m2", "is_replied": 0, "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m3", "is_replied": 0, "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m4", "is_replied": 0, "received_at": "2026-06-05 10:00:00"},
    ])
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    assert result["reply_rate"]["replied"] == 1
    assert result["reply_rate"]["total"] == 4
    assert result["reply_rate"]["rate"] == 0.25


async def test_by_category_counts(db):
    """by_category totals match seeded emails per category."""
    # Use high IDs to avoid colliding with the seeded "Otros" (id=1) from migration 19.
    await _seed_category(db, cat_id=10, name="Trabajo", color="#f00")
    await _seed_category(db, cat_id=11, name="Spam", color="#0f0")
    await _seed_emails(db, [
        {"gmail_id": "m1", "category_id": 10, "is_read": 1, "is_replied": 1, "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m2", "category_id": 10, "is_read": 0, "is_replied": 0, "received_at": "2026-06-05 10:00:00"},
        {"gmail_id": "m3", "category_id": 11, "is_read": 1, "is_replied": 0, "received_at": "2026-06-05 10:00:00"},
    ])
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    trabajo = next(c for c in result["by_category"] if c["name"] == "Trabajo")
    spam = next(c for c in result["by_category"] if c["name"] == "Spam")
    assert trabajo["total"] == 2
    assert trabajo["read"] == 1
    assert trabajo["replied"] == 1
    assert spam["total"] == 1
    assert spam["replied"] == 0


async def test_top_senders_limited_to_10(db):
    """top_senders never returns more than 10 entries."""
    await _seed_category(db)
    emails = [
        {"gmail_id": f"m{i}", "sender_email": f"sender{i}@x.com", "received_at": "2026-06-05 10:00:00"}
        for i in range(15)
    ]
    await _seed_emails(db, emails)
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    assert len(result["top_senders"]) == 10


async def test_empty_period_returns_zeros(db):
    """Period with no emails returns zeros, not errors."""
    await _seed_category(db)
    result = await compute_stats(db, "2026-06-01", "2026-06-30")
    assert result["period"]["total_emails"] == 0
    assert result["reply_rate"]["rate"] == 0.0
    assert result["volume_by_day"] == []
    assert result["autoreply"]["suggestions_generated"] == 0
