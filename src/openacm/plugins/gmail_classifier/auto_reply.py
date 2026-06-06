"""AutoReplyGenerator — generates AI reply suggestions for eligible emails."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

log = structlog.get_logger()

NOREPLY_PATTERNS = (
    "noreply@", "no-reply@", "donotreply@",
    "notifications@", "mailer-daemon@", "bounce@",
)


class AutoReplyGenerator:
    def __init__(self, db: Any, llm_router: Any, authed_email: str = ""):
        self._db = db
        self._llm = llm_router
        self._authed_email = authed_email

    def _is_noreply(self, sender_email: str) -> bool:
        e = (sender_email or "").lower().strip()
        return any(e.startswith(p) for p in NOREPLY_PATTERNS)

    async def _get_authed_email(self) -> str:
        if self._authed_email:
            return self._authed_email
        try:
            from openacm.plugins.gmail_classifier.processor import (
                _get_gmail_service, _get_authenticated_email,
            )
            svc = await _get_gmail_service()
            self._authed_email = await _get_authenticated_email(svc)
        except Exception:
            self._authed_email = ""
        return self._authed_email

    async def _enabled_categories(self) -> list[int]:
        if self._db is None:
            return []
        cursor = await self._db._db.execute(
            "SELECT value FROM gmail_classifier_settings "
            "WHERE key = 'autoreply_enabled_categories'"
        )
        row = await cursor.fetchone()
        if not row or not row["value"]:
            return []
        try:
            return json.loads(row["value"])
        except Exception:
            return []

    async def generate(self, email_id: int) -> dict | None:
        """Return {"body": str, "from_draft": bool} or None if not eligible."""
        cursor = await self._db._db.execute(
            "SELECT id, sender_email, thread_last_sender_email, is_replied, "
            "category_id, body_text, subject "
            "FROM gmail_emails WHERE id = ?",
            (email_id,),
        )
        email = await cursor.fetchone()
        if not email:
            return None

        enabled = await self._enabled_categories()
        if email["category_id"] not in enabled:
            return None

        if email["is_replied"]:
            return None

        authed = await self._get_authed_email()
        if authed and (email["thread_last_sender_email"] or "").lower() == authed.lower():
            return None

        if self._is_noreply(email["sender_email"]):
            return None

        draft_cursor = await self._db._db.execute(
            "SELECT draft_body FROM gmail_reply_drafts WHERE email_id = ?",
            (email_id,),
        )
        draft_row = await draft_cursor.fetchone()
        if draft_row:
            return {"body": draft_row["draft_body"], "from_draft": True}

        suggestion = await self._generate_suggestion(email_id, email)
        if suggestion:
            await self._db._db.execute(
                "UPDATE gmail_emails SET ai_suggestion = ? WHERE id = ?",
                (suggestion, email_id),
            )
            await self._db._db.commit()
            return {"body": suggestion, "from_draft": False}
        return None

    async def _generate_suggestion(self, email_id: int, email: Any) -> str | None:
        examples = await self._get_similar_examples(
            email["category_id"], email["body_text"]
        )

        cat_cursor = await self._db._db.execute(
            "SELECT name, description, context FROM gmail_categories WHERE id = ?",
            (email["category_id"],),
        )
        cat = await cat_cursor.fetchone()
        cat_name = cat["name"] if cat else ""
        cat_desc = cat["description"] if cat else ""
        cat_ctx = (cat["context"] if cat else "") or ""

        few_shot = ""
        if examples:
            parts = [
                f"Correo similar ({ex['subtype_label']}):\n"
                f"Original: {ex['email_context']}\n"
                f"Respuesta correcta: {ex['final_response']}"
                for ex in examples
            ]
            few_shot = "\n\n".join(parts) + "\n\n---\n\n"

        prompt = (
            f"Eres un asistente que redacta respuestas de correo profesionales.\n"
            f"Categoría: {cat_name} — {cat_desc}\n"
            f"{('Contexto: ' + cat_ctx + chr(10)) if cat_ctx else ''}"
            f"\n{few_shot}"
            f"Redacta una respuesta profesional para el siguiente correo. "
            f"Devuelve SOLO el cuerpo de la respuesta, sin asunto.\n\n"
            f"Asunto: {email['subject']}\n"
            f"Correo:\n{(email['body_text'] or '')[:3000]}"
        )

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}]
            )
            return (response.get("content") or "").strip() or None
        except Exception as exc:
            log.warning("AutoReply LLM call failed", error=str(exc))
            return None

    async def _get_similar_examples(
        self, category_id: int, body_text: str
    ) -> list[dict]:
        if not (body_text or "").strip():
            return []

        try:
            from openacm.core.local_router import LocalRouter
            model = LocalRouter._model
            if model is None:
                return []
        except Exception:
            return []

        try:
            import numpy as np
            loop = asyncio.get_event_loop()
            query_emb = await loop.run_in_executor(
                None,
                lambda: model.encode(
                    body_text[:2000], convert_to_numpy=True, show_progress_bar=False
                ),
            )
        except Exception as exc:
            log.warning("AutoReply embedding failed", error=str(exc))
            return []

        cursor = await self._db._db.execute(
            "SELECT subtype_label, email_context, final_response, embedding "
            "FROM gmail_reply_examples "
            "WHERE category_id = ? AND embedding IS NOT NULL",
            (category_id,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return []

        import numpy as np
        scored: list[tuple[float, dict]] = []
        for row in rows:
            try:
                stored = np.frombuffer(row["embedding"], dtype=np.float32)
                norm = np.linalg.norm(query_emb) * np.linalg.norm(stored)
                sim = float(np.dot(query_emb, stored) / (norm + 1e-9))
                scored.append((sim, dict(row)))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ex for _, ex in scored[:3]]
