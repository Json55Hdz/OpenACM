"""Unit tests for Home Assistant tools — ha_devices, ha_status."""
from unittest.mock import MagicMock
import pytest
from openacm.plugins.home_assistant import tools as ha_tools

STATES = [
    {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz Sala", "brightness": 200}},
    {"entity_id": "switch.tv", "state": "off", "attributes": {"friendly_name": "TV"}},
]


def _make_client_with_states(states):
    client = MagicMock()

    def _list(domain=""):
        if domain:
            return [s for s in states if s["entity_id"].startswith(f"{domain}.")]
        return list(states)

    def _find(name_or_id):
        for s in states:
            if s["entity_id"] == name_or_id:
                return s
            if s.get("attributes", {}).get("friendly_name", "").lower() == name_or_id.lower():
                return s
        return None

    client.list_states.side_effect = _list
    client.find_entity.side_effect = _find
    return client


class TestHaDevices:
    async def test_not_configured_returns_friendly_message(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", None)
        result = await ha_tools.ha_devices()
        assert "no está configurado" in result

    async def test_lists_all_devices(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_devices()
        assert "light.sala" in result
        assert "switch.tv" in result

    async def test_filters_by_domain(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_devices(domain="light")
        assert "light.sala" in result
        assert "switch.tv" not in result

    async def test_no_devices_of_domain_returns_friendly_message(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_devices(domain="climate")
        assert "No hay dispositivos" in result


class TestHaStatus:
    async def test_not_configured_returns_friendly_message(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", None)
        result = await ha_tools.ha_status("light.sala")
        assert "no está configurado" in result

    async def test_status_by_entity_id(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_status("light.sala")
        assert "Luz Sala" in result
        assert "on" in result

    async def test_status_by_friendly_name(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_status("TV")
        assert "switch.tv" in result

    async def test_unknown_entity_suggests_alternatives(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_client_with_states(STATES))
        result = await ha_tools.ha_status("nonexistent")
        assert "No encontré" in result
        assert "light.sala" in result


from unittest.mock import AsyncMock


def _make_control_client(states, service_result=None):
    client = MagicMock()

    def _find(name_or_id):
        for s in states:
            if s["entity_id"] == name_or_id:
                return s
            if s.get("attributes", {}).get("friendly_name", "").lower() == name_or_id.lower():
                return s
        return None

    client.find_entity.side_effect = _find
    client.call_service = AsyncMock(return_value=service_result or {"success": True, "result": []})
    return client


CONTROL_STATES = [
    {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz Sala"}},
    {"entity_id": "light.cocina", "state": "off", "attributes": {"friendly_name": "Luz Cocina"}},
    {"entity_id": "switch.tv", "state": "off", "attributes": {"friendly_name": "TV"}},
]


class TestHaControlValidation:
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", None)
        result = await ha_tools.ha_control(entity_id="light.sala", action="turn_on")
        assert "no está configurado" in result

    async def test_requires_entity_id_or_area(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_control_client(CONTROL_STATES))
        result = await ha_tools.ha_control(action="turn_on")
        assert "entity_id" in result and "area" in result

    async def test_unknown_entity_returns_error(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_control_client(CONTROL_STATES))
        result = await ha_tools.ha_control(entity_id="light.nonexistent", action="turn_on")
        assert "No encontré" in result


class TestHaControlGenericActions:
    async def test_turn_off_single_entity(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="light.sala", action="turn_off")

        client.call_service.assert_awaited_once_with("homeassistant", "turn_off", entity_id=["light.sala"])
        assert "✓" in result

    async def test_turn_off_multiple_mixed_domain_entities_in_one_call(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id=["light.sala", "switch.tv"], action="turn_off")

        client.call_service.assert_awaited_once_with(
            "homeassistant", "turn_off", entity_id=["light.sala", "switch.tv"]
        )
        assert "✓" in result

    async def test_turn_off_whole_area(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(area="sala", action="turn_off")

        client.call_service.assert_awaited_once_with("homeassistant", "turn_off", area_id="sala")
        assert "✓" in result

    async def test_generic_action_failure_reports_error(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES, service_result={"success": False, "error": "no responde"})
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="light.sala", action="turn_off")

        assert "✗" in result and "no responde" in result


class TestHaControlDomainActions:
    async def test_set_brightness(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="light.sala", action="set_brightness", brightness=80)

        client.call_service.assert_awaited_once_with(
            "light", "turn_on", entity_id=["light.sala"], brightness_pct=80
        )
        assert "✓" in result

    async def test_set_brightness_missing_param(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="light.sala", action="set_brightness")

        assert "necesita el parámetro 'brightness'" in result
        client.call_service.assert_not_awaited()

    async def test_domain_action_needs_entity_id_not_area(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(area="sala", action="set_brightness", brightness=80)

        assert "necesita 'entity_id'" in result

    async def test_domain_action_rejects_mixed_domains(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(
            entity_id=["light.sala", "switch.tv"], action="set_brightness", brightness=80
        )

        assert "mismo tipo" in result
        client.call_service.assert_not_awaited()

    async def test_action_not_valid_for_domain(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="switch.tv", action="set_brightness", brightness=80)

        assert "no es válido para 'switch'" in result

    async def test_set_temperature(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES + [
            {"entity_id": "climate.termostato", "state": "heat", "attributes": {}}
        ])
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="climate.termostato", action="set_temperature", temperature=22)

        client.call_service.assert_awaited_once_with(
            "climate", "set_temperature", entity_id=["climate.termostato"], temperature=22
        )
        assert "✓" in result


class TestHaControlActionAliases:
    """LLMs sometimes guess a shorter/common synonym before reading the exact
    accepted action names — normalize the obvious ones so the first call
    succeeds instead of retrying after an error."""

    async def test_on_is_an_alias_for_turn_on(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="light.sala", action="on")

        client.call_service.assert_awaited_once_with("homeassistant", "turn_on", entity_id=["light.sala"])
        assert "✓" in result

    async def test_off_is_an_alias_for_turn_off(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="light.sala", action="off")

        client.call_service.assert_awaited_once_with("homeassistant", "turn_off", entity_id=["light.sala"])
        assert "✓" in result

    async def test_action_is_case_and_whitespace_insensitive(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(entity_id="light.sala", action="  On ")

        client.call_service.assert_awaited_once_with("homeassistant", "turn_on", entity_id=["light.sala"])
        assert "✓" in result

    async def test_alias_also_works_with_area(self, monkeypatch):
        client = _make_control_client(CONTROL_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_control(area="sala", action="off")

        client.call_service.assert_awaited_once_with("homeassistant", "turn_off", area_id="sala")
        assert "✓" in result


SCENE_STATES = [
    {"entity_id": "scene.modo_noche", "state": "scening", "attributes": {"friendly_name": "Modo Noche"}},
    {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz Sala"}},
]


def _make_scene_client(states, service_result=None):
    client = MagicMock()

    def _list(domain=""):
        if domain:
            return [s for s in states if s["entity_id"].startswith(f"{domain}.")]
        return list(states)

    def _find(name_or_id):
        for s in states:
            if s["entity_id"] == name_or_id:
                return s
            if s.get("attributes", {}).get("friendly_name", "").lower() == name_or_id.lower():
                return s
        return None

    client.list_states.side_effect = _list
    client.find_entity.side_effect = _find
    client.call_service = AsyncMock(return_value=service_result or {"success": True, "result": []})
    return client


class TestHaScenes:
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", None)
        result = await ha_tools.ha_scenes()
        assert "no está configurado" in result

    async def test_lists_scenes_only(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_scene_client(SCENE_STATES))
        result = await ha_tools.ha_scenes()
        assert "Modo Noche" in result

    async def test_no_scenes_configured(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_scene_client([SCENE_STATES[1]]))
        result = await ha_tools.ha_scenes()
        assert "No hay escenas" in result


class TestHaActivateScene:
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", None)
        result = await ha_tools.ha_activate_scene("Modo Noche")
        assert "no está configurado" in result

    async def test_activates_by_friendly_name(self, monkeypatch):
        client = _make_scene_client(SCENE_STATES)
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_activate_scene("Modo Noche")

        client.call_service.assert_awaited_once_with("scene", "turn_on", entity_id="scene.modo_noche")
        assert "✓" in result and "Modo Noche" in result

    async def test_unknown_scene_lists_alternatives(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_scene_client(SCENE_STATES))
        result = await ha_tools.ha_activate_scene("Nonexistent")
        assert "No encontré" in result
        assert "Modo Noche" in result

    async def test_rejects_non_scene_entity(self, monkeypatch):
        monkeypatch.setattr(ha_tools, "_client", _make_scene_client(SCENE_STATES))
        result = await ha_tools.ha_activate_scene("Luz Sala")
        assert "No encontré la escena" in result

    async def test_activation_failure_reports_error(self, monkeypatch):
        client = _make_scene_client(SCENE_STATES, service_result={"success": False, "error": "timeout"})
        monkeypatch.setattr(ha_tools, "_client", client)

        result = await ha_tools.ha_activate_scene("Modo Noche")

        assert "✗" in result and "timeout" in result
