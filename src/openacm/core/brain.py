"""
Brain — the central AI engine.

Receives messages, builds context, calls the LLM, processes tool calls,
and returns responses. Handles the full agentic loop with safety limits.
"""

import json
from typing import Any

import structlog

from openacm.core.config import AssistantConfig
from openacm.core.events import (
    EVENT_MESSAGE_RECEIVED,
    EVENT_MESSAGE_SENT,
    EVENT_THINKING,
    EVENT_TOOL_CALLED,
    EVENT_TOOL_RESULT,
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

    async def process_message(
        self,
        content: str,
        user_id: str,
        channel_id: str,
        channel_type: str = "console",
        attachments: list[str] | None = None,
    ) -> str:
        """
        Process an incoming message and return the assistant's response.

        This is the main entry point. It:
        1. Adds the user message to memory
        2. Builds the context (system prompt + history)
        3. Calls the LLM
        4. If the LLM wants to call tools, executes them and loops
        5. Returns the final text response
        """
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

        # Build system prompt with OpenACM context FIRST, then skills
        system_prompt = self.config.system_prompt

        # 1. Agregar contexto de OpenACM — full on first message, short thereafter
        existing_messages = await self.memory.get_messages(user_id, channel_id)
        is_new_conversation = len(existing_messages) == 0
        openacm_context = get_openacm_context() if is_new_conversation else get_short_context()
        system_prompt = f"{openacm_context}\n\n{system_prompt}"

        # 2. Agregar skills relevantes si existen
        if self.skill_manager:
            skills_prompt = await self.skill_manager.get_active_skills_prompt(content)
            if skills_prompt:
                system_prompt = f"{system_prompt}\n\n{skills_prompt}"

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
            from openacm.security.crypto import decrypt_file

            structured_content = []
            if content:
                structured_content.append({"type": "text", "text": content})

            for att_id in attachments:
                file_path = Path("data/media") / att_id
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

                        # Only append as image if it's an image
                        if mime.startswith("image/"):
                            structured_content.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                                }
                            )
                        else:
                            # Not an image. LiteLLM vision spec only natively supports images for now.
                            # We append a note
                            structured_content.append(
                                {
                                    "type": "text",
                                    "text": f"\n[The user attached a file named {att_id} but it's not an image format supported by Vision API directly.]",
                                }
                            )
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
        if tools and profile.max_tools_per_call and len(tools) > profile.max_tools_per_call:
            log.info(
                "Capping tool count for provider",
                provider=profile.name,
                original=len(tools),
                cap=profile.max_tools_per_call,
            )
            tools = tools[: profile.max_tools_per_call]

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
                error_str = str(e)
                if "500" in error_str:
                    error_msg = "❌ Error: The AI server (OpenCode.ai) is experiencing issues. This is a temporary problem with the service provider, not your installation.\n\nPlease try again in a few moments."
                elif "timeout" in error_str.lower():
                    error_msg = "❌ Error: The request timed out. The AI server may be slow or overloaded.\n\nPlease try again."
                else:
                    error_msg = f"❌ Error communicating with LLM: {error_str}"

                log.error("LLM error", error=error_str)

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
                    # Si el contenido está vacío, hacer una última llamada pidiendo el resumen
                    log.warning("LLM returned empty content after tools, requesting summary")
                    await self.memory.add_message(
                        user_id,
                        channel_id,
                        "user",
                        "Por favor, resume los resultados obtenidos y proporciona la información solicitada.",
                    )
                    messages = await self.memory.get_messages(user_id, channel_id)
                    continue  # Volver al inicio del loop para hacer otra llamada

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

                # Also update the response to show attachment links clearly
                if generated_attachments:
                    attachment_links = "\n\n".join(
                        [f"📎 /api/media/{att}" for att in generated_attachments]
                    )
                    return f"{assistant_content}\n\n{attachment_links}"

                return assistant_content

            # Process tool calls
            # First, add the assistant message with tool_calls to memory
            await self.memory.add_message(
                user_id,
                channel_id,
                "assistant",
                response["content"] or "",
                tool_calls=response["tool_calls"],
            )
            messages = await self.memory.get_messages(user_id, channel_id)

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
                            tool_name, tool_args, user_id, channel_id, _brain=self
                        )

                        # Check if this is send_file_to_chat and extract attachment
                        if tool_name == "send_file_to_chat" and result.startswith("ATTACHMENT:"):
                            # Extract filename from ATTACHMENT:filename format
                            lines = result.split("\n")
                            if lines and lines[0].startswith("ATTACHMENT:"):
                                filename = lines[0].replace("ATTACHMENT:", "").strip()
                                generated_attachments.append(filename)
                                log.info(
                                    "File attachment detected", filename=filename, tool=tool_name
                                )
                    else:
                        result = f"Error: Tool '{tool_name}' not found"

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

        # If we hit max iterations, make one final LLM call to get the answer with all results
        try:
            log.warning("Max iterations reached, making final LLM call for summary")
            final_response = await self.llm_router.chat(
                messages=messages,
                tools=None,  # No tools in final call
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

                # Also update the response to show attachment links clearly
                if generated_attachments:
                    attachment_links = "\n\n".join(
                        [f"📎 /api/media/{att}" for att in generated_attachments]
                    )
                    return f"{final_content}\n\n{attachment_links}"

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
