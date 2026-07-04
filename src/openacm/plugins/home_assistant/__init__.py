"""Home Assistant Plugin — smart-home control via a running Home Assistant instance."""
from __future__ import annotations

from typing import Any

import structlog

from openacm.plugins import Plugin

log = structlog.get_logger()


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


PLUGIN = HomeAssistantPlugin()
