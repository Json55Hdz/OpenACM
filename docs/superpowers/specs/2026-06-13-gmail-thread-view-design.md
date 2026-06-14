# Gmail Classifier — Thread View

**Date:** 2026-06-13
**Status:** Approved for implementation

## Goal

Replace the per-message list in the Gmail Classifier with a per-thread (conversation) view. The left panel shows one entry per Gmail thread; the right panel shows the full conversation timeline when a thread is selected.

## Behavior

- **List (left panel):** one row per `thread_id`, sorted by latest message date descending.
- **Detail (right panel):** all messages in the thread in chronological order (oldest first), rendered as a vertical timeline with avatars.
- **Category:** determined by the **first (oldest) message** in the thread. Never changes as replies arrive.
- **Read state:** opening a thread marks **all** its messages as read (local DB + Gmail API if `auto_mark_read` is enabled), matching Gmail's behavior.
- **Single-message threads:** look identical to the current view — no visible difference to the user.
- **Recategorize:** changing the category from the detail panel updates **all** messages in the thread.

## Backend — New Endpoints (`router.py`)

### `GET /gmail-classifier/threads`

Returns a paginated list of threads. Groups `gmail_emails` by `thread_id`.

**Query params:** `category_id` (int), `search` (str), `page` (int, default 1), `per_page` (int, default 50).

**Category filter:** filters on the category of the first (oldest) message in the thread.

**Search:** matches if any message in the thread contains the term (subject, sender, body, snippet).

**Response per thread:**
```json
{
  "thread_id": "18f3a...",
  "subject": "Re: Propuesta Q3",
  "category_id": 2,
  "category_name": "Importantes",
  "category_color": "#ef4444",
  "category_icon": "Star",
  "message_count": 3,
  "unread_count": 1,
  "latest_at": "2026-06-13T10:42:00Z",
  "latest_snippet": "Ok revisé el doc y tengo...",
  "participants": [
    {"name": "Carlos", "email": "carlos@empresa.co"},
    {"name": "Jeison", "email": "jeisondh55@gmail.com"},
    {"name": "María", "email": "maria@empresa.co"}
  ]
}
```

`participants`: ordered list of unique senders (first appearance). The frontend renders them as a comma-separated string, replacing any entry whose `email` matches `auth_email` with "Yo".

### `GET /gmail-classifier/threads/{thread_id}/messages`

Returns all messages in the thread ordered by `received_at ASC`. Same fields as the current `/emails` response (including `gmail_id`, `body_html`, `body_text`, `is_read`, `is_replied`, `sender_email`, `sender_name`).

### `PATCH /gmail-classifier/threads/{thread_id}/read`

Marks all messages in the thread as read.

- `UPDATE gmail_emails SET is_read = 1 WHERE thread_id = ?`
- If `auto_mark_read = "true"`: removes `UNREAD` Gmail label from each message via API (runs in background with `asyncio.gather`, does not block the response).

### `PATCH /gmail-classifier/threads/{thread_id}/category`

Updates `category_id` for all messages in the thread and sets `manual_override = 1` on all of them.

```sql
UPDATE gmail_emails SET category_id = ?, manual_override = 1 WHERE thread_id = ?
```

### `GET /gmail-classifier/auth-status` (updated)

Adds `email` field to the existing response so the frontend can distinguish "Yo" from other participants in the timeline.

```json
{ "configured": true, "has_token": true, "ready": true, "email": "jeisondh55@gmail.com" }
```

## Backend — No Changes

- `/emails` endpoint stays intact (used by stats, backup, export).
- Processor, cron, `_sync_read_state`, classification — all unchanged.
- DB schema — no migrations needed (`thread_id` already exists on `gmail_emails`).

## Frontend

### `page.tsx`

- Replace `fetchEmails` with `fetchThreads` → calls `GET /threads`.
- State: `threads: Thread[]`, `selectedThread: Thread | null`, `threadMessages: Message[]`.
- On thread select:
  1. Set `selectedThread`.
  2. Fetch `GET /threads/{id}/messages` → set `threadMessages`.
  3. Call `PATCH /threads/{id}/read` (fire and forget).
  4. Update `threads` list: set `unread_count = 0` for that thread.
- Fetch `auth_email` from `GET /auth-status` once on mount.

### `ThreadList.tsx` (replaces `EmailList.tsx` in this page)

Compact Gmail-style rows (Option A from design session):

| Element | Content |
|---|---|
| Unread dot (blue) | Shown if `unread_count > 0` |
| Participants | Comma-separated sender names (e.g. "Carlos, Yo, María") |
| Subject | Subject of the first message |
| Snippet | Latest message snippet |
| Date | `latest_at` formatted (time if today, weekday if this week, date otherwise) |
| Count badge | `message_count` in a pill, only shown if > 1; blue if `unread_count > 0` |

### `ThreadDetail.tsx` (new, replaces `EmailDetail.tsx`)

**Header (sticky):**
- Subject
- Category badge (color + name)
- `N mensajes · Participantes`
- "Ver en Gmail" link → `https://mail.google.com/mail/u/0/#all/{thread_id}`

**Timeline body:**
For each message in `threadMessages` (chronological order):

```
[Avatar]  Sender name · date
          [Full email content: HtmlEmail or PlainTextBody]
          [Attachments row if any]
```

- **Avatar:** circle with sender's initial(s). Green background if `sender_email === auth_email` (the current user), gray for others.
- **Content:** use `HtmlEmail` (iframe) if `body_html` is set; `PlainTextBody` otherwise.
- **Inline images:** for each message, fetch `/emails/{id}/html` if `body_html` contains `cid:` (same logic as current `EmailDetail`).
- **Attachments:** use existing `list_attachments` + `download_attachment` endpoints per message.

**Bottom bar:**
- Category selector (dropdown) → on change calls `PATCH /threads/{id}/category`
- "Responder" button → opens reply composer targeting the last message in the thread (same composer as today, calls `POST /emails/{last_msg_id}/reply`)

**No explicit read/unread toggle** — the thread is marked read on open. If needed later, a toggle can be added.

## What Does Not Change

- Individual message endpoints (`/emails/{id}/read`, `/emails/{id}/reply`, `/emails/{id}/html`, attachments) — still used internally by `ThreadDetail`.
- Auto-reply suggestion — still fetched per last message of thread.
- Stats page, backup, export — operate on raw `gmail_emails`, unaffected.
- Classification and cron — operate per message, unaffected.
