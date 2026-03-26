"""
RAG Engine — Retrieval-Augmented Generation for long-term memory.

Uses ChromaDB with local sentence-transformer embeddings to store and
retrieve conversation fragments, notes, and document chunks.
"""

import os
import re
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

# Lazy-loaded globals
_chroma_client = None
_collection = None
_embedding_fn = None

PERSIST_DIR = "data/vectordb"
COLLECTION_NAME = "openacm_memory"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Global accessible reference for tools
_rag_engine = None


def _get_embedding_fn():
    """Lazy-load the embedding function."""
    global _embedding_fn
    if _embedding_fn is None:
        try:
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
            _embedding_fn = SentenceTransformerEmbeddingFunction(
                model_name=EMBEDDING_MODEL,
            )
            log.info("RAG embedding model loaded", model=EMBEDDING_MODEL)
        except Exception as e:
            log.error("Failed to load embedding model", error=str(e))
            raise
    return _embedding_fn


def _get_collection():
    """Lazy-load the ChromaDB collection."""
    global _chroma_client, _collection
    if _collection is None:
        import chromadb

        persist_path = Path(PERSIST_DIR)
        persist_path.mkdir(parents=True, exist_ok=True)

        _chroma_client = chromadb.PersistentClient(path=str(persist_path))
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=_get_embedding_fn(),
            metadata={"hnsw:space": "cosine"},
        )
        log.info("RAG collection ready", documents=_collection.count())
    return _collection


class RAGEngine:
    """Long-term memory engine using ChromaDB vector search."""

    def __init__(self):
        self._ready = False

    async def initialize(self):
        """Initialize the RAG engine (loads models + DB)."""
        try:
            import asyncio
            # Run the heavy init in a thread to not block the event loop
            await asyncio.to_thread(_get_collection)
            self._ready = True
            log.info("RAG engine initialized")
        except Exception as e:
            log.warning("RAG engine unavailable — running without long-term memory", error=str(e))
            self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready

    async def ingest(self, text: str, metadata: dict[str, Any] | None = None, doc_id: str | None = None):
        """
        Ingest text into the vector store.
        Splits into chunks and stores each with metadata.
        """
        if not self._ready:
            return

        import asyncio

        chunks = self._split_text(text)
        if not chunks:
            return

        collection = _get_collection()
        ids = []
        documents = []
        metadatas = []

        import hashlib
        for i, chunk in enumerate(chunks):
            chunk_id = doc_id or hashlib.sha256(chunk.encode()).hexdigest()[:16]
            full_id = f"{chunk_id}_{i}"
            ids.append(full_id)
            documents.append(chunk)
            metadatas.append(metadata or {})

        try:
            await asyncio.to_thread(
                collection.upsert,
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
        except Exception as e:
            log.error("RAG ingest failed", error=str(e))

    async def query(self, question: str, top_k: int = 5) -> list[str]:
        """
        Query the vector store for relevant fragments.
        Returns list of text fragments sorted by relevance.
        """
        if not self._ready:
            return []

        import asyncio
        collection = _get_collection()

        try:
            results = await asyncio.to_thread(
                collection.query,
                query_texts=[question],
                n_results=top_k,
            )
            if results and results["documents"]:
                # Flatten — results["documents"] is [[doc1, doc2, ...]]
                return results["documents"][0]
            return []
        except Exception as e:
            log.error("RAG query failed", error=str(e))
            return []

    async def ingest_conversation(self, messages: list[dict[str, Any]], user_id: str = "", channel_id: str = ""):
        """
        Ingest a list of conversation messages into long-term memory.
        Pairs user/assistant messages for better context.
        """
        if not self._ready:
            return

        pairs = []
        current_pair = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system" or not isinstance(content, str):
                continue

            current_pair.append(f"{role}: {content}")

            if role == "assistant" and current_pair:
                pairs.append("\n".join(current_pair))
                current_pair = []

        # Ingest remaining
        if current_pair:
            pairs.append("\n".join(current_pair))

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()

        for i, pair_text in enumerate(pairs):
            if len(pair_text.strip()) < 20:
                continue  # Skip trivial exchanges
            await self.ingest(
                pair_text,
                metadata={
                    "type": "conversation",
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "timestamp": ts,
                },
            )

    async def remember(self, note: str, user_id: str = ""):
        """Store a specific note/fact in long-term memory."""
        if not self._ready:
            return

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()

        await self.ingest(
            note,
            metadata={
                "type": "note",
                "user_id": user_id,
                "timestamp": ts,
            },
        )

    def _split_text(self, text: str, max_chunk: int = 500) -> list[str]:
        """Split text into chunks roughly max_chunk characters each."""
        if len(text) <= max_chunk:
            return [text] if text.strip() else []

        # Split by paragraphs first, then by sentences
        paragraphs = re.split(r'\n\s*\n', text)
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) <= max_chunk:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # If single paragraph is too long, split by sentences
                if len(para) > max_chunk:
                    sentences = re.split(r'(?<=[.!?])\s+', para)
                    current_chunk = ""
                    for sent in sentences:
                        if len(current_chunk) + len(sent) <= max_chunk:
                            current_chunk += (" " if current_chunk else "") + sent
                        else:
                            if current_chunk:
                                chunks.append(current_chunk)
                            current_chunk = sent
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        return [c for c in chunks if c.strip()]
""" 
async def get_stats(self) -> dict:
    if not self._ready:
        return {"status": "unavailable"}
    collection = _get_collection()
    return {
        "status": "ready",
        "documents": collection.count(),
        "model": EMBEDDING_MODEL,
    }
"""
