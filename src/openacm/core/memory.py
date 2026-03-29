"""
Memory Manager — conversation history management.

Stores, retrieves, and manages conversation history for each
user/channel combination, with automatic truncation.
"""

import json
from typing import Any
from datetime import datetime, timezone

import structlog

from openacm.core.config import AssistantConfig
from openacm.storage.database import Database

log = structlog.get_logger()

# Maximum estimated tokens for conversation context
MAX_CONTEXT_TOKENS = 16000


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

    @staticmethod
    def _content_for_db(content: Any) -> str:
        """Serialize message content to a clean, human-readable DB string.

        Multimodal lists (text + image_url parts) are flattened:
        - text parts → kept as-is
        - image_url parts → replaced with [IMAGE:file_id] markers
          (file_id is stored in the optional '_file_id' field added by brain.py)
        This prevents raw base64 blobs from ending up in history display.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                t = part.get("type")
                if t == "text":
                    txt = part.get("text", "").strip()
                    if txt:
                        parts.append(txt)
                elif t == "image_url":
                    file_id = part.get("_file_id", "")
                    parts.append(f"[IMAGE:{file_id}]" if file_id else "[📎 image]")
            return "\n".join(parts)
        return str(content)

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
        """Rough token estimate: 1 token ~ 4 characters."""
        total = 0
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += len(content) // 4
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total += len(part.get("text", "")) // 4
            if m.get("tool_calls"):
                try:
                    total += len(json.dumps(m["tool_calls"])) // 4
                except (TypeError, ValueError):
                    total += 50  # fallback estimate per tool call
        return total

    async def add_message(
        self,
        user_id: str,
        channel_id: str,
        role: str,
        content: Any,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
        reasoning_content: str | None = None,
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
        if reasoning_content is not None:  # include even when empty string
            message["reasoning_content"] = reasoning_content
        
        self._cache[key].append(message)
        
        # Truncate if needed — keep tool call pairs intact
        max_messages = self.config.max_context_messages
        if len(self._cache[key]) > max_messages:
            has_system = self._cache[key][0]["role"] == "system"
            system_msg = [self._cache[key][0]] if has_system else []
            rest = self._cache[key][1:] if has_system else self._cache[key][:]

            # Trim from the front but never split an assistant(tool_calls)+tool pair
            target = max_messages - len(system_msg)
            while len(rest) > target:
                # If the first message to drop is an assistant with tool_calls,
                # also drop all consecutive tool messages that follow it.
                if rest[0].get("role") == "assistant" and rest[0].get("tool_calls"):
                    rest.pop(0)
                    while rest and rest[0].get("role") == "tool":
                        rest.pop(0)
                else:
                    rest.pop(0)

            discarded_count = len(self._cache[key]) - len(system_msg) - len(rest)
            discarded = (self._cache[key][1:] if has_system else self._cache[key])[:discarded_count]
            self._cache[key] = system_msg + rest
            
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

        # Token-based truncation: keep total estimated tokens under budget
        while (
            self._estimate_tokens(self._cache[key]) > MAX_CONTEXT_TOKENS
            and len(self._cache[key]) > 3
        ):
            if self._cache[key][0]["role"] == "system":
                removed = self._cache[key].pop(1)
            else:
                removed = self._cache[key].pop(0)
            # Feed removed message to RAG
            try:
                from openacm.core.rag import _rag_engine
                if _rag_engine and _rag_engine.is_ready:
                    import asyncio
                    asyncio.create_task(
                        _rag_engine.ingest_conversation([removed], user_id, channel_id)
                    )
            except Exception:
                pass
        
        # Persist to database — serialize multimodal content to readable text
        db_content = self._content_for_db(content)
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

        On existing conversations the system prompt (messages[0]) is always
        refreshed so that context optimizations (short prompt, tool
        enforcement hints, etc.) take effect on every request.
        """
        key = self._key(user_id, channel_id)

        if key not in self._cache or not self._cache[key]:
            self._cache[key] = [
                {"role": "system", "content": system_prompt}
            ]
        else:
            # Refresh system prompt on every call
            if self._cache[key] and self._cache[key][0]["role"] == "system":
                self._cache[key][0]["content"] = system_prompt
            else:
                # Edge case: no system message at index 0 — prepend one
                self._cache[key].insert(0, {"role": "system", "content": system_prompt})

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
