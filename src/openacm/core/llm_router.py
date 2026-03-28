"""
LLM Router — unified interface to all LLM providers via LiteLLM.

Supports Ollama (local), OpenAI, Anthropic, Gemini, and 100+ other providers.
Handles model switching, streaming, retries, and token tracking.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import litellm
import structlog
import os

from openacm.core.config import LLMConfig
from openacm.core.events import EventBus, EVENT_LLM_REQUEST, EVENT_LLM_RESPONSE


@dataclass
class ProviderProfile:
    """Capability profile for a given LLM provider."""

    name: str
    needs_tool_enforcement: bool
    tool_choice_mode: str  # "auto", "required", "none"
    max_tools_per_call: int | None  # None = no limit

log = structlog.get_logger()

# Suppress LiteLLM's verbose logging
litellm.suppress_debug_info = True
litellm.set_verbose = False


class LLMRouter:
    """Unified LLM interface using LiteLLM."""

    def __init__(self, config: LLMConfig, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self._current_provider = config.default_provider
        self._current_model: str | None = None
        self._total_tokens = 0
        self._total_cost = 0.0
        self._total_requests = 0
        self._database: Any = None  # Set later for persistence

        # Configure LiteLLM with provider settings
        self._configure_providers()

    def _configure_providers(self):
        """Configure LiteLLM with provider-specific settings.

        NOTE: Do NOT set litellm.api_base globally here — it would override
        all providers.  api_base is passed per-request via _get_api_base().
        """
        pass

    @property
    def current_model(self) -> str:
        """Get the current model identifier."""
        if self._current_model:
            return self._current_model
        provider = self._current_provider
        if provider in self.config.providers:
            return self.config.providers[provider].get("default_model", "unknown")
        return "unknown"

    @property
    def current_provider(self) -> str:
        """Expose the current provider name."""
        return self._current_provider

    def get_provider_profile(self) -> ProviderProfile:
        """Return a capability profile for the current provider."""
        provider = self._current_provider.lower()
        if provider in ("openai", "anthropic"):
            return ProviderProfile(
                name=provider,
                needs_tool_enforcement=False,
                tool_choice_mode="auto",
                max_tools_per_call=None,
            )
        if provider == "gemini":
            return ProviderProfile(
                name=provider,
                needs_tool_enforcement=True,
                tool_choice_mode="auto",
                max_tools_per_call=15,
            )
        if provider == "ollama":
            return ProviderProfile(
                name=provider,
                needs_tool_enforcement=True,
                tool_choice_mode="auto",
                max_tools_per_call=10,
            )
        if provider == "openrouter":
            return ProviderProfile(
                name=provider,
                needs_tool_enforcement=True,
                tool_choice_mode="auto",
                max_tools_per_call=15,
            )
        if provider == "opencode_go":
            # OpenCode.ai proxy crashes with tool_choice="required"
            # (their backend fails reading usage.prompt_tokens).
            # Use "auto" and never enforce — let the model decide.
            return ProviderProfile(
                name=provider,
                needs_tool_enforcement=False,
                tool_choice_mode="auto",
                max_tools_per_call=15,
            )
        # Unknown / custom — conservative defaults
        return ProviderProfile(
            name=provider,
            needs_tool_enforcement=True,
            tool_choice_mode="auto",
            max_tools_per_call=15,
        )

    def set_model(self, model: str, provider: str | None = None):
        """
        Set the current model and optionally the provider.

        If provider is given explicitly, use it.
        Otherwise if model has 'provider/model' format, extract the provider.
        Otherwise keep the current provider.
        """
        if provider:
            self._current_provider = provider
            self._current_model = model
        elif "/" in model:
            # Explicit provider/model format
            self._current_provider = model.split("/")[0]
            self._current_model = model
        else:
            self._current_model = model
        log.info("Model changed", model=self.current_model, provider=self._current_provider)

    async def load_persisted_model(self, database: Any) -> None:
        """Load persisted model/provider from the database on startup."""
        self._database = database
        try:
            model = await database.get_setting("llm.current_model")
            provider = await database.get_setting("llm.current_provider")
            if model:
                self.set_model(model, provider=provider)
                log.info(
                    "Loaded persisted model",
                    model=self.current_model,
                    provider=self._current_provider,
                )
        except Exception as e:
            log.warning("Could not load persisted model", error=str(e))

    def _build_model_string(self) -> str:
        """Build the LiteLLM model string."""
        if self._current_model:
            # If already has provider prefix, use as-is
            if "/" in self._current_model:
                return self._current_model
            # Add provider prefix for non-openai providers
            provider = self._current_provider
            model = self._current_model
            if provider == "ollama":
                return f"ollama/{model}" if not model.startswith("ollama/") else model
            elif provider == "anthropic":
                return f"anthropic/{model}" if not model.startswith("anthropic/") else model
            elif provider == "gemini":
                return f"gemini/{model}" if not model.startswith("gemini/") else model
            elif provider == "openrouter":
                return f"openrouter/{model}" if not model.startswith("openrouter/") else model
            else:
                if self._get_api_base() and provider != "openai":
                    return f"openai/{model}" if not model.startswith("openai/") else model
                return model  # OpenAI models don't need prefix

        # Use default from config
        provider = self._current_provider
        if provider in self.config.providers:
            settings = self.config.providers[provider]
            model = settings.get("default_model", "")
            if provider == "ollama":
                return f"ollama/{model}" if not model.startswith("ollama/") else model
            elif provider == "anthropic":
                return f"anthropic/{model}" if not model.startswith("anthropic/") else model
            elif provider == "gemini":
                return f"gemini/{model}" if not model.startswith("gemini/") else model
            elif provider == "openrouter":
                return f"openrouter/{model}" if not model.startswith("openrouter/") else model
            else:
                if provider != "openai" and "base_url" in settings:
                    return f"openai/{model}"
                return model

        return "ollama/llama3.2"

    def _get_api_base(self) -> str | None:
        """Get API base URL for current provider."""
        provider = self._current_provider
        if provider in self.config.providers:
            return self.config.providers[provider].get("base_url")
        return None

    def _is_custom_provider(self) -> bool:
        """Check if current provider is a custom one (not natively supported by LiteLLM)."""
        native = {"ollama", "openai", "anthropic", "gemini"}
        return self._current_provider not in native and self._get_api_base() is not None

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

        is_kimi = "kimi" in self._current_provider.lower() or "moonshot" in self._current_provider.lower()

        # Pass 0: strip tool messages with empty tool_call_id
        messages = [
            msg for msg in messages
            if not (msg.get("role") == "tool" and not msg.get("tool_call_id"))
        ]

        # Pass 1: collect all tool_call_ids that already have a response
        responded_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "tool" and msg.get("tool_call_id"):
                responded_ids.add(msg["tool_call_id"])

        # Pass 2: normalize assistant tool_calls + inject missing responses
        normalized: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                clean_tool_calls = []
                for tc in msg["tool_calls"]:
                    cid = tc.get("id", "")
                    if not cid:
                        cid = f"call_{_uuid_norm.uuid4().hex[:12]}"
                        tc = {**tc, "id": cid}
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
                # Inject synthetic responses for any orphaned tool_call_ids
                for tc in clean_tool_calls:
                    cid = tc.get("id", "")
                    if cid and cid not in responded_ids:
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

        # Pass 3: drop tool responses with no matching tool_call
        all_tc_ids: set[str] = set()
        for msg in normalized:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    cid = tc.get("id", "")
                    if cid:
                        all_tc_ids.add(cid)

        final: list[dict[str, Any]] = []
        for msg in normalized:
            if msg.get("role") == "tool":
                tcid = msg.get("tool_call_id", "")
                if not tcid or tcid not in all_tc_ids:
                    log.warning(
                        "Dropping unmatched tool response",
                        tool_call_id=repr(tcid),
                        all_known_ids=list(all_tc_ids),
                    )
                    continue
            final.append(msg)

        return final

    async def _custom_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tool_choice_override: str | None = None,
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

        effective_tc = tool_choice_override or self.get_provider_profile().tool_choice_mode

        # Normalize messages (fix orphaned tool calls/responses, strip unknown fields)
        final = self._normalize_messages(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": final,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            if effective_tc and effective_tc != "auto":
                payload["tool_choice"] = effective_tc
        if max_tokens:
            payload["max_tokens"] = max_tokens

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
                        response_body=body_text[:2000],
                    )
                    raise httpx.HTTPStatusError(
                        f"Server error '{resp.status_code}' for url '{url}'",
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

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    fr = choices[0].get("finish_reason")
                    if fr:
                        finish_reason = fr

                    # Accumulate reasoning content (Kimi thinking mode).
                    # Check both delta-level and choices-level since providers differ.
                    rc = (
                        delta.get("reasoning_content")
                        or delta.get("thinking")
                        or choices[0].get("reasoning_content")
                        or choices[0].get("thinking")
                        or ""
                    )
                    if rc:
                        reasoning_parts.append(rc)

                    # Accumulate content
                    if delta.get("content"):
                        content_parts.append(delta["content"])

                    # Accumulate tool calls
                    for tc in delta.get("tool_calls", []):
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
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                },
            })

        captured_reasoning = "".join(reasoning_parts)
        log.debug(
            "Custom provider stream complete",
            model=model,
            reasoning_chars=len(captured_reasoning),
            tool_calls=len(assembled_tool_calls),
            content_chars=len("".join(content_parts)),
        )

        result = {
            "content": "".join(content_parts),
            "reasoning_content": captured_reasoning,
            "tool_calls": assembled_tool_calls,
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "model": model,
            "elapsed": 0,
            "finish_reason": finish_reason,
        }

        return result

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        max_retries: int = 3,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a chat completion request with automatic retries on server errors.

        Returns dict with: content, tool_calls, usage (tokens), model, etc.
        ``tool_choice`` overrides the provider-profile default when set.
        """
        model = self._build_model_string()
        api_base = self._get_api_base()

        start_time = time.time()
        self._total_requests += 1

        await self.event_bus.emit(
            EVENT_LLM_REQUEST,
            {
                "model": model,
                "message_count": len(messages),
                "has_tools": bool(tools),
            },
        )

        # Retry logic with exponential backoff
        last_error = None
        for attempt in range(max_retries):
            try:
                return await self._chat_attempt(
                    messages, tools, temperature, max_tokens, model, api_base, start_time,
                    tool_choice_override=tool_choice,
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Only retry on server errors (5xx) or timeouts
                is_retryable = (
                    "500" in str(e)
                    or "502" in str(e)
                    or "503" in str(e)
                    or "504" in str(e)
                    or "timeout" in error_str
                    or "server error" in error_str
                )

                if not is_retryable or attempt == max_retries - 1:
                    raise

                wait_time = 2**attempt  # Exponential backoff: 1s, 2s, 4s
                log.warning(
                    f"LLM request failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s...",
                    error=str(e),
                )
                await asyncio.sleep(wait_time)

        # Should never reach here
        raise last_error or Exception("Max retries exceeded")

    async def _chat_attempt(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int | None,
        model: str,
        api_base: str | None,
        start_time: float,
        tool_choice_override: str | None = None,
    ) -> dict[str, Any]:
        """Single chat attempt."""
        profile = self.get_provider_profile()
        effective_tool_choice = tool_choice_override or profile.tool_choice_mode

        # Normalize messages for all providers (fix orphaned tool calls, strip unknown fields)
        messages = self._normalize_messages(messages)

        try:
            # Use direct httpx for custom providers (LiteLLM mangles URLs)
            if self._is_custom_provider():
                result = await self._custom_chat(
                    messages, tools, temperature, max_tokens,
                    tool_choice_override=effective_tool_choice,
                )
                result["elapsed"] = time.time() - start_time
                result["model"] = model
            else:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": False,
                }

                if api_base:
                    kwargs["api_base"] = api_base

                # Dynamically inject API key for any custom provider
                api_key_env = f"{self._current_provider.upper()}_API_KEY"
                if api_key_env in os.environ:
                    kwargs["api_key"] = os.environ[api_key_env]

                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = effective_tool_choice
                if max_tokens:
                    kwargs["max_tokens"] = max_tokens

                response = await litellm.acompletion(**kwargs)

                elapsed = time.time() - start_time

                # Extract response data
                choice = response.choices[0]
                message = choice.message

                result = {
                    "content": message.content or "",
                    "tool_calls": [],
                    "usage": {
                        "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                        "total_tokens": getattr(response.usage, "total_tokens", 0),
                    },
                    "model": model,
                    "elapsed": elapsed,
                    "finish_reason": choice.finish_reason,
                }

                # Extract tool calls if present
                if hasattr(message, "tool_calls") and message.tool_calls:
                    result["tool_calls"] = [
                        {
                            "id": tc.id,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ]

            # Track totals
            self._total_tokens += result["usage"]["total_tokens"]

            await self.event_bus.emit(
                EVENT_LLM_RESPONSE,
                {
                    "model": model,
                    "tokens": result["usage"]["total_tokens"],
                    "elapsed": result["elapsed"],
                    "has_tool_calls": bool(result["tool_calls"]),
                },
            )

            log.debug(
                "LLM response",
                model=model,
                tokens=result["usage"]["total_tokens"],
                elapsed=f"{result['elapsed']:.2f}s",
                tool_calls=len(result["tool_calls"]),
            )

            return result

        except Exception as e:
            elapsed = time.time() - start_time
            log.error("LLM request failed", model=model, error=str(e), elapsed=f"{elapsed:.2f}s")
            raise

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream a chat completion response, yielding text chunks."""
        model = self._build_model_string()
        api_base = self._get_api_base()

        messages = self._normalize_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        if api_base:
            kwargs["api_base"] = api_base

        api_key_env = f"{self._current_provider.upper()}_API_KEY"
        if api_key_env in os.environ:
            kwargs["api_key"] = os.environ[api_key_env]

        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        response = await litellm.acompletion(**kwargs)

        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def list_models(self) -> dict[str, list[str]]:
        """List configured model providers and their default models."""
        result = {}
        for provider, settings in self.config.providers.items():
            default = settings.get("default_model", "")
            result[provider] = [default] if default else []
        return result

    def get_stats(self) -> dict[str, Any]:
        """Get usage statistics."""
        return {
            "total_requests": self._total_requests,
            "total_tokens": self._total_tokens,
            "total_cost": self._total_cost,
            "current_model": self.current_model,
            "current_provider": self._current_provider,
        }
