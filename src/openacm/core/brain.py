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
    EventBus,
    EVENT_MESSAGE_RECEIVED,
    EVENT_MESSAGE_SENT,
    EVENT_TOOL_CALLED,
    EVENT_TOOL_RESULT,
)
from openacm.core.llm_router import LLMRouter
from openacm.core.memory import MemoryManager

log = structlog.get_logger()


class Brain:
    """
    Central AI engine that processes messages through the LLM
    with tool calling support.
    """

    def __init__(
        self,
        config: AssistantConfig,
        llm_router: LLMRouter,
        memory: MemoryManager,
        event_bus: EventBus,
        tool_registry: Any = None,
    ):
        self.config = config
        self.llm_router = llm_router
        self.memory = memory
        self.event_bus = event_bus
        self.tool_registry = tool_registry

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
        await self.event_bus.emit(EVENT_MESSAGE_RECEIVED, {
            "content": content,
            "user_id": user_id,
            "channel_id": channel_id,
            "channel_type": channel_type,
            "attachments": attachments or []
        })

        # Get or create conversation with system prompt
        messages = await self.memory.get_or_create(
            user_id, channel_id, self.config.system_prompt
        )

        # RAG: Query long-term memory for relevant context
        try:
            from openacm.core.rag import _rag_engine
            if _rag_engine and _rag_engine.is_ready and content:
                memories = await _rag_engine.query(content, top_k=3)
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
                        messages = [m for m in messages if not (m.get("role") == "system" and "Memoria a largo plazo" in str(m.get("content", "")))]
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
                        if ext in [".png"]: mime = "image/png"
                        elif ext in [".jpg", ".jpeg"]: mime = "image/jpeg"
                        elif ext in [".gif"]: mime = "image/gif"
                        elif ext in [".webp"]: mime = "image/webp"
                        
                        # Only append as image if it's an image
                        if mime.startswith("image/"):
                            structured_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime};base64,{b64}"
                                }
                            })
                        else:
                            # Not an image. LiteLLM vision spec only natively supports images for now.
                            # We append a note
                            structured_content.append({
                                "type": "text",
                                "text": f"\n[The user attached a file named {att_id} but it's not an image format supported by Vision API directly.]"
                            })
                    except Exception as e:
                        log.error("Failed to load attachment", error=str(e), file_id=att_id)
            
            if structured_content:
                final_content = structured_content

        # Add user message
        await self.memory.add_message(user_id, channel_id, "user", final_content)
        messages = await self.memory.get_messages(user_id, channel_id)

        # Get tools in OpenAI format
        tools = None
        if self.tool_registry:
            tools = self.tool_registry.get_tools_schema()

        # Agentic loop: LLM may call tools multiple times
        iterations = 0
        max_iterations = self.config.max_tool_iterations

        while iterations < max_iterations:
            iterations += 1

            try:
                response = await self.llm_router.chat(
                    messages=messages,
                    tools=tools,
                )
            except Exception as e:
                error_msg = f"Error communicating with LLM: {str(e)}"
                log.error("LLM error", error=str(e))
                return error_msg

            # If no tool calls, we have the final answer
            if not response["tool_calls"]:
                assistant_content = response["content"]
                await self.memory.add_message(
                    user_id, channel_id, "assistant", assistant_content
                )
                await self.event_bus.emit(EVENT_MESSAGE_SENT, {
                    "content": assistant_content,
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                    "tokens": response["usage"]["total_tokens"],
                })
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

                await self.event_bus.emit(EVENT_TOOL_CALLED, {
                    "tool": tool_name,
                    "arguments": tool_args_str,
                    "user_id": user_id,
                    "channel_id": channel_id,
                })

                try:
                    # Parse arguments
                    tool_args = json.loads(tool_args_str) if tool_args_str else {}

                    # Execute tool
                    if self.tool_registry and tool_name in self.tool_registry.tools:
                        result = await self.tool_registry.execute(
                            tool_name, tool_args, user_id, channel_id
                        )
                    else:
                        result = f"Error: Tool '{tool_name}' not found"

                except json.JSONDecodeError:
                    result = f"Error: Invalid arguments for tool '{tool_name}'"
                except Exception as e:
                    result = f"Error executing tool '{tool_name}': {str(e)}"
                    log.error("Tool execution error", tool=tool_name, error=str(e))

                await self.event_bus.emit(EVENT_TOOL_RESULT, {
                    "tool": tool_name,
                    "result": result[:500],  # Truncate for event
                    "user_id": user_id,
                    "channel_id": channel_id,
                })

                # Add tool result to memory
                await self.memory.add_message(
                    user_id,
                    channel_id,
                    "tool",
                    str(result),
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )
                messages = await self.memory.get_messages(user_id, channel_id)

        # If we hit max iterations, return what we have
        return (
            "⚠️ Reached maximum tool iterations. "
            "The task might be too complex for a single request. "
            "Try breaking it down into smaller steps."
        )
