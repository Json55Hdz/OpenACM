"""Home Assistant Plugin — smart-home control via a running Home Assistant instance."""
from __future__ import annotations

from typing import Any

import structlog

from openacm.plugins import Plugin

log = structlog.get_logger()


_HOME_ASSISTANT_SKILL = """\
# Controlling Home Assistant

Golden rule: figure out the exact end state you want (which devices, which
attributes) and make **one** `ha_control` call that achieves all of it. Never
call once per device, and never call once per attribute (turn on, then set
color, then set brightness) — all of that belongs in the **same** call.

Use `ha_devices()` (or `ha_devices(area="Living Room")`) to look up real
`entity_id`s before guessing one — but only when you genuinely don't know the
name. If the user already told you which devices, or you just listed them,
don't list them again for the same task.

## `ha_control` — exact action names

| Domain | Actions | Params |
|---|---|---|
| Any domain | `turn_on`, `turn_off`, `toggle` (also accepts `on`/`off` as synonyms) | — |
| `light.*` | `set_brightness` | `brightness` 0-100 |
| `light.*` | `set_color_temp` | `kelvin` 2000-6500 |
| `light.*` | `set_color` | `red`/`green`/`blue`, 0-255 each |
| `climate.*` | `set_temperature` | `temperature` |
| `cover.*` | `open`, `close`, `stop` | — |
| `media_player.*` | `set_volume` | `volume` 0.0-1.0 |

There is no `dim`, `set`, or `activate` action — use exactly the names above.

## Combine turn-on + color + brightness in ONE call

`ha_control` accepts `red`/`green`/`blue`/`brightness`/`kelvin` **together
with** `action="turn_on"` (or `"toggle"`) — you don't need a separate
`action="set_color"` call. Correct example for "turn the office panels on in
green":

```
ha_control(entity_id="light.office_panel_1, light.office_panel_2, light.office_panel_3",
           action="turn_on", red=0, green=255, blue=0)
```

That's **one** call for 3 lights plus color, not six. Add `brightness=80` to
that same call if a specific brightness is also wanted.

## Multiple targets in one call

- `entity_id` accepts a single id, a list, or a comma-separated string — all
  three control everything in one real Home Assistant call:
  `ha_control(entity_id="light.living_room, switch.tv", action="turn_off")`
- A whole area works the same way, with `turn_on`/`turn_off`/`toggle` (plus
  color/brightness params if relevant):
  `ha_control(area="living_room", action="turn_off")`
- Domain-specific actions not combined with on/off (`set_temperature`,
  `open`/`close`/`stop`) need `entity_id` of the same type — `area` doesn't
  apply there.

## Do NOT re-check state immediately after controlling

`ha_control` tells you whether the call succeeded via a leading "✓" — TRUST
that. Do NOT call `ha_status`/`ha_devices` right after to "confirm" it
applied: the local state cache updates over WebSocket with a small delay, so
it can look like "nothing changed" even though it did, and you end up
repeating the same action unnecessarily. Checking is fine when the user
explicitly asks for current status — just don't make it part of the
turn-on/off/color-change flow itself.

## The `area` parameter is strict

`area` must match the exact area ID/slug in Home Assistant (Settings →
Areas), not how a person would casually say it. If you're not sure of the
exact slug, control `entity_id`s directly instead of guessing an `area`.

## Devices not covered by `ha_control` (vacuums, locks, etc.)

For domains `ha_control` doesn't cover (vacuums `vacuum.*`, locks `lock.*`,
fans `fan.*`, alarms, etc.):
1. `ha_list_services(domain)` to see what's actually available (e.g. `domain="vacuum"`).
2. `ha_call_service(entity_id, service, data={...})` to run it — `service` is
   **only** the service name (e.g. `"start"`, `"return_to_base"`), **never**
   with the domain prefixed (wrong: `"vacuum.start"`; right: `"start"`).

## Scenes

`ha_scenes()` to list, `ha_activate_scene(name)` to activate by name — don't
use `ha_control` for scenes.
"""


class HomeAssistantPlugin(Plugin):
    name = "home_assistant"
    version = "1.0.0"
    description = "Control smart-home devices through Home Assistant"
    author = "JsonProductions / OpenACM"

    def __init__(self):
        self._client = None

    # ── Config schema (Phase 1 dashboard config form) ───────────

    def get_config_schema(self) -> list[dict]:
        return [
            {
                "key": "ha_url",
                "label": "URL de Home Assistant",
                "type": "text",
                "required": True,
                "help": "ej. http://homeassistant.local:8123",
            },
            {
                "key": "ha_token",
                "label": "Long-Lived Access Token",
                "type": "password",
                "required": True,
                "help": "Genéralo desde tu perfil de usuario en Home Assistant.",
            },
        ]

    # ── Tools / API router / nav ─────────────────────────────────

    def get_tool_modules(self) -> list[Any]:
        from openacm.plugins.home_assistant import tools as _tools
        return [_tools]

    def get_api_router(self):
        from openacm.plugins.home_assistant import router as _r
        return _r.router

    def get_nav_items(self) -> list[dict]:
        return [
            {"path": "/home-assistant", "label": "Home Assistant", "icon": "Home", "section": "main"}
        ]

    def get_skills(self) -> list[dict]:
        return [
            {
                "name": "home-assistant-control",
                "description": "How to control Home Assistant devices correctly on the first try (exact action names, area targeting, multi-entity calls).",
                "category": "iot",
                "content": _HOME_ASSISTANT_SKILL,
            }
        ]

    def get_intent_keywords(self) -> dict[str, list[str]]:
        return {
            "iot": [
                "light", "lights", "luz", "luces", "lamp", "lampara", "bulb",
                "curtain", "curtains", "blind", "blinds", "persiana", "persianas",
                "cortina", "cortinas", "cover", "shutter",
                "switch", "enchufe", "plug", "outlet",
                "climate", "clima", "termostato", "thermostat", "temperatura",
                "home assistant", "domótica", "domotica", "casa inteligente",
                "smart home", "escena", "scene", "modo noche", "modo día",
                "turn on", "turn off", "enciende", "apaga", "encender", "apagar",
                "dim", "brightness", "brillo", "color", "temperatura de color",
                "open", "close", "abre", "cierra", "abrir", "cerrar",
                "volume", "volumen",
            ]
        }

    # ── Lifecycle ──────────────────────────────────────────────

    async def on_start(self, **app_context: Any) -> None:
        await super().on_start(**app_context)
        event_bus = app_context.get("event_bus")

        from openacm.plugins.home_assistant import tools as _tools_mod
        from openacm.plugins.home_assistant import router as _router_mod

        ha_url = await self.get_setting("ha_url", default="")
        ha_token = await self.get_setting("ha_token", default="")

        if not ha_url or not ha_token:
            log.info(
                "Home Assistant plugin loaded without configuration — "
                "inactive until /plugins is filled in"
            )
            return

        from openacm.plugins.home_assistant.client import HomeAssistantClient
        self._client = HomeAssistantClient(base_url=ha_url, token=ha_token, event_bus=event_bus)
        await self._client.fetch_states()
        self._client.start()

        _tools_mod._client = self._client
        _router_mod._client = self._client

        log.info("HomeAssistantPlugin started", url=ha_url)

    async def on_stop(self) -> None:
        if self._client:
            await self._client.stop()

        from openacm.plugins.home_assistant import tools as _tools_mod
        from openacm.plugins.home_assistant import router as _router_mod

        _tools_mod._client = None
        _router_mod._client = None
        self._client = None


PLUGIN = HomeAssistantPlugin()
