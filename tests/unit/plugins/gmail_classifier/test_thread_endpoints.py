"""Tests for the /threads endpoints in the gmail_classifier router."""
from __future__ import annotations

import pytest
import aiosqlite
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

import openacm.plugins.gmail_classifier.router as gcr


@pytest.fixture()
async def db_with_threads(tmp_path):
    """SQLite file DB with two threads seeded."""
    db_path = tmp_path / "test.db"
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    await conn.executescript("""
        CREATE TABLE gmail_categories (
            id INTEGER PRIMARY KEY,
            name TEXT,
            color TEXT DEFAULT '#6366f1',
            icon TEXT DEFAULT 'Tag'
        );
        CREATE TABLE gmail_emails (
            id INTEGER PRIMARY KEY,
            gmail_id TEXT,
            thread_id TEXT,
            subject TEXT,
            sender_name TEXT,
            sender_email TEXT,
            snippet TEXT,
            body_text TEXT,
            body_html TEXT,
            category_id INTEGER,
            is_read INTEGER DEFAULT 0,
            is_replied INTEGER DEFAULT 0,
            received_at TEXT,
            manual_override INTEGER DEFAULT 0
        );
    """)
    await conn.execute("INSERT INTO gmail_categories VALUES (1, 'Work', '#6366f1', 'Tag')")
    await conn.execute("INSERT INTO gmail_categories VALUES (2, 'Personal', '#10b981', 'Star')")

    # Thread A — 2 messages, 1 unread
    await conn.execute(
        "INSERT INTO gmail_emails VALUES (1,'gid1','tid-A','Hello team','Carlos','carlos@co.com',"
        "'lets meet','lets meet',NULL,1,1,0,'2026-06-10T08:00:00',0)"
    )
    await conn.execute(
        "INSERT INTO gmail_emails VALUES (2,'gid2','tid-A','Re: Hello team','Me','me@co.com',"
        "'sure thing','sure thing',NULL,1,0,0,'2026-06-10T09:00:00',0)"
    )

    # Thread B — 1 message, unread, different category
    await conn.execute(
        "INSERT INTO gmail_emails VALUES (3,'gid3','tid-B','Invoice #42','Vendor','v@v.com',"
        "'please pay','please pay',NULL,2,0,0,'2026-06-11T10:00:00',0)"
    )

    await conn.commit()

    class FakeDB:
        _db = conn

    original_db = gcr._db
    gcr._db = FakeDB()
    yield conn
    gcr._db = original_db
    await conn.close()


@pytest.fixture()
def app():
    a = FastAPI()
    a.include_router(gcr.router)
    return a


async def test_list_threads_returns_two_threads(db_with_threads, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/gmail-classifier/threads")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


async def test_list_threads_category_filter(db_with_threads, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/gmail-classifier/threads?category_id=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["thread_id"] == "tid-B"


async def test_list_threads_search(db_with_threads, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/gmail-classifier/threads?search=Invoice")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["thread_id"] == "tid-B"


async def test_list_threads_has_participants(db_with_threads, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/gmail-classifier/threads")
    items = resp.json()["items"]
    tid_a = next(i for i in items if i["thread_id"] == "tid-A")
    assert len(tid_a["participants"]) == 2
    emails = [p["email"] for p in tid_a["participants"]]
    assert "carlos@co.com" in emails
    assert "me@co.com" in emails


async def test_list_threads_unread_count(db_with_threads, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/gmail-classifier/threads")
    items = resp.json()["items"]
    tid_a = next(i for i in items if i["thread_id"] == "tid-A")
    assert tid_a["message_count"] == 2
    assert tid_a["unread_count"] == 1  # only msg 2 is unread
