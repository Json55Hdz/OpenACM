"""Home Assistant Plugin — smart-home control via a running Home Assistant instance."""
from __future__ import annotations

from typing import Any

import structlog

from openacm.plugins import Plugin

log = structlog.get_logger()


_HOME_ASSISTANT_SKILL = """\
# Controlar Home Assistant

Usa `ha_devices()` para ver los `entity_id` reales antes de adivinar uno.

## `ha_control` — nombres de acción EXACTOS

- **Cualquier dispositivo:** `turn_on`, `turn_off`, `toggle` (también acepta `on`/`off` como sinónimos).
- **Luces (`light.*`):** `set_brightness` (param `brightness` 0-100), `set_color_temp` (param `kelvin` 2000-6500), `set_color` (params `red`/`green`/`blue` 0-255 cada uno).
- **Clima (`climate.*`):** `set_temperature` (param `temperature`).
- **Cortinas (`cover.*`):** `open`, `close`, `stop`.
- **Reproductores (`media_player.*`):** `set_volume` (param `volume` 0.0-1.0).

No existen acciones como `dim`, `set`, `activate` — usa exactamente los nombres de arriba.

## Áreas/habitaciones y dispositivos no cubiertos por `ha_control`

- `ha_areas()` lista las habitaciones configuradas; `ha_devices(area="Sala")` filtra por una de ellas.
- Para dominios que `ha_control` no cubre (aspiradoras `vacuum.*`, cerraduras `lock.*`, ventiladores `fan.*`, alarmas, etc.), usa primero `ha_list_services(domain)` para ver qué funciones existen realmente, y luego `ha_call_service(entity_id, service, data={...})` para ejecutarla — no adivines nombres de servicio.

## Varias cosas a la vez, en una sola llamada

- Una lista de `entity_id` (aunque sean de tipos distintos) funciona con `turn_on`/`turn_off`/`toggle`:
  `ha_control(entity_id=["light.sala", "switch.tv"], action="turn_off")`
- Un área completa funciona igual, solo con esas tres acciones genéricas:
  `ha_control(area="sala", action="turn_off")`
- Acciones específicas de dominio (`set_brightness`, etc.) necesitan `entity_id` del mismo tipo — `area` no aplica ahí.

## El parámetro `area` es sensible

`area` debe coincidir EXACTO con el ID/slug del área en Home Assistant (Configuración → Áreas), no con cómo lo diría una persona. Si no estás seguro del slug exacto, mejor controla los `entity_id` directamente en vez de adivinar un `area`.

## Escenas

`ha_scenes()` para listar, `ha_activate_scene(name)` para activar por nombre — no uses `ha_control` para escenas.
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
