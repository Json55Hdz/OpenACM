"""
Memory Manager — conversation history management.

Stores, retrieves, and manages conversation history for each
user/channel combination, with automatic truncation and compaction.
"""

import asyncio
import json
from typing import Any
from datetime import datetime, timezone

import structlog

from openacm.core.config import AssistantConfig
from openacm.storage.database import Database

log = structlog.get_logger()

# Maximum estimated tokens for conversation context
MAX_CONTEXT_TOKENS = 22000  # ~66k chars with //3 estimate ≈ same window as before

# Conversation compaction settings
COMPACT_THRESHOLD = 25       # Trigger compaction after this many messages
COMPACT_KEEP_RECENT = 6      # Keep the last N messages verbatim after compaction

# Prompt used to summarize old messages
_COMPACT_SYSTEM_PROMPT = (
    "You are a conversation summarizer. Summarize the following conversation "
    "between a user and an AI assistant into a concise paragraph. "
    "Preserve key facts, decisions, file paths, code snippets, tool results, "
    "and any important context the assistant would need to continue helping. "
    "Write in the same language the user used. Be concise but thorough — "
    "this summary replaces the original messages."
)


class MemoryManager:
    """Manages conversation memory per user/channel pair."""

    def __init__(self, database: Database, config: AssistantConfig):
        self.database = database
        self.config = config
        self._llm_router: Any = None  # set by brain.py after init
        # In-memory cache for active conversations
        self._cache: dict[str, list[dict[str, Any]]] = {}
        # Track which conversations have a pending compaction to avoid double-firing
        self._compacting: set[str] = set()

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
        """Rough token estimate: 1 token ~ 3 characters (accounts for Spanish/English mixed content)."""
        total = 0
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += len(content) // 3
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total += len(part.get("text", "")) // 3
            if m.get("tool_calls"):
                try:
                    total += len(json.dumps(m["tool_calls"])) // 3
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
            self._cache[key] = system_msg + rest
            # Note: discarded messages are already persisted in SQLite via log_message.
            # RAG (ChromaDB) is reserved for explicit notes/facts, not conversation overflow.

        # Token-based truncation: keep total estimated tokens under budget
        # Removed messages are already in SQLite — no need to re-ingest into RAG.
        while (
            self._estimate_tokens(self._cache[key]) > MAX_CONTEXT_TOKENS
            and len(self._cache[key]) > 3
        ):
            if self._cache[key][0]["role"] == "system":
                self._cache[key].pop(1)
            else:
                self._cache[key].pop(0)
        
        # Persist to database — serialize multimodal content to readable text
        db_content = self._content_for_db(content)
        await self.database.log_message(
            user_id=user_id,
            channel_id=channel_id,
            role=role,
            content=db_content,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Auto-compact: when conversation gets long, summarize old messages
        non_system = [m for m in self._cache[key] if m.get("role") != "system"]
        if (
            len(non_system) >= COMPACT_THRESHOLD
            and key not in self._compacting
            and self._llm_router is not None
        ):
            asyncio.create_task(self._compact(user_id, channel_id))

    async def get_messages(self, user_id: str, channel_id: str) -> list[dict[str, Any]]:
        """Get conversation history for a user/channel pair."""
        key = self._key(user_id, channel_id)
        return self._cache.get(key, [])

    async def get_or_create(
        self, user_id: str, channel_id: str, system_prompt: str
    ) -> list[dict[str, Any]]:
        """
        Get existing conversation or create a new one with system prompt.

        On cache miss (new session / restart) restores the last N messages
        from SQLite so context survives across restarts.
        On existing conversations the system prompt (messages[0]) is always
        refreshed so that context optimizations take effect on every request.
        """
        key = self._key(user_id, channel_id)

        if key not in self._cache or not self._cache[key]:
            # Restore from DB — SQLite is the source of truth for history
            restored = await self._load_from_db(user_id, channel_id)
            self._cache[key] = [{"role": "system", "content": system_prompt}] + restored
        else:
            # Refresh system prompt on every call
            if self._cache[key][0]["role"] == "system":
                self._cache[key][0]["content"] = system_prompt
            else:
                self._cache[key].insert(0, {"role": "system", "content": system_prompt})

        return self._cache[key]

    async def _load_from_db(self, user_id: str, channel_id: str) -> list[dict[str, Any]]:
        """
        Load recent conversation messages from SQLite.
        Filters out system messages and tool results (no context to interpret them).
        Returns a list ready to be appended after the system prompt.
        """
        try:
            rows = await self.database.get_conversation(
                user_id, channel_id, limit=self.config.max_context_messages
            )
        except Exception:
            return []

        messages = []
        for row in rows:
            role = row.get("role", "")
            content = row.get("content", "")
            # Skip system messages (we add our own), tool results (need original tool_call_id),
            # and empty content
            if role in ("system", "tool") or not content or not content.strip():
                continue
            # Skip assistant messages that were pure tool-call planners (no visible text)
            messages.append({"role": role, "content": content})

        return messages

    async def _compact(self, user_id: str, channel_id: str) -> None:
        """
        Summarize older messages into a single summary message to save tokens.

        Keeps the system prompt + injects a summary + keeps the last COMPACT_KEEP_RECENT
        messages verbatim so the LLM has recent context.
        """
        key = self._key(user_id, channel_id)
        if key in self._compacting:
            return
        self._compacting.add(key)

        try:
            msgs = self._cache.get(key, [])
            if not msgs:
                return

            # Split: system prompt | old messages to summarize | recent messages to keep
            has_system = msgs[0]["role"] == "system"
            system_msg = [msgs[0]] if has_system else []
            rest = msgs[1:] if has_system else msgs[:]

            if len(rest) < COMPACT_THRESHOLD:
                return

            keep_count = COMPACT_KEEP_RECENT
            to_summarize = rest[:-keep_count] if keep_count < len(rest) else []
            to_keep = rest[-keep_count:] if keep_count < len(rest) else rest

            if len(to_summarize) < 4:
                return  # not worth summarizing fewer than 4 messages

            # Build a transcript of old messages for the summarizer
            transcript_lines = []
            for m in to_summarize:
                role = m.get("role", "unknown")
                content = m.get("content", "")
                if isinstance(content, list):
                    content = self._content_for_db(content)
                # Skip tool results and empty messages in transcript
                if not content or not content.strip():
                    continue
                label = {"user": "User", "assistant": "Assistant", "tool": "Tool"}.get(role, role)
                # Truncate very long messages in transcript
                if len(content) > 500:
                    content = content[:500] + "..."
                transcript_lines.append(f"{label}: {content}")

            if not transcript_lines:
                return

            transcript = "\n".join(transcript_lines)

            # Call LLM to summarize
            summary_messages = [
                {"role": "system", "content": _COMPACT_SYSTEM_PROMPT},
                {"role": "user", "content": f"Summarize this conversation:\n\n{transcript}"},
            ]

            result = await self._llm_router.chat(
                messages=summary_messages,
                temperature=0.3,
                max_tokens=500,
            )

            summary_text = result.get("content", "").strip()
            if not summary_text:
                log.warning("Compaction produced empty summary", key=key)
                return

            # Replace old messages with summary
            summary_msg = {
                "role": "assistant",
                "content": f"[Conversation summary — {len(to_summarize)} earlier messages]\n{summary_text}",
            }

            self._cache[key] = system_msg + [summary_msg] + to_keep

            log.info(
                "Conversation compacted",
                key=key,
                summarized_messages=len(to_summarize),
                kept_messages=len(to_keep),
                summary_tokens=self._estimate_tokens([summary_msg]),
            )

        except Exception as e:
            log.error("Conversation compaction failed", error=str(e), key=key)
        finally:
            self._compacting.discard(key)

    async def clear(self, user_id: str, channel_id: str):
        """Clear conversation history for a user/channel pair."""
        key = self._key(user_id, channel_id)
        self._cache.pop(key, None)
        log.info("Conversation cleared", user_id=user_id, channel_id=channel_id)

    async def clear_all(self):
        """Clear all conversation history."""
        self._cache.clear()
        log.info("All conversations cleared")
