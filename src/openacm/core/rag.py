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

    async def ingest_raw_chunks(self, chunks: list[dict[str, Any]]):
        """
        Ingest pre-split chunks in a single upsert call.
        Each chunk must have keys: id, text, metadata.
        Cheaper than calling ingest() per chunk — one embedding batch instead of N.
        """
        if not self._ready or not chunks:
            return
        import asyncio
        collection = _get_collection()
        try:
            await asyncio.to_thread(
                collection.upsert,
                ids=[c["id"] for c in chunks],
                documents=[c["text"] for c in chunks],
                metadatas=[c["metadata"] for c in chunks],
            )
        except Exception as e:
            log.error("RAG ingest_raw_chunks failed", error=str(e))

    async def delete_by_metadata(self, filter_dict: dict[str, Any]):
        """Delete items from the vector store based on metadata filters."""
        if not self._ready:
            return

        import asyncio
        collection = _get_collection()
        try:
            await asyncio.to_thread(collection.delete, where=filter_dict)
        except Exception as e:
            log.error("RAG delete_by_metadata failed", error=str(e))

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

    async def query_with_scores(
        self, question: str, top_k: int = 5
    ) -> list[tuple[str, float]]:
        """
        Query the vector store and return (document, distance) pairs.
        Lower distance = more relevant. Uses cosine distance (0 = identical, 2 = opposite).
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
                include=["documents", "distances"],
            )
            if results and results["documents"] and results["distances"]:
                docs = results["documents"][0]
                distances = results["distances"][0]
                return list(zip(docs, distances))
            return []
        except Exception as e:
            log.error("RAG query_with_scores failed", error=str(e))
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
        """
        Split text into semantically coherent chunks.
        Uses chonkie SentenceChunker when available; falls back to naive split.
        """
        if not text.strip():
            return []

        # ── 1. chonkie SentenceChunker (preferred) ────────────────────────
        try:
            from chonkie import SentenceChunker
            chunker = SentenceChunker(chunk_size=max_chunk, chunk_overlap=50)
            chunks = chunker(text)
            result = [c.text for c in chunks if c.text.strip()]
            if result:
                return result
        except Exception:
            pass  # chonkie unavailable or failed — use fallback below

        # ── 2. Naive paragraph/sentence split (fallback) ──────────────────
        if len(text) <= max_chunk:
            return [text]

        paragraphs = re.split(r'\n\s*\n', text)
        chunks: list[str] = []
        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) <= max_chunk:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
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

    async def get_stats(self) -> dict:
        """Return stats about stored memory: total docs, breakdown by type, folder size."""
        import asyncio
        import os

        if not self._ready:
            return {"status": "unavailable", "total": 0, "by_type": {}, "size_bytes": 0}

        collection = _get_collection()

        def _compute():
            total = collection.count()
            by_type: dict[str, int] = {}
            for type_name in ("note", "conversation", "code_archive"):
                try:
                    result = collection.get(where={"type": type_name}, include=[])
                    by_type[type_name] = len(result["ids"])
                except Exception:
                    by_type[type_name] = 0
            # Sum up any remaining types not in the list above
            known = sum(by_type.values())
            other = total - known
            if other > 0:
                by_type["other"] = other

            # Folder size
            size_bytes = 0
            persist = Path(PERSIST_DIR)
            if persist.exists():
                for f in persist.rglob("*"):
                    if f.is_file():
                        try:
                            size_bytes += f.stat().st_size
                        except OSError:
                            pass
            return {"status": "ready", "total": total, "by_type": by_type, "size_bytes": size_bytes}

        return await asyncio.to_thread(_compute)

    async def clear_all(self) -> int:
        """Delete ALL documents from the vector store. Returns count of deleted docs."""
        import asyncio
        if not self._ready:
            return 0
        collection = _get_collection()

        def _do_clear():
            total = collection.count()
            if total == 0:
                return 0
            # Get all IDs then delete them
            result = collection.get(include=[])
            ids = result.get("ids", [])
            if ids:
                collection.delete(ids=ids)
            return total

        return await asyncio.to_thread(_do_clear)
