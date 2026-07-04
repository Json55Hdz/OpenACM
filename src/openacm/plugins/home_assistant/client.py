"""Home Assistant Client — REST + WebSocket wrapper around a Home Assistant instance.

No device-specific driver code — Home Assistant's own domain/service model
(light.turn_on, climate.set_temperature, ...) is the abstraction layer this
client exposes as-is.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

import httpx
import structlog

log = structlog.get_logger()


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str, event_bus: Any = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.event_bus = event_bus
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
        self._states: dict[str, dict[str, Any]] = {}
        self._ws_task: asyncio.Task | None = None
        self._stop = False

    # ── REST ─────────────────────────────────────────────────────

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str | list[str] | None = None,
        area_id: str | None = None,
        **data: Any,
    ) -> dict[str, Any]:
        """Call a Home Assistant service. Never raises — always returns
        {"success": True, "result": [...]} or {"success": False, "error": "..."}.
        """
        target: dict[str, Any] = {}
        if entity_id:
            target["entity_id"] = entity_id
        if area_id:
            target["area_id"] = area_id

        try:
            resp = await self._http.post(
                f"/api/services/{domain}/{service}", json={**target, **data}
            )
        except httpx.HTTPError as exc:
            return {"success": False, "error": f"No se pudo conectar a Home Assistant: {exc}"}

        if resp.status_code == 401:
            return {
                "success": False,
                "error": "Token de Home Assistant inválido o expirado. Actualízalo en /plugins.",
            }
        if resp.status_code >= 400:
            return {"success": False, "error": f"Home Assistant respondió {resp.status_code}: {resp.text}"}

        try:
            result = resp.json()
        except ValueError as exc:
            return {"success": False, "error": f"Home Assistant returned non-JSON 2xx response: {exc}"}
        return {"success": True, "result": result}

    async def fetch_states(self) -> list[dict[str, Any]]:
        """Seed/refresh the in-memory state cache from GET /api/states."""
        try:
            resp = await self._http.get("/api/states")
        except httpx.HTTPError as exc:
            log.warning("HA fetch_states failed", error=str(exc))
            return []
        if resp.status_code != 200:
            log.warning("HA fetch_states non-200", status=resp.status_code)
            return []
        states = resp.json()
        for s in states:
            self._states[s["entity_id"]] = s
        return states

    # ── Cache reads ──────────────────────────────────────────────

    def get_state(self, entity_id: str) -> dict[str, Any] | None:
        return self._states.get(entity_id)

    def list_states(self, domain: str = "") -> list[dict[str, Any]]:
        states = list(self._states.values())
        if domain:
            states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]
        return states

    def find_entity(self, name_or_id: str) -> dict[str, Any] | None:
        """Exact entity_id match first, then case-insensitive friendly_name/partial-id match."""
        if name_or_id in self._states:
            return self._states[name_or_id]
        q = name_or_id.lower()
        for state in self._states.values():
            friendly = state.get("attributes", {}).get("friendly_name", "")
            if q == friendly.lower() or q in state["entity_id"].lower():
                return state
        return None

    # ── WebSocket (real-time) ────────────────────────────────────

    def start(self) -> None:
        """Start the background WebSocket listener (fetches initial state
        itself once connected)."""
        self._stop = False
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def stop(self) -> None:
        self._stop = True
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        result = self._http.aclose()
        if inspect.isawaitable(result):
            await result

    async def _ws_loop(self) -> None:
        import websockets

        ws_url = (
            self.base_url.replace("http://", "ws://").replace("https://", "wss://")
            + "/api/websocket"
        )
        backoff = 5

        while not self._stop:
            try:
                async with websockets.connect(ws_url) as ws:
                    await ws.recv()  # auth_required
                    await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                    auth_result = json.loads(await ws.recv())
                    if auth_result.get("type") != "auth_ok":
                        log.warning("HA WebSocket auth failed — not retrying", result=auth_result)
                        return

                    await self.fetch_states()
                    backoff = 5

                    await ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
                    await ws.recv()  # subscription ack

                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("type") != "event":
                            continue
                        event_data = msg.get("event", {}).get("data", {})
                        new_state = event_data.get("new_state")
                        entity_id = event_data.get("entity_id")
                        if not entity_id or new_state is None:
                            continue
                        self._states[entity_id] = new_state
                        if self.event_bus:
                            await self.event_bus.emit("ha:state_changed", {
                                "entity_id": entity_id,
                                "state": new_state,
                            })
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("HA WebSocket error, reconnecting", error=str(exc), wait=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
