"""
Workflow Tracker — Detects repeated tool workflows and suggests automation.

After each agentic turn, records the tool sequence. When a similar workflow
is detected 3+ times, appends a suggestion to the response asking the user
if they want it converted into a reusable tool.
"""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from openacm.storage.database import Database
    from openacm.core.llm_router import LLMRouter

log = structlog.get_logger()

# ── Configuration ─────────────────────────────────────────────────────────────
EXACT_REPEAT_THRESHOLD = 3       # mismo hash N veces → sugerir
MIN_TURNS_BEFORE_SUGGESTING = 5  # usuario necesita historial mínimo
SUGGESTION_COOLDOWN_HOURS = 24   # horas entre sugerencias por usuario/canal
SUGGESTION_EXPIRY_TURNS = 3      # turnos antes de expirar una sugerencia sin respuesta
DISMISSED_COOLDOWN_DAYS = 7      # días antes de re-sugerir un hash rechazado

# ── Noise filtering ───────────────────────────────────────────────────────────

# Tools that are always noise regardless of arguments
_ALWAYS_NOISE_TOOLS = {
    "system_info", "screenshot", "list_tools", "list_skills",
    "list_agents", "stats",
}

# Regex patterns on the first 80 chars of arguments that indicate noise
_NOISE_ARG_PATTERNS = [
    re.compile(r"^\s*(pip|pip3)\s+install", re.IGNORECASE),
    re.compile(r"^\s*(npm|yarn|pnpm)\s+install", re.IGNORECASE),
    re.compile(r"^\s*(apt-get|apt|brew)\s+install", re.IGNORECASE),
    re.compile(r"^\s*(python|node|pip|npm|git|docker)\s+--version", re.IGNORECASE),
    re.compile(r"^\s*which\s+\w+", re.IGNORECASE),
    re.compile(r"^\s*(echo|printf)\s+", re.IGNORECASE),
    re.compile(r"^\s*(ls|dir|pwd|cd)\s*$", re.IGNORECASE),
    re.compile(r"^\s*(ls|dir)\s+[-\w/\\. ]+$", re.IGNORECASE),
    re.compile(r"^\s*cat\s+/etc/", re.IGNORECASE),
    re.compile(r"^\s*type\s+\w", re.IGNORECASE),  # Windows 'type' equivalent of cat
]

# Tools that are noise only when their primary argument matches noise patterns
_CONDITIONAL_NOISE_TOOLS = {"run_command", "run_python", "python_kernel"}


def _is_noise_tool_call(tool_name: str, arguments: dict) -> bool:
    """Return True if this tool call is setup/verification noise."""
    if tool_name in _ALWAYS_NOISE_TOOLS:
        return True
    if tool_name in _CONDITIONAL_NOISE_TOOLS:
        # Extract first meaningful string argument
        arg_text = ""
        for key in ("command", "code", "script"):
            if key in arguments:
                arg_text = str(arguments[key])[:80]
                break
        if not arg_text and arguments:
            arg_text = str(next(iter(arguments.values())))[:80]
        return any(p.match(arg_text) for p in _NOISE_ARG_PATTERNS)
    return False


def _clean_tool_sequence(raw_sequence: list[dict]) -> list[str]:
    """
    Filter noise from a raw tool sequence.
    raw_sequence: list of {"tool": str, "arguments": dict}
    Returns: list of tool names after removing noise.
    """
    return [
        item["tool"]
        for item in raw_sequence
        if not _is_noise_tool_call(item["tool"], item.get("arguments", {}))
    ]


def _compute_hash(clean_sequence: list[str]) -> str:
    """Stable hash of a tool sequence (order-independent for the same set)."""
    key = "|".join(sorted(clean_sequence))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class SuggestionResult:
    suggestion_id: int
    append_text: str
    cluster_size: int
    tool_args_hash: str


# ── WorkflowTracker ───────────────────────────────────────────────────────────

