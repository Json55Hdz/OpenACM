"""Agents must know today's date: warranty windows, 'are you open today' and delivery
promises depend on it, and the model has no clock of its own."""
from datetime import datetime, timezone

from openacm.core.agent_runner import AgentRunner


class TestApplyCurrentDate:
    def test_appends_date_weekday_and_time_in_colombia(self):
        # 2026-11-22 03:30 UTC is still Saturday 21 Nov 22:30 in Bogotá (UTC-5, no DST)
        now = datetime(2026, 11, 22, 3, 30, tzinfo=timezone.utc)
        result = AgentRunner._apply_current_date("Be helpful.", now)
        assert result.startswith("Be helpful.")
        assert "2026-11-21" in result
        assert "sábado" in result
        assert "22:30" in result

    def test_names_sunday_so_opening_hours_can_be_answered(self):
        now = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)
        assert "domingo" in AgentRunner._apply_current_date("x", now)
