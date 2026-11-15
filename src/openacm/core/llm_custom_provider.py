"""LLMRouter's path for custom (OpenAI-compatible) providers: message normalising and the raw HTTP chat."""
import asyncio
import os
import time
from typing import Any, AsyncIterator

import litellm
import structlog

from openacm.constants import TRUNCATE_LLM_ERROR_CHARS
from openacm.utils.text import truncate, extract_and_strip_thinking
from openacm.core.llm_pricing import _count_tokens, _estimate_cost

log = structlog.get_logger()


class CustomProviderMixin:
    """Part of LLMRouter; it inherits this."""

    def _normalize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Sanitize message history for any provider.

        Fixes:
        - Orphaned tool_calls (no matching tool response) → inject synthetic response
        - Orphaned tool responses (no matching tool_call) → drop them
        - Empty tool_call_ids → assign stable UUID
        - reasoning_content → only kept for Kimi; stripped for all other providers
        - Gemini: strip reasoning_content from all messages (Gemini doesn't know the field)
        """
        import uuid as _uuid_norm

        _provider_lower = self._current_provider.lower()
        # Use explicit model if set; fall back to config default (e.g. on fresh install)
        _model_lower = (self._current_model or "").lower()
        if not _model_lower and self._current_provider in self.config.providers:
            _model_lower = self.config.providers[self._current_provider].get("default_model", "").lower()
        is_kimi = (
            "kimi" in _provider_lower
            or "moonshot" in _provider_lower
            or "kimi" in _model_lower
            or "moonshot" in _model_lower
        )

        # Pass 0: strip tool messages with empty tool_call_id
        messages = [
            msg for msg in messages
            if not (msg.get("role") == "tool" and not msg.get("tool_call_id"))
        ]

        # Pass 0b: drop leading tool messages — no assistant precedes them, Anthropic rejects them
        first_assistant = next((i for i, m in enumerate(messages) if m.get("role") == "assistant"), None)
        if first_assistant is not None:
            messages = [
                m for i, m in enumerate(messages)
                if m.get("role") != "tool" or i > first_assistant
            ]

        # Build index of tool responses by tool_call_id.
        # If there are multiple responses for the same ID (shouldn't happen, but be safe),
        # keep the last one. Tool messages will be placed immediately after the assistant
        # message that called them, guaranteeing the ordering the LLM spec requires.
        tool_response_index: dict[str, dict] = {}
        for msg in messages:
            if msg.get("role") == "tool" and msg.get("tool_call_id"):
                tool_response_index[msg["tool_call_id"]] = msg

        # Pass 2: rebuild with tool responses immediately after their calling assistant.
        # Tool messages are skipped in the main loop — they are inserted when their
        # assistant message is processed, ensuring correct adjacency even when the
        # original history has them out of order (e.g. after a subsequent assistant turn).
        normalized: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role")

            # Tool messages are placed by their assistant; skip here.
            if role == "tool":
                continue

            if role == "assistant" and msg.get("tool_calls"):
                clean_tool_calls = []
                for tc in msg["tool_calls"]:
                    cid = tc.get("id", "")
                    if not cid:
                        cid = f"call_{_uuid_norm.uuid4().hex[:12]}"
                    # Ensure required OpenAI spec field so litellm can build tool_use for Anthropic
                    tc = {**tc, "id": cid, "type": "function"}
                    clean_tool_calls.append(tc)
                msg = {**msg, "tool_calls": clean_tool_calls}

                # reasoning_content: keep only for Kimi, strip for everything else
                if is_kimi:
                    if not msg.get("reasoning_content"):
                        msg = {**msg, "reasoning_content": "I analyzed the request and determined the appropriate tool to use."}
                else:
                    if "reasoning_content" in msg:
                        msg = {k: v for k, v in msg.items() if k != "reasoning_content"}

                normalized.append(msg)

                # Immediately place tool responses for each tool_call
                for tc in clean_tool_calls:
                    cid = tc.get("id", "")
                    if not cid:
                        continue
                    if cid in tool_response_index:
                        normalized.append(tool_response_index[cid])
                    else:
                        log.warning("Injecting synthetic tool response for orphaned tool_call_id", id=cid)
                        normalized.append({
                            "role": "tool",
                            "tool_call_id": cid,
                            "content": "Error: Tool execution was interrupted or timed out.",
                        })
            else:
                # Strip reasoning_content from non-assistant messages too
                if not is_kimi and "reasoning_content" in msg:
                    msg = {k: v for k, v in msg.items() if k != "reasoning_content"}
                normalized.append(msg)

        # Strip top-level 'name' from all messages — rejected with 400 by providers like
        # OpenCode Go / Console Go / GLM-5.3-flash ("messages[N]: 'name' is not supported by this endpoint").
        # Tool call function names remain intact within tool_calls[...]['function']['name'].
        return [{k: v for k, v in m.items() if k != "name"} for m in normalized]

    async def _custom_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tool_choice_override: str | None = None,
        top_p: float | None = None,
    ) -> dict[str, Any]:
        """Direct httpx call for custom OpenAI-compatible providers.

        Uses streaming (stream=true) to work around proxies that crash
        when processing the non-streamed usage object (e.g. OpenCode.ai).
        Chunks are collected and reassembled into a standard response.
        """
        import httpx
        import json as _json

        api_base = self._get_api_base().rstrip("/")
        api_key_env = f"{self._current_provider.upper()}_API_KEY"
        api_key = os.environ.get(api_key_env, "")

        # Get clean model name (no openai/ prefix)
        model = self._current_model or self.config.providers[self._current_provider].get(
            "default_model", ""
        )

        url = f"{api_base}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if self._current_provider == "opencode_go":
            # OpenCode Go now expects a stable per-conversation session id
            # to enable server-side routing/prompt-caching optimizations.
            # Prefer the active channel id (real per-conversation identity);
            # fall back to a per-router-instance id if no stream context is set.
            _sctx = getattr(self, "_active_stream_ctx", None)
            if _sctx and _sctx[1]:
                headers["x-opencode-session"] = str(_sctx[1])
            else:
                if not getattr(self, "_opencode_session_id", None):
                    import uuid as _uuid_session
                    self._opencode_session_id = str(_uuid_session.uuid4())
                headers["x-opencode-session"] = self._opencode_session_id

        effective_tc = tool_choice_override or self.get_provider_profile().tool_choice_mode

        _provider_lower = self._current_provider.lower()
        _model_lower = (model or "").lower()
        is_kimi = "kimi" in _provider_lower or "moonshot" in _provider_lower or "kimi" in _model_lower

        # Messages already normalized by the caller (_chat_attempt); use as-is
        final = messages

        # kimi-k2.5 only accepts temperature=1
        effective_temperature = 1 if is_kimi else temperature

        payload: dict[str, Any] = {
            "model": model,
            "messages": final,
            "temperature": effective_temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            if effective_tc and effective_tc != "auto":
                payload["tool_choice"] = effective_tc
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if top_p is not None:
            payload["top_p"] = top_p

        # Inject extra model params (e.g. thinking mode) — skip standard keys already set above
        _STANDARD_KEYS = {"temperature", "max_tokens", "top_p", "model", "messages", "stream", "tools", "tool_choice"}
        for _k, _v in self._get_model_params().items():
            if _k not in _STANDARD_KEYS:
                payload[_k] = _v

        # Debug: log exactly what we're sending
        tool_names = [t["function"]["name"] for t in tools] if tools else []
        log.info(
            "Custom provider request (stream)",
            url=url,
            model=model,
            message_count=len(final),
            has_tools=bool(tools),
            tool_count=len(tools) if tools else 0,
            tool_names=tool_names,
            tool_choice=payload.get("tool_choice"),
            temperature=temperature,
            max_tokens=max_tokens,
            has_api_key=bool(api_key),
        )

        # Collect streamed chunks
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        # tool_calls keyed by index: {0: {"id": ..., "name": ..., "arguments": ...}}
        tool_calls_acc: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        stream_usage: dict[str, int] = {}

        # Ask providers to include usage in the final stream chunk (OpenAI-compatible flag).
        # Providers that don't support it will silently ignore it.
        payload.setdefault("stream_options", {"include_usage": True})

        # SECURITY: POR DISEÑO - HTTP client para APIs de LLM
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", url, headers=headers, json=payload, timeout=300.0
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    body_text = body.decode("utf-8", errors="replace")
                    log.error(
                        "Custom provider error response",
                        status=resp.status_code,
                        url=url,
                        model=model,
                        response_body=truncate(body_text, TRUNCATE_LLM_ERROR_CHARS),
                    )
                    error_prefix = (
                        "Rate limit" if resp.status_code == 429
                        else ("Server error" if resp.status_code >= 500 else "Client error")
                    )
                    raise httpx.HTTPStatusError(
                        f"{error_prefix} '{resp.status_code}' for url '{url}'",
                        request=resp.request,
                        response=resp,
                    )

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data_str)
                    except _json.JSONDecodeError:
                        continue

                    # Capture usage from any chunk that carries it
                    # (some providers send it in a final chunk with empty choices)
                    if chunk.get("usage"):
                        stream_usage = chunk["usage"]

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    fr = choices[0].get("finish_reason")
                    if fr:
                        finish_reason = fr

                    # Accumulate reasoning content — check every known field name.
                    # kimi-k2.6 uses "reasoning" (plain string per delta)
                    # deepseek/other proxies use "reasoning_content" or "thinking_content"
                    # some models embed it in content as <think>…</think>
                    rc = (
                        delta.get("reasoning")
                        or delta.get("reasoning_content")
                        or delta.get("thinking_content")
                        or delta.get("thinking")
                        or choices[0].get("reasoning")
                        or choices[0].get("reasoning_content")
                        or choices[0].get("thinking_content")
                        or choices[0].get("thinking")
                        or ""
                    )
                    if rc:
                        reasoning_parts.append(rc)
                        # Stream reasoning chunk to frontend in real-time
                        _sctx = getattr(self, "_active_stream_ctx", None)
                        if _sctx and self.event_bus:
                            _uid, _cid, _ctype = _sctx
                            await self.event_bus.emit("message.reasoning_stream", {
                                "chunk": rc,
                                "user_id": _uid,
                                "channel_id": _cid,
                                "channel_type": _ctype,
                                "swarm_id": None,
                                "worker_name": None,
                            })

                    # Accumulate content; extract <think>…</think> blocks if present
                    raw_content = delta.get("content") or ""
                    if raw_content:
                        content_parts.append(raw_content)

                    # Log raw delta keys once (first non-empty delta) for debugging
                    if not reasoning_parts and not content_parts and (delta or choices[0]):
                        log.debug("First delta keys", delta_keys=list(delta.keys()), choice_keys=list(choices[0].keys()))

                    # Accumulate tool calls
                    for tc in (delta.get("tool_calls") or []):
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc.get("id", ""),
                                "name": "",
                                "arguments": "",
                            }
                        if tc.get("id"):
                            tool_calls_acc[idx]["id"] = tc["id"]
                        func = tc.get("function", {})
                        if func.get("name"):
                            tool_calls_acc[idx]["name"] = func["name"]
                        if func.get("arguments"):
                            tool_calls_acc[idx]["arguments"] += func["arguments"]

        # Build final result
        import uuid as _uuid
        assembled_tool_calls = []
        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            # Kimi sometimes omits the id in the stream — generate one so it's never empty
            tc_id = tc["id"] or f"call_{_uuid.uuid4().hex[:12]}"
            assembled_tool_calls.append({
                "id": tc_id,
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                },
            })

        captured_reasoning = "".join(reasoning_parts)
        full_content = "".join(content_parts)

        # Extract thinking/reasoning and strip all thinking tags and blocks from content.
        # Some models embed thinking in content with or without opening tags.
        full_content, captured_reasoning = extract_and_strip_thinking(
            full_content, existing_reasoning=captured_reasoning
        )

        log.debug(
            "Custom provider stream assembled",
            reasoning_chars=len(captured_reasoning),
            content_chars=len(full_content),
            tool_calls=len(assembled_tool_calls),
        )

        # Build token usage from stream data; use litellm token_counter when missing.
        prompt_tokens = stream_usage.get("prompt_tokens", 0)
        completion_tokens = stream_usage.get("completion_tokens", 0)
        total_tokens = stream_usage.get("total_tokens", 0)
        if prompt_tokens == 0:
            prompt_tokens = _count_tokens(model, messages=messages)
        if completion_tokens == 0:
            output_text = full_content + "".join(reasoning_parts)
            completion_tokens = _count_tokens(model, text=output_text) if output_text else 1
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens

        log.debug(
            "Custom provider stream complete",
            model=model,
            reasoning_chars=len(captured_reasoning),
            tool_calls=len(assembled_tool_calls),
            content_chars=len(full_content),
            total_tokens=total_tokens,
            usage_from_stream=bool(stream_usage),
        )

        result = {
            "content": full_content,
            "reasoning_content": captured_reasoning,
            "tool_calls": assembled_tool_calls,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            "model": model,
            "elapsed": 0,
            "finish_reason": finish_reason,
        }

        return result
