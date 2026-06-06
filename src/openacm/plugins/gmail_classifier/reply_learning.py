"""ReplyLearningManager — saves learned reply examples when user sends or drafts."""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

import structlog

log = structlog.get_logger()

_SIMILARITY_THRESHOLD = 0.95


def _text_similar(a: str, b: str, threshold: float = _SIMILARITY_THRESHOLD) -> bool:
    """True if texts are similar enough that the user didn't meaningfully edit."""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold


class ReplyLearningManager:
    def __init__(self, db: Any, llm_router: Any):
        self._db = db
        self._llm = llm_router

    async def learn(self, email_id: int, final_body: str) -> None:
        """Learn from the user's sent/drafted reply. Idempotent per email_id."""
        final_body = (final_body or "").strip()
        if not final_body:
            return

        cursor = await self._db._db.execute(
            "SELECT ai_suggestion, body_text, subject, category_id "
            "FROM gmail_emails WHERE id = ?",
            (email_id,),
        )
        email = await cursor.fetchone()
        if not email:
            return

        # Idempotency check
        dup = await self._db._db.execute(
            "SELECT id FROM gmail_reply_examples WHERE source_email_id = ?",
            (email_id,),
        )
        if await dup.fetchone():
            return

        ai_suggestion = (email["ai_suggestion"] or "").strip()

        if _text_similar(ai_suggestion, final_body):
            await self._increment_use_count(email["category_id"])
        else:
            await self._save_example(
                email_id=email_id,
                category_id=email["category_id"],
                email_context=f"Asunto: {email['subject']}\n{(email['body_text'] or '')[:1000]}",
                original_suggestion=ai_suggestion,
                final_response=final_body,
                body_text=email["body_text"] or "",
            )

    async def _save_example(
        self,
        email_id: int,
        category_id: int,
        email_context: str,
        original_suggestion: str,
        final_response: str,
        body_text: str,
    ) -> None:
        subtype = await self._classify_subtype(email_context)
        embedding_blob = await self._generate_embedding(body_text)

        await self._db._db.execute(
            "INSERT INTO gmail_reply_examples "
            "(category_id, source_email_id, subtype_label, email_context, "
            "original_suggestion, final_response, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                category_id, email_id, subtype, email_context,
                original_suggestion, final_response, embedding_blob,
            ),
        )
        await self._db._db.commit()
        log.info("AutoReply: learned new example", email_id=email_id, subtype=subtype)

    async def _classify_subtype(self, email_context: str) -> str:
        prompt = (
            "Identifica el tipo de solicitud de este correo en 3-6 palabras clave en español.\n"
            "Responde SOLO con el tipo, sin explicación.\n"
            "Ejemplos: 'solicitud de estado de cuenta', 'reclamo de pago', 'solicitud de certificado'\n\n"
            f"Correo:\n{email_context[:1000]}"
        )
        try:
            response = await self._llm.chat(messages=[{"role": "user", "content": prompt}])
            return ((response.get("content") or "").strip())[:100] or "sin clasificar"
        except Exception:
            return "sin clasificar"

    async def _generate_embedding(self, body_text: str) -> bytes | None:
        if not (body_text or "").strip():
            return None
        try:
            from openacm.core.local_router import LocalRouter
            import asyncio
            model = LocalRouter._model
            if model is None:
                return None
            loop = asyncio.get_event_loop()
            emb = await loop.run_in_executor(
                None,
                lambda: model.encode(
                    body_text[:2000], convert_to_numpy=True, show_progress_bar=False
                ),
            )
            return emb.astype("float32").tobytes()
        except Exception as exc:
            log.warning("ReplyLearning embedding failed", error=str(exc))
            return None

    async def _increment_use_count(self, category_id: int) -> None:
        """Increment use_count on all examples for the given category."""
        await self._db._db.execute(
            "UPDATE gmail_reply_examples SET use_count = use_count + 1 "
            "WHERE category_id = ?",
            (category_id,),
        )
        await self._db._db.commit()
