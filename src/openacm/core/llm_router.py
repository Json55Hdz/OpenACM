"""
LLM Router — unified interface to all LLM providers via LiteLLM.

Supports Ollama (local), OpenAI, Anthropic, Gemini, and 100+ other providers.
Handles model switching, streaming, retries, and token tracking.
"""

import asyncio
import time
from typing import Any, AsyncIterator

import litellm
import structlog
import os

from openacm.core.config import LLMConfig
from openacm.core.events import EventBus, EVENT_LLM_REQUEST, EVENT_LLM_RESPONSE

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

        # Configure LiteLLM with provider settings
        self._configure_providers()

    def _configure_providers(self):
        """Configure LiteLLM with provider-specific settings."""
        for provider, settings in self.config.providers.items():
            if provider == "ollama" and "base_url" in settings:
                # Ollama uses api_base
                litellm.api_base = settings["base_url"]

    @property
    def current_model(self) -> str:
        """Get the current model identifier."""
        if self._current_model:
            return self._current_model
        provider = self._current_provider
        if provider in self.config.providers:
            return self.config.providers[provider].get("default_model", "unknown")
        return "unknown"

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
                return f"ollama/{model}"
            elif provider == "anthropic":
                return f"anthropic/{model}"
            elif provider == "gemini":
                return model  # gemini models already have prefix in config
            else:
                if self._get_api_base() and provider != "openai":
                    return f"openai/{model}"
                return model  # OpenAI models don't need prefix

        # Use default from config
        provider = self._current_provider
        if provider in self.config.providers:
            settings = self.config.providers[provider]
            model = settings.get("default_model", "")
            if provider == "ollama":
                return f"ollama/{model}"
            elif provider == "anthropic":
                return f"anthropic/{model}"
            elif provider == "gemini":
                return model
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

    async def _custom_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Direct httpx call for custom OpenAI-compatible providers."""
        import httpx

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

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if max_tokens:
            payload["max_tokens"] = max_tokens

        # SECURITY: POR DISEÑO - HTTP client para APIs de LLM
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=120.0)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        msg = choice["message"]
        usage = data.get("usage", {})

        result = {
            "content": msg.get("content") or "",
            "tool_calls": [],
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "model": model,
            "elapsed": 0,
            "finish_reason": choice.get("finish_reason", "stop"),
        }

        if msg.get("tool_calls"):
            result["tool_calls"] = [
                {
                    "id": tc["id"],
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
                for tc in msg["tool_calls"]
            ]

        return result

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """
        Send a chat completion request with automatic retries on server errors.

        Returns dict with: content, tool_calls, usage (tokens), model, etc.
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
                    messages, tools, temperature, max_tokens, model, api_base, start_time
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
    ) -> dict[str, Any]:
        """Single chat attempt."""
        try:
            # Use direct httpx for custom providers (LiteLLM mangles URLs)
            if self._is_custom_provider():
                result = await self._custom_chat(messages, tools, temperature, max_tokens)
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
                    kwargs["tool_choice"] = "auto"
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
