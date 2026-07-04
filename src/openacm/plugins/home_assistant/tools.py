"""Home Assistant Tools — AI interface for smart-home control via Home Assistant.

_client is None until HomeAssistantPlugin.on_start() sets it (once the user
has configured ha_url/ha_token from the /plugins dashboard).
"""
from __future__ import annotations

from typing import Any

from openacm.tools.base import tool

_client: Any = None

_NOT_CONFIGURED_MSG = "Home Assistant no está configurado. Configúralo desde el dashboard en /plugins."


@tool(
    name="ha_devices",
    description=(
        "List Home Assistant entities (lights, switches, climate, covers, "
        "media players, etc.), optionally filtered by domain "
        "(e.g. 'light', 'switch', 'climate', 'cover', 'media_player', 'vacuum')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Filter by Home Assistant domain, e.g. 'light'. Empty = all.",
                "default": "",
            },
        },
        "required": [],
    },
    risk_level="low",
    category="iot",
)
async def ha_devices(domain: str = "", **kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    states = _client.list_states(domain=domain)
    if not states:
        scope = f" del tipo '{domain}'" if domain else ""
        return f"No hay dispositivos{scope} registrados en Home Assistant."

    lines = [f"{len(states)} dispositivos:\n"]
    for s in states:
        name = s.get("attributes", {}).get("friendly_name", s["entity_id"])
        lines.append(f"  {s['entity_id']:30s}  {s['state']:12s}  {name}")
    return "\n".join(lines)


@tool(
    name="ha_status",
    description=(
        "Get the current state and attributes of one Home Assistant entity. "
        "Accepts an exact entity_id (e.g. 'light.sala') or a friendly name (e.g. 'Luz Sala')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Entity ID or friendly name."},
        },
        "required": ["entity_id"],
    },
    risk_level="low",
    category="iot",
)
async def ha_status(entity_id: str, **kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    state = _client.find_entity(entity_id)
    if state is None:
        candidates = [s["entity_id"] for s in _client.list_states()][:8]
        suggestion = f" ¿Quisiste decir uno de estos? {', '.join(candidates)}" if candidates else ""
        return f"No encontré '{entity_id}'.{suggestion}"

    name = state.get("attributes", {}).get("friendly_name", state["entity_id"])
    attrs = {k: v for k, v in state.get("attributes", {}).items() if k != "friendly_name"}
    return f"{name} ({state['entity_id']}): {state['state']}\nAtributos: {attrs}"
