"""
Memory Manager — conversation history management.

Stores, retrieves, and manages conversation history for each
user/channel combination, with automatic truncation.
"""

from typing import Any
from datetime import datetime, timezone

import structlog

from openacm.core.config import AssistantConfig
from openacm.storage.database import Database

log = structlog.get_logger()


class MemoryManager:
    """Manages conversation memory per user/channel pair."""

    def __init__(self, database: Database, config: AssistantConfig):
        self.database = database
        self.config = config
        # In-memory cache for active conversations
        self._cache: dict[str, list[dict[str, Any]]] = {}

    def _key(self, user_id: str, channel_id: str) -> str:
        """Generate a unique key for a user/channel pair."""
        return f"{channel_id}:{user_id}"

    async def add_message(
        self,
        user_id: str,
        channel_id: str,
        role: str,
        content: Any,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ):
        """Add a message to the conversation history."""
        key = self._key(user_id, channel_id)
        
        if key not in self._cache:
            self._cache[key] = []
        
        message: dict[str, Any] = {
            "role": role,
            "content": content,
        }
        
        if tool_calls:
            message["tool_calls"] = tool_calls
        if tool_call_id:
            message["tool_call_id"] = tool_call_id
        if name:
            message["name"] = name
        
        self._cache[key].append(message)
        
        # Truncate if needed
        max_messages = self.config.max_context_messages
        if len(self._cache[key]) > max_messages:
            # Keep the system prompt (first message) and trim the oldest after that
            if self._cache[key][0]["role"] == "system":
                discarded = self._cache[key][1:-(max_messages - 1)]
                self._cache[key] = [self._cache[key][0]] + self._cache[key][-(max_messages - 1):]
            else:
                discarded = self._cache[key][:-max_messages]
                self._cache[key] = self._cache[key][-max_messages:]
            
            # Ingest discarded messages into RAG for long-term memory
            if discarded:
                try:
                    from openacm.core.rag import _rag_engine
                    if _rag_engine and _rag_engine.is_ready:
                        import asyncio
                        asyncio.create_task(
                            _rag_engine.ingest_conversation(discarded, user_id, channel_id)
                        )
                except Exception:
                    pass  # RAG is optional
        
        # Persist to database (stringified for non-text objects)
        db_content = str(content) if not isinstance(content, str) else content
        await self.database.log_message(
            user_id=user_id,
            channel_id=channel_id,
            role=role,
            content=db_content,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def get_messages(self, user_id: str, channel_id: str) -> list[dict[str, Any]]:
        """Get conversation history for a user/channel pair."""
        key = self._key(user_id, channel_id)
        return self._cache.get(key, [])

    async def get_or_create(
        self, user_id: str, channel_id: str, system_prompt: str
    ) -> list[dict[str, Any]]:
        """
        Get existing conversation or create a new one with system prompt.
        """
        key = self._key(user_id, channel_id)
        
        if key not in self._cache or not self._cache[key]:
            self._cache[key] = [
                {"role": "system", "content": system_prompt}
            ]
        
        return self._cache[key]

    async def clear(self, user_id: str, channel_id: str):
        """Clear conversation history for a user/channel pair."""
        key = self._key(user_id, channel_id)
        self._cache.pop(key, None)
        log.info("Conversation cleared", user_id=user_id, channel_id=channel_id)

    async def clear_all(self):
        """Clear all conversation history."""
        self._cache.clear()
        log.info("All conversations cleared")
