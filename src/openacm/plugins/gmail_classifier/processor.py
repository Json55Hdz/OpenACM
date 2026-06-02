"""Gmail batch processor — fetches emails, classifies via LLM, persists to DB."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger()

# Module-level singleton set by plugin on_start
_processor: "GmailBatchProcessor | None" = None

BATCH_SIZE = 20  # emails per LLM classification call


async def _get_gmail_service():
    """Return an authenticated Gmail API service (v1)."""
    from openacm.tools.google_services import _get_google_service
    return await _get_google_service("gmail", "v1")


async def _get_authenticated_email(service) -> str:
    """Return the authenticated user's email address."""
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


async def _get_or_create_label(service, name: str, cache: dict) -> str | None:
    """Return Gmail label ID for `name`, creating it if it doesn't exist."""
    if name in cache:
        return cache[name]
    try:
        # List existing labels
        result = service.users().labels().list(userId="me").execute()
        for lbl in result.get("labels", []):
            if lbl["name"].lower() == name.lower():
                cache[name] = lbl["id"]
                return lbl["id"]
        # Create it
        created = service.users().labels().create(
            userId="me",
            body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        ).execute()
        cache[name] = created["id"]
        return created["id"]
    except Exception as exc:
        log.warning("Failed to get/create Gmail label", name=name, error=str(exc))
        return None


async def apply_gmail_actions(
    service,
    gmail_id: str,
    mark_read: bool,
    label_name: str | None,
    label_cache: dict,
) -> None:
    """Apply mark-as-read and/or label to a single Gmail message."""
    add_labels: list[str] = []
    remove_labels: list[str] = []

    if mark_read:
        remove_labels.append("UNREAD")

    if label_name:
        label_id = await _get_or_create_label(service, label_name, label_cache)
        if label_id:
            add_labels.append(label_id)

    if add_labels or remove_labels:
        try:
            service.users().messages().modify(
                userId="me",
                id=gmail_id,
                body={"addLabelIds": add_labels, "removeLabelIds": remove_labels},
            ).execute()
        except Exception as exc:
            log.warning("Failed to modify Gmail message", gmail_id=gmail_id, error=str(exc))


def _parse_headers(headers: list[dict]) -> dict[str, str]:
    return {h["name"]: h["value"] for h in headers}


def _parse_sender(from_header: str) -> tuple[str, str]:
    """Split 'Name <email>' into (name, email)."""
    m = re.match(r"^(.*?)\s*<([^>]+)>$", from_header.strip())
    if m:
        return m.group(1).strip().strip('"'), m.group(2).strip()
    return from_header.strip(), from_header.strip()


def _extract_body(payload: dict) -> tuple[str, str]:
    """Extract (plain_text, html) from a Gmail message payload.

    Handles:
    - text/plain and text/html direct parts
    - multipart/alternative, multipart/mixed, multipart/related (all recursed)
    - Large bodies returned as base64 in body.data
    """
    import base64 as _b64

    def _decode(data: str) -> str:
        try:
            # Gmail uses URL-safe base64; pad to multiple of 4
            padded = data + "=" * (-len(data) % 4)
            return _b64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _collect(part: dict, texts: list, htmls: list, depth: int = 0) -> None:
        if depth > 10:
            return
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        body_data = body.get("data", "")
        parts = part.get("parts", [])

        if mime == "text/plain":
            if body_data:
                texts.append(_decode(body_data))
        elif mime == "text/html":
            if body_data:
                htmls.append(_decode(body_data))
        elif mime.startswith("multipart/"):
            # Prefer alternative: try to collect html first from alternatives
            for p in parts:
                _collect(p, texts, htmls, depth + 1)
        else:
            # Unknown/attachment — skip but recurse into sub-parts if any
            for p in parts:
                _collect(p, texts, htmls, depth + 1)

    texts: list[str] = []
    htmls: list[str] = []
    _collect(payload, texts, htmls)

    plain = "\n\n".join(t for t in texts if t.strip()).strip()
    html = "\n".join(h for h in htmls if h.strip()).strip()

    # If plain looks like HTML/CSS, move it to html bucket
    _html_markers = re.compile(r"<!DOCTYPE|<html|<body|<div|<table|@media", re.IGNORECASE)
    if plain and not html and _html_markers.search(plain[:500]):
        html, plain = plain, ""

    # Derive plain text from HTML if we only have HTML
    if not plain and html:
        plain = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        plain = re.sub(r"<[^>]+>", " ", plain)
        plain = re.sub(r"\s{2,}", " ", plain).strip()

    return plain, html


def _internaldate_to_iso(ms_str: str) -> str:
    try:
        ts = int(ms_str) / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


