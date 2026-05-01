"""Workflow tracking, routine hints, and auto-tool generation for Brain."""

import asyncio
import json

import structlog

from openacm.core.messages import (
    MSG_ROUTINES_HEADER,
    MSG_ROUTINES_FOOTER,
    MSG_TOOL_GEN_FAILED,
    MSG_TOOL_GEN_SUCCESS,
    MSG_TOOL_GEN_ERROR,
    MSG_TOOL_REGISTRY_UNAVAILABLE,
)

log = structlog.get_logger()


class BrainWorkflowMixin:

    async def _run_workflow_hook(
        self,
        user_id: str,
        channel_id: str,
        user_message: str,
        tool_sequence_for_turn: list[dict],
        final_response_text: str,
    ) -> str:
        """
        After each agentic turn with tool calls, record the workflow and
        optionally append a suggestion if a repeated pattern is detected.
        Returns final_response_text, possibly with suggestion appended.
        """
        if not self.workflow_tracker or not tool_sequence_for_turn:
            return await self._append_routine_mentions(final_response_text)

        from openacm.core.workflow_tracker import _ALWAYS_NOISE_TOOLS
        import hashlib as _hashlib

        # Filter out meta-tools that don't represent user workflows
        _wf_clean = [
            t["tool"] for t in tool_sequence_for_turn
            if t["tool"] not in {"create_tool", "create_skill", "edit_tool", "delete_tool"}
        ]
        if not _wf_clean:
            return final_response_text

        _signal_tools = [t for t in _wf_clean if t not in _ALWAYS_NOISE_TOOLS]
        if not _signal_tools:
            return final_response_text

        # Record the turn asynchronously (non-blocking)
        asyncio.create_task(
            self.workflow_tracker.record_turn(
                user_id, channel_id, user_message, tool_sequence_for_turn
            )
        )

        # Evaluate whether to show a suggestion
        _sug_hash = _hashlib.sha256(
            "|".join(sorted(_signal_tools)).encode()
        ).hexdigest()[:16]

        try:
            _suggestion = await self.workflow_tracker.evaluate_suggestion(
                user_id, channel_id, _sug_hash
            )
        except Exception as e:
            log.debug("Workflow suggestion evaluation failed", error=str(e))
            _suggestion = None

        if _suggestion:
            _suggestion_key = f"{channel_id}:{user_id}"
            self._pending_suggestions[_suggestion_key] = _suggestion
            return final_response_text + _suggestion.append_text

        return await self._append_routine_mentions(final_response_text)

    async def _append_routine_mentions(self, response_text: str) -> str:
        """
        If there are new pending routines that haven't been mentioned in chat,
        append a brief, friendly note about them.  Only fires once per routine.
        """
        try:
            db = self.memory.database
            routines = await db.get_unmentioned_routines(limit=2)
            if not routines:
                return response_text

            ids = [r["id"] for r in routines]
            await db.mark_routines_mentioned(ids)

            lines = ["\n\n---"]
            lines.append(MSG_ROUTINES_HEADER)
            for r in routines:
                name = r.get("name", "Rutina")
                desc = r.get("description", "")
                apps_raw = r.get("apps", "[]")
                try:
                    import json as _json
                    apps = [a["app_name"] for a in _json.loads(apps_raw) if isinstance(a, dict)]
                except Exception:
                    apps = []
                apps_str = ", ".join(apps[:4]) if apps else "varias apps"
                pct = int(r.get("confidence", 0) * 100)
                line = f"  • **{name}** — {apps_str} ({pct}% de confianza)"
                if desc:
                    line += f"\n    _{desc}_"
                lines.append(line)
            lines.append(MSG_ROUTINES_FOOTER)
            return response_text + "\n".join(lines)
        except Exception as exc:
            log.debug("_append_routine_mentions failed", error=str(exc))
            return response_text

    def _check_workflow_confirmation(self, content: str) -> str:
        """Returns 'yes', 'no', or 'unknown'."""
        text = content.strip().lower()
        if len(text) > 50:  # long message = probably not a confirmation
            return "unknown"
        yes_words = {"sí", "si", "yes", "dale", "adelante", "hazlo", "confirmo",
                     "ok", "claro", "por supuesto", "crear", "conviértelo", "convierte",
                     "generar", "generate", "quiero", "va"}
        no_words = {"no", "nope", "nah", "cancelar", "cancel", "omitir", "skip",
                    "no gracias", "déjalo", "olvídalo", "paso"}
        tokens = set(text.replace(",", " ").replace(".", " ").split())
        if tokens & yes_words:
            return "yes"
        if tokens & no_words:
            return "no"
        return "unknown"

    async def _handle_tool_creation_from_workflow(
        self,
        suggestion,  # SuggestionResult
        user_id: str,
        channel_id: str,
        channel_type: str,
    ) -> str:
        """Generate and initiate tool creation from a detected workflow pattern."""
        import re as _re

        try:
            # Resolve and get cluster data
            rep_executions = await self.workflow_tracker.resolve_suggestion(
                suggestion.suggestion_id, accepted=True
            )
            if not rep_executions:
                return "No pude recuperar el contexto del flujo. Intenta de nuevo."

            cluster = await self.workflow_tracker.get_cluster_context(rep_executions)

            # Build generation prompt
            messages_preview = "\n".join(f'- "{m}"' for m in cluster["user_messages"][:3])
            tools_preview = " → ".join(cluster["most_common_sequence"])

            gen_prompt = (
                f"You are OpenACM's tool generator. The user has repeated this workflow "
                f"{cluster['example_count']} times.\n\n"
                f"## User's typical requests:\n{messages_preview}\n\n"
                f"## Tool sequence used:\n{tools_preview}\n\n"
                f"Generate a Python async tool that automates this workflow. "
                f"Respond ONLY with valid JSON:\n"
                f"{{\n"
                f'  "name": "snake_case_name_max_30_chars",\n'
                f'  "description": "one sentence describing what it does",\n'
                f'  "parameters": "param1: description\\nparam2: description (optional)",\n'
                f'  "code": "complete async Python implementation using run_command/run_python/web_search as needed"\n'
                f"}}"
            )

            response = await self.llm_router.chat(
                messages=[{"role": "user", "content": gen_prompt}],
                temperature=0.3,
                max_tokens=1500,
            )
            raw = response.get("content", "").strip()

            # Parse JSON response
            json_match = _re.search(r'\{.*\}', raw, _re.DOTALL)
            if not json_match:
                return MSG_TOOL_GEN_FAILED

            tool_data = json.loads(json_match.group())

            # Invoke create_tool in preview mode (apply=False)
            if self.tool_registry and "create_tool" in self.tool_registry.tools:
                result = await self.tool_registry.execute(
                    "create_tool",
                    {
                        "name": tool_data.get("name", "auto_workflow"),
                        "description": tool_data.get("description", ""),
                        "parameters": tool_data.get("parameters", ""),
                        "code": tool_data.get("code", ""),
                        "apply": False,
                    },
                    user_id, channel_id, channel_type, _brain=self
                )
                return MSG_TOOL_GEN_SUCCESS.format(result=result)

            return MSG_TOOL_REGISTRY_UNAVAILABLE

        except Exception as e:
            log.error("Workflow tool creation failed", error=str(e))
            return MSG_TOOL_GEN_ERROR.format(error=str(e)[:200])
