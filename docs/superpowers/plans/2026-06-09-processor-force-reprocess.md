# Processor Force Re-process Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Manual "Procesar" runs always re-classify all emails from the selected date (resetting manual_override); cron runs keep the current incremental behavior.

**Architecture:** Add `force: bool = False` to `GmailBatchProcessor.process()` and `_upsert()`. When `force=True`: skip the existing-ID filter and use a different UPSERT SQL that always overwrites `category_id` and resets `manual_override=0`. The `POST /process` endpoint passes `force=True`; the cron call stays unchanged (uses default `force=False`). Frontend adds a static yellow warning banner above the Procesar button.

**Tech Stack:** Python/aiosqlite (backend), React/Next.js (frontend).

---

## File map

| Action | Path |
|--------|------|
| **Modify** | `src/openacm/plugins/gmail_classifier/processor.py` |
| **Modify** | `src/openacm/plugins/gmail_classifier/router.py` |
| **Modify** | `frontend/app/gmail-classifier/page.tsx` |
| **Modify** | `tests/unit/test_gmail_classifier.py` |

---

### Task 1: `processor.py` — `force` parameter in `_upsert` and `process`

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/processor.py`
- Modify: `tests/unit/test_gmail_classifier.py`

The two behavior differences when `force=True`:
1. `process()` does not filter out already-existing IDs — it processes everything from Gmail.
2. `_upsert()` always writes `category_id = excluded.category_id` and sets `manual_override = 0`, ignoring any previous manual override.

- [ ] **Step 1: Write failing tests for `_upsert` force behavior**

Append to `tests/unit/test_gmail_classifier.py`:

```python
# ─── _upsert force flag ───────────────────────────────────────────────────────

@pytest.fixture
async def processor_with_categories(db, mock_llm_router, event_bus):
    """Processor with 'Importantes' and 'Otros' categories seeded."""
    from openacm.plugins.gmail_classifier.processor import GmailBatchProcessor
    # Seed categories
    cursor = await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description) VALUES (?, ?)",
        ("Importantes", "Alta prioridad"),
    )
    otros_cursor = await db._db.execute(
        "SELECT id FROM gmail_categories WHERE name = 'Otros'"
    )
    await db._db.commit()
    return GmailBatchProcessor(db=db, llm_router=mock_llm_router, event_bus=event_bus)


@pytest.mark.asyncio
async def test_upsert_force_true_overrides_manual_override(db, processor_with_categories):
    """force=True rewrites category and clears manual_override even when manual_override=1."""
    proc = processor_with_categories

    # Load the two category IDs
    c1 = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Importantes'")
    importantes_id = (await c1.fetchone())["id"]
    c2 = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Otros'")
    otros_id = (await c2.fetchone())["id"]

    # Pre-insert an email with manual_override=1 pointing to 'Otros'
    await db._db.execute(
        "INSERT INTO gmail_emails "
        "(gmail_id, thread_id, subject, sender_name, sender_email, snippet, "
        " body_text, body_html, category_id, is_read, is_replied, ai_classified, "
        " manual_override, thread_last_sender_email, received_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 1, ?, datetime('now'))",
        ("gid1", "tid1", "Asunto", "Sender", "s@x.com", "preview",
         "body", "", otros_id, ""),
    )
    await db._db.commit()

    email = {
        "gmail_id": "gid1", "thread_id": "tid1", "subject": "Asunto",
        "sender_name": "Sender", "sender_email": "s@x.com",
        "snippet": "preview", "body_text": "body", "body_html": "",
        "is_read": 0, "is_replied": 0, "thread_last_sender_email": "",
        "received_at": "2026-06-09T00:00:00+00:00",
    }
    categories = await proc._load_categories()
    classifications = {"gid1": "Importantes"}

    await proc._upsert([email], classifications, categories, force=True)

    cursor = await db._db.execute(
        "SELECT category_id, manual_override, ai_classified FROM gmail_emails WHERE gmail_id='gid1'"
    )
    row = await cursor.fetchone()
    assert row["category_id"] == importantes_id
    assert row["manual_override"] == 0
    assert row["ai_classified"] == 1


