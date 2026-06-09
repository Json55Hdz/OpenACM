"""Gmail Classifier — FastAPI router for all API endpoints."""
from __future__ import annotations

import asyncio
import base64
import json
import re
from email.mime.text import MIMEText
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field

log = structlog.get_logger()

router = APIRouter(prefix="/gmail-classifier", tags=["gmail-classifier"])

# Set by GmailClassifierPlugin.on_start()
_db: Any = None
_processor: Any = None
_auto_reply: Any = None
_learning: Any = None
_llm_router: Any = None
_event_bus: Any = None
_plugin: Any = None  # GmailClassifierPlugin instance — used to restart digest cron


def _require_db():
    if _db is None:
        raise HTTPException(status_code=503, detail="Gmail Classifier not initialized")
    return _db


def _require_processor():
    if _processor is None:
        raise HTTPException(status_code=503, detail="Gmail Classifier processor not initialized")
    return _processor


def _require_auto_reply():
    if _auto_reply is None:
        raise HTTPException(status_code=503, detail="AutoReply not initialized")
    return _auto_reply


def _require_learning():
    if _learning is None:
        raise HTTPException(status_code=503, detail="ReplyLearning not initialized")
    return _learning


def _require_llm():
    if _llm_router is None:
        raise HTTPException(status_code=503, detail="LLM no configurado")
    return _llm_router


# ─── Pydantic models ─────────────────────────────────────────────────────────

PatternType = Literal["sender_email", "sender_domain", "subject_contains"]


class CategoryPattern(BaseModel):
    type: PatternType
    value: str


class CategoryBody(BaseModel):
    name: str
    description: str = ""
    color: str = "#6366f1"
    icon: str = "Tag"
    context: str = ""
    known_senders: list[str] = Field(default_factory=list)
    patterns: list[CategoryPattern] = Field(default_factory=list)


def _normalize_senders(senders: list[str]) -> list[str]:
    """Lowercase, strip, dedupe, drop empties."""
    seen: set[str] = set()
    out: list[str] = []
    for s in senders:
        v = (s or "").strip().lower()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _normalize_patterns(patterns: list[CategoryPattern]) -> list[dict]:
    out: list[dict] = []
    for p in patterns:
        v = (p.value or "").strip()
        if not v:
            continue
        # Normalize domain: strip leading @ and lowercase
        if p.type == "sender_domain":
            v = v.lstrip("@").lower()
        elif p.type == "sender_email":
            v = v.lower()
        else:  # subject_contains: keep case as user typed but lower for matching elsewhere
            v = v.lower()
        out.append({"type": p.type, "value": v})
    return out


def _row_to_category(row: Any, include_email_count: bool = False) -> dict:
    """Convert a SQLite row to a category dict with parsed JSON fields."""
    d = dict(row)
    try:
        d["known_senders"] = json.loads(d.get("known_senders") or "[]")
    except Exception:
        d["known_senders"] = []
    try:
        d["patterns"] = json.loads(d.get("patterns") or "[]")
    except Exception:
        d["patterns"] = []
    d["context"] = d.get("context") or ""
    return d


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
    autoreply_enabled_categories: str | None = None
    autoreply_model: str | None = None
    autoreply_timeout_seconds: int | None = None


class DraftBody(BaseModel):
    body: str


class ReplyExampleUpdate(BaseModel):
    subtype_label: str | None = None
    final_response: str | None = None


class CronBody(BaseModel):
    schedule: str


# ─── Categories ──────────────────────────────────────────────────────────────

@router.get("/categories")
async def list_categories():
    db = _require_db()
    cursor = await db._db.execute(
        "SELECT gc.id, gc.name, gc.description, gc.color, gc.icon, "
        "gc.context, gc.known_senders, gc.patterns, "
        "COUNT(ge.id) as email_count "
        "FROM gmail_categories gc "
        "LEFT JOIN gmail_emails ge ON ge.category_id = gc.id "
        "GROUP BY gc.id ORDER BY gc.id"
    )
    rows = await cursor.fetchall()
    return [_row_to_category(r) for r in rows]


