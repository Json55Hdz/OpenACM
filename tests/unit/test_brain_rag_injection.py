"""Long-term memory (RAG) fragments must reach the model, not only the dashboard event."""

import pytest

from openacm.core import rag as rag_module


class _FakeRag:
    is_ready = True

    async def query_with_scores(self, query, top_k=5):
        return [("RECUERDO-UNICO-QWERTY el usuario prefiere Postgres", 0.05)]


async def test_rag_fragments_are_in_the_messages_the_llm_receives(brain, mock_llm_router, monkeypatch):
    monkeypatch.setattr(rag_module, "_rag_engine", _FakeRag())
    await brain.process_message("que base de datos prefiero para mi proyecto", "u1", "chan1", "web")

    sent = mock_llm_router.chat.await_args.kwargs.get("messages") or mock_llm_router.chat.await_args.args[0]
    assert "RECUERDO-UNICO-QWERTY" in str(sent)