@pytest.mark.asyncio
async def test_upsert_force_false_preserves_manual_override(db, processor_with_categories):
    """force=False (default) preserves manual_override=1 and keeps old category."""
    proc = processor_with_categories

    c1 = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Importantes'")
    importantes_id = (await c1.fetchone())["id"]
    c2 = await db._db.execute("SELECT id FROM gmail_categories WHERE name='Otros'")
    otros_id = (await c2.fetchone())["id"]

    # Pre-insert with manual_override=1 pointing to 'Otros'
    await db._db.execute(
        "INSERT INTO gmail_emails "
        "(gmail_id, thread_id, subject, sender_name, sender_email, snippet, "
        " body_text, body_html, category_id, is_read, is_replied, ai_classified, "
        " manual_override, thread_last_sender_email, received_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 1, ?, datetime('now'))",
        ("gid2", "tid2", "Asunto", "Sender", "s@x.com", "preview",
         "body", "", otros_id, ""),
    )
    await db._db.commit()

    email = {
        "gmail_id": "gid2", "thread_id": "tid2", "subject": "Asunto",
        "sender_name": "Sender", "sender_email": "s@x.com",
        "snippet": "preview", "body_text": "body", "body_html": "",
        "is_read": 0, "is_replied": 0, "thread_last_sender_email": "",
        "received_at": "2026-06-09T00:00:00+00:00",
    }
    categories = await proc._load_categories()
    classifications = {"gid2": "Importantes"}

    # force=False — manual_override should be preserved
    await proc._upsert([email], classifications, categories, force=False)

    cursor = await db._db.execute(
        "SELECT category_id, manual_override FROM gmail_emails WHERE gmail_id='gid2'"
    )
    row = await cursor.fetchone()
    assert row["category_id"] == otros_id   # unchanged — manual override kept
    assert row["manual_override"] == 1
```

- [ ] **Step 2: Run to confirm the tests fail**

```
pytest tests/unit/test_gmail_classifier.py::test_upsert_force_true_overrides_manual_override tests/unit/test_gmail_classifier.py::test_upsert_force_false_preserves_manual_override -v
```

Expected: `TypeError: _upsert() got an unexpected keyword argument 'force'`

- [ ] **Step 3: Update `_upsert` in `processor.py` to accept `force`**

Find the `_upsert` method signature (line ~493):
```python
    async def _upsert(
        self,
        emails: list[dict],
        classifications: dict[str, str],
        categories: list[dict],
    ) -> list[tuple[dict, int]]:
```

Replace with:
```python
    async def _upsert(
        self,
        emails: list[dict],
        classifications: dict[str, str],
        categories: list[dict],
        force: bool = False,
    ) -> list[tuple[dict, int]]:
```

Then replace the entire `await self._db._db.execute(...)` block inside the `for email in emails:` loop. Currently it starts with `# If the row already exists...` (line ~507). Replace from that comment through the closing `)` of the execute call with:

```python
            if force:
                await self._db._db.execute(
                    """
                    INSERT INTO gmail_emails
                        (gmail_id, thread_id, subject, sender_name, sender_email,
                         snippet, body_text, body_html, category_id, is_read, is_replied, ai_classified, thread_last_sender_email, received_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(gmail_id) DO UPDATE SET
                        thread_id     = excluded.thread_id,
                        subject       = excluded.subject,
                        sender_name   = excluded.sender_name,
                        sender_email  = excluded.sender_email,
                        snippet       = excluded.snippet,
                        body_text     = excluded.body_text,
                        body_html     = excluded.body_html,
                        category_id   = excluded.category_id,
                        is_replied    = excluded.is_replied,
                        thread_last_sender_email = excluded.thread_last_sender_email,
                        ai_classified = 1,
                        manual_override = 0,
                        last_synced   = CURRENT_TIMESTAMP
                    """,
                    (
                        email["gmail_id"],
                        email["thread_id"],
                        email["subject"],
                        email["sender_name"],
                        email["sender_email"],
                        email["snippet"],
                        email.get("body_text", ""),
                        email.get("body_html", ""),
                        cat_id,
                        email["is_read"],
                        email["is_replied"],
                        email.get("thread_last_sender_email", ""),
                        email["received_at"],
                    ),
                )
            else:
                # Preserve manual_override=1 rows — user-chosen category is kept.
                await self._db._db.execute(
                    """
                    INSERT INTO gmail_emails
                        (gmail_id, thread_id, subject, sender_name, sender_email,
                         snippet, body_text, body_html, category_id, is_read, is_replied, ai_classified, thread_last_sender_email, received_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(gmail_id) DO UPDATE SET
                        thread_id     = excluded.thread_id,
                        subject       = excluded.subject,
                        sender_name   = excluded.sender_name,
                        sender_email  = excluded.sender_email,
                        snippet       = excluded.snippet,
                        body_text     = excluded.body_text,
                        body_html     = excluded.body_html,
                        category_id   = CASE WHEN gmail_emails.manual_override = 1
                                             THEN gmail_emails.category_id
                                             ELSE excluded.category_id END,
                        is_replied    = excluded.is_replied,
                        thread_last_sender_email = excluded.thread_last_sender_email,
                        ai_classified = CASE WHEN gmail_emails.manual_override = 1
                                             THEN gmail_emails.ai_classified
                                             ELSE 1 END,
                        last_synced   = CURRENT_TIMESTAMP
                    """,
                    (
                        email["gmail_id"],
                        email["thread_id"],
                        email["subject"],
                        email["sender_name"],
                        email["sender_email"],
                        email["snippet"],
                        email.get("body_text", ""),
                        email.get("body_html", ""),
                        cat_id,
                        email["is_read"],
                        email["is_replied"],
                        email.get("thread_last_sender_email", ""),
                        email["received_at"],
                    ),
                )
```

- [ ] **Step 4: Update `process()` to accept `force` and use it**

Find the `process` method signature (line ~191):
```python
    async def process(self, since_date: str) -> dict:
```

Replace with:
```python
    async def process(self, since_date: str, force: bool = False) -> dict:
```

Find the existing-ID filter block (~line 215-228):
```python
            # 1b. Skip IDs we've already persisted (manual overrides and
            # AI-classified alike). This is the biggest cron optimization:
            # in steady state we only process newly-arrived emails.
            existing_cursor = await self._db._db.execute(
                "SELECT gmail_id FROM gmail_emails"
            )
            existing_ids = {r["gmail_id"] for r in await existing_cursor.fetchall()}
            msg_ids = [mid for mid in all_ids if mid not in existing_ids]
            skipped_count = len(all_ids) - len(msg_ids)
            if skipped_count:
                log.info(
                    "Gmail processor: skipping already-processed emails",
                    skipped=skipped_count, new=len(msg_ids),
                )
```

Replace with:
```python
            # 1b. In cron mode (force=False) skip IDs already persisted —
            # the biggest optimization: only new emails are fetched/classified.
            # In force mode (manual trigger) process everything from Gmail.
            if force:
                msg_ids = all_ids
                log.info("Gmail processor: force mode — reprocessing all emails", total=len(msg_ids))
            else:
                existing_cursor = await self._db._db.execute(
                    "SELECT gmail_id FROM gmail_emails"
                )
                existing_ids = {r["gmail_id"] for r in await existing_cursor.fetchall()}
                msg_ids = [mid for mid in all_ids if mid not in existing_ids]
                skipped_count = len(all_ids) - len(msg_ids)
                if skipped_count:
                    log.info(
                        "Gmail processor: skipping already-processed emails",
                        skipped=skipped_count, new=len(msg_ids),
                    )
```

Then find the `_upsert` call inside the batch loop (~line 242):
```python
                saved = await self._upsert(emails, classifications, categories)
```

