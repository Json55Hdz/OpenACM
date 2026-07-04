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
        "(e.g. 'light', 'switch', 'climate', 'cover', 'media_player', 'vacuum') "
        "and/or by area/room name (use ha_areas() to see valid area names)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Filter by Home Assistant domain, e.g. 'light'. Empty = all.",
                "default": "",
            },
            "area": {
                "type": "string",
                "description": "Filter by area/room name, e.g. 'Sala'. Empty = all. See ha_areas().",
                "default": "",
            },
        },
        "required": [],
    },
    risk_level="low",
    category="iot",
)
async def ha_devices(domain: str = "", area: str = "", **kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    states = _client.list_states(domain=domain, area=area)
    if not states:
        scope = f" del tipo '{domain}'" if domain else ""
        scope += f" en el área '{area}'" if area else ""
        return f"No hay dispositivos{scope} registrados en Home Assistant."

    lines = [f"{len(states)} dispositivos:\n"]
    for s in states:
        name = s.get("attributes", {}).get("friendly_name", s["entity_id"])
        lines.append(f"  {s['entity_id']:30s}  {s['state']:12s}  {name}")
    return "\n".join(lines)


@tool(
    name="ha_areas",
    description="List Home Assistant areas/rooms (e.g. 'Sala', 'Cocina') for organizing/filtering devices by location.",
    parameters={"type": "object", "properties": {}, "required": []},
    risk_level="low",
    category="iot",
)
async def ha_areas(**kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    areas = _client.list_areas()
    if not areas:
        return "No hay áreas configuradas en Home Assistant."

    lines = ["Áreas disponibles:\n"]
    for a in areas:
        lines.append(f"  {a['name']}")
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

# Common shorthand an LLM reaches for before it's seen the exact accepted
# action names — normalize these instead of erroring and waiting for a retry.
_ACTION_ALIASES = {
    "on": "turn_on",
    "off": "turn_off",
    "switch_on": "turn_on",
    "switch_off": "turn_off",
}

# domain -> { verb: (ha_service, caller_param_name | None, ha_field_name | None) }
# Actions not in _GENERIC_ACTIONS need a single, consistent domain across all
# targeted entities so we know which service to call.
_DOMAIN_ACTIONS: dict[str, dict[str, tuple[str, str | None, str | None]]] = {
    "light": {
        "set_brightness": ("turn_on", "brightness", "brightness_pct"),
        "set_color_temp": ("turn_on", "kelvin", "color_temp_kelvin"),
        # set_color needs 3 values (red/green/blue) composed into rgb_color —
        # handled as a special case in ha_control, this entry only makes it
        # show up correctly in validation/availability messages.
        "set_color": ("turn_on", None, None),
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
        "open, close, stop (cover); set_volume (media_player, param 'volume' 0.0-1.0); "
        "set_color (light, params 'red'/'green'/'blue' 0-255 each). "
        "entity_id can be a single id, a list of ids, or use `area` to target every "
        "entity in a Home Assistant area at once (e.g. area='sala' turns off every "
        "device in the living room in one call) — area only works with turn_on/off/toggle. "
        "IMPORTANT: `area` must match the exact Home Assistant area ID/slug (see Settings → "
        "Areas in Home Assistant), not just its display name or how you'd say it out loud — "
        "a name that doesn't match an area silently matches zero entities and this tool will "
        "still report success even though nothing happened."
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
                "description": (
                    "Home Assistant area ID/slug to target every entity in it (only with "
                    "turn_on/turn_off/toggle). Use instead of entity_id. Must match the exact "
                    "area ID/slug as shown in Home Assistant's Settings → Areas — not just the "
                    "area's human-readable display name — otherwise the call silently matches "
                    "zero entities while still reporting success."
                ),
                "default": "",
            },
            "brightness": {"type": "integer", "description": "0-100, for set_brightness"},
            "kelvin": {"type": "integer", "description": "2000-6500, for set_color_temp"},
            "temperature": {"type": "number", "description": "Target temperature, for set_temperature"},
            "volume": {"type": "number", "description": "0.0-1.0, for set_volume"},
            "red": {"type": "integer", "description": "0-255, for set_color"},
            "green": {"type": "integer", "description": "0-255, for set_color"},
            "blue": {"type": "integer", "description": "0-255, for set_color"},
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
    red: int | None = None,
    green: int | None = None,
    blue: int | None = None,
    **kwargs,
) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    if not entity_id and not area:
        return "Debes indicar 'entity_id' o 'area'."

    normalized_action = action.strip().lower()
    action = _ACTION_ALIASES.get(normalized_action, normalized_action)

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

    if action == "set_color":
        if red is None or green is None or blue is None:
            return "La acción 'set_color' necesita los parámetros 'red', 'green' y 'blue' (0-255)."
        result = await _client.call_service("light", "turn_on", entity_id=ids, rgb_color=[red, green, blue])
        target_desc = ", ".join(ids)
        return f"✓ {action} aplicado a {target_desc}." if result["success"] else f"✗ {result['error']}"

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


@tool(
    name="ha_scenes",
    description="List Home Assistant scenes available to activate.",
    parameters={"type": "object", "properties": {}, "required": []},
    risk_level="low",
    category="iot",
)
async def ha_scenes(**kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    scenes = _client.list_states(domain="scene")
    if not scenes:
        return "No hay escenas configuradas en Home Assistant."

    lines = ["Escenas disponibles:\n"]
    for s in scenes:
        name = s.get("attributes", {}).get("friendly_name", s["entity_id"])
        lines.append(f"  {name}")
    return "\n".join(lines)


@tool(
    name="ha_activate_scene",
    description="Activate a Home Assistant scene by name, e.g. 'Modo Noche'.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Scene name or entity_id."},
        },
        "required": ["name"],
    },
    risk_level="low",
    category="iot",
)
async def ha_activate_scene(name: str, **kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    state = _client.find_entity(name)
    if state is None or not state["entity_id"].startswith("scene."):
        scenes = [
            s.get("attributes", {}).get("friendly_name", s["entity_id"])
            for s in _client.list_states(domain="scene")
        ]
        suggestion = f" Escenas disponibles: {', '.join(scenes)}" if scenes else ""
        return f"No encontré la escena '{name}'.{suggestion}"

    result = await _client.call_service("scene", "turn_on", entity_id=state["entity_id"])
    if result["success"]:
        friendly = state.get("attributes", {}).get("friendly_name", state["entity_id"])
        return f"✓ Escena '{friendly}' activada."
    return f"✗ {result['error']}"


@tool(
    name="ha_list_services",
    description=(
        "List the Home Assistant services/functions available for a domain "
        "(e.g. 'vacuum', 'fan', 'lock', 'alarm_control_panel') — use this to "
        "discover what a device type can do before calling ha_call_service, "
        "for anything not already covered by ha_control."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "HA domain, e.g. 'vacuum', 'fan', 'lock'."},
        },
        "required": ["domain"],
    },
    risk_level="low",
    category="iot",
)
async def ha_list_services(domain: str, **kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    services = await _client.list_services(domain=domain)
    if not services:
        return f"No encontré servicios para el dominio '{domain}'."

    lines = [f"Servicios de '{domain}':\n"]
    for key, meta in services.items():
        service_name = key.split(".", 1)[1]
        fields = ", ".join(meta["fields"]) if meta["fields"] else "sin parámetros"
        desc = meta.get("description") or meta.get("name") or ""
        lines.append(f"  {service_name}: {desc} ({fields})")
    return "\n".join(lines)


@tool(
    name="ha_call_service",
    description=(
        "Call ANY Home Assistant service directly by its exact name — use this "
        "for device types not already covered by ha_control (vacuum, fan, lock, "
        "alarm_control_panel, humidifier, etc.). Use ha_list_services(domain) "
        "first if you're not sure which service/fields to use."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Entity ID or friendly name."},
            "service": {"type": "string", "description": "Exact service name, e.g. 'start', 'return_to_base', 'lock'."},
            "data": {
                "type": "object",
                "description": "Extra fields the service needs, as a flat object, e.g. {'command': 'clean_zone'}.",
                "default": {},
            },
        },
        "required": ["entity_id", "service"],
    },
    risk_level="medium",
    category="iot",
)
async def ha_call_service(entity_id: str, service: str, data: dict | None = None, **kwargs) -> str:
    if _client is None:
        return _NOT_CONFIGURED_MSG

    state = _client.find_entity(entity_id)
    if state is None:
        return f"No encontré '{entity_id}'. Usa ha_devices() para ver los dispositivos disponibles."

    domain = state["entity_id"].split(".")[0]
    result = await _client.call_service(domain, service, entity_id=state["entity_id"], **(data or {}))
    if result["success"]:
        return f"✓ {service} aplicado a {state['entity_id']}."
    return f"✗ {result['error']}"