@router.post("/categories")
async def create_category(body: CategoryBody):
    db = _require_db()
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    senders_json = json.dumps(_normalize_senders(body.known_senders), ensure_ascii=False)
    patterns_json = json.dumps(_normalize_patterns(body.patterns), ensure_ascii=False)
    try:
        cursor = await db._db.execute(
            "INSERT INTO gmail_categories "
            "(name, description, color, icon, context, known_senders, patterns) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                body.name.strip(), body.description, body.color, body.icon,
                body.context, senders_json, patterns_json,
            ),
        )
        await db._db.commit()
        row_cursor = await db._db.execute(
            "SELECT * FROM gmail_categories WHERE id = ?", (cursor.lastrowid,)
        )
        row = await row_cursor.fetchone()
        return _row_to_category(row)
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
    senders_json = json.dumps(_normalize_senders(body.known_senders), ensure_ascii=False)
    patterns_json = json.dumps(_normalize_patterns(body.patterns), ensure_ascii=False)
    await db._db.execute(
        "UPDATE gmail_categories "
        "SET name=?, description=?, color=?, icon=?, context=?, known_senders=?, patterns=? "
        "WHERE id=?",
        (
            body.name.strip(), body.description, body.color, body.icon,
            body.context, senders_json, patterns_json, cat_id,
        ),
    )
    await db._db.commit()
    cursor2 = await db._db.execute("SELECT * FROM gmail_categories WHERE id = ?", (cat_id,))
    return _row_to_category(await cursor2.fetchone())


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


# Color palette used to give imported Gmail labels a sensible default color.
_IMPORT_COLORS = [
    "#6366f1", "#3b82f6", "#10b981", "#f59e0b",
    "#ef4444", "#8b5cf6", "#ec4899", "#0ea5e9",
    "#14b8a6", "#f97316", "#84cc16",
]

# Gmail system labels are returned with type=system; we also blacklist a few
# CATEGORY_* labels that come back as type=user but are clearly system.
_SYSTEM_LABEL_NAMES = {
    "INBOX", "SENT", "DRAFT", "DRAFTS", "TRASH", "SPAM", "IMPORTANT",
    "STARRED", "UNREAD", "CHAT", "CHATS",
    "CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS",
    "CATEGORY_UPDATES", "CATEGORY_FORUMS",
}