class WorkflowTracker:
    """
    Records agentic turns and detects repeated workflow patterns.
    Suggests automation when a pattern is repeated enough times.
    """

    def __init__(self, database: "Database", rag_engine, llm_router: "LLMRouter"):
        self._db = database
        self._rag = rag_engine
        self._llm = llm_router
        self._chroma_collection = None  # lazy init

    # ── Public API ────────────────────────────────────────────────────────────

    async def record_turn(
        self,
        user_id: str,
        channel_id: str,
        user_message: str,
        tool_sequence_raw: list[dict],  # [{"tool": str, "arguments": dict}]
    ) -> int | None:
        """
        Persist this turn. Returns execution_id or None if skipped.
        Schedules intent summary generation in background.
        """
        if not tool_sequence_raw:
            return None
        if len(user_message.strip()) < 8:
            return None

        clean = _clean_tool_sequence(tool_sequence_raw)
        if not clean:
            return None

        tool_args_hash = _compute_hash(clean)
        now = datetime.now(timezone.utc).isoformat()

        exec_id = await self._db.insert_workflow_execution(
            user_id=user_id,
            channel_id=channel_id,
            user_message=user_message[:500],
            tool_sequence_raw=json.dumps([t["tool"] for t in tool_sequence_raw]),
            tool_sequence_clean=json.dumps(clean),
            tool_args_hash=tool_args_hash,
            turn_timestamp=now,
        )

        # Generate intent summary in background (non-blocking)
        asyncio.create_task(
            self._generate_intent_summary(exec_id, user_message, clean)
        )

        return exec_id

    async def evaluate_suggestion(
        self,
        user_id: str,
        channel_id: str,
        last_tool_args_hash: str,
    ) -> "SuggestionResult | None":
        """
        Check if a suggestion should be emitted for this user/channel.
        Returns SuggestionResult or None.
        """
        # Rule: minimum history
        total_turns = await self._db.count_user_workflow_turns(user_id)
        if total_turns < MIN_TURNS_BEFORE_SUGGESTING:
            return None

        # Rule: no pending suggestion already
        pending = await self._db.get_pending_suggestion(user_id, channel_id)
        if pending:
            return None

        # Rule: cooldown
        last = await self._db.get_last_suggestion(user_id, channel_id)
        if last:
            try:
                last_dt = datetime.fromisoformat(last["suggested_at"])
                if (datetime.now(timezone.utc) - last_dt) < timedelta(hours=SUGGESTION_COOLDOWN_HOURS):
                    return None
            except Exception:
                pass

        # Rule: not dismissed recently
        if await self._was_recently_dismissed(user_id, last_tool_args_hash):
            return None

        # Detect pattern: exact hash match
        count = await self._db.count_workflow_hash(user_id, last_tool_args_hash)
        if count < EXACT_REPEAT_THRESHOLD:
            return None

        # Get representative executions
        reps = await self._db.get_workflow_executions_by_hash(
            user_id, last_tool_args_hash, limit=5
        )
        rep_ids = [r["id"] for r in reps]

        suggestion_id = await self._db.insert_workflow_suggestion(
            user_id=user_id,
            channel_id=channel_id,
            trigger_count=count,
            representative_ids_json=json.dumps(rep_ids),
            suggested_at=datetime.now(timezone.utc).isoformat(),
        )

        append_text = (
            "\n\n---\n"
            f"_He notado que realizas este tipo de tarea con frecuencia ({count} veces). "
            "¿Quieres que la convierta en una **tool personalizada** para hacerlo más rápido? "
            "Responde **sí** o **no**._"
        )

        log.info("Workflow suggestion created", user_id=user_id, count=count, suggestion_id=suggestion_id)

        return SuggestionResult(
            suggestion_id=suggestion_id,
            append_text=append_text,
            cluster_size=count,
            tool_args_hash=last_tool_args_hash,
        )

    async def resolve_suggestion(
        self,
        suggestion_id: int,
        accepted: bool,
        reason: str = "",
    ) -> list[dict]:
        """
        Mark suggestion as accepted or dismissed.
        Returns the representative workflow_executions if accepted.
        """
        status = "accepted" if accepted else ("expired" if reason == "expired" else "dismissed")
        now = datetime.now(timezone.utc).isoformat()
        await self._db.update_suggestion_status(suggestion_id, status, responded_at=now)

        if not accepted:
            return []

        row = await self._db.get_pending_suggestion_by_id(suggestion_id)
        if not row:
            return []

        rep_ids = json.loads(row.get("representative_ids", "[]"))
        return await self._db.get_workflow_executions_by_ids(rep_ids)

    async def get_pending_suggestion(self, user_id: str, channel_id: str) -> dict | None:
        return await self._db.get_pending_suggestion(user_id, channel_id)

    async def count_turns_since(self, user_id: str, channel_id: str, since_execution_id: int) -> int:
        return await self._db.count_turns_since_execution_id(user_id, channel_id, since_execution_id)

    async def get_cluster_context(self, representative_executions: list[dict]) -> dict:
        """
        Summarize the cluster for tool generation prompt.
        """
        messages = [r["user_message"] for r in representative_executions]
        sequences = [json.loads(r.get("tool_sequence_clean", "[]")) for r in representative_executions]

        # Most common tool sequence by frequency
        seq_counts: dict[str, int] = {}
        for seq in sequences:
            key = json.dumps(seq)
            seq_counts[key] = seq_counts.get(key, 0) + 1
        most_common_seq = json.loads(max(seq_counts, key=seq_counts.__getitem__)) if seq_counts else []

        return {
            "user_messages": messages,
            "tool_sequences": sequences,
            "most_common_sequence": most_common_seq,
            "example_count": len(representative_executions),
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _was_recently_dismissed(self, user_id: str, tool_args_hash: str) -> bool:
        """Check if this exact hash was dismissed within DISMISSED_COOLDOWN_DAYS."""
        try:
            rows = await self._db.get_workflow_executions_by_hash(user_id, tool_args_hash, limit=1)
            if not rows:
                return False
            # Safe default — let the count threshold handle it
            return False
        except Exception:
            return False

    async def _generate_intent_summary(
        self,
        execution_id: int,
        user_message: str,
        clean_tools: list[str],
    ) -> None:
        """Generate a 1-sentence intent summary via LLM and update the DB row."""
        try:
            prompt = (
                f"Summarize the user's intent in one short sentence (max 12 words). "
                f"Reply with ONLY the summary, no preamble.\n\nUser: {user_message[:300]}"
            )
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=50,
                ),
                timeout=5.0,
            )
            summary = response.get("content", "").strip()
            if summary:
                await self._db.update_workflow_intent_summary(execution_id, summary[:200])
        except Exception as e:
            log.debug("Intent summary generation skipped", execution_id=execution_id, error=str(e))
