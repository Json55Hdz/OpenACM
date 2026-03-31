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
        self.terminal_history: list[dict] = []
        # Tracks the active processing task per channel — used for interruption
        self._channel_tasks: dict[str, asyncio.Task] = {}
        # Queued message per channel while a task is running (one slot — latest wins)
        self._channel_queue: dict[str, tuple] = {}
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

    def _prepare_messages_for_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        is_tool_loop: bool,
    ) -> list[dict[str, Any]]:
        """Return a shallow copy of *messages* with optional enforcement injection.

        The enforcement hint is only added when:
        - tools are available,
        - the provider profile says it needs enforcement, AND
        - we are NOT already inside a tool-calling loop (iterations > 1).

        The enforcement is appended to the system prompt (messages[0]) instead
        of inserted as a separate message, because Gemini requires strict
        function_call → function_response adjacency and rejects any message
        in between.

        The original list is never mutated (memory stays clean).
        """
        profile = self.llm_router.get_provider_profile()

        if not tools or not profile.needs_tool_enforcement or is_tool_loop:
            return list(messages)  # shallow copy, no injection

        prepared = list(messages)

        # Append enforcement to the system prompt (messages[0]).
        # We copy the dict so the in-memory cache is not mutated.
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

            if _rag_engine and _rag_engine.is_ready and content:
                scored_results = await _rag_engine.query_with_scores(content, top_k=5)
                # Only keep relevant results (cosine distance < 1.0) and limit to 2
                memories = [doc for doc, dist in scored_results if dist < 1.0][:2]
                if memories:
                    memory_block = "\n".join(f"- {m[:200]}" for m in memories)
                    # Inject as a system-level hint (after the main system prompt)
                    # Check if we already have a memory injection and update it
                    memory_msg = {
                        "role": "system",
                        "content": (
                            f"[Memoria a largo plazo — fragmentos relevantes encontrados]:\n"
                            f"{memory_block}\n"
                            f"[Usa esta información si es relevante para la conversación actual.]"
                        ),
                    }
                    # Insert after the first system prompt but before user messages
                    if len(messages) > 1 and messages[0]["role"] == "system":
                        # Remove old memory injection if present
                        messages = [
                            m
                            for m in messages
                            if not (
                                m.get("role") == "system"
                                and "Memoria a largo plazo" in str(m.get("content", ""))
                            )
                        ]
                        messages.insert(1, memory_msg)
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

            try:
                response = await self.llm_router.chat(
                    messages=prepared_messages,
                    tools=tools,
                    tool_choice=tc_override,
                )
            except Exception as e:
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

                # Send error as a message so channels (Telegram, etc.) can display it
                await self.event_bus.emit(
                    EVENT_MESSAGE_SENT,
                    {
                        "content": error_msg,
                        "user_id": user_id,
                        "channel_id": channel_id,
                        "channel_type": channel_type,
                        "tokens": 0,
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

                # Prefix ATTACHMENT: lines so server.py extracts them as structured attachments
                if generated_attachments:
                    prefix = "\n".join(f"ATTACHMENT:{att}" for att in generated_attachments)
                    return f"{prefix}\n{assistant_content}"

                return assistant_content

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

            # Execute each tool call
            for tool_call in response["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_args_str = tool_call["function"]["arguments"]
                tool_call_id = tool_call["id"]

                log.info("Tool call", tool=tool_name, args=tool_args_str)

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
                    },
                )

                try:
                    # Parse arguments
                    tool_args = json.loads(tool_args_str) if tool_args_str else {}

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
                    return "⏹ Cancelado — ¿en qué más puedo ayudarte?"
                except json.JSONDecodeError:
                    result = f"Error: Invalid arguments for tool '{tool_name}'"
                except Exception as e:
                    result = f"Error executing tool '{tool_name}': {str(e)}"
                    log.error("Tool execution error", tool=tool_name, error=str(e))

                await self.event_bus.emit(
                    EVENT_TOOL_RESULT,
                    {
                        "tool": tool_name,
                        "result": result[:500],  # Truncate for event
                        "user_id": user_id,
                        "channel_id": channel_id,
                    },
                )

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

                return final_content
            else:
                return (
                    "⚠️ He ejecutado varias herramientas pero no obtuve una respuesta final clara. "
                    "Los resultados están disponibles en el historial. ¿Te gustaría que intentemos de otra forma?"
                )
        except Exception as e:
            log.error("Error in final LLM call after max iterations", error=str(e))
            return (
                "⚠️ He ejecutado varias herramientas pero alcanzé el límite de pasos. "
                "Revisa el dashboard para ver los resultados completos, o intenta dividir tu solicitud en pasos más pequeños."
            )
