"""
Fast-path handler registry for the LocalRouter.

Each handler is an async function registered to a specific intent.
Brain._execute_fast_path() looks up the handler and calls it directly,
bypassing the cloud LLM entirely.

To add support for a new intent, just write a new function:

    @register("MY_NEW_INTENT")
    async def handle_my_new_intent(brain, message, user_id, channel_id, channel_type):
        result = await brain.tool_registry.execute(...)
        return f"Done: {result}"   # return None to fall back to the LLM

That's it. No if/else to touch anywhere else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

import structlog

if TYPE_CHECKING:
    from openacm.core.brain import Brain

log = structlog.get_logger()

# intent → async handler function
_REGISTRY: dict[str, Callable[..., Awaitable[str | None]]] = {}

# ── App keyword → Windows shell command ────────────────────────────────────
APP_COMMANDS: dict[str, str] = {
    "chrome":      "start chrome",
    "google":      "start chrome https://google.com",
    "gugel":       "start chrome https://google.com",
    "firefox":     "start firefox",
    "edge":        "start msedge",
    "spotify":     "start spotify",
    "discord":     "start discord",
    "whatsapp":    "start whatsapp",
    "telegram":    "start telegram",
    "notepad":     "start notepad",
    "excel":       "start excel",
    "word":        "start winword",
    "powerpoint":  "start powerpnt",
    "vscode":      "code",
    "vs code":     "code",
    "explorer":    "explorer .",
    "calculadora": "start calc",
    "calculator":  "start calc",
    "paint":       "start mspaint",
}

# ── Media keyword → shell command ──────────────────────────────────────────
MEDIA_COMMANDS: dict[str, str] = {
    "spotify":  "start spotify",
    "youtube":  "start chrome https://www.youtube.com",
    "música":   "start spotify",
    "musica":   "start spotify",
    "music":    "start spotify",
    "canción":  "start spotify",
    "cancion":  "start spotify",
    "song":     "start spotify",
}


def register(intent: str):
    """Decorator that registers a function as the fast-path handler for an intent."""
    def decorator(fn: Callable[..., Awaitable[str | None]]):
        _REGISTRY[intent] = fn
        return fn
    return decorator


async def dispatch(
    intent: str,
    brain: "Brain",
    message: str,
    user_id: str,
    channel_id: str,
    channel_type: str,
) -> str | None:
    """
    Look up and call the handler for the given intent.

    Priority:
      1. Learned action (exact phrase → concrete tool call, no LLM needed)
      2. Registered intent handler (heuristic fallback)

    Returns the response string, or None to fall back to the LLM.
    """
    # ── 1. Learned action lookup ──────────────────────────────────────────
    learned = brain.local_router.lookup_action(message)
    if learned:
        try:
            result = await brain.tool_registry.execute(
                learned["tool"], learned["args"], user_id, channel_id, _brain=brain
            )
            return learned.get("response") or "✅ Listo."
        except Exception as e:
            log.warning("Fast-path: learned action failed, trying handler", error=str(e))

    # ── 2. Registered intent handler ─────────────────────────────────────
    handler = _REGISTRY.get(intent)
    if handler is None:
        return None
    try:
        return await handler(brain, message, user_id, channel_id, channel_type)
    except Exception as e:
        log.warning("Fast-path handler error", intent=intent, error=str(e))
        return None


# ── Handlers ───────────────────────────────────────────────────────────────

@register("SYSTEM_INFO")
async def handle_system_info(
    brain: "Brain", message: str, user_id: str, channel_id: str, channel_type: str
) -> str | None:
    raw = await brain.tool_registry.execute(
        "system_info", {"detail": "summary"}, user_id, channel_id, _brain=brain
    )
    return f"Aquí está el resumen del sistema:\n\n{raw}"


@register("SCREENSHOT")
async def handle_screenshot(
    brain: "Brain", message: str, user_id: str, channel_id: str, channel_type: str
) -> str | None:
    raw = await brain.tool_registry.execute(
        "take_screenshot", {}, user_id, channel_id, _brain=brain
    )
    return f"Captura tomada. {raw}"


@register("OPEN_APP")
async def handle_open_app(
    brain: "Brain", message: str, user_id: str, channel_id: str, channel_type: str
) -> str | None:
    msg_lower = message.lower()
    matched = next((k for k in APP_COMMANDS if k in msg_lower), None)
    if matched is None:
        return None  # Unknown app → let the LLM figure it out

    cmd = APP_COMMANDS[matched]
    await brain.tool_registry.execute(
        "run_command", {"command": cmd}, user_id, channel_id, _brain=brain
    )
    return f"Abriendo {matched.title()}..."


@register("PLAY_MEDIA")
async def handle_play_media(
    brain: "Brain", message: str, user_id: str, channel_id: str, channel_type: str
) -> str | None:
    msg_lower = message.lower()
    cmd = next(
        (v for k, v in MEDIA_COMMANDS.items() if k in msg_lower),
        "start spotify",  # sensible default
    )
    await brain.tool_registry.execute(
        "run_command", {"command": cmd}, user_id, channel_id, _brain=brain
    )
    return "¡Dale! Abriendo la música..."
