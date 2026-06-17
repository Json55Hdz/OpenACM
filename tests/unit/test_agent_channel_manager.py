"""Tests for AgentChannelManager."""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_manager():
    from openacm.channels.agent_telegram_bot import AgentChannelManager
    runner = MagicMock()
    runner.run = AsyncMock(return_value="ok")
    runner.llm_router = MagicMock()
    runner.memory = MagicMock()
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    event_bus.on = MagicMock()
    event_bus.off = MagicMock()
    db = MagicMock()
    db.get_all_agents = AsyncMock(return_value=[])
    db.get_agent_channels = AsyncMock(return_value=[])
    db.get_agent = AsyncMock(return_value=None)
    return AgentChannelManager(agent_runner=runner, event_bus=event_bus, database=db)


class TestAgentChannelManager:
    def test_instantiation(self):
        mgr = _make_manager()
        assert mgr._channels == {}
        assert mgr._whatsapp_by_phone == {}

    async def test_start_all_empty(self):
        mgr = _make_manager()
        await mgr.start_all()
        assert mgr._channels == {}

    async def test_start_all_skips_inactive_agents(self):
        from openacm.channels.agent_telegram_bot import AgentChannelManager
        runner = MagicMock()
        event_bus = MagicMock()
        event_bus.emit = AsyncMock()
        event_bus.on = MagicMock()
        db = MagicMock()
        db.get_all_agents = AsyncMock(return_value=[
            {"id": 1, "name": "A", "is_active": 0, "system_prompt": "x", "allowed_tools": "none"}
        ])
        db.get_agent_channels = AsyncMock(return_value=[])
        mgr = AgentChannelManager(agent_runner=runner, event_bus=event_bus, database=db)
        await mgr.start_all()
        db.get_agent_channels.assert_not_called()

    async def test_get_channel_by_phone_returns_none_when_empty(self):
        mgr = _make_manager()
        assert mgr.get_channel_by_phone("12345") is None

    async def test_get_channel_by_phone_returns_channel_after_register(self):
        from openacm.channels.agent_whatsapp_channel import AgentWhatsAppChannel
        mgr = _make_manager()
        mock_ch = MagicMock(spec=AgentWhatsAppChannel)
        mgr._whatsapp_by_phone["12345"] = mock_ch
        assert mgr.get_channel_by_phone("12345") is mock_ch

    async def test_stop_channel_telegram_removes_from_dict(self):
        mgr = _make_manager()
        mock_bot = MagicMock()
        mock_bot.stop = AsyncMock()
        mgr._channels[1] = {"telegram": mock_bot}
        await mgr.stop_channel(1, "telegram")
        mock_bot.stop.assert_awaited_once()
        assert "telegram" not in mgr._channels.get(1, {})

    async def test_stop_all_stops_everything(self):
        mgr = _make_manager()
        mock_tg = MagicMock()
        mock_tg.stop = AsyncMock()
        mock_wa = MagicMock()
        mock_wa.stop = AsyncMock()
        mock_wa.config = MagicMock()
        mock_wa.config.phone_number_id = "555"
        mgr._channels[1] = {"telegram": mock_tg, "whatsapp": mock_wa}
        mgr._whatsapp_by_phone["555"] = mock_wa
        await mgr.stop_all()
        mock_tg.stop.assert_awaited_once()
        mock_wa.stop.assert_awaited_once()
        assert mgr._channels == {}
        assert mgr._whatsapp_by_phone == {}

    def test_get_status_returns_list(self):
        mgr = _make_manager()
        mock_tg = MagicMock()
        mock_tg.is_connected = True
        mgr._channels[1] = {"telegram": mock_tg}
        status = mgr.get_status()
        assert len(status) == 1
        assert status[0]["agent_id"] == 1
        assert status[0]["type"] == "telegram"
        assert status[0]["connected"] is True
