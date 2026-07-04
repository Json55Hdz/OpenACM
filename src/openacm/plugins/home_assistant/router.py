"""Home Assistant — FastAPI router for the /home-assistant dashboard page."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/home-assistant", tags=["home-assistant"])

# Set by HomeAssistantPlugin.on_start()
_client: Any = None


def _require_client():
    if _client is None:
        raise HTTPException(status_code=503, detail="Home Assistant no está configurado")
    return _client


@router.get("/devices")
async def list_devices(domain: str = "", area: str = ""):
    client = _require_client()
    return {"devices": client.list_states(domain=domain, area=area)}


@router.get("/areas")
async def list_areas():
    client = _require_client()
    return {"areas": client.list_areas()}


@router.post("/devices/{entity_id}/control")
async def control_device(entity_id: str, body: dict):
    client = _require_client()
    action = body.get("action", "")
    if not action:
        raise HTTPException(status_code=400, detail="Falta 'action'")

    domain = entity_id.split(".")[0]
    service = body.get("service", action)
    data = {k: v for k, v in body.items() if k not in ("action", "service")}

    result = await client.call_service(domain, service, entity_id=entity_id, **data)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result["error"])
    return {"status": "ok"}


@router.get("/scenes")
async def list_scenes():
    client = _require_client()
    return {"scenes": client.list_states(domain="scene")}


@router.post("/scenes/{entity_id}/activate")
async def activate_scene(entity_id: str):
    client = _require_client()
    result = await client.call_service("scene", "turn_on", entity_id=entity_id)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result["error"])
    return {"status": "ok"}