class GmailBatchProcessor:
    def __init__(self, db: Any, llm_router: Any, event_bus: Any):
        self._db = db
        self._llm = llm_router
        self._event_bus = event_bus
        self.is_running = False
        self._stop_requested = False
        self._processed = 0
        self._total = 0
        self._errors = 0
        self._started_at: str | None = None
        self._last_completed_at: str | None = None

    @property
    def status(self) -> dict:
        return {
            "running": self.is_running,
            "processed": self._processed,
            "total": self._total,
            "errors": self._errors,
            "started_at": self._started_at,
            "last_completed_at": self._last_completed_at,
        }

    async def process(self, since_date: str) -> dict:
        """Fetch, classify and persist all emails since since_date (YYYY/MM/DD)."""
        if self.is_running:
            raise RuntimeError("Processor is already running")

        self.is_running = True
        self._stop_requested = False
        self._processed = 0
        self._total = 0
        self._errors = 0
        self._started_at = datetime.now(timezone.utc).isoformat()

        try:
            service = await _get_gmail_service()
            auth_email = await _get_authenticated_email(service)
            categories = await self._load_categories()
            settings = await self._load_settings()
            auto_mark_read = settings.get("auto_mark_read") == "true"
            auto_apply_label = settings.get("auto_apply_label") == "true"
            label_cache: dict = {}

            # 1. Collect all message IDs
            msg_ids = await self._fetch_all_ids(service, since_date)
            self._total = len(msg_ids)
            await self._emit("gmail_classifier.progress", {"processed": 0, "total": self._total})

            # 2. Process in batches
            cat_by_id: dict[int, str] = {c["id"]: c["name"] for c in categories}
            for i in range(0, len(msg_ids), BATCH_SIZE):
                if self._stop_requested:
                    log.info("Gmail classification stopped by user request")
                    break
                batch_ids = msg_ids[i: i + BATCH_SIZE]
                emails = await self._fetch_details(service, batch_ids, auth_email)
                classifications = await self._classify(emails, categories)
                saved = await self._upsert(emails, classifications, categories)

                # Apply Gmail actions if enabled
                if auto_mark_read or auto_apply_label:
                    for email, cat_id in saved:
                        label_name = cat_by_id.get(cat_id) if auto_apply_label else None
                        await apply_gmail_actions(
                            service, email["gmail_id"],
                            mark_read=auto_mark_read,
                            label_name=label_name,
                            label_cache=label_cache,
                        )
                        await asyncio.sleep(0.05)

                self._processed += len(emails)
                await self._emit("gmail_classifier.progress", {
                    "processed": self._processed,
                    "total": self._total,
                })
                await asyncio.sleep(0)  # yield to event loop

            self._last_completed_at = datetime.now(timezone.utc).isoformat()
            await self._emit("gmail_classifier.completed", {
                "total": self._total,
                "processed": self._processed,
                "errors": self._errors,
                "last_completed_at": self._last_completed_at,
            })
            return {"total": self._total, "processed": self._processed, "errors": self._errors}

        except Exception as exc:
            log.error("Gmail batch processing failed", error=str(exc))
            await self._emit("gmail_classifier.error", {"message": str(exc)})
            raise
        finally:
            self.is_running = False

    # ── Internal helpers ──────────────────────────────────────

    async def _fetch_all_ids(self, service, since_date: str) -> list[str]:
        ids: list[str] = []
        # Gmail after: operator expects YYYY/MM/DD format (slashes required)
        query = f"after:{since_date}" if since_date else ""
        page_token = None
        while True:
            kwargs: dict = {"userId": "me", "maxResults": 500}
            if query:
                kwargs["q"] = query
            if page_token:
                kwargs["pageToken"] = page_token
            result = service.users().messages().list(**kwargs).execute()
            for m in result.get("messages", []):
                ids.append(m["id"])
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        return ids

    async def _fetch_details(self, service, ids: list[str], auth_email: str) -> list[dict]:
        emails = []
        for msg_id in ids:
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_id, format="full",
                ).execute()
                headers = _parse_headers(msg.get("payload", {}).get("headers", []))
                from_header = headers.get("From", "")
                sender_name, sender_email = _parse_sender(from_header)
                thread_id = msg.get("threadId", "")

                # Determine is_replied: check if last message in thread was from auth user
                is_replied = 0
                try:
                    thread = service.users().threads().get(
                        userId="me", id=thread_id, format="metadata",
                        metadataFields="messages/payload/headers",
                    ).execute()
                    last_msg = thread.get("messages", [{}])[-1]
                    last_from = _parse_headers(
                        last_msg.get("payload", {}).get("headers", [])
                    ).get("From", "")
                    _, last_email = _parse_sender(last_from)
                    is_replied = 1 if last_email.lower() == auth_email.lower() else 0
                except Exception:
                    pass

                is_read = 0 if "UNREAD" in msg.get("labelIds", []) else 1
                body_text, body_html = _extract_body(msg.get("payload", {}))
                emails.append({
                    "gmail_id": msg_id,
                    "thread_id": thread_id,
                    "subject": headers.get("Subject", "(sin asunto)"),
                    "sender_name": sender_name,
                    "sender_email": sender_email,
                    "snippet": msg.get("snippet", "")[:200],
                    "body_text": body_text,
                    "body_html": body_html,
                    "is_read": is_read,
                    "is_replied": is_replied,
                    "received_at": _internaldate_to_iso(msg.get("internalDate", "0")),
                })
                await asyncio.sleep(0.05)  # Gmail API rate limiting
            except Exception as exc:
                log.warning("Failed to fetch email", gmail_id=msg_id, error=str(exc))
                self._errors += 1
        return emails

    async def _load_settings(self) -> dict:
        cursor = await self._db._db.execute("SELECT key, value FROM gmail_classifier_settings")
        rows = await cursor.fetchall()
        return {r["key"]: r["value"] for r in rows}

    async def _load_categories(self) -> list[dict]:
        cursor = await self._db._db.execute(
            "SELECT id, name, description FROM gmail_categories ORDER BY id"
        )
        rows = await cursor.fetchall()
        return [{"id": r["id"], "name": r["name"], "description": r["description"]} for r in rows]

    async def _classify(self, emails: list[dict], categories: list[dict]) -> dict[str, str]:
        """Call LLM to classify emails. Returns {gmail_id: category_name}."""
        if not emails or not categories:
            return {}

        cat_block = "\n".join(
            f"- {c['name']}: {c['description']}" for c in categories
            if c["name"] != "Otros"
        )
        cat_block += "\n- Otros: Usa esta cuando el correo no encaje en ninguna categoría."

        email_block = "\n".join(
            f'{i + 1}. [gmail_id={e["gmail_id"]}] De: {e["sender_email"]} | Asunto: {e["subject"]} | Preview: {e["snippet"]}'
            for i, e in enumerate(emails)
        )

        prompt = (
            "Eres un clasificador de correos. Clasifica cada correo en EXACTAMENTE una de estas categorías:\n"
            f"{cat_block}\n\n"
            "Devuelve SOLO un JSON array sin explicaciones:\n"
            '[{"gmail_id": "ID_EXACTO", "category": "NombreCategoria"}, ...]\n\n'
            f"Correos a clasificar:\n{email_block}"
        )

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.get("content", "")
            # Extract JSON array from response (may have surrounding text)
            match = re.search(r"\[.*?\]", content, re.DOTALL)
            if not match:
                raise ValueError("No JSON array in LLM response")
            items = json.loads(match.group(0))
            return {item["gmail_id"]: item["category"] for item in items if "gmail_id" in item}
        except Exception as exc:
            log.warning("LLM classification failed, defaulting to Otros", error=str(exc))
            return {}

    async def _upsert(
        self,
        emails: list[dict],
        classifications: dict[str, str],
        categories: list[dict],
    ) -> list[tuple[dict, int]]:
        cat_by_name = {c["name"]: c["id"] for c in categories}
        otros_id = cat_by_name.get("Otros")
        saved: list[tuple[dict, int]] = []

        for email in emails:
            cat_name = classifications.get(email["gmail_id"], "Otros")
            cat_id = cat_by_name.get(cat_name, otros_id)

            await self._db._db.execute(
                """
                INSERT INTO gmail_emails
                    (gmail_id, thread_id, subject, sender_name, sender_email,
                     snippet, body_text, body_html, category_id, is_read, is_replied, ai_classified, received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
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
                    ai_classified = 1,
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
                    email["received_at"],
                ),
            )
            if cat_id is not None:
                saved.append((email, cat_id))
        await self._db._db.commit()
        return saved

    async def apply_retroactive(self, mark_read: bool, apply_label: bool) -> dict:
        """Apply Gmail actions to all already-classified emails in the DB."""
        if not mark_read and not apply_label:
            return {"applied": 0}

        service = await _get_gmail_service()
        label_cache: dict = {}

        cursor = await self._db._db.execute(
            "SELECT ge.gmail_id, gc.name as category_name "
            "FROM gmail_emails ge "
            "LEFT JOIN gmail_categories gc ON ge.category_id = gc.id "
            "WHERE ge.ai_classified = 1"
        )
        rows = await cursor.fetchall()
        count = 0
        for row in rows:
            await apply_gmail_actions(
                service,
                row["gmail_id"],
                mark_read=mark_read,
                label_name=row["category_name"] if apply_label else None,
                label_cache=label_cache,
            )
            count += 1
            await asyncio.sleep(0.05)
            if count % 50 == 0:
                await self._emit("gmail_classifier.retroactive_progress", {"applied": count, "total": len(rows)})

        await self._emit("gmail_classifier.retroactive_progress", {"applied": count, "total": len(rows)})
        return {"applied": count}

    async def _emit(self, event: str, data: dict) -> None:
        if self._event_bus:
            try:
                await self._event_bus.emit(event, data)
            except Exception:
                pass
