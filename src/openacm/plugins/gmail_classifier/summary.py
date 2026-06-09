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
