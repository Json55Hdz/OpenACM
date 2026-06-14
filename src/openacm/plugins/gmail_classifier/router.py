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
_cached_auth_email: str | None = None


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


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so a literal % or _ in the query matches itself.

    Paired with `ESCAPE '\\'` in the SQL. Backslash is escaped first so we don't
    double-escape the escapes we add for % and _.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
    digest_enabled: str | None = None
    digest_time: str | None = None
    digest_days: str | None = None
    digest_agent_id: str | None = None
    digest_chat_id: str | None = None


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
    search: str | None = None,
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

    # Free-text search across every meaningful column. Each whitespace-separated
    # term must match somewhere (AND between terms, OR across columns) so the user
    # can narrow results by typing more words.
    if search and search.strip():
        for term in search.split():
            like = f"%{_escape_like(term)}%"
            conditions.append(
                "(ge.subject LIKE ? ESCAPE '\\' "
                "OR ge.sender_name LIKE ? ESCAPE '\\' "
                "OR ge.sender_email LIKE ? ESCAPE '\\' "
                "OR ge.snippet LIKE ? ESCAPE '\\' "
                "OR ge.body_text LIKE ? ESCAPE '\\')"
            )
            params.extend([like, like, like, like, like])

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


# ─── Threads ─────────────────────────────────────────────────────────────────

