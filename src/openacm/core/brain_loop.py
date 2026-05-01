"""Agentic loop and LLM message preparation for Brain."""

import asyncio
import json
import re

import structlog

from openacm.core.acm_context import current_channel_id
from openacm.core.events import (
    EVENT_MESSAGE_SENT,
    EVENT_THINKING,
    EVENT_TOOL_CALLED,
    EVENT_TOOL_RESULT,
)
from openacm.core.messages import (
    MSG_CANCELLED,
    MSG_CANCELLED_FOLLOWUP,
    MSG_COMPACTING,
    MSG_EMPTY_RESPONSE,
    MSG_MAX_ITERATIONS,
    MSG_STEP,
    MSG_THINKING,
    MSG_TOOL_EXECUTING,
)
from openacm.core.output_compressor import compress as compress_output, compression_summary

log = structlog.get_logger()

# Matches all ANSI/VT100 escape sequences (colors, cursor moves, OSC title-set, etc.)
# Order matters: longer/more-specific patterns must come first.
_ANSI_RE = re.compile(
    r'\x1b(?:'
    r'\][^\x07\x1b]*(?:\x07|\x1b\\)'   # OSC: ESC ] ... BEL or ST  (e.g. \x1b]0;title\x1b\\)
    r'|\[[0-?]*[ -/]*[@-~]'            # CSI: ESC [ ... final byte  (e.g. \x1b[1;32m)
    r'|[@-Z\\-_]'                       # 2-byte Fe/Fs: ESC + single char in range
    r')'
)


def _strip_ansi(text: str) -> str:
    """Remove ANSI/VT100 escape sequences from terminal output."""
    return _ANSI_RE.sub("", text)


def _clean_tool_call_id(call_id: str) -> str:
    """
    Strip Gemini's extended-thinking blob from tool call IDs.

    When a Gemini model runs with thinking enabled, LiteLLM encodes the
    thinking tokens inside the tool call ID as:
        call_<hex>__thought__<base64-blob>
    The blob can be thousands of characters and gets re-sent in every
    subsequent tool message, burning tokens. We keep only the stable prefix.
    """
    if "__thought__" in call_id:
        call_id = call_id.split("__thought__")[0]
    return call_id


