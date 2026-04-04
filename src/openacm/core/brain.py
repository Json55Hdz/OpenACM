"""
Brain — the central AI engine.

Receives messages, builds context, calls the LLM, processes tool calls,
and returns responses. Handles the full agentic loop with safety limits.
"""

import asyncio
import json
from typing import Any

import structlog

from openacm.core.config import AssistantConfig
from openacm.core.local_router import LocalRouter
from openacm.core.events import (
    EVENT_MESSAGE_RECEIVED,
    EVENT_MESSAGE_SENT,
    EVENT_THINKING,
    EVENT_TOOL_CALLED,
    EVENT_TOOL_RESULT,
    EVENT_ROUTER_LEARNED,
    EVENT_SKILL_ACTIVE,
    EventBus,
)
from openacm.core.llm_router import LLMRouter
from openacm.core.memory import MemoryManager
from openacm.core.acm_context import get_openacm_context, get_short_context

log = structlog.get_logger()


class Brain:
    """
    Central AI engine that processes messages through the LLM
    with tool calling support.
    """

    # Enforcement message injected for providers that need it
    _TOOL_ENFORCEMENT_MSG = (
        "You are OpenACM. You MUST respond by calling one of your tools. "
        "Do NOT describe what you would do — actually DO it using a tool call. "
        "Available tools: run_command, run_python, web_search, browser_agent, "
        "file_ops, send_file_to_chat, google_services, screenshot, system_info. "
        "If you need a Python library, install it first with run_command (pip install X) then use run_python. "
        "You CAN install packages. You CAN access the internet. You CAN create any file. "
        "NEVER say 'as a language model' or 'I cannot'. Execute the user's request NOW."
    )

    def __init__(
        self,
        config: AssistantConfig,
        llm_router: LLMRouter,
        memory: MemoryManager,
        event_bus: EventBus,
        tool_registry: Any = None,
        skill_manager: Any = None,
    ):
        self.config = config
        self.llm_router = llm_router
        self.memory = memory
        self.event_bus = event_bus
        self.tool_registry = tool_registry
        self.skill_manager = skill_manager
        # Give memory access to LLM router for conversation compaction
        self.memory._llm_router = llm_router
        self.terminal_history: list[dict] = []
        # Tracks the active processing task per channel — used for interruption
        self._channel_tasks: dict[str, asyncio.Task] = {}
        # Queued message per channel while a task is running (one slot — latest wins)
        self._channel_queue: dict[str, tuple] = {}
        self.workflow_tracker = None  # injected by app.py
        self._pending_suggestions: dict[str, object] = {}  # key: "channel_id:user_id"
        # Last N agentic loop traces for debugging
        self._traces: list[dict] = []
        self._MAX_TRACES = 20
        _lr = getattr(config, "local_router", None)
        self.local_router = LocalRouter(
            confidence_threshold=_lr.confidence_threshold if _lr else 0.88,
            observation_mode=not _lr.enabled if _lr else False,
        )

    async def _execute_fast_path(
        self,
        intent: str,
        message: str,
        user_id: str,
        channel_id: str,
        channel_type: str,
    ) -> str | None:
        """
        Execute a simple intent directly without calling the LLM.
        Dispatches to the handler registered in fast_path.py for this intent.
        Returns the response string, or None to fall through to the LLM.
        """
        from openacm.core.fast_path import dispatch

        response = await dispatch(intent, self, message, user_id, channel_id, channel_type)
        if response is None:
            return None

        await self.memory.add_message(user_id, channel_id, "assistant", response)
        await self.event_bus.emit(EVENT_MESSAGE_SENT, {
            "content": response,
            "user_id": user_id,
            "channel_id": channel_id,
            "channel_type": channel_type,
            "tokens": 0,
        })
        await self.event_bus.emit(EVENT_THINKING, {
            "status": "done",
            "user_id": user_id,
            "channel_id": channel_id,
            "channel_type": channel_type,
        })
        log.info("Fast-path executed", intent=intent)
        return response

    async def _maybe_learn_from_tools(
        self,
        original_message: str,
        tool_calls: list[dict],
        router_task: asyncio.Task,
    ) -> None:
        """
        Passive learning: infer the user's intent from what tools the LLM called
        and teach the LocalRouter — so next time it can skip the LLM entirely.

        Only learns when:
        - The LLM called exactly one tool (unambiguous intent signal)
        - The router was uncertain (confidence below threshold)
        - We can map that tool to a known intent
        """
        from openacm.core.local_router import TOOL_TO_INTENT, RUN_COMMAND_HINTS

        if len(tool_calls) != 1:
            return  # ambiguous — multiple tools called

        try:
            router_result = await asyncio.wait_for(asyncio.shield(router_task), timeout=2.0)
        except Exception:
            router_result = None

        # Only learn if the router was uncertain (below threshold)
        if router_result and router_result.is_fast_path_eligible:
            return  # already confident, no need to learn

        tool_name = tool_calls[0]["function"]["name"]
        tool_args = tool_calls[0]["function"]["arguments"]

        # Direct tool → intent mapping
        inferred_intent = TOOL_TO_INTENT.get(tool_name)

        # run_command: check arguments for app/media hints
        if not inferred_intent and tool_name == "run_command":
            args_lower = tool_args.lower()
            for hint, intent in RUN_COMMAND_HINTS.items():
                if hint in args_lower:
                    inferred_intent = intent
                    break

        if not inferred_intent:
            return  # can't infer intent from this tool call

        # If the router already guessed right, still learn to boost confidence
        if router_result and router_result.intent != inferred_intent:
            return  # router was wrong — don't reinforce a bad pattern

        learned = await self.local_router.learn(original_message, inferred_intent)
        if learned:
            await self.event_bus.emit(EVENT_ROUTER_LEARNED, {
                "intent": inferred_intent,
                "message": original_message,
            })

        # Also learn the concrete action so fast_path can replay it later
        await self._maybe_learn_action(original_message, tool_name, tool_args, inferred_intent)

    async def _maybe_learn_action(
        self,
        phrase: str,
        tool_name: str,
        tool_args_str: str,
        intent: str,
    ) -> None:
        """
        Store a phrase → concrete tool call for direct fast-path replay.

        Safety rules (by design):
        - open_url: always learnable — opening a URL is safe and deterministic
        - run_command: only when intent == OPEN_APP — avoids learning arbitrary shell commands
        - All other tools: ignored
        """
        try:
            args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
        except Exception:
            return

        if tool_name == "open_url":
            url = args.get("url", "")
            if not url:
                return
            # Extract a readable label from the URL for the response message
            from urllib.parse import urlparse
            label = urlparse(url).netloc or url
            await self.local_router.learn_action(
                phrase, tool_name, args, intent, f"Abriendo {label}..."
            )

        elif tool_name == "run_command" and intent == "OPEN_APP":
            command = args.get("command", "")
            if not command:
                return
            # Use the last token of the command as the app name (e.g. "start blender" → "Blender")
            app_name = command.strip().split()[-1].title()
            await self.local_router.learn_action(
                phrase, tool_name, args, intent, f"Abriendo {app_name}..."
            )

    # ── Multimodal helpers ────────────────────────────────────────────────

    def _save_trace(self, trace: dict) -> None:
        """Store a completed trace, keeping only the last _MAX_TRACES entries."""
        self._traces.append(trace)
        if len(self._traces) > self._MAX_TRACES:
            self._traces = self._traces[-self._MAX_TRACES:]
        # Also emit a structured log so it shows up in debug mode
        log.info(
            "Agentic loop trace",
            trace_id=trace["id"],
            outcome=trace["outcome"],
            total_elapsed_ms=trace["total_elapsed_ms"],
            iterations=len(trace["iterations"]),
            context_chars_last=[it["context_chars"] for it in trace["iterations"]],
            tool_calls_summary=[
                f"{tc['tool']}({tc['result_chars']}ch{'!trunc' if tc['truncated'] else ''})"
                for it in trace["iterations"]
                for tc in it["tool_calls"]
            ],
        )

    def _extract_pdf_text(self, raw_bytes: bytes) -> str:
        """Extract text from a PDF using pypdf."""
        import io
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(p for p in pages if p.strip())
            return text[:12000] or "[PDF has no extractable text]"
        except ImportError:
            return "[pypdf not installed — install with: pip install pypdf]"
        except Exception as e:
            log.warning("PDF extraction failed", error=str(e))
            return f"[PDF extraction error: {e}]"

    async def _transcribe_audio(self, raw_bytes: bytes, ext: str) -> str | None:
        """
        Transcribe audio bytes to text.
        Priority: OpenAI Whisper API → faster-whisper local → None.
        """
        import os

        # ── 1. OpenAI Whisper API ──────────────────────────────────────────
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            try:
                import httpx
                mime_map = {
                    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
                    ".m4a": "audio/mp4", ".webm": "audio/webm", ".flac": "audio/flac",
                }
                mime = mime_map.get(ext, "audio/mpeg")
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        files={"file": (f"audio{ext}", raw_bytes, mime)},
                        data={"model": "whisper-1"},
                        timeout=60.0,
                    )
                    if resp.status_code == 200:
                        return resp.json().get("text", "")
                    log.warning("Whisper API error", status=resp.status_code)
            except Exception as e:
                log.warning("OpenAI Whisper transcription failed", error=str(e))

        # ── 2. Local faster-whisper ────────────────────────────────────────
        try:
            import tempfile, os as _os
            from faster_whisper import WhisperModel

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(raw_bytes)
                tmp_path = f.name
            try:
                loop = asyncio.get_event_loop()

                def _run():
                    model = WhisperModel("base", device="cpu", compute_type="int8")
                    segments, _ = model.transcribe(tmp_path, beam_size=5)
                    return " ".join(seg.text for seg in segments).strip()

                return await loop.run_in_executor(None, _run)
            finally:
                _os.unlink(tmp_path)
        except ImportError:
            pass
        except Exception as e:
            log.warning("Local Whisper transcription failed", error=str(e))

        return None

    # Messages older than this index (from the end) get their tool results
    # and reasoning_content aggressively truncated to save tokens.
    _RECENT_MSG_WINDOW = 8  # keep full detail for the last N messages
    _OLD_TOOL_RESULT_MAX = 300  # chars to keep for old tool results
    _OLD_REASONING_MAX = 0  # strip reasoning_content from old messages entirely

    def _prepare_messages_for_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        is_tool_loop: bool,
    ) -> list[dict[str, Any]]:
        """Return a copy of *messages* optimized for the LLM call.

        Optimizations applied:
        1. Tool enforcement injection (for weak providers)
        2. Truncate old tool results — after the LLM already processed them,
           keeping the full 6K chars is wasteful. Old results are trimmed to ~300 chars.
        3. Strip reasoning_content from old messages — these can be thousands of
           tokens from thinking models (Kimi, DeepSeek) and are never useful in history.

        The original list is never mutated (memory stays clean).
        """
        profile = self.llm_router.get_provider_profile()
        total = len(messages)
        cutoff = max(0, total - self._RECENT_MSG_WINDOW)

        prepared = []
        for i, msg in enumerate(messages):
            is_old = i > 0 and i < cutoff  # index 0 = system, always keep

            # Check if this message needs any modification
            needs_copy = False

            if is_old:
                # Truncate old tool results
                if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                    content = msg["content"]
                    if len(content) > self._OLD_TOOL_RESULT_MAX:
                        needs_copy = True

                # Strip reasoning_content from old messages
                if msg.get("reasoning_content"):
                    needs_copy = True

            if needs_copy:
                msg = msg.copy()
                if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                    content = msg["content"]
                    if len(content) > self._OLD_TOOL_RESULT_MAX:
                        msg["content"] = (
                            content[:self._OLD_TOOL_RESULT_MAX]
                            + f" [...{len(content)} chars truncated]"
                        )
                if msg.get("reasoning_content") and self._OLD_REASONING_MAX == 0:
                    msg.pop("reasoning_content", None)

            prepared.append(msg)

        # Tool enforcement injection for weak providers
        if tools and profile.needs_tool_enforcement and not is_tool_loop:
            if prepared and prepared[0].get("role") == "system":
                sys_msg = prepared[0].copy()
                sys_msg["content"] = f"{sys_msg['content']}\n\n{self._TOOL_ENFORCEMENT_MSG}"
                prepared[0] = sys_msg

        return prepared

    _CANCEL_KEYWORDS = {"cancel", "cancelar", "stop", "detener", "para", "parar", "abort"}

    async def process_message(
        self,
        content: str,
        user_id: str,
        channel_id: str,
        channel_type: str = "console",
        attachments: list[str] | None = None,
    ) -> str:
        """
        Public entry point — wraps _run() in a dedicated cancellable task.

        Behaviour when a task is already running for this channel:
        - Cancel keywords ("cancel", "stop", "cancelar", …) → cancel immediately.
        - Any other message → queue it (latest wins) and notify the user.
          The queued message is processed automatically once the current task finishes.
        """
        _task_key = f"{channel_type}:{channel_id}"
        _prev = self._channel_tasks.get(_task_key)

        if _prev and not _prev.done():
            is_cancel = content.strip().lower() in self._CANCEL_KEYWORDS
            if is_cancel:
                _prev.cancel()
                self._channel_tasks.pop(_task_key, None)
                self._channel_queue.pop(_task_key, None)
                await asyncio.sleep(0)
                await self.event_bus.emit(EVENT_THINKING, {
                    "status": "done",
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                })
                return "⏹ Cancelado."
            else:
                # Queue the message — latest message wins
                self._channel_queue[_task_key] = (content, user_id, channel_id, channel_type, attachments)
                await self.event_bus.emit(EVENT_THINKING, {
                    "status": "queued",
                    "message": "⏳ Procesando tarea anterior... tu mensaje se enviará al terminar.",
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                })
                return "⏳ Procesando algo, espera... (escribe «cancelar» para detener)"

        # No active task — run immediately
        self._channel_queue.pop(_task_key, None)
        task = asyncio.create_task(
            self._run_then_drain(content, user_id, channel_id, channel_type, attachments, _task_key)
        )
        self._channel_tasks[_task_key] = task

        try:
            return await task
        except asyncio.CancelledError:
            return "⏹ Cancelado."

    async def _run_then_drain(
        self,
        content: str,
        user_id: str,
        channel_id: str,
        channel_type: str,
        attachments: list[str] | None,
        task_key: str,
    ) -> str:
        """Run _run(), then process any queued message afterwards."""
        try:
            result = await self._run(content, user_id, channel_id, channel_type, attachments)
        finally:
            self._channel_tasks.pop(task_key, None)

        # Process queued message if any
        queued = self._channel_queue.pop(task_key, None)
        if queued:
            q_content, q_user, q_channel, q_type, q_attach = queued
            await self.event_bus.emit(EVENT_THINKING, {
                "status": "start",
                "message": "▶ Procesando tu mensaje...",
                "user_id": q_user,
                "channel_id": q_channel,
                "channel_type": q_type,
            })
            next_task = asyncio.create_task(
                self._run_then_drain(q_content, q_user, q_channel, q_type, q_attach, task_key)
            )
            self._channel_tasks[task_key] = next_task
            # Don't await — let it run in background

        return result

    async def _run(
        self,
        content: str,
        user_id: str,
        channel_id: str,
        channel_type: str = "console",
        attachments: list[str] | None = None,
    ) -> str:
        """Core message processing — runs inside a cancellable task."""
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

        # Emitir evento thinking para mostrar que estamos procesando
        await self.event_bus.emit(
            EVENT_THINKING,
            {
                "status": "start",
                "message": "🤔 Pensando...",
                "user_id": user_id,
                "channel_id": channel_id,
                "channel_type": channel_type,
            },
        )

        # LocalRouter: classify intent for observation + passive learning
        _router_task = asyncio.create_task(self.local_router.observe(content))

        # Accumulate tool calls for this agentic turn (for workflow tracking)
        _tool_sequence_for_turn: list[dict] = []

        # Build system prompt with OpenACM context FIRST, then skills
        system_prompt = self.config.system_prompt

        # 1. Agregar contexto de OpenACM — full on first message, short thereafter
        existing_messages = await self.memory.get_messages(user_id, channel_id)
        is_new_conversation = len(existing_messages) == 0
        openacm_context = get_openacm_context() if is_new_conversation else get_short_context()
        system_prompt = f"{openacm_context}\n\n{system_prompt}"

        # 2. Agregar contexto de la terminal del usuario si hay historial reciente
        if self.terminal_history:
            recent = [
                e for e in self.terminal_history[-10:] if e.get("command")
            ]
            if recent:
                term_lines = []
                for e in recent:
                    output = e.get("output", "").strip()
                    if output:
                        term_lines.append(f"$ {e['command']}\n{output[:500]}")
                    else:
                        term_lines.append(f"$ {e['command']}")
                terminal_ctx = "\n".join(term_lines)
                system_prompt += (
                    f"\n\n## User's Recent Terminal Activity\n"
                    f"The user has an interactive terminal open. "
                    f"These are their recent commands and outputs:\n"
                    f"```\n{terminal_ctx}\n```\n"
                    f"Use this context to understand what the user is working on. "
                    f"You can reference these results in your responses."
                )

        # 3. Agregar skills relevantes si existen
        if self.skill_manager:
            skills_prompt = await self.skill_manager.get_active_skills_prompt(content)
            if skills_prompt:
                system_prompt = f"{system_prompt}\n\n{skills_prompt}"
                matched = self.skill_manager.last_matched_skill_names
                if matched:
                    await self.event_bus.emit(EVENT_SKILL_ACTIVE, {
                        "skills": matched,
                        "channel_id": channel_id,
                        "channel_type": channel_type,
                    })

        # 4. Inyectar tools MCP activas en el system prompt
        if self.tool_registry:
            mcp_tools = [
                t for t in self.tool_registry.tools.values() if t.category == "mcp"
            ]
            if mcp_tools:
                # Group by server name (prefix: mcp__{server}__)
                servers: dict[str, list[str]] = {}
                for t in mcp_tools:
                    parts = t.name.split("__", 2)
                    server = parts[1] if len(parts) >= 3 else "unknown"
                    servers.setdefault(server, []).append(
                        f"  - `{t.name}`: {t.description.split('] ', 1)[-1]}"
                    )
                lines = ["## MCP Connected Servers"]
                lines.append(
                    "You have access to external tools from MCP servers. "
                    "Call them directly by their full name when useful."
                )
                for srv, tool_lines in servers.items():
                    lines.append(f"\n### {srv}")
                    lines.extend(tool_lines)
                system_prompt = f"{system_prompt}\n\n" + "\n".join(lines)

        # Get or create conversation with system prompt
        messages = await self.memory.get_or_create(user_id, channel_id, system_prompt)

        # RAG: Query long-term memory for relevant context (score-filtered)
        try:
            from openacm.core.rag import _rag_engine
            from openacm.core.events import EVENT_MEMORY_RECALL

            if _rag_engine and _rag_engine.is_ready and content:
                await self.event_bus.emit(EVENT_MEMORY_RECALL, {
                    "status": "searching",
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                    "count": 0,
                })
                scored_results = await _rag_engine.query_with_scores(content, top_k=5)
                # Only keep relevant results (cosine distance < 1.0) and limit to 2
                memories = [doc for doc, dist in scored_results if dist < 1.0][:2]
                if memories:
                    await self.event_bus.emit(EVENT_MEMORY_RECALL, {
                        "status": "found",
                        "channel_id": channel_id,
                        "channel_type": channel_type,
                        "count": len(memories),
                    })
                    memory_block = "\n".join(f"- {m[:200]}" for m in memories)
                    memory_msg = {
                        "role": "system",
                        "content": (
                            f"[Long-term memory — relevant fragments retrieved]:\n"
                            f"{memory_block}\n"
                            f"[Use this information if relevant to the current conversation.]"
                        ),
                    }
                    if len(messages) > 1 and messages[0]["role"] == "system":
                        messages = [
                            m
                            for m in messages
                            if not (
                                m.get("role") == "system"
                                and "Long-term memory" in str(m.get("content", ""))
                            )
                        ]
                        messages.insert(1, memory_msg)
                else:
                    await self.event_bus.emit(EVENT_MEMORY_RECALL, {
                        "status": "empty",
                        "channel_id": channel_id,
                        "channel_type": channel_type,
                        "count": 0,
                    })
        except Exception:
            pass  # RAG is optional, never break the main flow

        # Build structured content if there are attachments
        final_content = content
        if attachments:
            import base64
            from pathlib import Path
            from openacm.security.crypto import decrypt_file, get_media_dir

            structured_content = []
            if content:
                structured_content.append({"type": "text", "text": content})

            for att_id in attachments:
                file_path = get_media_dir() / att_id
                if file_path.exists():
                    try:
                        raw_bytes = decrypt_file(file_path)
                        b64 = base64.b64encode(raw_bytes).decode("utf-8")

                        ext = file_path.suffix.lower()
                        mime = "application/octet-stream"
                        if ext in [".png"]:
                            mime = "image/png"
                        elif ext in [".jpg", ".jpeg"]:
                            mime = "image/jpeg"
                        elif ext in [".gif"]:
                            mime = "image/gif"
                        elif ext in [".webp"]:
                            mime = "image/webp"

                        if mime.startswith("image/"):
                            structured_content.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64}"},
                                "_file_id": att_id,  # preserved for DB serialization
                            })
                        elif ext == ".pdf":
                            text = self._extract_pdf_text(raw_bytes)
                            structured_content.append({
                                "type": "text",
                                "text": f"[PDF — {file_path.name}]:\n{text}",
                            })
                        elif ext in (".mp3", ".wav", ".ogg", ".m4a", ".webm", ".flac"):
                            transcript = await self._transcribe_audio(raw_bytes, ext)
                            if transcript:
                                structured_content.append({
                                    "type": "text",
                                    "text": f"[Audio transcript]:\n{transcript}",
                                })
                            else:
                                structured_content.append({
                                    "type": "text",
                                    "text": f"[Audio file attached: {file_path.name} — transcription unavailable. No Whisper API key or faster-whisper installed.]",
                                })
                        elif ext in (".txt", ".md", ".csv", ".log", ".json", ".yaml", ".yml", ".xml", ".html"):
                            try:
                                text = raw_bytes.decode("utf-8", errors="replace")
                                structured_content.append({
                                    "type": "text",
                                    "text": f"[File — {file_path.name}]:\n{text[:12000]}",
                                })
                            except Exception:
                                pass
                        else:
                            structured_content.append({
                                "type": "text",
                                "text": f"[File attached: {file_path.name} ({ext})]",
                            })
                    except Exception as e:
                        log.error("Failed to load attachment", error=str(e), file_id=att_id)

            if structured_content:
                final_content = structured_content

        # Add user message
        await self.memory.add_message(user_id, channel_id, "user", final_content)
        messages = await self.memory.get_messages(user_id, channel_id)

        # Get tools in OpenAI format — filtered by user intent to save tokens
        tools = None
        if self.tool_registry:
            tools = self.tool_registry.get_tools_by_intent(content)

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
            iterations += 1
            is_tool_loop = iterations > 1

            # Actualizar estado thinking
            await self.event_bus.emit(
                EVENT_THINKING,
                {
                    "status": "processing",
                    "message": f"🔄 Step {iterations}/{max_iterations}...",
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
                response = await self.llm_router.chat(
                    messages=prepared_messages,
                    tools=tools,
                    tool_choice=tc_override,
                )
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

                # Hide thinking indicator
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

                # Verificar que tenemos contenido real
                if not assistant_content or not assistant_content.strip():
                    # Empty content — model finished tool calls but returned no text.
                    # Break out and let the post-loop summary call handle it with tools=None
                    # (looping just injects duplicate "resume" messages and never helps).
                    log.warning("LLM returned empty content after tools, requesting summary")
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
            await self.memory.add_message(
                user_id,
                channel_id,
                "assistant",
                response["content"] or "",
                tool_calls=response["tool_calls"],
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
                tool_call_id = tool_call["id"]

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

                # Emitir thinking mientras ejecuta el tool
                await self.event_bus.emit(
                    EVENT_THINKING,
                    {
                        "status": "tool_execution",
                        "message": f"⚙️ Ejecutando {tool_name}...",
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
                    return "⏹ Cancelado — ¿en qué más puedo ayudarte?"
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
                        "result": result[:500],  # Truncate for event
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

                # Add tool result to memory (truncated to avoid token bloat)
                MAX_TOOL_RESULT_CHARS = 6000
                result_for_memory = str(result)
                if len(result_for_memory) > MAX_TOOL_RESULT_CHARS:
                    result_for_memory = (
                        result_for_memory[: MAX_TOOL_RESULT_CHARS - 100]
                        + f"\n... [truncated, full output was {len(str(result))} chars]"
                    )

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

        # If we hit max iterations OR the model returned empty content, make one final
        # LLM call with tools=None to force a plain-text summary of what was done.
        try:
            log.warning("Making final summary LLM call (no tools)")
            # Inject a one-time summary request so the model knows to write text now
            summary_messages = list(messages) + [{
                "role": "user",
                "content": "Por favor, resume los resultados obtenidos y responde al usuario.",
            }]
            final_response = await self.llm_router.chat(
                messages=summary_messages,
                tools=None,  # No tools — force text output
            )

            final_content = final_response["content"]
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
                return (
                    "⚠️ He ejecutado varias herramientas pero no obtuve una respuesta final clara. "
                    "Los resultados están disponibles en el historial. ¿Te gustaría que intentemos de otra forma?"
                )
        except Exception as e:
            log.error("Error in final LLM call after max iterations", error=str(e))
            _trace["outcome"] = "max_iterations_error"
            _trace["total_elapsed_ms"] = int((_time.monotonic() - _trace_t0) * 1000)
            self._save_trace(_trace)
            return (
                "⚠️ He ejecutado varias herramientas pero alcanzé el límite de pasos. "
                "Revisa el dashboard para ver los resultados completos, o intenta dividir tu solicitud en pasos más pequeños."
            )

    # ── Workflow tracking helpers ─────────────────────────────────────────────

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
            lines.append("📅 **He detectado nuevas rutinas en tu actividad:**")
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
            lines.append("Puedes verlas y ejecutarlas en la pestaña **Mis Rutinas**.")
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
                return "No pude generar la tool. Inténtalo manualmente con 'crea una tool que...'."

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
                return f"Basándome en tus flujos repetidos, generé esta tool:\n\n{result}"

            return "Tool registry no disponible. No se pudo crear la tool."

        except Exception as e:
            log.error("Workflow tool creation failed", error=str(e))
            return f"Error al generar la tool automáticamente: {str(e)[:200]}"