@router.get("/threads")
async def list_threads(
    category_id: int | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 50,
):
    db = _require_db()

    # Build WHERE conditions that apply to the outer (post-aggregation) query.
    outer_conditions: list[str] = []
    params: list = []

    if category_id is not None:
        outer_conditions.append("t.category_id = ?")
        params.append(category_id)

    if search and search.strip():
        for term in search.split():
            like = f"%{_escape_like(term)}%"
            outer_conditions.append(
                "EXISTS (SELECT 1 FROM gmail_emails s "
                "WHERE COALESCE(s.thread_id, s.gmail_id) = t.thread_id "
                "AND (s.subject LIKE ? ESCAPE '\\' "
                "OR s.sender_name LIKE ? ESCAPE '\\' "
                "OR s.sender_email LIKE ? ESCAPE '\\' "
                "OR s.snippet LIKE ? ESCAPE '\\' "
                "OR s.body_text LIKE ? ESCAPE '\\'))"
            )
            params.extend([like, like, like, like, like])

    where = ("WHERE " + " AND ".join(outer_conditions)) if outer_conditions else ""

    # CTE groups emails by effective thread_id (falls back to gmail_id for NULL thread_id).
    inner = f"""
        WITH threads AS (
          SELECT
            COALESCE(ge.thread_id, ge.gmail_id) AS thread_id,
            (SELECT m.subject FROM gmail_emails m
             WHERE COALESCE(m.thread_id, m.gmail_id) = COALESCE(ge.thread_id, ge.gmail_id)
             ORDER BY m.received_at ASC LIMIT 1) AS subject,
            (SELECT m.category_id FROM gmail_emails m
             WHERE COALESCE(m.thread_id, m.gmail_id) = COALESCE(ge.thread_id, ge.gmail_id)
             ORDER BY m.received_at ASC LIMIT 1) AS category_id,
            COUNT(ge.id) AS message_count,
            SUM(CASE WHEN ge.is_read = 0 THEN 1 ELSE 0 END) AS unread_count,
            MAX(ge.received_at) AS latest_at,
            (SELECT m.snippet FROM gmail_emails m
             WHERE COALESCE(m.thread_id, m.gmail_id) = COALESCE(ge.thread_id, ge.gmail_id)
             ORDER BY m.received_at DESC LIMIT 1) AS latest_snippet
          FROM gmail_emails ge
          GROUP BY COALESCE(ge.thread_id, ge.gmail_id)
        )
        SELECT t.thread_id, t.subject, t.category_id, t.message_count,
               t.unread_count, t.latest_at, t.latest_snippet,
               gc.name AS category_name, gc.color AS category_color, gc.icon AS category_icon
        FROM threads t
        LEFT JOIN gmail_categories gc ON t.category_id = gc.id
        {where}
    """

    count_row = await (await db._db.execute(
        f"SELECT COUNT(*) AS total FROM ({inner}) _sub", params
    )).fetchone()
    total = count_row["total"]

    offset = (page - 1) * per_page
    rows = await (await db._db.execute(
        f"{inner} ORDER BY t.latest_at DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    )).fetchall()

    # Fetch participants in a single bulk query for all returned threads.
    thread_ids = [r["thread_id"] for r in rows]
    participants_map: dict[str, list[dict]] = {tid: [] for tid in thread_ids}
    if thread_ids:
        ph = ",".join("?" * len(thread_ids))
        p_rows = await (await db._db.execute(
            f"""
            SELECT COALESCE(thread_id, gmail_id) AS tid,
                   sender_name, sender_email, MIN(received_at) AS first_seen
            FROM gmail_emails
            WHERE COALESCE(thread_id, gmail_id) IN ({ph})
            GROUP BY COALESCE(thread_id, gmail_id), sender_email
            ORDER BY COALESCE(thread_id, gmail_id), first_seen ASC
            """,
            thread_ids,
        )).fetchall()
        for p in p_rows:
            tid = p["tid"]
            if tid in participants_map:
                participants_map[tid].append({
                    "name": p["sender_name"] or p["sender_email"] or "",
                    "email": p["sender_email"] or "",
                })

    items = []
    for r in rows:
        d = dict(r)
        d["participants"] = participants_map.get(r["thread_id"], [])
        items.append(d)

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.patch("/emails/{email_id}/read")
async def toggle_read(email_id: int, body: ReadToggle):
    db = _require_db()
    cursor = await db._db.execute("SELECT gmail_id FROM gmail_emails WHERE id = ?", (email_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Email not found")
    gmail_id = row["gmail_id"]
    await db._db.execute(
        "UPDATE gmail_emails SET is_read = ? WHERE id = ?",
        (1 if body.is_read else 0, email_id),
    )
    await db._db.commit()

    # Sync read state to Gmail if the setting is enabled.
    # This is the ONLY place where read state is pushed to Gmail — not during classification.
    try:
        sc = await db._db.execute(
            "SELECT value FROM gmail_classifier_settings WHERE key = 'auto_mark_read'"
        )
        sr = await sc.fetchone()
        if sr and sr["value"] == "true":
            from openacm.tools.google_services import _get_google_service
            service = await _get_google_service("gmail", "v1")
            modify_body = (
                {"removeLabelIds": ["UNREAD"]} if body.is_read
                else {"addLabelIds": ["UNREAD"]}
            )
            service.users().messages().modify(
                userId="me", id=gmail_id, body=modify_body
            ).execute()
    except Exception as exc:
        log.warning("Failed to sync read state to Gmail", email_id=email_id, error=str(exc))

    row_cursor = await db._db.execute("SELECT * FROM gmail_emails WHERE id = ?", (email_id,))
    row2 = dict(await row_cursor.fetchone())
    row2["is_read"] = bool(row2["is_read"])
    return row2


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


# ─── Attachments & rich HTML ─────────────────────────────────────────────────


def _collect_attachment_parts(payload: dict) -> list[dict]:
    """Walk a Gmail message payload tree and return every part with attachment bytes.

    Each entry: {attachment_id, filename, mime_type, size, content_id, inline}.
    Inline parts (images referenced from the HTML body via `cid:`) are flagged so
    the document list can hide them — they're handled by the HTML resolver instead.
    """
    out: list[dict] = []

    def _walk(part: dict, depth: int = 0) -> None:
        if depth > 15:
            return
        body = part.get("body", {}) or {}
        att_id = body.get("attachmentId")
        if att_id:
            hdrs = {h.get("name", "").lower(): h.get("value", "") for h in part.get("headers", []) or []}
            content_id = hdrs.get("content-id", "").strip().strip("<>")
            disposition = hdrs.get("content-disposition", "").lower()
            inline = "inline" in disposition or bool(content_id)
            filename = part.get("filename") or content_id or "archivo"
            out.append({
                "attachment_id": att_id,
                "filename": filename,
                "mime_type": part.get("mimeType", "application/octet-stream"),
                "size": body.get("size", 0),
                "content_id": content_id,
                "inline": inline,
            })
        for p in part.get("parts", []) or []:
            _walk(p, depth + 1)

    _walk(payload)
    return out


async def _email_gmail_id(email_id: int) -> str:
    """Resolve a local email row id to its Gmail message id, or 404."""
    db = _require_db()
    cursor = await db._db.execute("SELECT gmail_id FROM gmail_emails WHERE id = ?", (email_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Correo no encontrado")
    return row["gmail_id"]


@router.get("/emails/{email_id}/attachments")
async def list_attachments(email_id: int):
    """List real document attachments for an email (fetched live from Gmail)."""
    gmail_id = await _email_gmail_id(email_id)
    from openacm.tools.google_services import _get_google_service
    try:
        service = await _get_google_service("gmail", "v1")
        msg = service.users().messages().get(userId="me", id=gmail_id, format="full").execute()
    except Exception as exc:
        log.warning("Failed to fetch attachments", email_id=email_id, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Error al consultar Gmail: {exc}")

    parts = _collect_attachment_parts(msg.get("payload", {}))
    # Only surface real documents — inline images belong to the HTML body.
    docs = [
        {"attachment_id": p["attachment_id"], "filename": p["filename"],
         "mime_type": p["mime_type"], "size": p["size"]}
        for p in parts if not p["inline"]
    ]
    return {"items": docs}


@router.get("/emails/{email_id}/attachments/{attachment_id}")
async def download_attachment(email_id: int, attachment_id: str):
    """Stream a single attachment's bytes. Disposition is inline so browsers can
    preview images/PDFs; the frontend forces a download for other types."""
    gmail_id = await _email_gmail_id(email_id)
    from openacm.tools.google_services import _get_google_service
    try:
        service = await _get_google_service("gmail", "v1")
        # Re-walk the message to recover this attachment's filename + mime type.
        msg = service.users().messages().get(userId="me", id=gmail_id, format="full").execute()
        meta = next(
            (p for p in _collect_attachment_parts(msg.get("payload", {})) if p["attachment_id"] == attachment_id),
            None,
        )
        att = service.users().messages().attachments().get(
            userId="me", messageId=gmail_id, id=attachment_id,
        ).execute()
    except Exception as exc:
        log.warning("Failed to download attachment", email_id=email_id, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Error al descargar adjunto: {exc}")

    data = att.get("data", "")
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    mime = meta["mime_type"] if meta else "application/octet-stream"
    filename = (meta["filename"] if meta else "archivo").replace('"', "")

    from fastapi import Response
    from urllib.parse import quote
    return Response(
        content=raw,
        media_type=mime,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/emails/{email_id}/html")
async def email_html(email_id: int):
    """Return the email's HTML body with inline `cid:` images resolved to data URIs.

    This is what makes embedded images actually render in the viewer. Falls back to
    the stored body_html if Gmail can't be reached, so the viewer never goes blank.
    """
    db = _require_db()
    cursor = await db._db.execute(
        "SELECT gmail_id, body_html FROM gmail_emails WHERE id = ?", (email_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Correo no encontrado")

    html = row["body_html"] or ""
    if not html or "cid:" not in html:
        return {"html": html, "resolved": False}

    from openacm.tools.google_services import _get_google_service
    try:
        service = await _get_google_service("gmail", "v1")
        msg = service.users().messages().get(userId="me", id=row["gmail_id"], format="full").execute()
        inline_parts = [p for p in _collect_attachment_parts(msg.get("payload", {})) if p["content_id"]]

        for p in inline_parts:
            att = service.users().messages().attachments().get(
                userId="me", messageId=row["gmail_id"], id=p["attachment_id"],
            ).execute()
            data = att.get("data", "")
            b64 = base64.b64encode(
                base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
            ).decode("ascii")
            data_uri = f"data:{p['mime_type']};base64,{b64}"
            # Replace src="cid:ID" / src='cid:ID' / src=cid:ID for this content-id.
            cid = re.escape(p["content_id"])
            html = re.sub(rf"""(["'])cid:{cid}\1""", lambda m, u=data_uri: m.group(1) + u + m.group(1), html)
            html = re.sub(rf"""(?<==)cid:{cid}(?=[\s>])""", data_uri, html)
    except Exception as exc:
        log.warning("Failed to resolve inline images", email_id=email_id, error=str(exc))
        return {"html": row["body_html"] or "", "resolved": False}

    return {"html": html, "resolved": True}


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

    # If auto_apply_label was just turned ON, apply labels retroactively in background.
    # Read state is NOT applied retroactively — it syncs per-click, not in bulk.
    proc = _processor
    if proc:
        apply_label_on = updates.get("auto_apply_label") == "true" and old.get("auto_apply_label") != "true"
        if apply_label_on:
            asyncio.create_task(proc.apply_retroactive(
                mark_read=False,
                apply_label=True,
            ))

    _DIGEST_KEYS = {"digest_enabled", "digest_time", "digest_days", "digest_agent_id", "digest_chat_id"}
    if any(k in updates for k in _DIGEST_KEYS) and _plugin:
        _plugin._start_digest_cron()

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
    """Check if Gmail OAuth is configured and return the authenticated email."""
    global _cached_auth_email
    from pathlib import Path
    creds_path = Path("config/google_credentials.json")
    token_path = Path("config/google_token.json")
    configured = creds_path.exists()
    has_token = token_path.exists()

    if has_token and _cached_auth_email is None:
        try:
            from openacm.plugins.gmail_classifier.processor import (
                _get_gmail_service, _get_authenticated_email,
            )
            svc = await _get_gmail_service()
            _cached_auth_email = await _get_authenticated_email(svc)
        except Exception as exc:
            log.debug("auth_status: could not resolve email", error=str(exc))

    return {
        "configured": configured,
        "has_token": has_token,
        "ready": configured and has_token,
        "email": _cached_auth_email,
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


@router.post("/summary/test-send")
async def test_send_digest():
    """Generate the summary and emit channel:send immediately (for testing config)."""
    import datetime as _dt
    db = _require_db()
    llm = _require_llm()
    if _event_bus is None:
        raise HTTPException(status_code=503, detail="Event bus no disponible")

    cursor = await db._db.execute(
        "SELECT key, value FROM gmail_classifier_settings "
        "WHERE key IN ('digest_agent_id', 'digest_chat_id')"
    )
    cfg = {r["key"]: r["value"] for r in await cursor.fetchall()}
    agent_id_str = cfg.get("digest_agent_id", "")
    chat_id = cfg.get("digest_chat_id", "")

    if not agent_id_str or not chat_id:
        raise HTTPException(
            status_code=400,
            detail="digest_agent_id o digest_chat_id no configurado",
        )
    try:
        agent_id = int(agent_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="digest_agent_id inválido")

    from openacm.plugins.gmail_classifier.summary import generate_inbox_summary
    try:
        summary = await generate_inbox_summary(db, llm, _event_bus)
        await _event_bus.emit("channel:send", {
            "agent_id": agent_id,
            "target_id": chat_id,
            "text": summary,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"sent": True}


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