@router.post("/categories/import-labels")
async def import_gmail_labels():
    """Import the user's Gmail labels as categories.

    Only labels with type='user' are imported. Existing category names (case-
    insensitive) are skipped — your edits and the seeded defaults are safe.
    """
    db = _require_db()
    try:
        from openacm.plugins.gmail_classifier.processor import _get_gmail_service
        service = await _get_gmail_service()
        result = service.users().labels().list(userId="me").execute()
        labels = result.get("labels", [])
    except Exception as exc:
        log.error("import_gmail_labels: gmail fetch failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"No se pudieron leer las etiquetas de Gmail: {exc}")

    # Existing names, case-insensitive
    cursor = await db._db.execute("SELECT name FROM gmail_categories")
    existing = {(r["name"] or "").lower() for r in await cursor.fetchall()}

    created: list[str] = []
    skipped: list[str] = []
    color_idx = 0

    for lbl in labels:
        name = (lbl.get("name") or "").strip()
        ltype = lbl.get("type", "user")
        if not name:
            continue
        if ltype != "user":
            continue
        if name.upper() in _SYSTEM_LABEL_NAMES:
            continue
        # Gmail allows nested labels like "Trabajo/Clientes"; take the leaf so the
        # display name is short, fall back to the full path if collision.
        display = name.split("/")[-1].strip() or name

        if display.lower() in existing:
            skipped.append(display)
            continue

        color = _IMPORT_COLORS[color_idx % len(_IMPORT_COLORS)]
        color_idx += 1
        try:
            await db._db.execute(
                "INSERT INTO gmail_categories "
                "(name, description, color, icon, context, known_senders, patterns) "
                "VALUES (?, ?, ?, ?, ?, '[]', '[]')",
                (
                    display,
                    f"Importada desde Gmail (etiqueta: {name})",
                    color,
                    "Tag",
                    "",
                ),
            )
            existing.add(display.lower())
            created.append(display)
        except Exception as exc:
            log.warning("import_gmail_labels: insert failed", name=display, error=str(exc))
            skipped.append(display)

    await db._db.commit()
    return {"created": len(created), "skipped": len(skipped), "names": created}


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
    # manual_override=1 protects this assignment from being overwritten by
    # future cron runs that would otherwise re-classify the email.
    await db._db.execute(
        "UPDATE gmail_emails SET category_id = ?, manual_override = 1 WHERE id = ?",
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
        try:
            if _learning:
                await _learning.learn(email_id=email_id, final_body=body.body)
        except Exception as exc:
            log.warning("AutoReply learning failed on send", error=str(exc))
        return {"success": True, "to": row["sender_email"]}

    except Exception as exc:
        log.error("Failed to send reply", email_id=email_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to send reply: {exc}")


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
        service = await _get_google_service("gmail", "v1")

        # Fetch the original message to get threadId and Message-ID header
        # so the draft appears inside the existing conversation, not as a new one.
        orig = service.users().messages().get(
            userId="me", id=row["gmail_id"], format="metadata",
            metadataHeaders=["Message-ID"],
        ).execute()
        thread_id = orig.get("threadId", "")
        orig_message_id = next(
            (h["value"] for h in orig.get("payload", {}).get("headers", [])
             if h["name"] == "Message-ID"),
            "",
        )

        subject = row["subject"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        message = MIMEText(body.body)
        message["to"] = row["sender_email"]
        message["subject"] = subject
        if orig_message_id:
            message["In-Reply-To"] = orig_message_id
            message["References"] = orig_message_id
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        draft_msg: dict = {"raw": raw}
        if thread_id:
            draft_msg["threadId"] = thread_id

        existing = await db._db.execute(
            "SELECT gmail_draft_id FROM gmail_reply_drafts WHERE email_id = ?", (email_id,)
        )
        existing_row = await existing.fetchone()

        if existing_row and existing_row["gmail_draft_id"]:
            draft = service.users().drafts().update(
                userId="me",
                id=existing_row["gmail_draft_id"],
                body={"message": draft_msg},
            ).execute()
        else:
            draft = service.users().drafts().create(
                userId="me", body={"message": draft_msg}
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
        try:
            await learning.learn(email_id=email_id, final_body=body.body)
        except Exception as exc:
            log.warning("AutoReply learning failed on draft save", error=str(exc))
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


# ─── Processing ───────────────────────────────────────────────────────────────

@router.post("/process")
async def start_process(body: ProcessBody):
    proc = _require_processor()
    if proc.is_running:
        raise HTTPException(status_code=409, detail="Processing already in progress")
    asyncio.create_task(proc.process(body.since_date, force=True))
    return {"started": True, "since_date": body.since_date}


@router.get("/process/status")
async def process_status():
    proc = _require_processor()
    from openacm.plugins.gmail_classifier import PLUGIN
    status = dict(proc.status)
    cron_task = getattr(PLUGIN, "_cron_task", None)
    status["cron_active"] = bool(cron_task and not cron_task.done())
    return status


@router.post("/process/stop")
async def stop_process():
    proc = _require_processor()
    if not proc.is_running:
        return {"stopped": False, "message": "No hay proceso en curso"}
    proc._stop_requested = True
    return {"stopped": True, "message": "Deteniendo al finalizar el lote actual…"}


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

    # Read current values to detect changes
    cursor = await db._db.execute("SELECT key, value FROM gmail_classifier_settings")
    old = {r["key"]: r["value"] for r in await cursor.fetchall()}

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    for key, value in updates.items():
        await db._db.execute(
            "INSERT INTO gmail_classifier_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    await db._db.commit()

    # If a Gmail-action setting was just turned ON, apply retroactively in background
    proc = _processor
    if proc:
        mark_read_on  = updates.get("auto_mark_read")  == "true" and old.get("auto_mark_read")  != "true"
        apply_label_on = updates.get("auto_apply_label") == "true" and old.get("auto_apply_label") != "true"
        if mark_read_on or apply_label_on:
            asyncio.create_task(proc.apply_retroactive(
                mark_read=mark_read_on,
                apply_label=apply_label_on,
            ))

    cursor2 = await db._db.execute("SELECT key, value FROM gmail_classifier_settings")
    rows = await cursor2.fetchall()
    return {r["key"]: r["value"] for r in rows}


# ─── Suggest Categories ───────────────────────────────────────────────────────

@router.post("/suggest-categories")
async def suggest_categories():
    """Sample recent emails and ask the LLM to suggest the top 5 categories."""
    proc = _require_processor()
    db = _require_db()

    try:
        from openacm.plugins.gmail_classifier.processor import _get_gmail_service, _get_authenticated_email
        import json, re as _re

        service = await _get_gmail_service()
        auth_email = await _get_authenticated_email(service)

        # Fetch up to 150 recent message IDs (no date filter — just most recent)
        result = service.users().messages().list(userId="me", maxResults=150).execute()
        msg_ids = [m["id"] for m in result.get("messages", [])]

        if not msg_ids:
            raise HTTPException(status_code=400, detail="No se encontraron correos")

        # Fetch metadata for each (subject + sender)
        samples = []
        for msg_id in msg_ids[:150]:
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["Subject", "From"],
                ).execute()
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                subject = headers.get("Subject", "")
                sender = headers.get("From", "")
                snippet = msg.get("snippet", "")[:100]
                if subject or sender:
                    samples.append(f"De: {sender} | Asunto: {subject} | {snippet}")
            except Exception:
                continue

        if not samples:
            raise HTTPException(status_code=400, detail="No se pudieron leer los correos")

        email_block = "\n".join(f"{i+1}. {s}" for i, s in enumerate(samples[:100]))

        prompt = (
            "Analiza estos correos y sugiere las 5 categorías MÁS ÚTILES para organizar "
            "la bandeja de este usuario. Basa las categorías en los patrones reales que ves.\n\n"
            f"Correos de muestra:\n{email_block}\n\n"
            "Devuelve SOLO un JSON array con exactamente 5 objetos, sin texto adicional:\n"
            '[\n'
            '  {"name": "Nombre corto", "description": "Descripción de qué correos van aquí", '
            '"color": "#hexcolor", "icon": "LucideIconName"},\n'
            '  ...\n'
            ']\n\n'
            "Colores sugeridos (usa variedad): #6366f1 #3b82f6 #10b981 #f59e0b #ef4444 #8b5cf6 #ec4899 #0ea5e9\n"
            "Iconos válidos (lucide-react): Tag Mail Car FileText Inbox Briefcase Home Star Bell Users "
            "ShoppingCart Calendar Map Truck Landmark Building2 Package Wrench CreditCard Globe Megaphone\n"
            "El campo 'name' debe estar en español y ser corto (1-2 palabras)."
        )

        response = await proc._llm.chat(
            messages=[{"role": "user", "content": prompt}],
        )
        log.info("suggest_categories LLM response keys", keys=list(response.keys()) if isinstance(response, dict) else type(response).__name__)
        # content key varies by provider/streaming mode
        content = (
            response.get("content")
            or response.get("text")
            or response.get("message")
            or ""
        )
        if isinstance(content, dict):
            content = content.get("content") or content.get("text") or ""
        log.info("suggest_categories LLM content", content_preview=str(content)[:300])

        # Strip markdown code fences if present (```json ... ``` or ``` ... ```)
        clean = _re.sub(r"```(?:json)?\s*", "", content)
        clean = _re.sub(r"```", "", clean)

        # Grab the outermost [...] array (greedy so we get all items)
        match = _re.search(r"\[[\s\S]*\]", clean)
        if not match:
            raise HTTPException(status_code=500, detail=f"La IA no devolvió JSON válido. Respuesta: {content[:300]}")

        suggestions = json.loads(match.group(0))
        if not isinstance(suggestions, list) or len(suggestions) == 0:
            raise HTTPException(status_code=500, detail="La IA devolvió una lista vacía")

        return {"suggestions": suggestions[:5]}

    except HTTPException:
        raise
    except Exception as exc:
        log.error("suggest_categories failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Auth Status ──────────────────────────────────────────────────────────────

@router.get("/auth-status")
async def auth_status():
    """Check if Gmail OAuth is configured (credentials + token files exist)."""
    from pathlib import Path
    creds_path = Path("config/google_credentials.json")
    token_path = Path("config/google_token.json")
    configured = creds_path.exists()
    has_token = token_path.exists()
    return {
        "configured": configured,
        "has_token": has_token,
        "ready": configured and has_token,
    }


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


# ─── Stats ───────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(from_date: str, to_date: str):
    """Return aggregated email stats for the given inclusive date range."""
    try:
        import datetime
        datetime.date.fromisoformat(from_date)
        datetime.date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")
    db = _require_db()
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be <= to_date")
    from openacm.plugins.gmail_classifier.stats import compute_stats
    return await compute_stats(db, from_date, to_date)


# ─── Inbox Summary ────────────────────────────────────────────────────────────

@router.get("/summary")
async def get_inbox_summary():
    """Generate and return an AI summary of today's inbox."""
    import datetime as _dt
    from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
    db = _require_db()
    llm = _require_llm()
    summary = await generate_inbox_summary(db, llm, _event_bus)
    return {"summary": summary, "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}


@router.get("/export/excel")
async def export_excel(from_date: str, to_date: str):
    """Generate and return an Excel report for the given date range."""
    import datetime
    try:
        datetime.date.fromisoformat(from_date)
        datetime.date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be <= to_date")
    db = _require_db()
    from fastapi.responses import StreamingResponse
    from openacm.plugins.gmail_classifier.stats import compute_stats
    from openacm.plugins.gmail_classifier.excel_export import generate_excel
    stats = await compute_stats(db, from_date, to_date)
    buf = generate_excel(stats, from_date, to_date)
    filename = f"gmail_stats_{from_date}_{to_date}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Config Backup / Restore ─────────────────────────────────────────────────

@router.get("/export")
async def export_config_endpoint():
    """Download plugin configuration as a JSON backup file."""
    import datetime
    from fastapi import Response
    from openacm.plugins.gmail_classifier.backup import export_config as _export_config
    db = _require_db()
    data = await _export_config(db)
    today = datetime.date.today().isoformat()
    filename = f"gmail-classifier-backup-{today}.json"
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_config_endpoint(file: UploadFile):
    """Import configuration from a JSON backup file (smart merge)."""
    from openacm.plugins.gmail_classifier.backup import import_config as _import_config
    db = _require_db()
    if file.size and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (máx 10 MB)")
    raw = await file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"El archivo no es un JSON válido: {exc}")
    try:
        summary = await _import_config(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al importar: {exc}")
    return summary
