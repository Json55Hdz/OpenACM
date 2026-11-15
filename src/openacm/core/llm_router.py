"""
LLM Router — unified interface to all LLM providers via LiteLLM.

Supports Ollama (local), OpenAI, Anthropic, Gemini, and 100+ other providers.
Handles model switching, streaming, retries, and token tracking.
"""

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import litellm
import structlog

from openacm.constants import TRUNCATE_LLM_ERROR_CHARS
from openacm.utils.text import truncate, extract_and_strip_thinking
from openacm.core.config import LLMConfig
from openacm.core.events import EventBus, EVENT_LLM_REQUEST, EVENT_LLM_RESPONSE
from openacm.core.llm_custom_provider import CustomProviderMixin
from openacm.core.llm_pricing import (  # noqa: F401  (re-exported for other modules)
    _PROVIDER_PRICING_PREFIX,
    _count_tokens,
    _estimate_cost,
)


@dataclass
class ProviderProfile:
    """Capability profile for a given LLM provider."""

    name: str
    needs_tool_enforcement: bool
    tool_choice_mode: str  # "auto", "required", "none"
    max_tools_per_call: int | None  # None = no limit (every provider currently uses None; the cap mechanism stays for future use)

log = structlog.get_logger()

# Suppress LiteLLM's verbose logging
litellm.suppress_debug_info = True
litellm.set_verbose = False

