"""Reading what the LLM and the workers write: plans, JSON repair, task status, output trimming."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from openacm.constants import TRUNCATE_SWARM_TASK_OUTPUT_CHARS
from openacm.utils.text import truncate

log = structlog.get_logger()


class SwarmParsingMixin:
    """Methods of SwarmManager, kept in their own module to keep swarm_manager.py readable."""

    @staticmethod
    def _parse_task_status(response: str) -> tuple[str, str]:
        """
        Scan the last few lines of a worker response for an explicit status marker.
        Returns (status, fail_reason) where status is 'completed', 'failed', or 'waiting'.
        'waiting' means the worker asked the user a question and needs an answer to proceed.
        Falls back to failure detection heuristics before defaulting to 'completed'.
        """
        import re as _re

        # Signals that the brain interrupted the worker before it could finish.
        # These must be detected BEFORE checking for TASK_STATUS markers so a
        # partial response that happens to precede one of these strings doesn't
        # accidentally get marked completed.
        _BRAIN_INTERRUPTS = (
            "alcanzé el límite de pasos",       # brain: max_iterations in Spanish
            "no obtuve una respuesta final",     # brain: empty_response fallback
            "❌ request timed out",              # brain/swarm: readError/timeout
            "readError",                         # raw exception string
            "readerror",
            "timed out",
            "task timed out",
        )
        response_lower = response.lower()
        _has_marker = _re.search(r"^\s*TASK_STATUS:\s*(COMPLETED|FAILED)", response, _re.IGNORECASE | _re.MULTILINE)
        # An explicit marker is the worker's own verdict: a finished report that merely mentions
        # "timed out" must not be turned into a failure. Phrases only decide when there is none.
        if not _has_marker and any(sig.lower() in response_lower for sig in _BRAIN_INTERRUPTS):
            return "failed", "Worker hit step limit or connection timeout before completing"

        for line in reversed(response.strip().splitlines()):
            line = line.strip()
            m = _re.match(r"TASK_STATUS:\s*(COMPLETED|FAILED)(?::\s*(.*))?", line, _re.IGNORECASE)
            if m:
                status = m.group(1).lower()
                reason = (m.group(2) or "").strip()
                # Special case: waiting_for_user means blocked on user input, not a real failure
                if "waiting_for_user" in reason.lower():
                    return "waiting", reason
                return status, reason
        # No explicit marker — infer from output quality rather than defaulting to success.
        # A response with code blocks or substantial content is likely real work; anything
        # short or empty is a silent failure that should be retried, not treated as done.
        stripped = response.strip() if response else ""
        if "```" in stripped or len(stripped) > 400:
            return "completed", ""
        return "failed", "Worker produced no output and did not confirm completion (missing TASK_STATUS marker)"

    @staticmethod
    def _smart_truncate_output(text: str, max_chars: int) -> str:
        """
        Truncate a task output while preserving code blocks.
        Workers downstream need the actual code above all else — prose can be cut,
        but a fenced code block that gets sliced in half is worse than nothing.
        Strategy:
          1. If the full text fits, return it as-is.
          2. Collect all fenced code blocks. If they fit within the budget, include
             all of them plus as much leading prose as the remaining budget allows.
          3. If code alone exceeds the budget, include blocks greedily until full.
        """
        import re as _re
        if len(text) <= max_chars:
            return text

        code_blocks = _re.findall(r"```[\s\S]*?```", text)
        if not code_blocks:
            return text[:max_chars] + "\n… [truncated]"

        code_total = sum(len(b) for b in code_blocks)
        if code_total <= max_chars:
            prose_budget = max_chars - code_total
            prose = _re.sub(r"```[\s\S]*?```", "", text).strip()
            header = (prose[:prose_budget] + "\n\n") if prose_budget > 80 else ""
            return header + "\n\n".join(code_blocks)

        # Code alone overflows — include blocks greedily
        parts: list[str] = []
        remaining = max_chars
        for block in code_blocks:
            if remaining <= 0:
                break
            if len(block) <= remaining:
                parts.append(block)
                remaining -= len(block)
            else:
                parts.append(block[:remaining] + "\n… [truncated]\n```")
                remaining = 0
        return "\n\n".join(parts)

    @staticmethod
    @staticmethod
    def _json_is_truncated(text: str) -> bool:
        """Return True if the JSON looks cut off (unbalanced braces/brackets)."""
        t = text.strip()
        opens = t.count("{") - t.count("}")
        arr_opens = t.count("[") - t.count("]")
        return opens > 0 or arr_opens > 0

    @staticmethod
    def _extract_json_array(text: str) -> str:
        """Pull the first [...] JSON array out of an LLM response (strips fences/prose)."""
        import re as _re
        stripped = text.strip()
        # Direct array
        if stripped.startswith("["):
            return stripped
        # Fenced code block
        m = _re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", stripped)
        if m:
            candidate = m.group(1).strip()
            if candidate.startswith("["):
                return candidate
        # Any [...] in the text
        m = _re.search(r"\[[\s\S]*\]", stripped)
        if m:
            return m.group()
        return stripped

    @staticmethod
    def _repair_json(text: str) -> str:
        """
        Best-effort repair of common LLM JSON mistakes:
        - Trailing commas before } or ]
        - Truncated JSON: close what is still open, innermost first.

        Walks the text so braces inside strings are not counted. A reply cut off inside a
        string cannot be repaired honestly, so it is returned as is and fails to parse.
        """
        import re as _re
        # Remove trailing commas before closing brackets/braces
        text = _re.sub(r",\s*([}\]])", r"\1", text)

        stack: list[str] = []
        in_string = False
        escaped = False
        for ch in text:
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack and stack[-1] == ch:
                stack.pop()
        if in_string or not stack:
            return text
        return text.rstrip().rstrip(",") + "".join(reversed(stack))

    def _parse_plan(self, text: str) -> dict:
        """Extract JSON plan from LLM response."""
        import re
        stripped = text.strip()

        # 1. Direct parse (model returned raw JSON)
        try:
            return json.loads(stripped)
        except Exception:
            pass

        # 2. Extract content from markdown fence using regex (handles trailing newlines, ```json, etc.)
        fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", stripped)
        if fence_match:
            candidate = fence_match.group(1).strip()
            try:
                return json.loads(candidate)
            except Exception:
                # Try repairing the fenced content (truncated JSON)
                try:
                    return json.loads(self._repair_json(candidate))
                except Exception:
                    pass

        # 3. Find any {...} JSON object in the text (greedy — catches the outermost object)
        obj_match = re.search(r"\{[\s\S]*\}", stripped)
        if obj_match:
            try:
                return json.loads(obj_match.group())
            except Exception:
                pass

        # 4. Repair from the first { to the end of the reply. A reply cut off mid-task must be
        #    closed from the END: repairing only up to the last } would drop the cut-off tasks
        #    and the swarm would start with a smaller plan than the model wrote.
        first_brace = stripped.find("{")
        if first_brace != -1:
            for candidate in (stripped[first_brace:], obj_match.group() if obj_match else ""):
                try:
                    plan = json.loads(self._repair_json(candidate))
                except Exception:
                    continue
                log.warning("Swarm plan looked cut off and was repaired; the last task may be incomplete")
                return plan

        log.error("Failed to parse swarm plan", text=text[:500])
        raise ValueError("Could not extract valid JSON from swarm plan response")

    @staticmethod
    def _safe_slug(text: str, max_len: int = 40) -> str:
        """Convert any string to a filesystem/ID-safe slug."""
        import re as _re
        slug = _re.sub(r'[^a-z0-9_-]', '_', text.lower())
        slug = _re.sub(r'_+', '_', slug).strip('_')
        return (slug[:max_len] or "unnamed")
