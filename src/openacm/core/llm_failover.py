"""
Failover between models.

If the model a request was meant for is down (outage, rate limit, bad key, network), the same
request is tried on the next model of the owner's fallback list instead of failing the whole turn.
A provider that just failed is skipped for a short, growing cool-down so a dead provider does not
cost every message its full retry wait.

Only calls that did not name an explicit model (``model_override``, used by swarm workers with a
chosen model) fail over: a caller that asked for a specific model gets that model or the error.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import structlog

log = structlog.get_logger()

COOLDOWN_BASE_S = 30
COOLDOWN_MAX_S = 300
# Fewer retries on a model that has a fallback behind it: the next model is a better use of the wait
RETRIES_WITH_FALLBACK = 2

_SECRET_PATTERNS = re.compile(
    "|".join([
        r"(?:sk|gsk|xai|pk|rk)[-_][A-Za-z0-9_\-]{8,}",          # provider key prefixes
        r"AIza[0-9A-Za-z_\-]{20,}",                              # Google API keys
        r"Bearer\s+\S+",
        r"(?i:(?:x-)?api[-_]?key|token|authorization|secret|password|passwd)[\"'\s]*[=:][\"'\s]*[^\s,;\"'&]{4,}",
        r"://[^/\s:@]+:[^/\s@]+@",                             # user:password@ in a URL
        r"[?&][^=\s&]{1,40}=[^\s&\"']{1,200}",                  # URL query strings (keys travel there)
        r"[A-Za-z0-9_\-]{32,}",                           # any long token-looking string
    ])
)


def _known_secret_values() -> list[str]:
    """The real key/token values configured in this process: they must never be stored."""
    import os

    markers = ("KEY", "TOKEN", "SECRET", "PASSWORD")
    return [v for k, v in os.environ.items() if v and len(v) >= 8 and any(m in k.upper() for m in markers)]


def scrub_error(text: str, limit: int = 300) -> str:
    """An error message that is safe to store and show: no keys, tokens, URL credentials or query
    strings, and none of the secret values configured in the environment; short."""
    out = str(text)
    for value in _known_secret_values():
        out = out.replace(value, "[hidden]")
    return _SECRET_PATTERNS.sub("[hidden]", out)[:limit]


class FailoverMixin:
    """Mixed into LLMRouter. Needs: routes, _chat, _route_override, _base_provider, _base_model,
    event_bus, _database."""

    def _health_state(self) -> dict[str, dict[str, float]]:
        if not hasattr(self, "_provider_health"):
            self._provider_health: dict[str, dict[str, float]] = {}
        return self._provider_health

    def _cooling(self, provider: str) -> bool:
        return self._health_state().get(provider, {}).get("until", 0) > time.time()

    def _mark_ok(self, provider: str) -> None:
        self._health_state().pop(provider, None)

    def _mark_failed(self, provider: str, exc: BaseException) -> None:
        state = self._health_state().setdefault(provider, {"fails": 0, "until": 0})
        state["fails"] += 1
        state["until"] = time.time() + min(COOLDOWN_MAX_S, COOLDOWN_BASE_S * 2 ** (state["fails"] - 1))
        state["last_error_at"] = time.time()

    def provider_health(self) -> dict[str, Any]:
        now = time.time()
        return {
            p: {"fails": int(s["fails"]), "cooling_for_s": max(0, int(s["until"] - now))}
            for p, s in self._health_state().items()
        }

    def _fallback_chain(self, primary: tuple[str, str | None] | None) -> list[tuple[str, str | None]]:
        """The owner's fallbacks, minus the model the request is already going to."""
        effective = primary or (self._base_provider, self._base_model)
        out: list[tuple[str, str | None]] = []
        for fb in self.routes.fallbacks():
            cand = (fb["provider"], fb.get("model") or None)
            if cand == effective or cand in out:
                continue
            out.append(cand)
        return out

    async def _chat_with_failover(
        self, primary: tuple[str, str | None] | None, role: str | None, args: tuple, kwargs: dict
    ) -> dict[str, Any]:
        from openacm.core.llm_router import _route_override

        chain: list[tuple[str, str | None] | None] = [primary, *self._fallback_chain(primary)]
        last_exc: BaseException | None = None

        for i, cand in enumerate(chain):
            is_last = i == len(chain) - 1
            provider = cand[0] if cand else self._base_provider
            if not is_last and self._cooling(provider):
                log.info("Skipping a model that failed recently", provider=provider)
                continue

            kw = dict(kwargs)
            if not is_last:
                kw.setdefault("max_retries", RETRIES_WITH_FALLBACK)
            token = _route_override.set(cand) if cand else None
            try:
                model_name = self.current_model
                result = await self._chat(*args, **kw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self._mark_failed(provider, exc)
                nxt = next((c for c in chain[i + 1:]), None) if not is_last else None
                await self._record_error(provider, model_name, role, exc, nxt)
                continue
            finally:
                if token is not None:
                    _route_override.reset(token)

            self._mark_ok(provider)
            if i > 0 or (last_exc is not None):
                await self.event_bus.emit("llm.failover", {
                    "used": f"{provider}/{model_name}", "role": role,
                    "reason": scrub_error(last_exc, 120) if last_exc else "skipped (cooling down)",
                })
            return result

        assert last_exc is not None
        raise last_exc

    async def _record_error(self, provider: str, model: str, role: str | None,
                            exc: BaseException, nxt: tuple[str, str | None] | None) -> None:
        log.warning("LLM call failed", provider=provider, model=model, error=scrub_error(exc, 200),
                    failing_over_to=(f"{nxt[0]}/{nxt[1] or 'default'}" if nxt else None))
        db = getattr(self, "_database", None)
        if db is None:
            return
        try:
            await db.log_llm_error(
                provider=provider, model=str(model or ""), role=role or "",
                error_class=type(exc).__name__, message=scrub_error(exc),
                failover_to=(f"{nxt[0]}/{nxt[1] or 'default'}" if nxt else ""),
            )
        except Exception:  # noqa: BLE001  never let monitoring break a request
            pass
