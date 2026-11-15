"""Token counting and cost estimation (pricing table in USD per 1M tokens)."""
import structlog

import litellm

log = structlog.get_logger()


# ── Token pricing table (USD per 1M tokens) ─────────────────────────────────
# Format: model_prefix_lowercase → (input_price, output_price)
def _count_tokens(model: str, messages: list | None = None, text: str | None = None) -> int:
    """
    Count tokens using LiteLLM's token_counter (wraps tiktoken + model-specific
    tokenizers for Claude, Gemini, etc.).  Falls back to char/4 if unavailable.

    Pass `messages` to count a full prompt (system + history + tools).
    Pass `text` to count a completion string.
    """
    try:
        if messages is not None:
            return litellm.token_counter(model=model, messages=messages)
        if text is not None:
            return litellm.token_counter(model=model, text=text)
    except Exception:
        pass
    # Hard fallback: ~4 chars per token (works for English/code, rough for other langs)
    src = (text or "") if text else "".join(
        (m.get("content") or "") if isinstance(m.get("content"), str)
        else "".join(p.get("text", "") for p in (m.get("content") or []) if isinstance(p, dict))
        for m in (messages or [])
    )
    return max(1, len(src) // 4)


# Maps internal provider names → litellm pricing prefix
_PROVIDER_PRICING_PREFIX: dict[str, str] = {
    "anthropic": "anthropic",
    "gemini": "gemini",
    "openrouter": "openrouter",
    "xai": "xai",
    "deepinfra": "deepinfra",
    "fireworks": "fireworks_ai",
    "together": "together_ai",
    "groq": "groq",
    "mistral": "mistral",
    "cohere": "cohere",
    "perplexity": "perplexity",
    "vertex_ai": "vertex_ai",
    "bedrock": "bedrock",
    "azure": "azure",
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated USD cost using LiteLLM's built-in pricing database.

    Lookup order:
    1. Exact key (e.g. 'xai/grok-3-beta' or 'anthropic/claude-sonnet-4-6')
    2. Bare model name (e.g. 'grok-4o', 'gpt-4o')
    3. Suffix match for any key ending with '/<bare_name>'
       — catches custom-provider models like kimi-k2.5 → azure_ai/kimi-k2.5
    """
    try:
        bare = model.split("/")[-1] if "/" in model else model
        pricing = litellm.model_cost.get(model) or litellm.model_cost.get(bare)
        if not pricing:
            suffix = f"/{bare}"
            for k, v in litellm.model_cost.items():
                if k.endswith(suffix):
                    pricing = v
                    break
        if pricing:
            return (
                pricing.get("input_cost_per_token", 0.0) * prompt_tokens
                + pricing.get("output_cost_per_token", 0.0) * completion_tokens
            )
    except Exception:
        pass
    log.debug("No pricing data for model — cost reported as 0", model=model)
    return 0.0
