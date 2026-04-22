"""
Set Workspace Tool — lets the AI pin a working directory for the current conversation.
"""

from pathlib import Path

from openacm.tools.base import tool


@tool(
    name="set_workspace",
    description=(
        "Pin a working directory for this conversation. "
        "After calling this, ALL file operations will use the given path by default. "
        "Call with action='clear' to revert to the global default. "
        "Call with action='show' to see the current pinned workspace."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to use as workspace. Required when action='set'.",
            },
            "action": {
                "type": "string",
                "enum": ["set", "show", "clear"],
                "description": "'set' (default) pins the path, 'show' displays the current one, 'clear' removes the pin.",
                "default": "set",
            },
        },
        "required": [],
    },
    risk_level="low",
    category="system",
)
async def set_workspace(
    path: str = "",
    action: str = "set",
    **kwargs,
) -> str:
    brain = kwargs.get("_brain")
    user_id = kwargs.get("_user_id", "")
    channel_id = kwargs.get("_channel_id", "")

    if brain is None:
        return "Error: brain context not available."

    mem = brain.memory
    prompt_cache_key = f"{channel_id}:{user_id}"

    if action == "show":
        current = mem.get_conversation_workspace(user_id, channel_id)
        if current:
            return f"Current workspace for this conversation: {current}"
        from openacm.core.acm_context import _resolve_workspace
        return f"No workspace pinned. Global default: {_resolve_workspace()}"

    if action == "clear":
        mem.clear_conversation_workspace(user_id, channel_id)
        brain._system_prompt_hash.pop(prompt_cache_key, None)
        from openacm.core.acm_context import _resolve_workspace
        return f"Workspace pin removed. Back to global default: {_resolve_workspace()}"

    # action == "set"
    if not path:
        return "Error: 'path' is required when action is 'set'."

    resolved = str(Path(path).resolve())
    mem.set_conversation_workspace(user_id, channel_id, resolved)
    # Bust the prompt cache so the new workspace appears on the very next message
    brain._system_prompt_hash.pop(prompt_cache_key, None)
    return f"Workspace set to: {resolved}\nAll file operations in this conversation will use this path."