class LLMRouter(CustomProviderMixin):
    """Unified LLM interface using LiteLLM."""

    def __init__(self, config: LLMConfig, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self._current_provider = config.default_provider
        from openacm.core.model_capabilities import ModelCapabilities
        self.capabilities = ModelCapabilities(self)
        self._current_model: str | None = None
        self._total_tokens = 0
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
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

    def get_context_window(self, model: str | None = None) -> int | None:
        """Return the max input tokens for a model.

        Priority: manual config overrides → litellm database → parse from model name.
        Returns None if nothing matches so callers can fall back to a default.
        """
        import re
        m = (model or self.current_model or "").strip()
        if not m:
            return None

        # 1. Manual overrides configured by the user (substring match, case-insensitive)
        overrides: dict[str, int] = getattr(self.config, "model_context_overrides", {})
        m_lower = m.lower()
        for pattern, tokens in overrides.items():
            if pattern.lower() in m_lower:
                return tokens

        # 2. litellm model database
        try:
            info = litellm.get_model_info(m)
            tokens = info.get("max_input_tokens") or info.get("max_tokens")
            if tokens:
                return int(tokens)
        except Exception:
            pass

        # 3. Parse suffix from model name: "128k" → 131072, "1m" → 1048576, "200k" → 204800
        match = re.search(r"(\d+(?:\.\d+)?)\s*([mk])", m_lower)
        if match:
            num, unit = float(match.group(1)), match.group(2)
            return int(num * (1024 if unit == "k" else 1024 * 1024))

        return None

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
                max_tools_per_call=None,
            )
        if provider == "ollama":
            return ProviderProfile(
                name=provider,
                needs_tool_enforcement=True,
                tool_choice_mode="auto",
                max_tools_per_call=None,
            )
        if provider == "openrouter":
            return ProviderProfile(
                name=provider,
                needs_tool_enforcement=True,
                tool_choice_mode="auto",
                max_tools_per_call=None,
            )
        if provider == "opencode_go":
            # OpenCode.ai proxy crashes with tool_choice="required"
            # (their backend fails reading usage.prompt_tokens).
            # Use "auto" and never enforce — let the model decide.
            # No tool-count cap: OpenCode publishes no such limit (the old 15 was an
            # unmeasured guess copied from Gemini and silently dropped plugin tools).
            # If the backend ever rejects a request for too many tools, re-introduce
            # a cap HERE — tool lists are relevance-ranked, so truncation is safe.
            return ProviderProfile(
                name=provider,
                needs_tool_enforcement=False,
                tool_choice_mode="auto",
                max_tools_per_call=None,
            )
        if provider == "xai":
            # xAI Grok — OpenAI-compatible API, full tool support
            return ProviderProfile(
                name=provider,
                needs_tool_enforcement=False,
                tool_choice_mode="auto",
                max_tools_per_call=None,
            )
        # CLI providers — tool calling via text injection, no native tool schema
        if self._is_cli_provider():
            return ProviderProfile(
                name=provider,
                needs_tool_enforcement=False,
                tool_choice_mode="auto",
                max_tools_per_call=None,
            )

        # Unknown / custom — conservative defaults
        return ProviderProfile(
            name=provider,
            needs_tool_enforcement=True,
            tool_choice_mode="auto",
            max_tools_per_call=None,
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
        # Measure what this model can really do (image/audio input) in the background.
        self.capabilities.schedule_probe()

    async def load_persisted_model(self, database: Any) -> None:
        """Load persisted model/provider from the database on startup."""
        self._database = database
        await self.capabilities.load(database)
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

        # Restore model params
        try:
            import json as _json
            mp_json = await database.get_setting("llm.model_params")
            if mp_json:
                all_mp = _json.loads(mp_json)
                for prov, mp in all_mp.items():
                    if prov in self.config.providers:
                        self.config.providers[prov]["model_params"] = mp
                log.info("Loaded persisted model params", providers=list(all_mp.keys()))
        except Exception as e:
            log.warning("Could not load persisted model params", error=str(e))

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
                return f"openai/{model}"  # route via Ollama's OpenAI-compat /v1 endpoint
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
                return f"openai/{model}"  # route via Ollama's OpenAI-compat /v1 endpoint
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

        return "openai/llama3.2"  # fallback Ollama OpenAI-compat

    def _pricing_model_key(self) -> str:
        """Return the litellm.model_cost key that matches this provider+model for pricing.

        This is distinct from _build_model_string() which adds 'openai/' for custom
        OpenAI-compat endpoints.  For pricing we want 'xai/grok-3-beta', not 'openai/grok-3-beta'.
        """
        provider = self._current_provider.lower()
        model = self._current_model or ""
        prefix = _PROVIDER_PRICING_PREFIX.get(provider)
        if prefix:
            return f"{prefix}/{model}" if "/" not in model else model
        # OpenAI and unknown providers: try bare name (gpt-4o is in model_cost without prefix)
        return model

    def _get_api_base(self) -> str | None:
        """Get API base URL for current provider."""
        provider = self._current_provider
        if provider in self.config.providers:
            return self.config.providers[provider].get("base_url")
        return None

    # Models known to support thinking/reasoning mode via the `thinking` API param.
    # Pattern matched case-insensitively against the model name.
    _THINKING_MODEL_PATTERNS = [
        "kimi", "moonshot", "deepseek-r1", "deepseek/r1",
        "qwq", "o1", "o3", "claude-3-7",
        "grok-3-mini", "gemini-2.0-flash-thinking", "gemini-2.5", "gemini-3",
    ]

    def _get_model_params(self) -> dict:
        """Get stored params for current provider+model, auto-injecting thinking for known models."""
        provider_cfg = self.config.providers.get(self._current_provider, {})
        model = self._current_model or provider_cfg.get("default_model", "")
        params = dict(provider_cfg.get("model_params", {}).get(model, {}))

        # Auto-inject thinking params for models known to support it,
        # unless the caller already set a `thinking` key (either enabled or disabled).
        if "thinking" not in params:
            m_lower = model.lower()
            if any(p in m_lower for p in self._THINKING_MODEL_PATTERNS):
                params["thinking"] = {"type": "enabled", "budget_tokens": 8000}

        return params

    def set_model_params(self, provider: str, model: str, params: dict) -> None:
        """Persist params for a provider+model into live config."""
        if provider not in self.config.providers:
            return
        mp = self.config.providers[provider].setdefault("model_params", {})
        if model not in mp:
            mp[model] = {}
        for k in ("temperature", "max_tokens", "top_p"):
            if k in params:
                v = params[k]
                mp[model][k] = v  # None = unset

    def _is_cli_provider(self) -> bool:
        """Return True if the current provider is a CLI-type provider (no API key needed)."""
        provider = self._current_provider
        if provider in self.config.providers:
            return self.config.providers[provider].get("type") == "cli"
        return False

    def _is_custom_provider(self) -> bool:
        """Check if current provider is a custom one (not natively supported by LiteLLM)."""
        native = {"ollama", "openai", "anthropic", "gemini"}
        return self._current_provider not in native and self._get_api_base() is not None


    @staticmethod
    def _enforce_model_temperature(model: str, temperature: float) -> float:
        """Some models require a specific temperature range. Clamp silently."""
        # Gemini 3.x requires temperature == 1.0; lower values cause infinite loops.
        if "gemini-3" in model.lower() or "gemini-3." in model.lower():
            return 1.0
        return temperature

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        max_retries: int = 3,
        tool_choice: str | None = None,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a chat completion request with automatic retries on server errors.

        Returns dict with: content, tool_calls, usage (tokens), model, etc.
        ``tool_choice`` overrides the provider-profile default when set.
        ``model_override`` bypasses the current provider/model and uses the given
        LiteLLM model string directly (e.g. ``"anthropic/claude-opus-4-6"``).
        """
        # Resolve per-model param defaults (config overrides hardcoded defaults)
        _mp = self._get_model_params()
        if temperature is None:
            temperature = float(_mp.get("temperature", 0.7))
        if max_tokens is None and _mp.get("max_tokens"):
            max_tokens = int(_mp["max_tokens"])
        _top_p: float | None = _mp.get("top_p") or None

        model = model_override or self._build_model_string()
        api_base = None if model_override else self._get_api_base()
        temperature = self._enforce_model_temperature(model, temperature)

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
                    top_p=_top_p,
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Retry on transient server errors (5xx) and network drops.
                # ReadError / RemoteDisconnected mean the server closed the TCP
                # connection mid-stream — common with long-running LLM requests.
                # We do NOT retry asyncio.TimeoutError: that means we waited past
                # our own budget; re-sending would just double the wait.
                _e_str = str(e)
                _e_type = type(e).__name__.lower()
                is_rate_limit = (
                    "429" in _e_str
                    or "rate limit" in error_str
                    or "rate_limit" in error_str
                    or "too many requests" in error_str
                    or "ratelimit" in _e_type
                )
                # Client errors (400 Bad Request, 401 Unauthorized, etc.) are permanent, not transient
                is_client_error = (
                    any(c in _e_str for c in ("'400'", " 400 ", "401", "403", "404", "client error"))
                    or "bad request" in error_str
                    or "unauthorized" in error_str
                ) and not is_rate_limit

                is_retryable = (
                    not is_client_error
                    and (
                        is_rate_limit
                        or "500" in _e_str
                        or "502" in _e_str
                        or "503" in _e_str
                        or "504" in _e_str
                        or "server error" in error_str
                        or "readerror" in _e_type          # httpx: server dropped stream
                        or "read error" in error_str
                        or "remotedisconnected" in _e_type  # http.client level drop
                        or "connectionerror" in _e_type
                        or "connectionreset" in error_str
                        or "peer closed" in error_str
                    )
                )

                if not is_retryable or attempt == max_retries - 1:
                    raise

                # Longer wait for connection drops — give the remote server time to recover.
                # For rate limits (429), respect Retry-After header if provided, otherwise exponential backoff with jitter.
                is_network_drop = "readerror" in _e_type or "connectionerror" in _e_type or "remotedisconnected" in _e_type
                if is_rate_limit:
                    import random
                    retry_after = None
                    resp = getattr(e, "response", None)
                    if resp is not None and hasattr(resp, "headers"):
                        try:
                            ra_val = resp.headers.get("retry-after")
                            if ra_val:
                                retry_after = float(ra_val)
                        except (ValueError, TypeError):
                            pass
                    if retry_after is not None:
                        wait_time = max(retry_after, 1.0)
                    else:
                        wait_time = float(2 ** (attempt + 1)) + random.uniform(0.2, 0.8)
                elif is_network_drop:
                    wait_time = float(10 * (attempt + 1))
                else:
                    wait_time = float(2 ** attempt)

                log.warning(
                    f"LLM request failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time:.1f}s...",
                    error=str(e),
                    error_type=type(e).__name__,
                    is_rate_limit=is_rate_limit,
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
        top_p: float | None = None,
    ) -> dict[str, Any]:
        """Single chat attempt."""
        temperature = self._enforce_model_temperature(model, temperature)
        profile = self.get_provider_profile()
        effective_tool_choice = tool_choice_override or profile.tool_choice_mode

        # Normalize messages for all providers (fix orphaned tool calls, strip unknown fields)
        messages = self._normalize_messages(messages)

        try:
            # Per-provider timeout overrides the global default.
            # Set in config: llm.providers.<id>.timeout (seconds), 0 = no timeout.
            _provider_cfg = self.config.providers.get(self._current_provider, {})
            _raw_timeout = _provider_cfg.get("timeout", self.config.timeout)
            _llm_timeout: float | None = float(_raw_timeout) if _raw_timeout else None

            if self._is_cli_provider():
                from openacm.core.cli_provider import CLIProvider
                provider_cfg = self.config.providers.get(self._current_provider, {})
                cli = CLIProvider(provider_cfg)
                result = await asyncio.wait_for(
                    cli.chat(messages, tools, temperature, max_tokens),
                    timeout=provider_cfg.get("timeout", 300),
                )
                result["elapsed"] = time.time() - start_time
                result["model"] = model

            elif self._is_custom_provider():
                result = await asyncio.wait_for(
                    self._custom_chat(
                        messages, tools, temperature, max_tokens,
                        tool_choice_override=effective_tool_choice,
                        top_p=top_p,
                    ),
                    timeout=_llm_timeout,
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
                    # Ollama: use OpenAI-compatible /v1 endpoint (required for litellm 1.x)
                    if self._current_provider == "ollama":
                        kwargs["api_base"] = api_base.rstrip("/") + "/v1"
                        kwargs["api_key"] = "ollama"  # litellm requires a non-empty key
                    else:
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
                if top_p is not None:
                    kwargs["top_p"] = top_p

                # Anthropic prompt caching: convert system message and mark last
                # user message as cacheable to reduce costs on repeated context.
                if self._current_provider == "anthropic" or (
                    self._current_model and self._current_model.startswith("claude")
                ):
                    kwargs["extra_headers"] = {
                        "anthropic-beta": "prompt-caching-2024-07-31"
                    }
                    cached_msgs: list[dict[str, Any]] = []
                    for msg in kwargs["messages"]:
                        if msg.get("role") == "system":
                            raw = msg.get("content", "")
                            if isinstance(raw, str):
                                msg = {
                                    **msg,
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": raw,
                                            "cache_control": {"type": "ephemeral"},
                                        }
                                    ],
                                }
                        cached_msgs.append(msg)
                    # Mark the last user message (before any tool interaction) as
                    # cacheable so stable conversation history is reused from cache.
                    last_user_idx = None
                    for idx in range(len(cached_msgs) - 1, -1, -1):
                        if cached_msgs[idx].get("role") == "user":
                            last_user_idx = idx
                            break
                    if last_user_idx is not None:
                        u_msg = cached_msgs[last_user_idx]
                        raw_u = u_msg.get("content", "")
                        if isinstance(raw_u, str):
                            cached_msgs[last_user_idx] = {
                                **u_msg,
                                "content": [
                                    {
                                        "type": "text",
                                        "text": raw_u,
                                        "cache_control": {"type": "ephemeral"},
                                    }
                                ],
                            }
                        elif isinstance(raw_u, list) and raw_u:
                            # Already a content block list — attach cache_control to last block
                            new_blocks = list(raw_u)
                            new_blocks[-1] = {
                                **new_blocks[-1],
                                "cache_control": {"type": "ephemeral"},
                            }
                            cached_msgs[last_user_idx] = {**u_msg, "content": new_blocks}
                    kwargs["messages"] = cached_msgs

                # Inject extra model params (thinking mode, etc.) into litellm kwargs.
                # Gemini uses a native thinkingConfig (not the OpenAI-style thinking param).
                _LITELLM_STD = {"temperature", "max_tokens", "top_p", "model", "messages",
                                "stream", "tools", "tool_choice", "api_base", "api_key",
                                "extra_headers", "extra_body"}
                _model_lower = model.lower()
                for _ek, _ev in self._get_model_params().items():
                    if _ek in _LITELLM_STD or _ek in ("temperature", "max_tokens", "top_p"):
                        continue
                    if _ek == "thinking" and "gemini" in _model_lower:
                        # Gemini needs includeThoughts:True to expose the reasoning text
                        _budget = _ev.get("budget_tokens", 8000) if isinstance(_ev, dict) else 8000
                        _eb = kwargs.setdefault("extra_body", {})
                        _eb.setdefault("generationConfig", {})["thinkingConfig"] = {
                            "thinkingBudget": _budget,
                            "includeThoughts": True,
                        }
                    else:
                        kwargs[_ek] = _ev

                response = await asyncio.wait_for(
                    litellm.acompletion(**kwargs, drop_params=True),
                    timeout=_llm_timeout,
                )

                elapsed = time.time() - start_time

                # Extract response data
                choice = response.choices[0]
                message = choice.message

                api_pt = getattr(response.usage, "prompt_tokens", 0) or 0
                api_ct = getattr(response.usage, "completion_tokens", 0) or 0
                api_tt = getattr(response.usage, "total_tokens", 0) or 0

                # Some providers return 0 — count precisely with litellm token_counter
                if api_pt == 0:
                    api_pt = _count_tokens(model, messages=messages)
                if api_ct == 0:
                    out_text = (message.content or "") + "".join(
                        (tc.function.arguments or "") + (tc.function.name or "")
                        for tc in (getattr(message, "tool_calls", None) or [])
                    )
                    api_ct = _count_tokens(model, text=out_text) if out_text else 1
                if api_tt == 0:
                    api_tt = api_pt + api_ct

                _raw_content = message.content or ""
                # Extract reasoning from dedicated field or think tags in content
                _reasoning = (
                    getattr(message, "reasoning_content", None)
                    or getattr(message, "thinking_content", None)
                    or getattr(message, "thinking", None)
                    or ""
                )
                _raw_content, _reasoning = extract_and_strip_thinking(
                    _raw_content, existing_reasoning=_reasoning
                )

                result = {
                    "content": _raw_content,
                    "reasoning_content": _reasoning,
                    "tool_calls": [],
                    "usage": {
                        "prompt_tokens": api_pt,
                        "completion_tokens": api_ct,
                        "total_tokens": api_tt,
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
                            "type": "function",  # required by OpenAI spec; litellm uses this to build tool_use blocks for Anthropic
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ]

            # Track totals
            pt = result["usage"]["prompt_tokens"]
            ct = result["usage"]["completion_tokens"]
            pricing_key = self._pricing_model_key()
            cost = _estimate_cost(pricing_key, pt, ct)
            result["usage"]["cost"] = cost
            result["usage"]["elapsed_ms"] = int(result["elapsed"] * 1000)

            self._total_tokens += result["usage"]["total_tokens"]
            self._total_prompt_tokens += pt
            self._total_completion_tokens += ct
            self._total_cost += cost
            self._total_requests += 1

            await self.event_bus.emit(
                EVENT_LLM_RESPONSE,
                {
                    "model": model,
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                    "tokens": result["usage"]["total_tokens"],
                    "cost": cost,
                    "elapsed": result["elapsed"],
                    "has_tool_calls": bool(result["tool_calls"]),
                },
            )

            # Persist token usage so the dashboard can show historical stats
            if self._database:
                try:
                    await self._database.log_llm_usage(
                        model=pricing_key,
                        provider=self._current_provider,
                        prompt_tokens=pt,
                        completion_tokens=ct,
                        total_tokens=result["usage"]["total_tokens"],
                        elapsed_ms=int(result["elapsed"] * 1000),
                        cost=cost,
                    )
                except Exception:
                    pass  # Never block a response due to a DB write error

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
            error_msg = str(e) or repr(e) or type(e).__name__
            log.error("LLM request failed", model=model, error=error_msg, elapsed=f"{elapsed:.2f}s")
            raise

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        model_override: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream a chat completion response, yielding text chunks."""
        # Resolve per-model param defaults (config overrides hardcoded defaults)
        _mp = self._get_model_params()
        if temperature is None:
            temperature = float(_mp.get("temperature", 0.7))
        if max_tokens is None and _mp.get("max_tokens"):
            max_tokens = int(_mp["max_tokens"])
        _top_p: float | None = _mp.get("top_p") or None

        model = model_override if model_override else self._build_model_string()
        api_base = self._get_api_base()
        temperature = self._enforce_model_temperature(model, temperature)

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
        if _top_p is not None:
            kwargs["top_p"] = _top_p

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
            "total_prompt_tokens": self._total_prompt_tokens,
            "total_completion_tokens": self._total_completion_tokens,
            "total_cost": self._total_cost,
            "current_model": self.current_model,
            "current_provider": self._current_provider,
        }

    def get_usage_snapshot(self) -> dict[str, Any]:
        """Return a snapshot of cumulative usage counters (for delta computation)."""
        return {
            "prompt_tokens": self._total_prompt_tokens,
            "completion_tokens": self._total_completion_tokens,
            "total_tokens": self._total_tokens,
            "cost": self._total_cost,
            "requests": self._total_requests,
        }
