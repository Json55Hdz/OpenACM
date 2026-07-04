"""Confirm ha:state_changed is wired into the real-time WebSocket broadcast pipeline."""
import pytest

TEST_TOKEN = "test-dashboard-token"


@pytest.fixture
def dashboard_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", TEST_TOKEN)
    return TEST_TOKEN


class TestHaStateChangedBroadcast:
    async def test_ha_state_changed_is_registered_on_event_bus(self, dashboard_token, client, event_bus):
        assert "ha:state_changed" in event_bus._handlers
        assert len(event_bus._handlers["ha:state_changed"]) >= 1