Replace with:
```python
                saved = await self._upsert(emails, classifications, categories, force=force)
```

- [ ] **Step 5: Run all tests to confirm everything passes**

```
pytest tests/unit/test_gmail_classifier.py -v
```

Expected: all existing tests + 2 new tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/processor.py tests/unit/test_gmail_classifier.py
git commit -m "feat: processor.process() force=True re-classifies all emails, resets manual_override"
```

---

### Task 2: `router.py` — pass `force=True` to manual process endpoint

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/router.py`

- [ ] **Step 1: Update the `POST /process` endpoint**

Find (around line 641-645):
```python
    proc = _require_processor()
    if proc.is_running:
        raise HTTPException(status_code=409, detail="Processing already in progress")
    asyncio.create_task(proc.process(body.since_date))
    return {"started": True, "since_date": body.since_date}
```

Replace with:
```python
    proc = _require_processor()
    if proc.is_running:
        raise HTTPException(status_code=409, detail="Processing already in progress")
    asyncio.create_task(proc.process(body.since_date, force=True))
    return {"started": True, "since_date": body.since_date}
```

- [ ] **Step 2: Verify the module imports cleanly**

```
python -c "from openacm.plugins.gmail_classifier.router import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Confirm cron call is unchanged**

Read `src/openacm/plugins/gmail_classifier/__init__.py` around line 264 and confirm the cron call is:
```python
await self._processor.process(since_date)
```
This uses `force=False` (default) — no change needed.

- [ ] **Step 4: Run full test suite**

```
pytest tests/unit/test_gmail_classifier.py tests/unit/test_gmail_backup.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/router.py
git commit -m "feat: POST /process passes force=True — manual trigger always reprocesses"
```

---

### Task 3: Frontend — warning banner above Procesar button

**Files:**
- Modify: `frontend/app/gmail-classifier/page.tsx`

- [ ] **Step 1: Add the warning banner**

In `page.tsx`, find the Procesar/Detener button area. Currently it looks like this (around the `processStatus.running` conditional):

```tsx
                ) : (
                  <button
                    onClick={handleProcess}
                    className="btn-primary text-[12px] py-[7px] px-3"
                  >
                    <RefreshCw size={13} />
                    Procesar
                  </button>
                )}
```

Add the warning banner **above** the entire `processStatus.running` ternary block (before the stop/process button conditional). Find the container div that holds the buttons and insert before the ternary:

```tsx
                {/* Re-process warning */}
                {!processStatus.running && (
                  <p className="text-[11px] text-amber-500/80">
                    ⚠ Al procesar se reclasificarán todos los correos desde la fecha seleccionada, incluyendo los que ya tenías guardados.
                  </p>
                )}
```

The warning only shows when not running (hides during active processing so it doesn't clutter the progress view).

- [ ] **Step 2: Run TypeScript check**

```
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/gmail-classifier/page.tsx
git commit -m "feat: gmail classifier — re-process warning banner above Procesar button"
```

---

### Task 4: Full verification

- [ ] **Step 1: Run all Gmail-related tests**

```
pytest tests/unit/test_gmail_classifier.py tests/unit/test_gmail_backup.py tests/unit/test_gmail_stats.py tests/unit/test_gmail_excel.py -v
```

Expected: all pass.

- [ ] **Step 2: Verify TypeScript**

```
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Confirm cron call has no `force` arg**

```
python -c "
import ast, pathlib
src = pathlib.Path('src/openacm/plugins/gmail_classifier/__init__.py').read_text()
assert 'force' not in src or 'force=False' not in src or src.count('force=True') == 0, 'cron must not pass force=True'
print('OK — cron does not pass force=True')
"
```

Expected: `OK — cron does not pass force=True`

- [ ] **Step 4: Confirm router passes force=True**

```
python -c "
import pathlib
src = pathlib.Path('src/openacm/plugins/gmail_classifier/router.py').read_text()
assert 'force=True' in src, 'router must pass force=True'
print('OK — router passes force=True')
"
```

Expected: `OK — router passes force=True`
