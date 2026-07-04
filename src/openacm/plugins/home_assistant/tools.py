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


_GENERIC_ACTIONS = {"turn_on", "turn_off", "toggle"}

# domain -> { verb: (ha_service, caller_param_name | None, ha_field_name | None) }
# Actions not in _GENERIC_ACTIONS need a single, consistent domain across all
# targeted entities so we know which service to call.
_DOMAIN_ACTIONS: dict[str, dict[str, tuple[str, str | None, str | None]]] = {
    "light": {
        "set_brightness": ("turn_on", "brightness", "brightness_pct"),
        "set_color_temp": ("turn_on", "kelvin", "color_temp_kelvin"),
    },
    "climate": {
        "set_temperature": ("set_temperature", "temperature", "temperature"),
    },
    "cover": {
        "open": ("open_cover", None, None),
        "close": ("close_cover", None, None),
        "stop": ("stop_cover", None, None),
    },
    "media_player": {
        "set_volume": ("volume_set", "volume", "volume_level"),
    },
}


@tool(
    name="ha_control",
    description=(
        "Control one or more Home Assistant entities. Actions: turn_on, turn_off, "
        "toggle (any domain, can target multiple entities or a whole area at once); "
        "set_brightness (light, param 'brightness' 0-100); "
        "set_color_temp (light, param 'kelvin' 2000-6500); "
        "set_temperature (climate, param 'temperature'); "
        "open, close, stop (cover); set_volume (media_player, param 'volume' 0.0-1.0). "
        "entity_id can be a single id, a list of ids, or use `area` to target every "
        "entity in a Home Assistant area at once (e.g. area='sala' turns off every "
        "device in the living room in one call) — area only works with turn_on/off/toggle."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "description": "Entity ID or list of entity IDs, e.g. 'light.sala' or ['light.sala', 'light.cocina']. Omit if using 'area'.",
            },
            "action": {
                "type": "string",
                "description": "turn_on, turn_off, toggle, set_brightness, set_color_temp, set_temperature, open, close, stop, set_volume",
            },
            "area": {
                "type": "string",
                "description": "Home Assistant area name to target every entity in it (only with turn_on/turn_off/toggle). Use instead of entity_id.",
                "default": "",
            },
            "brightness": {"type": "integer", "description": "0-100, for set_brightness"},
            "kelvin": {"type": "integer", "description": "2000-6500, for set_color_temp"},
            "temperature": {"type": "number", "description": "Target temperature, for set_temperature"},
            "volume": {"type": "number", "description": "0.0-1.0, for set_volume"},
        },
        "required": ["action"],
    },
    risk_level="low",
    category="iot",
)
async def ha_control(
    entity_id: str | list[str] | None = None,
    action: str = "",
    area: str = "",
    brightness: int | None = None,
    kelvin: int | None = None,
    temperature: float | None = None,
    volume: float | None = None,
    **kwargs,
) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    if not entity_id and not area:
        return "Debes indicar 'entity_id' o 'area'."

    caller_params = {"brightness": brightness, "kelvin": kelvin, "temperature": temperature, "volume": volume}

    ids: list[str] = []
    if entity_id:
        raw_ids = entity_id if isinstance(entity_id, list) else [entity_id]
        for raw in raw_ids:
            state = _client.find_entity(raw)
            if state is None:
                return f"No encontré '{raw}'. Usa ha_devices() para ver los dispositivos disponibles."
            ids.append(state["entity_id"])

    if action in _GENERIC_ACTIONS:
        if ids:
            result = await _client.call_service("homeassistant", action, entity_id=ids)
            target_desc = ", ".join(ids)
        else:
            result = await _client.call_service("homeassistant", action, area_id=area)
            target_desc = f"área '{area}'"
        return f"✓ {action} aplicado a {target_desc}." if result["success"] else f"✗ {result['error']}"

    if not ids:
        return f"La acción '{action}' necesita 'entity_id' (no funciona solo con 'area')."

    domains = {i.split(".")[0] for i in ids}
    if len(domains) > 1:
        return f"'{action}' necesita que todas las entidades sean del mismo tipo (encontré: {', '.join(sorted(domains))})."
    domain = domains.pop()

    domain_actions = _DOMAIN_ACTIONS.get(domain, {})
    if action not in domain_actions:
        available = ", ".join(sorted(_GENERIC_ACTIONS | set(domain_actions)))
        return f"'{action}' no es válido para '{domain}'. Acciones disponibles: {available}."

    service, caller_key, ha_key = domain_actions[action]
    data: dict[str, Any] = {}
    if caller_key:
        value = caller_params.get(caller_key)
        if value is None:
            return f"La acción '{action}' necesita el parámetro '{caller_key}'."
        data[ha_key] = value

    result = await _client.call_service(domain, service, entity_id=ids, **data)
    target_desc = ", ".join(ids)
    return f"✓ {action} aplicado a {target_desc}." if result["success"] else f"✗ {result['error']}"
