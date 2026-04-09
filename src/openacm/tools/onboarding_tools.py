"""
onboarding_tools.py - Tools to manage the initial user profile interview.
"""

import yaml
from pathlib import Path
import structlog
from openacm.tools.base import tool
from openacm.core.config import _find_project_root

log = structlog.get_logger()

@tool(
    name="save_user_profile",
    description=(
        "Permanently configures the basic behavior of the system and ends Onboarding mode. "
        "Use this tool ONLY ONCE the user has told you their name, the name they want to call you, "
        "and how they want you to behave."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_name": {
                "type": "string",
                "description": "The user's name."
            },
            "assistant_name": {
                "type": "string",
                "description": "The new name the user wants to give you (if provided). Use 'OpenACM' if they didn't specify one."
            },
            "behaviors": {
                "type": "string",
                "description": "The permanent instructions that will guide your personality and behavior (e.g. 'Always speak briefly, politely, and use pirate slang')."
            }
        },
        "required": ["user_name", "assistant_name", "behaviors"],
    },
    risk_level="low",
    needs_sandbox=False,
    category="system",
)
async def save_user_profile(user_name: str, assistant_name: str, behaviors: str, **kwargs) -> str:
    """Save the user's profile and configure the assistant."""
    import re
    _brain = kwargs.get("_brain")

    # Sanitization
    behaviors = behaviors.strip()[:1000]
    user_name = user_name.strip()[:100]
    assistant_name = assistant_name.strip()[:100] or "OpenACM"

    # Guardar en VectorDB para prioridad histórica
    try:
        from openacm.core.rag import _rag_engine
        if _rag_engine and getattr(_rag_engine, "is_ready", getattr(_rag_engine, "_ready", False)):
            note = (
                f"USER CORE PROFILE:\n"
                f"Human's name: {user_name}\n"
                f"My name as an assistant: {assistant_name}\n"
                f"Personality rules / Behavior Invariants: {behaviors}"
            )
            await _rag_engine.remember(note)
    except Exception as e:
        log.error("Failed to save profile to RAG", error=str(e))

    # Guardar en config.yaml permanentemente
    root = _find_project_root()
    config_file = root / "config" / "default.yaml"
    
    data = {}
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            log.error("Failed to read config", error=str(e))
    
    # Manejar estructura A (Assistant)
    assistant_config = data.get("A", {})
    assistant_config["name"] = assistant_name
    assistant_config["onboarding_completed"] = True

    # Get the base system prompt: prefer A.system_prompt, fall back to assistant.system_prompt
    base_section = data.get("assistant", {})
    original_prompt = (
        assistant_config.get("system_prompt")
        or base_section.get("system_prompt")
        or "You are a helpful AI assistant."
    )

    # Remove any existing behavior/name block if Onboarding is run twice
    original_prompt = re.sub(r"\n\n\[USER INSTRUCTIONS - BEHAVIOR MODE\].*$", "", original_prompt, flags=re.DOTALL)

    # Replace any "You are <name>" opener so the assistant uses its new name
    original_prompt = re.sub(r"^You are \w[\w\s]*,", f"You are {assistant_name},", original_prompt)

    new_prompt = original_prompt + f"\n\n[USER INSTRUCTIONS - BEHAVIOR MODE]: My user's name is {user_name}. You must try to adhere to this personality ALWAYS: {behaviors}"
    
    assistant_config["system_prompt"] = new_prompt
    data["A"] = assistant_config

    config_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        return f"Error al guardar la configuración local: {e}"

    # Try to update the active config in memory dynamically (field by field to prevent losing refs)
    try:
        from openacm.web.server import _config
        if _config and _brain:
            _config.assistant.name = assistant_name
            _config.assistant.onboarding_completed = True
            _config.assistant.system_prompt = new_prompt
            _brain.config.name = assistant_name
            _brain.config.onboarding_completed = True
            _brain.config.system_prompt = new_prompt
    except Exception:
        pass

    return (
        f"User profile saved successfully! You are now {assistant_name}. "
        f"The user is {user_name} and your behavior is modified. "
        "Onboarding is concluded. Reply briefly that the setup was a success and you are ready for action."
    )

__all__ = ["save_user_profile"]
