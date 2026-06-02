"""Gmail Classifier — FastAPI router for all API endpoints."""
from __future__ import annotations

import asyncio
import base64
import re
from email.mime.text import MIMEText
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = structlog.get_logger()

router = APIRouter(prefix="/gmail-classifier", tags=["gmail-classifier"])

# Set by GmailClassifierPlugin.on_start()
_db: Any = None
_processor: Any = None


def _require_db():
    if _db is None:
        raise HTTPException(status_code=503, detail="Gmail Classifier not initialized")
    return _db


def _require_processor():
    if _processor is None:
        raise HTTPException(status_code=503, detail="Gmail Classifier processor not initialized")
    return _processor


# ─── Pydantic models ─────────────────────────────────────────────────────────

class CategoryBody(BaseModel):
    name: str
    description: str = ""
    color: str = "#6366f1"
    icon: str = "Tag"


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


class CronBody(BaseModel):
    schedule: str


# ─── Categories ──────────────────────────────────────────────────────────────

@router.get("/categories")
async def list_categories():
    db = _require_db()
    cursor = await db._db.execute(
        "SELECT gc.id, gc.name, gc.description, gc.color, gc.icon, "
        "COUNT(ge.id) as email_count "
        "FROM gmail_categories gc "
        "LEFT JOIN gmail_emails ge ON ge.category_id = gc.id "
        "GROUP BY gc.id ORDER BY gc.id"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@router.post("/categories")
async def create_category(body: CategoryBody):
    db = _require_db()
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    try:
        cursor = await db._db.execute(
            "INSERT INTO gmail_categories (name, description, color, icon) VALUES (?, ?, ?, ?)",
            (body.name.strip(), body.description, body.color, body.icon),
        )
        await db._db.commit()
        row_cursor = await db._db.execute(
            "SELECT * FROM gmail_categories WHERE id = ?", (cursor.lastrowid,)
        )
        row = await row_cursor.fetchone()
        return dict(row)
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
    await db._db.execute(
        "UPDATE gmail_categories SET name=?, description=?, color=?, icon=? WHERE id=?",
        (body.name.strip(), body.description, body.color, body.icon, cat_id),
    )
    await db._db.commit()
    cursor2 = await db._db.execute("SELECT * FROM gmail_categories WHERE id = ?", (cat_id,))
    return dict(await cursor2.fetchone())


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
    await db._db.execute(
        "UPDATE gmail_emails SET category_id = ? WHERE id = ?",
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
        return {"success": True, "to": row["sender_email"]}

    except Exception as exc:
        log.error("Failed to send reply", email_id=email_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to send reply: {exc}")


# ─── Processing ───────────────────────────────────────────────────────────────

@router.post("/process")
async def start_process(body: ProcessBody):
    proc = _require_processor()
    if proc.is_running:
        raise HTTPException(status_code=409, detail="Processing already in progress")
    asyncio.create_task(proc.process(body.since_date))
    return {"started": True, "since_date": body.since_date}


@router.get("/process/status")
async def process_status():
    proc = _require_processor()
    return proc.status


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
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    for key, value in updates.items():
        await db._db.execute(
            "INSERT INTO gmail_classifier_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    await db._db.commit()
    cursor = await db._db.execute("SELECT key, value FROM gmail_classifier_settings")
    rows = await cursor.fetchall()
    return {r["key"]: r["value"] for r in rows}


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