class BrainLoopMixin:

    # Messages older than this index (from the end) get aggressively stripped to save tokens.
    _RECENT_MSG_WINDOW = 6  # keep full detail for the last N messages
    _OLD_REASONING_MAX = 0  # strip reasoning_content from old messages entirely

    def _prepare_messages_for_llm(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        is_tool_loop: bool,
    ) -> list[dict]:
        """Return a copy of *messages* optimized for the LLM call.

        Optimizations applied (only to messages older than _RECENT_MSG_WINDOW):
        1. Tool enforcement injection (for weak providers)
        2. Null old tool results — content → "" (tool_call_id kept for structure).
           After the LLM processed a tool result, storing its text is wasteful.
        3. Strip tool_call arguments from old assistant messages — the JSON args blob
           can be hundreds of tokens; only the function name + id are needed for context.
        4. Strip reasoning_content from old messages (thinking models produce huge blobs).

        The original list is never mutated (memory stays clean).
        """
        profile = self.llm_router.get_provider_profile()
        total = len(messages)
        cutoff = max(0, total - self._RECENT_MSG_WINDOW)

        # Index of the last user message — images in older user messages are replaced
        # with placeholders since the LLM has already "seen" them.
        last_user_idx = max(
            (i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1
        )

        prepared = []
        for i, msg in enumerate(messages):
            is_old = i > 0 and i < cutoff  # index 0 = system, always keep

            needs_copy = False
            role = msg.get("role")

            # 5. Replace base64 image data in user messages that are not the latest.
            # Once the LLM has processed an image and responded, re-sending the full
            # base64 blob on every subsequent call wastes thousands of tokens.
            if (
                role == "user"
                and i != last_user_idx
                and isinstance(msg.get("content"), list)
            ):
                has_image = any(
                    p.get("type") == "image_url" for p in msg["content"] if isinstance(p, dict)
                )
                if has_image:
                    needs_copy = True

            if is_old:
                # tool messages: null content entirely — tool_call_id is all that's needed
                if role == "tool" and msg.get("content"):
                    needs_copy = True

                # assistant messages with tool_calls: strip the arguments JSON blob
                if role == "assistant" and msg.get("tool_calls"):
                    needs_copy = True

                # strip reasoning_content from old messages
                if msg.get("reasoning_content"):
                    needs_copy = True

            if needs_copy:
                msg = msg.copy()

                # Replace base64 images with lightweight placeholders
                if role == "user" and isinstance(msg.get("content"), list):
                    new_parts = []
                    for part in msg["content"]:
                        if isinstance(part, dict) and part.get("type") == "image_url":
                            file_id = part.get("_file_id", "image")
                            new_parts.append({"type": "text", "text": f"[IMAGE: {file_id} — already processed]"})
                        else:
                            new_parts.append(part)
                    msg["content"] = new_parts

                if is_old:
                    if role == "tool":
                        msg["content"] = ""

                    if role == "assistant" and msg.get("tool_calls"):
                        slim_calls = []
                        for tc in msg["tool_calls"]:
                            fn = tc.get("function", {})
                            slim_calls.append({
                                "id": tc.get("id", ""),
                                "type": tc.get("type", "function"),
                                "function": {"name": fn.get("name", ""), "arguments": "{}"},
                            })
                        msg["tool_calls"] = slim_calls

                    if msg.get("reasoning_content"):
                        msg.pop("reasoning_content", None)

            prepared.append(msg)

        # Tool enforcement injection for weak providers
        if tools and profile.needs_tool_enforcement and not is_tool_loop:
            if prepared and prepared[0].get("role") == "system":
                sys_msg = prepared[0].copy()
                sys_msg["content"] = f"{sys_msg['content']}\n\n{self._TOOL_ENFORCEMENT_MSG}"
                prepared[0] = sys_msg

        return prepared

    async def _run(
        self,
        content: str,
        user_id: str,
        channel_id: str,
        channel_type: str = "console",
        attachments: list[str] | None = None,
        is_transparent: bool = False,
    ) -> str:
        """Core message processing — runs inside a cancellable task."""
        from openacm.core.events import EVENT_MESSAGE_RECEIVED

        if not is_transparent:
            await self.event_bus.emit(
                EVENT_MESSAGE_RECEIVED,
                {
                    "content": content,
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                    "attachments": attachments or [],
                },
            )

        # ── Workflow suggestion interception ──────────────────────────────────────
        _suggestion_key = f"{channel_id}:{user_id}"
        _pending_sug = self._pending_suggestions.get(_suggestion_key)
        if _pending_sug:
            _confirmation = self._check_workflow_confirmation(content)
            if _confirmation == "yes":
                self._pending_suggestions.pop(_suggestion_key, None)
                return await self._handle_tool_creation_from_workflow(
                    _pending_sug, user_id, channel_id, channel_type
                )
            elif _confirmation == "no":
                self._pending_suggestions.pop(_suggestion_key, None)
                if self.workflow_tracker:
                    await self.workflow_tracker.resolve_suggestion(
                        _pending_sug.suggestion_id, accepted=False
                    )
                # fall through — process the message normally

        await self.event_bus.emit(
            EVENT_THINKING,
            {
                "status": "start",
                "message": MSG_THINKING,
                "user_id": user_id,
                "channel_id": channel_id,
                "channel_type": channel_type,
            },
        )

        # LocalRouter: classify intent for observation + passive learning
        _router_task = asyncio.create_task(self.local_router.observe(content))

        # Accumulate tool calls for this agentic turn (for workflow tracking)
        _tool_sequence_for_turn: list[dict] = []

        # Build system prompt + fetch/create conversation messages
        _system_prompt, messages = await self._build_system_prompt(content, user_id, channel_id, channel_type)

        # Inject RAG long-term memory context
        messages = await self._inject_rag_context(content, channel_id, channel_type, messages)

        # Build structured content if there are attachments
        final_content = content
        if attachments:
            final_content = await self._resolve_attachment_content(content, attachments)

        # Add user message
        if not is_transparent:
            await self.memory.add_message(user_id, channel_id, "user", final_content)

        # Compact synchronously if needed — pauses the conversation like Claude Code does
        if self.memory.should_compact(user_id, channel_id):
            await self.event_bus.emit(EVENT_THINKING, {
                "status": "queued",
                "message": MSG_COMPACTING,
                "user_id": user_id,
                "channel_id": channel_id,
                "channel_type": channel_type,
            })
            try:
                await self.memory._compact(user_id, channel_id)
            except Exception as compact_err:
                log.error("Auto-compaction failed", error=str(compact_err))

        messages = await self.memory.get_messages(user_id, channel_id)

        # Get tools in OpenAI format — filtered by user intent to save tokens
        tools = None
        if self.tool_registry:
            tools = self.tool_registry.get_tools_by_intent(content)
            # During onboarding, always include save_user_profile so the LLM can call it
            if not getattr(self.config, "onboarding_completed", False):
                sp_def = self.tool_registry.tools.get("save_user_profile")
                if sp_def:
                    if tools is None:
                        tools = []
                    if not any(t.get("function", {}).get("name") == "save_user_profile" for t in tools):
                        tools.append(sp_def.to_slim_schema())

        # Cap tool count for providers with limited context
        profile = self.llm_router.get_provider_profile()
        if tools and profile.max_tools_per_call is not None:
            if profile.max_tools_per_call == 0:
                # Provider does not support tools at all
                tools = None
                log.info("Tools disabled for provider", provider=profile.name)
            elif len(tools) > profile.max_tools_per_call:
                log.info(
                    "Capping tool count for provider",
                    provider=profile.name,
                    original=len(tools),
                    cap=profile.max_tools_per_call,
                )
                tools = tools[: profile.max_tools_per_call]

        # Fast-path: if the LocalRouter is confident, skip the LLM entirely
        if not self.local_router.observation_mode:
            try:
                _router_result = await asyncio.wait_for(
                    asyncio.shield(_router_task), timeout=0.15
                )
                if _router_result and _router_result.is_fast_path_eligible:
                    fast_response = await self._execute_fast_path(
                        _router_result.intent, content, user_id, channel_id, channel_type
                    )
                    if fast_response is not None:
                        return fast_response
            except asyncio.TimeoutError:
                pass  # Router still classifying — continue to LLM
            except Exception as e:
                log.warning("Fast-path error, falling back to LLM", error=str(e))

        # Agentic loop: LLM may call tools multiple times
        iterations = 0
        max_iterations = self.config.max_tool_iterations
        generated_attachments: list[str] = []  # Track files generated by send_file_to_chat
        _last_tool_signature: str | None = None  # For repeated-call loop detection
        _repeated_call_count: int = 0
        _empty_response_retried: bool = False  # Guard: only inject the "write now" turn once
        _task_key_for_cancel = f"{channel_type}:{channel_id}"
        _cancel_event = self._cancel_flags.setdefault(_task_key_for_cancel, asyncio.Event())

        # ── Trace: record this request for debugging ──────────────────────────
        import time as _time
        import uuid as _uuid
        _trace: dict = {
            "id": _uuid.uuid4().hex[:8],
            "started_at": _time.strftime("%Y-%m-%dT%H:%M:%S"),
            "user_message": content[:200],
            "channel_id": channel_id,
            "user_id": user_id,
            "iterations": [],
            "total_elapsed_ms": 0,
            "outcome": "running",
        }
        _trace_t0 = _time.monotonic()
        # ─────────────────────────────────────────────────────────────────────

        while iterations < max_iterations:
            # Check cancel flag at every iteration — catches cancels that came in
            # while a subprocess was running in run_in_executor (CancelledError alone
            # doesn't interrupt executor threads).
            if _cancel_event.is_set():
                _cancel_event.clear()
                return "⏹ Cancelado."

            iterations += 1
            is_tool_loop = iterations > 1

            await self.event_bus.emit(
                EVENT_THINKING,
                {
                    "status": "processing",
                    "message": MSG_STEP.format(iterations=iterations, max_iterations=max_iterations),
                    "iteration": iterations,
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                },
            )

            # Build a copy with optional tool-enforcement injection
            prepared_messages = self._prepare_messages_for_llm(messages, tools, is_tool_loop)

            # Force tool usage on the first iteration for weak providers
            tc_override = None
            if (
                tools
                and not is_tool_loop
                and profile.needs_tool_enforcement
            ):
                tc_override = "required"

            # Trace: snapshot context before calling LLM
            _ctx_chars = sum(
                len(str(m.get("content", ""))) for m in prepared_messages
            )
            _iter_trace: dict = {
                "iteration": iterations,
                "message_count": len(prepared_messages),
                "context_chars": _ctx_chars,
                "llm_elapsed_ms": None,
                "tool_calls": [],
                "error": None,
            }
            _llm_t0 = _time.monotonic()

            try:
                _ctx_token = current_channel_id.set(channel_id)
                try:
                    response = await self.llm_router.chat(
                        messages=prepared_messages,
                        tools=tools,
                        tool_choice=tc_override,
                    )
                finally:
                    current_channel_id.reset(_ctx_token)
                _iter_trace["llm_elapsed_ms"] = int((_time.monotonic() - _llm_t0) * 1000)
            except Exception as e:
                _iter_trace["llm_elapsed_ms"] = int((_time.monotonic() - _llm_t0) * 1000)
                _iter_trace["error"] = f"{type(e).__name__}: {e}"
                _trace["iterations"].append(_iter_trace)
                _trace["outcome"] = "timeout" if "timeout" in str(e).lower() or not str(e) else "error"
                _trace["total_elapsed_ms"] = int((_time.monotonic() - _trace_t0) * 1000)
                self._save_trace(_trace)
                error_str = str(e) or repr(e) or type(e).__name__
                if "500" in error_str:
                    error_msg = f"❌ LLM server error (500): {error_str}\n\nThis is a temporary problem with the service provider. Please try again."
                elif "timeout" in error_str.lower() or not str(e):
                    error_msg = f"❌ Request timed out ({type(e).__name__}): The AI server did not respond in time. Try again or switch model."
                else:
                    error_msg = f"❌ LLM error ({type(e).__name__}): {error_str}"

                log.error("LLM error", error=error_str, exc_type=type(e).__name__)

                await self.event_bus.emit(
                    EVENT_THINKING,
                    {
                        "status": "error",
                        "message": "❌ Error connecting to AI service",
                        "user_id": user_id,
                        "channel_id": channel_id,
                        "channel_type": channel_type,
                    },
                )

                # Send error as a message so channels (Telegram, etc.) can display it.
                # is_error=True tells the events WS to always show this, even for the
                # web channel (normally non-partial web messages are skipped there).
                await self.event_bus.emit(
                    EVENT_MESSAGE_SENT,
                    {
                        "content": error_msg,
                        "user_id": user_id,
                        "channel_id": channel_id,
                        "channel_type": channel_type,
                        "tokens": 0,
                        "is_error": True,
                    },
                )

                return error_msg

            # If no tool calls, we have the final answer
            if not response["tool_calls"]:
                assistant_content = response["content"]

                # Empty content — Gemini and some models return "" after tool calls
                # because they consider the tool call itself as their "response".
                # Strategy: inject one explicit "write your response NOW" turn and retry.
                # Only do this once to avoid infinite injection loops.
                if not assistant_content or not assistant_content.strip():
                    if not _empty_response_retried:
                        _empty_response_retried = True
                        _swarm_hint = (
                            "\nYou MUST end your response with:\n"
                            "  TASK_STATUS: COMPLETED\n"
                            "  or TASK_STATUS: FAILED: <reason>"
                            if channel_type == "swarm" else ""
                        )
                        # Use "system" role so the model does NOT treat this as
                        # a user request — prevents hallucinating fake user messages.
                        messages = list(messages) + [{
                            "role": "system",
                            "content": (
                                "[INSTRUCTION]: Your last response was empty. "
                                "Write your final summary now based on what you did. "
                                "Do NOT call any more tools."
                                + _swarm_hint
                            ),
                        }]
                        log.warning("LLM returned empty content — injecting response-forcing system turn")
                        continue
                    # Already retried — give up and go to summary call
                    log.warning("LLM returned empty content twice, going to summary")
                    break

                await self.memory.add_message(user_id, channel_id, "assistant", assistant_content)

                # Prepare message data with attachments if any were generated
                message_data = {
                    "content": assistant_content,
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                    "tokens": response["usage"]["total_tokens"],
                }

                # Add attachments if send_file_to_chat was used
                if generated_attachments:
                    message_data["attachments"] = generated_attachments
                    log.info("Sending message with attachments", count=len(generated_attachments))

                await self.event_bus.emit(EVENT_MESSAGE_SENT, message_data)

                _iter_trace["llm_elapsed_ms"] = _iter_trace.get("llm_elapsed_ms")
                _trace["iterations"].append(_iter_trace)
                _trace["outcome"] = "success"
                _trace["total_elapsed_ms"] = int((_time.monotonic() - _trace_t0) * 1000)
                self._save_trace(_trace)

                # Prefix ATTACHMENT: lines so server.py extracts them as structured attachments
                if generated_attachments:
                    prefix = "\n".join(f"ATTACHMENT:{att}" for att in generated_attachments)
                    _wf_result = await self._run_workflow_hook(
                        user_id, channel_id, content, _tool_sequence_for_turn,
                        f"{prefix}\n{assistant_content}"
                    )
                    return _wf_result

                _wf_result = await self._run_workflow_hook(
                    user_id, channel_id, content, _tool_sequence_for_turn, assistant_content
                )
                return _wf_result

            # Process tool calls
            # First, add the assistant message with tool_calls to memory.
            # reasoning_content must be preserved for models like Kimi K2.5 that
            # use thinking mode — they reject histories missing this field.
            # Clean tool call IDs before storing — strips Gemini __thought__ blobs
            # that encode extended-thinking tokens and waste thousands of tokens per turn.
            clean_tool_calls = [
                {**tc, "id": _clean_tool_call_id(tc["id"])}
                for tc in response["tool_calls"]
            ]
            await self.memory.add_message(
                user_id,
                channel_id,
                "assistant",
                response["content"] or "",
                tool_calls=clean_tool_calls,
                reasoning_content=response.get("reasoning_content"),  # "" is valid, None means skip
            )
            messages = await self.memory.get_messages(user_id, channel_id)

            # If the LLM wrote something before calling tools, emit it immediately
            # so the frontend shows it in real-time (not just after all tools finish).
            if response["content"] and response["content"].strip():
                await self.event_bus.emit(
                    EVENT_MESSAGE_SENT,
                    {
                        "content": response["content"],
                        "user_id": user_id,
                        "channel_id": channel_id,
                        "channel_type": channel_type,
                        "tokens": 0,
                        "partial": True,  # signals: more tool calls may follow
                    },
                )

            # Passive learning: on the first iteration, infer intent from tool calls
            # and teach the LocalRouter so it can fast-path next time.
            if iterations == 1 and response["tool_calls"]:
                asyncio.create_task(self._maybe_learn_from_tools(
                    content, response["tool_calls"], _router_task
                ))

            # Loop detection: if the model calls the exact same tool+args twice in a
            # row it's stuck. Break early to avoid burning tokens indefinitely.
            _call_sig = "|".join(
                f"{tc['function']['name']}:{tc['function']['arguments']}"
                for tc in response["tool_calls"]
            )
            if _call_sig == _last_tool_signature:
                _repeated_call_count += 1
                if _repeated_call_count >= 2:
                    log.warning(
                        "Loop detected — same tool call repeated, breaking",
                        signature=_call_sig[:120],
                        iterations=iterations,
                    )
                    _trace["outcome"] = "loop_detected"
                    final_response = (
                        "I seem to be stuck in a loop calling the same tool repeatedly. "
                        "Please try rephrasing your request or check if the required tool is available."
                    )
                    await self.event_bus.emit(
                        EVENT_MESSAGE_SENT,
                        {"content": final_response, "user_id": user_id,
                         "channel_id": channel_id, "channel_type": channel_type, "tokens": 0},
                    )
                    await self.memory.add_message(user_id, channel_id, "assistant", final_response)
                    break
            else:
                _last_tool_signature = _call_sig
                _repeated_call_count = 0

            # Execute each tool call
            for tool_call in response["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_args_str = tool_call["function"]["arguments"]
                tool_call_id = _clean_tool_call_id(tool_call["id"])

                log.info("Tool call", tool=tool_name, args=tool_args_str[:200])
                _tool_trace: dict = {
                    "tool": tool_name,
                    "args_chars": len(tool_args_str),
                    "result_chars": 0,
                    "truncated": False,
                    "elapsed_ms": 0,
                    "error": None,
                }
                _tool_t0 = _time.monotonic()

                await self.event_bus.emit(
                    EVENT_THINKING,
                    {
                        "status": "tool_execution",
                        "message": MSG_TOOL_EXECUTING.format(tool_name=tool_name),
                        "tool": tool_name,
                        "user_id": user_id,
                        "channel_id": channel_id,
                        "channel_type": channel_type,
                    },
                )

                await self.event_bus.emit(
                    EVENT_TOOL_CALLED,
                    {
                        "tool": tool_name,
                        "arguments": tool_args_str,
                        "user_id": user_id,
                        "channel_id": channel_id,
                        "channel_type": channel_type,
                    },
                )

                try:
                    # Parse arguments
                    tool_args = json.loads(tool_args_str) if tool_args_str else {}

                    # Record tool call for workflow tracking
                    _tool_sequence_for_turn.append({
                        "tool": tool_name,
                        "arguments": tool_args if isinstance(tool_args, dict) else {},
                    })

                    # Execute tool
                    if self.tool_registry and tool_name in self.tool_registry.tools:
                        result = await self.tool_registry.execute(
                            tool_name, tool_args, user_id, channel_id, channel_type, _brain=self
                        )

                        # Any tool can return ATTACHMENT:filename on the first line
                        if result.startswith("ATTACHMENT:"):
                            first_line = result.split("\n")[0]
                            filename = first_line.replace("ATTACHMENT:", "").strip()
                            if filename:
                                generated_attachments.append(filename)
                                log.info("File attachment detected", filename=filename, tool=tool_name)
                    else:
                        result = f"Error: Tool '{tool_name}' not found"

                except asyncio.CancelledError:
                    log.info("Tool execution cancelled by new message", tool=tool_name)
                    _tool_trace["error"] = "CancelledError"
                    _iter_trace["tool_calls"].append(_tool_trace)
                    _trace["iterations"].append(_iter_trace)
                    _trace["outcome"] = "cancelled"
                    _trace["total_elapsed_ms"] = int((_time.monotonic() - _trace_t0) * 1000)
                    self._save_trace(_trace)
                    return MSG_CANCELLED_FOLLOWUP
                except json.JSONDecodeError:
                    result = f"Error: Invalid arguments for tool '{tool_name}'"
                    _tool_trace["error"] = "JSONDecodeError"
                except Exception as e:
                    result = f"Error executing tool '{tool_name}': {str(e)}"
                    _tool_trace["error"] = str(e)
                    log.error("Tool execution error", tool=tool_name, error=str(e))

                await self.event_bus.emit(
                    EVENT_TOOL_RESULT,
                    {
                        "tool": tool_name,
                        "result": result[:5000],  # Display cap — LLM gets separately compressed copy
                        "user_id": user_id,
                        "channel_id": channel_id,
                        "channel_type": channel_type,
                    },
                )

                # Complete tool trace entry
                _tool_trace["elapsed_ms"] = int((_time.monotonic() - _tool_t0) * 1000)
                _tool_trace["result_chars"] = len(str(result))
                _tool_trace["truncated"] = len(str(result)) > 6000
                _iter_trace["tool_calls"].append(_tool_trace)

                # Compress tool result before adding to LLM context
                MAX_TOOL_RESULT_CHARS = 6000
                result_for_memory, _orig_len, _comp_len = compress_output(
                    _strip_ansi(str(result)), tool_name, tool_args if isinstance(tool_args, dict) else {}
                )
                if _orig_len != _comp_len:
                    log.debug(
                        "Tool output compressed",
                        tool=tool_name,
                        summary=compression_summary(_orig_len, _comp_len),
                    )
                # Hard cap — if still too large after compression, truncate head+tail
                if len(result_for_memory) > MAX_TOOL_RESULT_CHARS:
                    head = result_for_memory[:3500]
                    tail = result_for_memory[-1000:]
                    omitted = len(result_for_memory) - 4500
                    result_for_memory = head + f"\n... [{omitted} chars omitted] ...\n" + tail

                await self.memory.add_message(
                    user_id,
                    channel_id,
                    "tool",
                    result_for_memory,
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )
                messages = await self.memory.get_messages(user_id, channel_id)

            _trace["iterations"].append(_iter_trace)

        # If we hit max iterations OR the model returned empty content twice, make one final
        # LLM call with tools=None to force a plain-text summary of what was done.
        try:
            log.warning("Making final summary LLM call (no tools)")

            # Build a context-aware forcing prompt
            _swarm_status_reminder = (
                "\n\nCRITICAL: You MUST end your response with exactly one of:\n"
                "  TASK_STATUS: COMPLETED\n"
                "  TASK_STATUS: FAILED: <brief reason>"
                if channel_type == "swarm" else ""
            )
            summary_messages = list(messages) + [{
                "role": "user",
                "content": (
                    "Write your final response now as plain text. "
                    "Summarize what you accomplished, what worked, and what the outcome is. "
                    "Do NOT call any tools."
                    + _swarm_status_reminder
                ),
            }]
            _ctx_token2 = current_channel_id.set(channel_id)
            try:
                final_response = await self.llm_router.chat(
                    messages=summary_messages,
                    tools=None,  # No tools — force text output
                    temperature=0.2,  # Low temp → deterministic, less likely to return empty
                )
            finally:
                current_channel_id.reset(_ctx_token2)

            final_content = (final_response.get("content") or "").strip()

            # Model still returned empty — synthesize from tool call history
            if not final_content:
                tool_names: list[str] = []
                last_results: list[str] = []
                for m in messages:
                    if m.get("role") == "assistant":
                        for tc in (m.get("tool_calls") or []):
                            fn = tc.get("function", {})
                            tool_names.append(fn.get("name", "tool"))
                    elif m.get("role") == "tool" and m.get("content"):
                        last_results.append(str(m["content"])[:400])

                tools_used = ", ".join(dict.fromkeys(tool_names)) or "none"
                last_result_text = last_results[-1] if last_results else "(no output)"
                status_line = "\n\nTASK_STATUS: COMPLETED" if channel_type == "swarm" else ""
                final_content = (
                    f"Task execution finished. Tools used: {tools_used}.\n\n"
                    f"Last output:\n{last_result_text}"
                    f"{status_line}"
                )
                log.warning("Summary LLM returned empty — using synthesized response")
            if final_content and final_content.strip():
                await self.memory.add_message(user_id, channel_id, "assistant", final_content)

                # Prepare message data with attachments if any were generated
                message_data = {
                    "content": final_content,
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                    "tokens": final_response["usage"]["total_tokens"],
                }

                # Add attachments if send_file_to_chat was used
                if generated_attachments:
                    message_data["attachments"] = generated_attachments
                    log.info(
                        "Sending final message with attachments", count=len(generated_attachments)
                    )

                await self.event_bus.emit(EVENT_MESSAGE_SENT, message_data)

                # Prefix ATTACHMENT: lines so server.py extracts them as structured attachments
                if generated_attachments:
                    prefix = "\n".join(f"ATTACHMENT:{att}" for att in generated_attachments)
                    return f"{prefix}\n{final_content}"

                _trace["outcome"] = "success"
                _trace["total_elapsed_ms"] = int((_time.monotonic() - _trace_t0) * 1000)
                self._save_trace(_trace)
                _wf_result = await self._run_workflow_hook(
                    user_id, channel_id, content, _tool_sequence_for_turn, final_content
                )
                return _wf_result
            else:
                _trace["outcome"] = "empty_response"
                _trace["total_elapsed_ms"] = int((_time.monotonic() - _trace_t0) * 1000)
                self._save_trace(_trace)
                return MSG_EMPTY_RESPONSE
        except Exception as e:
            log.error("Error in final LLM call after max iterations", error=str(e))
            _trace["outcome"] = "max_iterations_error"
            _trace["total_elapsed_ms"] = int((_time.monotonic() - _trace_t0) * 1000)
            self._save_trace(_trace)
            return MSG_MAX_ITERATIONS
