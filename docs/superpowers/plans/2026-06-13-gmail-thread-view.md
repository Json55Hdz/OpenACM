# Gmail Classifier — Thread View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-message email list in the Gmail Classifier with a grouped-by-thread view — one row per Gmail conversation in the left panel, full timeline on click in the right panel.

**Architecture:** 5 backend changes to `router.py` (4 new thread endpoints + update auth-status to include the authenticated user's email). 2 new frontend components (`ThreadList.tsx`, `ThreadDetail.tsx`). `page.tsx` state refactored from per-message (`Email[]`) to per-thread (`Thread[]` + `Message[]`). No DB schema changes needed — `thread_id` already exists on `gmail_emails`.

**Tech Stack:** FastAPI + aiosqlite async SQLite (backend), SQLite CTEs for thread grouping, Next.js 14 / React 18 (frontend).

---

## File Map

| Action | Path |
|--------|------|
| Modify | `src/openacm/plugins/gmail_classifier/router.py` |
| Create | `frontend/app/gmail-classifier/components/ThreadList.tsx` |
| Create | `frontend/app/gmail-classifier/components/ThreadDetail.tsx` |
| Modify | `frontend/app/gmail-classifier/page.tsx` |
| Create | `tests/unit/plugins/gmail_classifier/test_thread_endpoints.py` |

---

## Task 1: Backend — add `email` field to `auth-status`

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/router.py`

The current `GET /auth-status` returns `{configured, has_token, ready}`. The frontend needs `email` to distinguish "Yo" from other participants in the thread timeline.

**Strategy:** cache the email in a module-level var (`_cached_auth_email`) on first call. Subsequent calls return from cache instantly. If the Gmail API call fails (no valid token), `email` is `null`.

- [ ] **Step 1: Add the module-level cache variable**

Open `router.py`. After the existing module-level vars (`_db`, `_processor`, etc., lines 20–26), add:

```python
_cached_auth_email: str | None = None
```

- [ ] **Step 2: Replace the `auth_status` function**

Find the existing `auth_status` function (around line 1025) and replace it entirely:

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/router.py
git commit -m "feat(gmail): add email field to auth-status response"
```

---

## Task 2: Backend — `GET /gmail-classifier/threads`

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/router.py`
- Create: `tests/unit/plugins/gmail_classifier/test_thread_endpoints.py`

Returns a paginated list of threads. Each thread aggregates all messages that share the same `thread_id`. Emails with `thread_id = NULL` are treated as single-message threads using their `gmail_id` as a fallback.

**The SQL approach:** a CTE groups `gmail_emails` by `COALESCE(thread_id, gmail_id)` and uses correlated subqueries to pull subject/category/snippet from the first/last message. Category filter and search happen on the outer query. Participants are fetched in a second bulk query.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/plugins/gmail_classifier/test_thread_endpoints.py`:

```python
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
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/unit/plugins/gmail_classifier/test_thread_endpoints.py -v
```

Expected: FAIL — `404 Not Found` on `/gmail-classifier/threads` (endpoint doesn't exist yet).

- [ ] **Step 3: Add `GET /threads` to `router.py`**

Add a Pydantic model for the category body used in thread endpoints, and the endpoint. Insert after the `# ─── Emails` section (after line 410 in the current file — right after `list_emails`):

```python
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
```

- [ ] **Step 4: Run the tests again**

```
pytest tests/unit/plugins/gmail_classifier/test_thread_endpoints.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/router.py \
        tests/unit/plugins/gmail_classifier/test_thread_endpoints.py
git commit -m "feat(gmail): GET /threads endpoint with category filter, search, participants"
```

---

## Task 3: Backend — `GET /gmail-classifier/threads/{thread_id}/messages`

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/router.py`
- Modify: `tests/unit/plugins/gmail_classifier/test_thread_endpoints.py`

Returns all messages in a thread ordered chronologically (oldest first). Returns the same fields as `GET /emails` rows.

- [ ] **Step 1: Add failing test**

Append to `test_thread_endpoints.py`:

```python
async def test_thread_messages_returns_ordered(db_with_threads, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/gmail-classifier/threads/tid-A/messages")
    assert resp.status_code == 200
    msgs = resp.json()
    assert len(msgs) == 2
    # Ordered oldest first
    assert msgs[0]["gmail_id"] == "gid1"
    assert msgs[1]["gmail_id"] == "gid2"


async def test_thread_messages_404_unknown_thread(db_with_threads, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/gmail-classifier/threads/no-such-thread/messages")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/unit/plugins/gmail_classifier/test_thread_endpoints.py::test_thread_messages_returns_ordered -v
```

Expected: FAIL — endpoint doesn't exist yet (404 or route not found).

- [ ] **Step 3: Add the endpoint to `router.py`** (insert right after `list_threads`)

```python
@router.get("/threads/{thread_id}/messages")
async def list_thread_messages(thread_id: str):
    db = _require_db()
    rows = await (await db._db.execute(
        """
        SELECT ge.*, gc.name AS category_name, gc.color AS category_color, gc.icon AS category_icon
        FROM gmail_emails ge
        LEFT JOIN gmail_categories gc ON ge.category_id = gc.id
        WHERE COALESCE(ge.thread_id, ge.gmail_id) = ?
        ORDER BY ge.received_at ASC
        """,
        (thread_id,),
    )).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="Thread not found")
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests**

```
pytest tests/unit/plugins/gmail_classifier/test_thread_endpoints.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/router.py \
        tests/unit/plugins/gmail_classifier/test_thread_endpoints.py
git commit -m "feat(gmail): GET /threads/{id}/messages endpoint"
```

---

## Task 4: Backend — `PATCH /gmail-classifier/threads/{thread_id}/read`

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/router.py`
- Modify: `tests/unit/plugins/gmail_classifier/test_thread_endpoints.py`

Marks all messages in the thread as read in the local DB. If `auto_mark_read = "true"`, also removes the `UNREAD` Gmail label from each message via the API (fire and forget — runs in the background so the endpoint doesn't block on network calls).

- [ ] **Step 1: Add the settings table to the test DB and a failing test**

Append to `test_thread_endpoints.py`:

```python
async def test_patch_thread_read_marks_all_messages(db_with_threads, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/gmail-classifier/threads/tid-A/read")
    assert resp.status_code == 200

    # Verify DB: both messages in tid-A are now read
    conn = db_with_threads
    rows = await (await conn.execute(
        "SELECT is_read FROM gmail_emails WHERE thread_id = 'tid-A'"
    )).fetchall()
    assert all(r["is_read"] == 1 for r in rows)


async def test_patch_thread_read_404(db_with_threads, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/gmail-classifier/threads/no-such/read")
    assert resp.status_code == 404
```

Note: the `db_with_threads` fixture doesn't create `gmail_classifier_settings` (so `auto_mark_read` lookup returns nothing — that's fine, it just won't sync to Gmail, which is the correct test behavior).

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/unit/plugins/gmail_classifier/test_thread_endpoints.py::test_patch_thread_read_marks_all_messages -v
```

Expected: FAIL.

- [ ] **Step 3: Add the endpoint** (insert after `list_thread_messages`)

```python
@router.patch("/threads/{thread_id}/read")
async def mark_thread_read(thread_id: str):
    db = _require_db()

    # Verify thread exists
    row = await (await db._db.execute(
        "SELECT COUNT(*) AS cnt FROM gmail_emails WHERE COALESCE(thread_id, gmail_id) = ?",
        (thread_id,),
    )).fetchone()
    if not row or row["cnt"] == 0:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Fetch gmail_ids BEFORE updating so we know which ones were unread
    unread_rows = await (await db._db.execute(
        "SELECT gmail_id FROM gmail_emails WHERE COALESCE(thread_id, gmail_id) = ? AND is_read = 0",
        (thread_id,),
    )).fetchall()
    gmail_ids = [r["gmail_id"] for r in unread_rows]

    await db._db.execute(
        "UPDATE gmail_emails SET is_read = 1 WHERE COALESCE(thread_id, gmail_id) = ?",
        (thread_id,),
    )
    await db._db.commit()

    # Sync to Gmail in background if setting is on (non-blocking).
    if gmail_ids:
        async def _sync_to_gmail(ids: list[str]) -> None:
            try:
                sc = await db._db.execute(
                    "SELECT value FROM gmail_classifier_settings WHERE key = 'auto_mark_read'"
                )
                sr = await sc.fetchone()
                if not (sr and sr["value"] == "true"):
                    return
                from openacm.tools.google_services import _get_google_service
                service = await _get_google_service("gmail", "v1")
                await asyncio.gather(*[
                    asyncio.to_thread(
                        service.users().messages().modify(
                            userId="me", id=gid, body={"removeLabelIds": ["UNREAD"]}
                        ).execute
                    )
                    for gid in ids
                ], return_exceptions=True)
            except Exception as exc:
                log.warning("mark_thread_read: Gmail sync failed", thread_id=thread_id, error=str(exc))

        asyncio.create_task(_sync_to_gmail(gmail_ids))

    return {"thread_id": thread_id, "marked_read": len(gmail_ids)}
```

- [ ] **Step 4: Run tests**

```
pytest tests/unit/plugins/gmail_classifier/test_thread_endpoints.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/router.py \
        tests/unit/plugins/gmail_classifier/test_thread_endpoints.py
git commit -m "feat(gmail): PATCH /threads/{id}/read — mark all thread messages as read"
```

---

## Task 5: Backend — `PATCH /gmail-classifier/threads/{thread_id}/category`

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/router.py`
- Modify: `tests/unit/plugins/gmail_classifier/test_thread_endpoints.py`

Updates `category_id` for ALL messages in the thread and sets `manual_override = 1` so the classifier won't overwrite the choice on the next cron run.

- [ ] **Step 1: Add failing test** (append to `test_thread_endpoints.py`)

```python
async def test_patch_thread_category_updates_all_messages(db_with_threads, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/gmail-classifier/threads/tid-A/category",
            json={"category_id": 2},
        )
    assert resp.status_code == 200

    conn = db_with_threads
    rows = await (await conn.execute(
        "SELECT category_id, manual_override FROM gmail_emails WHERE thread_id = 'tid-A'"
    )).fetchall()
    assert all(r["category_id"] == 2 for r in rows)
    assert all(r["manual_override"] == 1 for r in rows)


async def test_patch_thread_category_invalid_category(db_with_threads, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/gmail-classifier/threads/tid-A/category",
            json={"category_id": 9999},
        )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/unit/plugins/gmail_classifier/test_thread_endpoints.py::test_patch_thread_category_updates_all_messages -v
```

Expected: FAIL.

- [ ] **Step 3: Add the endpoint and Pydantic model** (insert in `router.py` after `mark_thread_read`)

First add the Pydantic model near the other models (after `RecategorizeBody`, around line 136):
```python
class ThreadCategoryBody(BaseModel):
    category_id: int
```

Then add the endpoint:

```python
@router.patch("/threads/{thread_id}/category")
async def recategorize_thread(thread_id: str, body: ThreadCategoryBody):
    db = _require_db()

    cat_row = await (await db._db.execute(
        "SELECT id FROM gmail_categories WHERE id = ?", (body.category_id,)
    )).fetchone()
    if not cat_row:
        raise HTTPException(status_code=404, detail="Category not found")

    cnt_row = await (await db._db.execute(
        "SELECT COUNT(*) AS cnt FROM gmail_emails WHERE COALESCE(thread_id, gmail_id) = ?",
        (thread_id,),
    )).fetchone()
    if not cnt_row or cnt_row["cnt"] == 0:
        raise HTTPException(status_code=404, detail="Thread not found")

    await db._db.execute(
        "UPDATE gmail_emails SET category_id = ?, manual_override = 1 "
        "WHERE COALESCE(thread_id, gmail_id) = ?",
        (body.category_id, thread_id),
    )
    await db._db.commit()
    return {"thread_id": thread_id, "category_id": body.category_id, "updated": cnt_row["cnt"]}
```

- [ ] **Step 4: Run all tests**

```
pytest tests/unit/plugins/gmail_classifier/test_thread_endpoints.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/router.py \
        tests/unit/plugins/gmail_classifier/test_thread_endpoints.py
git commit -m "feat(gmail): PATCH /threads/{id}/category — recategorize entire thread"
```

---

## Task 6: Frontend — `ThreadList.tsx`

**Files:**
- Create: `frontend/app/gmail-classifier/components/ThreadList.tsx`

Compact Gmail-style list. One row per thread. Unread dot, participant names (replacing the auth user with "Yo"), subject, latest snippet, smart date, and a count badge when `message_count > 1`.

- [ ] **Step 1: Create the file**

```tsx
'use client';

export interface Participant {
  name: string;
  email: string;
}

export interface Thread {
  thread_id: string;
  subject: string;
  category_id: number;
  category_name: string;
  category_color: string;
  category_icon: string;
  message_count: number;
  unread_count: number;
  latest_at: string;
  latest_snippet: string;
  participants: Participant[];
}

interface ThreadListProps {
  threads: Thread[];
  selectedId: string | null;
  authEmail: string | null;
  onSelect: (thread: Thread) => void;
}

function formatThreadDate(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffDays = Math.floor(diffMs / 86_400_000);
    if (diffDays === 0) {
      return d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' });
    }
    if (diffDays < 7) {
      return d.toLocaleDateString('es-CO', { weekday: 'short' });
    }
    return d.toLocaleDateString('es-CO', { day: '2-digit', month: 'short' });
  } catch {
    return '';
  }
}

function buildParticipantString(participants: Participant[], authEmail: string | null): string {
  return participants
    .map(p => (authEmail && p.email === authEmail ? 'Yo' : (p.name || p.email)))
    .join(', ');
}

export function ThreadList({ threads, selectedId, authEmail, onSelect }: ThreadListProps) {
  if (threads.length === 0) {
    return (
      <div className="w-72 flex-shrink-0 border-r border-[var(--acm-border)] flex items-center justify-center text-[var(--acm-fg-4)] text-[12px]">
        Sin conversaciones
      </div>
    );
  }

  return (
    <div className="w-72 flex-shrink-0 border-r border-[var(--acm-border)] overflow-y-auto acm-scroll">
      {threads.map(thread => {
        const unread = thread.unread_count > 0;
        const isSelected = selectedId === thread.thread_id;
        const participantStr = buildParticipantString(thread.participants, authEmail);

        return (
          <button
            key={thread.thread_id}
            onClick={() => onSelect(thread)}
            className={`w-full text-left px-4 py-3 border-b border-[var(--acm-border)] transition-colors ${
              isSelected
                ? 'bg-[var(--acm-accent-tint)] border-l-2 border-l-[var(--acm-accent)]'
                : 'hover:bg-[var(--acm-elev)]'
            }`}
          >
            <div className="flex items-start gap-2">
              {/* Unread dot */}
              <div
                className={`w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5 ${
                  unread ? 'bg-[var(--acm-accent)]' : 'bg-transparent'
                }`}
              />

              <div className="min-w-0 flex-1">
                {/* Row 1: participants + date + count badge */}
                <div className="flex items-center justify-between gap-1 mb-0.5">
                  <p className={`text-[12px] truncate ${unread ? 'text-[var(--acm-fg)] font-semibold' : 'text-[var(--acm-fg-2)]'}`}>
                    {participantStr || thread.subject}
                  </p>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    {thread.message_count > 1 && (
                      <span
                        className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
                          unread
                            ? 'bg-[var(--acm-accent)] text-white'
                            : 'bg-[var(--acm-elev)] text-[var(--acm-fg-4)]'
                        }`}
                      >
                        {thread.message_count}
                      </span>
                    )}
                    <span className="text-[10px] text-[var(--acm-fg-4)] mono">
                      {formatThreadDate(thread.latest_at)}
                    </span>
                  </div>
                </div>

                {/* Row 2: subject */}
                <p className={`text-[12px] truncate mb-0.5 ${unread ? 'text-[var(--acm-fg-2)] font-medium' : 'text-[var(--acm-fg-3)]'}`}>
                  {thread.subject}
                </p>

                {/* Row 3: snippet */}
                <p className="text-[11px] text-[var(--acm-fg-4)] truncate">
                  {thread.latest_snippet}
                </p>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/gmail-classifier/components/ThreadList.tsx
git commit -m "feat(gmail): ThreadList component — compact thread rows with unread dot and count badge"
```

---

## Task 7: Frontend — `ThreadDetail.tsx`

**Files:**
- Create: `frontend/app/gmail-classifier/components/ThreadDetail.tsx`

Timeline view of all messages in a thread. Sticky header with subject, category badge, participant count, and a "Ver en Gmail" link. Each message shows an avatar (green for "Yo", gray for others), sender + date, full HTML/text body, and attachments. Bottom bar: category selector + reply composer (targets the last message).

- [ ] **Step 1: Create the file**

```tsx
'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { CornerUpLeft, ExternalLink, ChevronDown, Paperclip, Download, FileText, Image as ImageIcon, File } from 'lucide-react';
import type { Thread } from './ThreadList';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Message {
  id: number;
  gmail_id: string;
  thread_id: string;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
  body_text: string;
  body_html: string;
  category_id: number;
  is_read: number;
  is_replied: number;
  received_at: string;
}

interface Category {
  id: number;
  name: string;
  color: string;
}

interface Attachment {
  attachment_id: string;
  filename: string;
  mime_type: string;
  size: number;
}

interface ThreadDetailProps {
  thread: Thread | null;
  messages: Message[];
  categories: Category[];
  authEmail: string | null;
  onRecategorize: (threadId: string, categoryId: number) => void;
  autoReplyCategoryIds: number[];
  token: string | undefined;
  suggestionTimeoutMs: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const HTML_BASE_STYLES = `
  <style>
    * { box-sizing: border-box; }
    html, body { max-width: 100%; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 13px; line-height: 1.6; color: #1a1a1a; background: #ffffff;
      margin: 0; padding: 12px; word-break: break-word; overflow-wrap: anywhere;
    }
    img { max-width: 100% !important; height: auto !important; }
    a { color: #2563eb; }
    p { margin: 0 0 8px; }
    table { max-width: 100% !important; border-collapse: collapse; }
    td, th { word-break: break-word; }
    blockquote { margin: 0 0 8px; padding: 4px 0 4px 12px; border-left: 3px solid #d1d5db; color: #4b5563; }
    hr { border: none; border-top: 1px solid #e5e7eb; margin: 12px 0; }
  </style>
`;

function HtmlEmail({ html }: { html: string }) {
  const src = `<!DOCTYPE html><html><head><meta charset="utf-8">${HTML_BASE_STYLES}</head><body>${html}</body></html>`;
  return (
    <iframe
      srcDoc={src}
      sandbox="allow-same-origin"
      className="w-full border-0 rounded-[var(--acm-radius)] bg-white"
      style={{ minHeight: '120px', height: '100%' }}
      onLoad={e => {
        const frame = e.currentTarget;
        try {
          const h = frame.contentDocument?.body?.scrollHeight;
          if (h) frame.style.height = `${h + 24}px`;
        } catch { /* cross-origin */ }
      }}
    />
  );
}

function PlainTextBody({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/).map(p => p.trim()).filter(Boolean);
  return (
    <div className="space-y-2">
      {paragraphs.map((para, i) => (
        <p key={i} className="text-[13px] text-[var(--acm-fg-2)] leading-relaxed break-words">
          {para.split('\n').map((line, j) => (
            <span key={j}>{line}{j < para.split('\n').length - 1 && <br />}</span>
          ))}
        </p>
      ))}
    </div>
  );
}

function formatBytes(n: number): string {
  if (!n) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function attachmentIcon(mime: string) {
  if (mime.startsWith('image/')) return ImageIcon;
  if (mime === 'application/pdf' || mime.startsWith('text/')) return FileText;
  return File;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function formatMsgDate(iso: string): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('es-CO', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return ''; }
}

// ── Per-message sub-component ─────────────────────────────────────────────────

function MessageCard({
  msg,
  isMe,
  token,
}: {
  msg: Message;
  isMe: boolean;
  token: string | undefined;
}) {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [resolvedHtml, setResolvedHtml] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    fetch(`/api/gmail-classifier/emails/${msg.id}/attachments`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => (r.ok ? r.json() : { items: [] }))
      .then(data => { if (!cancelled) setAttachments(data.items ?? []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [msg.id, token]);

  useEffect(() => {
    if (!token) return;
    const stored = `${msg.body_html || ''}${msg.body_text || ''}`;
    if (!stored.includes('cid:')) return;
    let cancelled = false;
    fetch(`/api/gmail-classifier/emails/${msg.id}/html`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => (r.ok ? r.json() : null))
      .then(data => { if (!cancelled && data?.resolved && data.html) setResolvedHtml(data.html); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [msg.id, token]);

  const downloadAttachment = useCallback(async (att: Attachment) => {
    if (!token) return;
    setDownloadingId(att.attachment_id);
    try {
      const res = await fetch(
        `/api/gmail-classifier/emails/${msg.id}/attachments/${att.attachment_id}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const previewable = att.mime_type.startsWith('image/') || att.mime_type === 'application/pdf';
      if (previewable) {
        window.open(url, '_blank', 'noopener');
      } else {
        const a = document.createElement('a');
        a.href = url; a.download = att.filename;
        document.body.appendChild(a); a.click(); a.remove();
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      console.error('[attachment] download failed:', err);
    } finally {
      setDownloadingId(null);
    }
  }, [msg.id, token]);

  const looksLikeHtml = (s: string) =>
    /<!DOCTYPE|<html|<body|<div|<table|<td|<span|<p\s|<br|@media|\.u-row/i.test(s.slice(0, 500));
  const storedHtml = msg.body_html || (looksLikeHtml(msg.body_text) ? msg.body_text : '');
  const htmlToRender = resolvedHtml ?? storedHtml;
  const hasHtml = !!htmlToRender;
  const bodyContent = msg.body_text || msg.snippet;

  const avatarLabel = isMe ? 'Yo' : initials(msg.sender_name || msg.sender_email || '?');

  return (
    <div className="flex gap-3 px-5 py-4 border-b border-[var(--acm-border)]">
      {/* Avatar */}
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-bold flex-shrink-0 mt-0.5 ${
          isMe
            ? 'bg-emerald-900/60 text-emerald-400'
            : 'bg-[var(--acm-elev)] text-[var(--acm-fg-3)]'
        }`}
      >
        {avatarLabel}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Meta */}
        <div className="flex items-baseline gap-2 mb-2">
          <span className={`text-[12px] font-semibold ${isMe ? 'text-emerald-400' : 'text-[var(--acm-fg)]'}`}>
            {isMe ? 'Yo' : (msg.sender_name || msg.sender_email)}
          </span>
          {!isMe && msg.sender_name && (
            <span className="text-[11px] text-[var(--acm-fg-4)]">&lt;{msg.sender_email}&gt;</span>
          )}
          <span className="text-[10px] text-[var(--acm-fg-4)] mono ml-auto flex-shrink-0">
            {formatMsgDate(msg.received_at)}
          </span>
        </div>

        {/* Body */}
        {hasHtml ? (
          <HtmlEmail html={htmlToRender} />
        ) : bodyContent ? (
          <PlainTextBody text={bodyContent} />
        ) : (
          <p className="text-[12px] text-[var(--acm-fg-4)] italic">Sin contenido.</p>
        )}

        {/* Attachments */}
        {attachments.length > 0 && (
          <div className="mt-3">
            <div className="flex items-center gap-1.5 mb-1.5">
              <Paperclip size={11} className="text-[var(--acm-fg-4)]" />
              <span className="text-[11px] text-[var(--acm-fg-4)]">
                {attachments.length} adjunto{attachments.length === 1 ? '' : 's'}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {attachments.map(att => {
                const Icon = attachmentIcon(att.mime_type);
                const isDownloading = downloadingId === att.attachment_id;
                return (
                  <button
                    key={att.attachment_id}
                    onClick={() => downloadAttachment(att)}
                    disabled={isDownloading}
                    className="group flex items-center gap-2 max-w-[220px] bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] px-2 py-1.5 hover:border-[var(--acm-accent)] transition-colors text-left"
                  >
                    <Icon size={14} className="text-[var(--acm-accent)] flex-shrink-0" />
                    <span className="flex flex-col min-w-0">
                      <span className="text-[11px] text-[var(--acm-fg-2)] truncate">{att.filename}</span>
                      {att.size > 0 && (
                        <span className="text-[10px] text-[var(--acm-fg-4)]">{formatBytes(att.size)}</span>
                      )}
                    </span>
                    {isDownloading ? (
                      <div className="h-3 w-3 rounded-full border-2 border-[var(--acm-fg-4)] border-t-transparent animate-spin flex-shrink-0" />
                    ) : (
                      <Download size={12} className="text-[var(--acm-fg-4)] group-hover:text-[var(--acm-accent)] flex-shrink-0" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function ThreadDetail({
  thread,
  messages,
  categories,
  authEmail,
  onRecategorize,
  autoReplyCategoryIds,
  token,
  suggestionTimeoutMs,
}: ThreadDetailProps) {
  const [localMessages, setLocalMessages] = useState<Message[]>(messages);
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyText, setReplyText] = useState('');
  const [sending, setSending] = useState(false);
  const [replySuccess, setReplySuccess] = useState(false);
  const [replyError, setReplyError] = useState('');
  const [suggestionLoading, setSuggestionLoading] = useState(false);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  const suggestionCache = useRef<Map<number, string>>(new Map());

  // Sync localMessages when parent provides new messages (thread switch)
  useEffect(() => {
    setLocalMessages(messages);
    setReplyOpen(false);
    setReplyText('');
    setReplySuccess(false);
    setReplyError('');
    setSuggestionError(null);
  }, [messages]);

  const lastMsg = localMessages[localMessages.length - 1] ?? null;

  // Auto-reply suggestion for last message
  useEffect(() => {
    if (!lastMsg || !autoReplyCategoryIds || !token) return;
    const categoryEnabled = autoReplyCategoryIds.includes(lastMsg.category_id);
    if (!categoryEnabled) return;
    const cached = suggestionCache.current.get(lastMsg.id);
    if (cached !== undefined) { setReplyText(cached); return; }

    let timedOut = false;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => { timedOut = true; controller.abort(); }, suggestionTimeoutMs);
    setSuggestionLoading(true);

    fetch(`/api/gmail-classifier/emails/${lastMsg.id}/suggest-reply`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then(r => r.json())
      .then(data => {
        if (data.eligible && data.body) {
          suggestionCache.current.set(lastMsg.id, data.body);
          setReplyText(data.body);
        }
      })
      .catch(err => {
        if (err.name === 'AbortError' && !timedOut) return;
        const secs = Math.round((suggestionTimeoutMs) / 1000);
        setSuggestionError(timedOut ? `Tiempo agotado (${secs}s)` : `Error: ${err?.message}`);
      })
      .finally(() => { setSuggestionLoading(false); clearTimeout(timeoutId); });

    return () => { controller.abort(); clearTimeout(timeoutId); };
  }, [lastMsg?.id, autoReplyCategoryIds, token, suggestionTimeoutMs]);

  const handleSendReply = async () => {
    if (!lastMsg || !replyText.trim()) return;
    setSending(true);
    setReplyError('');
    try {
      const res = await fetch(`/api/gmail-classifier/emails/${lastMsg.id}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ body: replyText.trim() }),
      });
      if (res.ok) {
        setLocalMessages(prev =>
          prev.map(m => m.id === lastMsg.id ? { ...m, is_replied: 1, is_read: 1 } : m)
        );
        setReplyText('');
        setReplySuccess(true);
        setReplyOpen(false);
        setTimeout(() => setReplySuccess(false), 4000);
      } else {
        setReplyError('Error al enviar. Verifica la conexión con Gmail.');
      }
    } catch {
      setReplyError('Error de conexión.');
    } finally {
      setSending(false);
    }
  };

  if (!thread) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-[var(--acm-fg-4)]">
        <div className="w-10 h-10 rounded-full bg-[var(--acm-elev)] flex items-center justify-center opacity-40">
          <CornerUpLeft size={20} />
        </div>
        <p className="text-[13px]">Selecciona una conversación</p>
      </div>
    );
  }

  const participantNames = thread.participants
    .map(p => (authEmail && p.email === authEmail ? 'Yo' : (p.name || p.email)))
    .join(', ');

  const gmailThreadUrl = `https://mail.google.com/mail/u/0/#all/${thread.thread_id}`;

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* ── Sticky header ── */}
      <div className="px-5 pt-4 pb-3 border-b border-[var(--acm-border)] flex-shrink-0">
        <div className="flex items-start justify-between gap-3 mb-1">
          <h2 className="text-[15px] font-semibold text-[var(--acm-fg)] leading-snug">
            {thread.subject}
          </h2>
          <a
            href={gmailThreadUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-secondary text-[11px] py-[5px] px-2.5 flex-shrink-0"
          >
            <ExternalLink size={11} /> Ver en Gmail
          </a>
        </div>
        <div className="flex items-center gap-3">
          <span
            className="text-[10px] px-2 py-0.5 rounded-full font-medium"
            style={{
              background: `${thread.category_color}22`,
              color: thread.category_color,
            }}
          >
            {thread.category_name}
          </span>
          <span className="text-[11px] text-[var(--acm-fg-4)]">
            {thread.message_count} mensaje{thread.message_count === 1 ? '' : 's'}
            {participantNames ? ` · ${participantNames}` : ''}
          </span>
          {replySuccess && (
            <span className="text-[11px] text-[var(--acm-ok)] ml-auto">✓ Respuesta enviada</span>
          )}
        </div>
      </div>

      {/* ── Timeline ── */}
      <div className="flex-1 overflow-y-auto acm-scroll min-h-0">
        {localMessages.map(msg => (
          <MessageCard
            key={msg.id}
            msg={msg}
            isMe={!!(authEmail && msg.sender_email === authEmail)}
            token={token}
          />
        ))}
      </div>

      {/* ── Bottom bar ── */}
      <div className="px-5 py-2.5 border-t border-[var(--acm-border)] bg-[var(--acm-elev)] flex items-center gap-2 flex-wrap flex-shrink-0">
        {/* Category selector */}
        <div className="relative">
          <select
            value={thread.category_id}
            onChange={e => onRecategorize(thread.thread_id, Number(e.target.value))}
            className="bg-[var(--acm-card)] border border-[var(--acm-border)] text-[var(--acm-fg-2)] text-[12px] rounded-[var(--acm-radius)] px-3 py-1.5 pr-7 appearance-none outline-none focus:border-[var(--acm-accent)] transition-colors cursor-pointer"
          >
            {categories.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <ChevronDown size={11} className="absolute right-2 top-2 text-[var(--acm-fg-4)] pointer-events-none" />
        </div>

        {lastMsg?.is_replied === 1 && (
          <span className="text-[11px] text-[var(--acm-ok)] flex items-center gap-1">
            <span className="dot dot-ok" /> Respondido
          </span>
        )}

        {suggestionLoading && (
          <span className="text-[11px] text-[var(--acm-fg-4)] flex items-center gap-1.5">
            <div className="h-3 w-3 rounded-full border-2 border-current border-t-transparent animate-spin" />
            Preparando respuesta…
          </span>
        )}
        {suggestionError && (
          <span className="text-[11px] text-[var(--acm-fg-4)]">{suggestionError}</span>
        )}

        <button
          onClick={() => setReplyOpen(o => !o)}
          className="btn-secondary text-[11px] py-[5px] px-2.5 ml-auto"
        >
          <CornerUpLeft size={12} />
          {replyOpen ? 'Cerrar' : 'Responder'}
        </button>
      </div>

      {/* ── Reply composer ── */}
      {replyOpen && lastMsg && (
        <div className="px-5 py-4 border-t border-[var(--acm-border)] flex-shrink-0 bg-[var(--acm-base)]">
          <p className="text-[11px] text-[var(--acm-fg-4)] mb-2">
            <CornerUpLeft size={11} className="inline mr-1" />
            Responder a <span className="text-[var(--acm-fg-3)]">{lastMsg.sender_email}</span>
          </p>
          <textarea
            value={replyText}
            onChange={e => setReplyText(e.target.value)}
            placeholder="Escribe tu respuesta…"
            rows={5}
            autoFocus
            className="w-full bg-[var(--acm-elev)] border border-[var(--acm-border)] text-[var(--acm-fg)] text-[13px] rounded-[var(--acm-radius)] px-3 py-2.5 resize-y outline-none focus:border-[var(--acm-accent)] transition-colors placeholder:text-[var(--acm-fg-4)] leading-relaxed"
          />
          <div className="flex items-center justify-between mt-2">
            <span className="text-[11px] text-[var(--acm-err)]">{replyError}</span>
            <div className="flex gap-2">
              <button onClick={() => setReplyOpen(false)} className="btn-secondary text-[12px] py-[6px] px-3">
                Cancelar
              </button>
              <button
                onClick={handleSendReply}
                disabled={sending || !replyText.trim()}
                className="btn-primary text-[12px] py-[6px] px-3"
              >
                {sending ? 'Enviando…' : 'Enviar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/gmail-classifier/components/ThreadDetail.tsx
git commit -m "feat(gmail): ThreadDetail component — timeline with avatars, attachments, reply composer"
```

---

## Task 8: Frontend — wire `page.tsx` to use threads

**Files:**
- Modify: `frontend/app/gmail-classifier/page.tsx`

Replace the per-message state (`emails`, `selectedEmail`) with per-thread state (`threads`, `selectedThread`, `threadMessages`, `authEmail`). Swap `EmailList` → `ThreadList` and `EmailDetail` → `ThreadDetail` in the split view. Keep all existing modals, toolbar, search bar, and cron polling untouched.

- [ ] **Step 1: Update imports at the top of `page.tsx`**

Replace:
```tsx
import { EmailList } from './components/EmailList';
import { EmailDetail } from './components/EmailDetail';
```
With:
```tsx
import { ThreadList } from './components/ThreadList';
import { ThreadDetail } from './components/ThreadDetail';
import type { Thread } from './components/ThreadList';
import type { Message } from './components/ThreadDetail';
```

- [ ] **Step 2: Update the `AuthStatus` interface**

Find:
```tsx
interface AuthStatus {
  configured: boolean;
  has_token: boolean;
  ready: boolean;
}
```
Replace with:
```tsx
interface AuthStatus {
  configured: boolean;
  has_token: boolean;
  ready: boolean;
  email: string | null;
}
```

- [ ] **Step 3: Replace per-message state with per-thread state**

Find this block (around line 136–139):
```tsx
const [emails, setEmails] = useState<Email[]>([]);
const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
const [selectedEmail, setSelectedEmail] = useState<Email | null>(null);
```
Replace with:
```tsx
const [threads, setThreads] = useState<Thread[]>([]);
const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
const [selectedThread, setSelectedThread] = useState<Thread | null>(null);
const [threadMessages, setThreadMessages] = useState<Message[]>([]);
const [authEmail, setAuthEmail] = useState<string | null>(null);
```

- [ ] **Step 4: Update `fetchAuthStatus` to capture `email`**

Find:
```tsx
const fetchAuthStatus = useCallback(async () => {
  try {
    const res = await apiFetch('/auth-status');
    if (res.ok) setAuthStatus(await res.json());
  } catch { /* ignore */ }
}, [apiFetch]);
```
Replace with:
```tsx
const fetchAuthStatus = useCallback(async () => {
  try {
    const res = await apiFetch('/auth-status');
    if (res.ok) {
      const data = await res.json();
      setAuthStatus(data);
      setAuthEmail(data.email ?? null);
    }
  } catch { /* ignore */ }
}, [apiFetch]);
```

- [ ] **Step 5: Replace `fetchEmails` with `fetchThreads`**

Find the entire `fetchEmails` function:
```tsx
const fetchEmails = useCallback(async () => {
  const q = searchQuery.trim();
  const params = new URLSearchParams({ page: '1', per_page: '50' });
  if (q) {
    params.set('search', q);
  } else if (selectedCategoryId !== null) {
    params.set('category_id', String(selectedCategoryId));
  }
  const res = await apiFetch(`/emails?${params}`);
  if (res.ok) {
    const data = await res.json();
    setEmails(data.items);
  }
}, [apiFetch, selectedCategoryId, searchQuery]);
```
Replace with:
```tsx
const fetchThreads = useCallback(async () => {
  const q = searchQuery.trim();
  const params = new URLSearchParams({ page: '1', per_page: '50' });
  if (q) {
    params.set('search', q);
  } else if (selectedCategoryId !== null) {
    params.set('category_id', String(selectedCategoryId));
  }
  const res = await apiFetch(`/threads?${params}`);
  if (res.ok) {
    const data = await res.json();
    setThreads(data.items);
  }
}, [apiFetch, selectedCategoryId, searchQuery]);
```

- [ ] **Step 6: Update `pollStatus` to call `fetchThreads`**

In `pollStatus`, replace both occurrences of `fetchEmails()` with `fetchThreads()`.

- [ ] **Step 7: Update the background 30s poll to call `fetchThreads`**

In the `setInterval` effect, replace `fetchEmails()` with `fetchThreads()`.

- [ ] **Step 8: Update the effect that calls `fetchEmails` on dependency change**

Find:
```tsx
useEffect(() => {
  fetchEmails();
}, [fetchEmails]);
```
Replace with:
```tsx
useEffect(() => {
  fetchThreads();
}, [fetchThreads]);
```

- [ ] **Step 9: Add `handleThreadSelect` and `handleThreadRecategorize` — remove old handlers**

Remove `handleEmailSelect`, `handleEmailRead`, `handleRecategorize`, `handleReply`.

Add instead (right before the `notReady` constant):

```tsx
const handleThreadSelect = async (thread: Thread) => {
  setSelectedThread(thread);
  const res = await apiFetch(`/threads/${thread.thread_id}/messages`);
  if (res.ok) {
    setThreadMessages(await res.json());
  }
  if (thread.unread_count > 0) {
    void apiFetch(`/threads/${thread.thread_id}/read`, { method: 'PATCH' });
    setThreads(prev =>
      prev.map(t => t.thread_id === thread.thread_id ? { ...t, unread_count: 0 } : t)
    );
  }
};

const handleThreadRecategorize = async (threadId: string, categoryId: number) => {
  const res = await apiFetch(`/threads/${threadId}/category`, {
    method: 'PATCH',
    body: JSON.stringify({ category_id: categoryId }),
  });
  if (res.ok) {
    fetchThreads();
    fetchCategories();
    setSelectedThread(prev =>
      prev?.thread_id === threadId ? { ...prev, category_id: categoryId } : prev
    );
  }
};
```

- [ ] **Step 10: Replace the split view JSX**

Find the split view block:
```tsx
{/* Split view */}
<div className="flex flex-1 min-h-0">
  <EmailList
    emails={emails}
    selectedId={selectedEmail?.id ?? null}
    onSelect={handleEmailSelect}
  />
  <EmailDetail
    email={selectedEmail}
    categories={categories}
    onReadToggle={handleEmailRead}
    onRecategorize={handleRecategorize}
    onReply={handleReply}
    autoReplyCategoryIds={autoReplyCategoryIds}
    token={token ?? undefined}
    suggestionTimeoutMs={suggestionTimeoutMs}
  />
</div>
```
Replace with:
```tsx
{/* Split view */}
<div className="flex flex-1 min-h-0">
  <ThreadList
    threads={threads}
    selectedId={selectedThread?.thread_id ?? null}
    authEmail={authEmail}
    onSelect={handleThreadSelect}
  />
  <ThreadDetail
    thread={selectedThread}
    messages={threadMessages}
    categories={categories}
    authEmail={authEmail}
    onRecategorize={handleThreadRecategorize}
    autoReplyCategoryIds={autoReplyCategoryIds}
    token={token ?? undefined}
    suggestionTimeoutMs={suggestionTimeoutMs}
  />
</div>
```

- [ ] **Step 11: Update the search results count in the search bar**

Find:
```tsx
Búsqueda global · {emails.length} resultado{emails.length === 1 ? '' : 's'}
```
Replace with:
```tsx
Búsqueda global · {threads.length} resultado{threads.length === 1 ? '' : 's'}
```

- [ ] **Step 12: Update the `CategoryTabs` onSelect to reset `selectedThread`**

Find:
```tsx
onSelect={id => { setSelectedCategoryId(id); setSelectedEmail(null); }}
```
Replace with:
```tsx
onSelect={id => { setSelectedCategoryId(id); setSelectedThread(null); setThreadMessages([]); }}
```

- [ ] **Step 13: Update the `CategoryManager` onSaved callback**

Find:
```tsx
onSaved={() => { fetchCategories(); fetchEmails(); }}
```
Replace with:
```tsx
onSaved={() => { fetchCategories(); fetchThreads(); }}
```

- [ ] **Step 14: Remove the `Email` interface** from `page.tsx` (it's no longer used there — the `Thread` and `Message` types come from the component files).

Find and delete the `interface Email { ... }` block (lines 36–53 in the current file).

- [ ] **Step 15: Run the app and smoke test**

```
uv run openacm
```

Open `http://localhost:PORT/gmail-classifier`. Verify:
1. Thread list shows grouped conversations, not individual messages.
2. Clicking a thread opens the timeline showing all messages in order.
3. Opening an unread thread marks it as read (dot disappears).
4. Category selector in the detail panel updates all messages in the thread.
5. Reply composer appears on "Responder" click and sends to the last message.
6. Search filters threads (any message matching = thread appears).
7. Category tab filter works.

- [ ] **Step 16: Commit**

```bash
git add frontend/app/gmail-classifier/page.tsx
git commit -m "feat(gmail): wire page.tsx to thread view — ThreadList + ThreadDetail replace per-message UI"
```

---

## Done

At this point the feature is complete:
- `GET /threads` groups conversations by `thread_id`, with category, search, and pagination.
- `GET /threads/{id}/messages` returns the full chronological timeline.
- `PATCH /threads/{id}/read` marks all messages as read (+ optional Gmail sync).
- `PATCH /threads/{id}/category` recategorizes every message in the thread.
- `GET /auth-status` now includes `email` for "Yo" detection.
- `ThreadList` shows compact rows with unread dot, participant names, count badge.
- `ThreadDetail` shows a per-sender timeline with avatars, full HTML/attachments, reply composer.
- All existing `/emails` endpoints, stats, backup, export, and cron are untouched.
