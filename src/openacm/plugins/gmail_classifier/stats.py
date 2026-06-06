# src/openacm/plugins/gmail_classifier/stats.py
"""Async SQL aggregations for the Gmail Classifier stats endpoint."""
from __future__ import annotations
from typing import Any


async def compute_stats(db: Any, from_date: str, to_date: str) -> dict:
    """Return aggregated email stats for the inclusive date range [from_date, to_date]."""
    p = (from_date, to_date)

    # Total emails in period
    cur = await db._db.execute(
        "SELECT COUNT(*) FROM gmail_emails "
        "WHERE received_at >= ? AND received_at < date(?, '+1 day')", p
    )
    total = (await cur.fetchone())[0]

    # Volume by day
    cur = await db._db.execute(
        "SELECT date(received_at) as d, COUNT(*) as c FROM gmail_emails "
        "WHERE received_at >= ? AND received_at < date(?, '+1 day') "
        "GROUP BY d ORDER BY d", p
    )
    volume_by_day = [{"date": r[0], "count": r[1]} for r in await cur.fetchall()]

    # By category
    cur = await db._db.execute(
        "SELECT c.id, c.name, c.color, "
        "COUNT(e.id) as total, "
        "SUM(CASE WHEN e.is_read=1 THEN 1 ELSE 0 END) as read_count, "
        "SUM(CASE WHEN e.is_replied=1 THEN 1 ELSE 0 END) as replied, "
        "SUM(CASE WHEN e.ai_classified=1 THEN 1 ELSE 0 END) as ai_classified "
        "FROM gmail_categories c "
        "LEFT JOIN gmail_emails e ON e.category_id = c.id "
        "  AND e.received_at >= ? AND e.received_at < date(?, '+1 day') "
        "GROUP BY c.id ORDER BY total DESC, c.name ASC",
        p,
    )
    by_category = [
        {
            "id": r[0], "name": r[1], "color": r[2],
            "total": r[3] or 0, "read": r[4] or 0,
            "replied": r[5] or 0, "ai_classified": r[6] or 0,
        }
        for r in await cur.fetchall()
    ]

    # Top 10 senders
    cur = await db._db.execute(
        "SELECT sender_email, sender_name, COUNT(*) as c FROM gmail_emails "
        "WHERE received_at >= ? AND received_at < date(?, '+1 day') "
        "GROUP BY sender_email ORDER BY c DESC LIMIT 10", p
    )
    top_senders = [{"email": r[0], "name": r[1] or "", "count": r[2]} for r in await cur.fetchall()]

    # Reply rate
    cur = await db._db.execute(
        "SELECT COUNT(*), SUM(is_replied) FROM gmail_emails "
        "WHERE received_at >= ? AND received_at < date(?, '+1 day')", p
    )
    rr = await cur.fetchone()
    replied_count = rr[1] or 0
    reply_rate = round(replied_count / total, 3) if total else 0.0

    # Autoreply: suggestions generated
    cur = await db._db.execute(
        "SELECT COUNT(*) FROM gmail_emails "
        "WHERE ai_suggestion != '' AND received_at >= ? AND received_at < date(?, '+1 day')", p
    )
    suggestions = (await cur.fetchone())[0]

    # Autoreply: drafts saved
    cur = await db._db.execute(
        "SELECT COUNT(*) FROM gmail_reply_drafts "
        "WHERE created_at >= ? AND created_at < date(?, '+1 day')", p
    )
    drafts = (await cur.fetchone())[0]

    # Autoreply: examples learned + avg use_count
    cur = await db._db.execute(
        "SELECT COUNT(*), COALESCE(AVG(use_count), 0.0) FROM gmail_reply_examples "
        "WHERE created_at >= ? AND created_at < date(?, '+1 day')", p
    )
    ex = await cur.fetchone()

    return {
        "period": {"from": from_date, "to": to_date, "total_emails": total},
        "volume_by_day": volume_by_day,
        "by_category": by_category,
        "top_senders": top_senders,
        "reply_rate": {"total": total, "replied": replied_count, "rate": reply_rate},
        "autoreply": {
            "suggestions_generated": suggestions,
            "drafts_saved": drafts,
            "examples_learned": ex[0],
            "avg_use_count": round(ex[1], 2),
        },
    }
