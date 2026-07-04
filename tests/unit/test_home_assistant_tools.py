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
