"""Unit tests for the Home Assistant router endpoints."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from openacm.plugins.home_assistant import router as ha_router


@pytest.fixture
def app_client():
    app = FastAPI()
    app.include_router(ha_router.router, prefix="/api")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _mock_ha_client(monkeypatch):
    client = MagicMock()
    client.list_states.side_effect = lambda domain="": (
        [{"entity_id": "light.sala", "state": "on", "attributes": {}}] if domain in ("", "light") else []
    )
    client.call_service = AsyncMock(return_value={"success": True, "result": []})
    monkeypatch.setattr(ha_router, "_client", client)
    yield client
    monkeypatch.setattr(ha_router, "_client", None)


class TestListDevicesEndpoint:
    async def test_list_devices(self, app_client, _mock_ha_client):
        async with app_client as ac:
            resp = await ac.get("/api/home-assistant/devices")
        assert resp.status_code == 200
        assert resp.json()["devices"][0]["entity_id"] == "light.sala"

    async def test_not_configured_503s(self, app_client, monkeypatch):
        monkeypatch.setattr(ha_router, "_client", None)
        async with app_client as ac:
            resp = await ac.get("/api/home-assistant/devices")
        assert resp.status_code == 503


class TestControlDeviceEndpoint:
    async def test_control_device_success(self, app_client, _mock_ha_client):
        async with app_client as ac:
            resp = await ac.post(
                "/api/home-assistant/devices/light.sala/control",
                json={"action": "turn_on", "brightness_pct": 80},
            )
        assert resp.status_code == 200
        _mock_ha_client.call_service.assert_awaited_once_with(
            "light", "turn_on", entity_id="light.sala", brightness_pct=80
        )

    async def test_control_device_missing_action_400s(self, app_client, _mock_ha_client):
        async with app_client as ac:
            resp = await ac.post("/api/home-assistant/devices/light.sala/control", json={})
        assert resp.status_code == 400

    async def test_control_device_service_failure_502s(self, app_client, _mock_ha_client):
        _mock_ha_client.call_service = AsyncMock(return_value={"success": False, "error": "offline"})
        async with app_client as ac:
            resp = await ac.post(
                "/api/home-assistant/devices/light.sala/control", json={"action": "turn_off"}
            )
        assert resp.status_code == 502


class TestScenesEndpoints:
    async def test_list_scenes(self, app_client, _mock_ha_client):
        _mock_ha_client.list_states.side_effect = lambda domain="": (
            [{"entity_id": "scene.modo_noche", "state": "scening", "attributes": {}}] if domain == "scene" else []
        )
        async with app_client as ac:
            resp = await ac.get("/api/home-assistant/scenes")
        assert resp.status_code == 200
        assert resp.json()["scenes"][0]["entity_id"] == "scene.modo_noche"

    async def test_activate_scene(self, app_client, _mock_ha_client):
        async with app_client as ac:
            resp = await ac.post("/api/home-assistant/scenes/scene.modo_noche/activate")
        assert resp.status_code == 200
        _mock_ha_client.call_service.assert_awaited_once_with("scene", "turn_on", entity_id="scene.modo_noche")
