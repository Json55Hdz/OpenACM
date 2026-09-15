"""Tests for the save_customer_name tool."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from openacm.tools.customer_profile_tool import save_customer_name


def _make_brain(database=None):
    brain = MagicMock()
    brain.memory = MagicMock()
    brain.memory.database = database if database is not None else AsyncMock()
    return brain


class TestSaveCustomerName:
    async def test_saves_name_via_database(self):
        brain = _make_brain()
        result = await save_customer_name(
            name="Juan", _brain=brain, _user_id="a1_wa_573001112233", _channel_id="573001112233",
        )
        brain.memory.database.set_customer_name.assert_awaited_once_with(
            "a1_wa_573001112233", "573001112233", "Juan",
        )
        assert "Juan" in result

    async def test_strips_whitespace(self):
        brain = _make_brain()
        await save_customer_name(name="  Ana  ", _brain=brain, _user_id="u1", _channel_id="c1")
        brain.memory.database.set_customer_name.assert_awaited_once_with("u1", "c1", "Ana")

    async def test_empty_name_errors_without_saving(self):
        brain = _make_brain()
        result = await save_customer_name(name="   ", _brain=brain, _user_id="u1", _channel_id="c1")
        assert result.startswith("Error")
        brain.memory.database.set_customer_name.assert_not_awaited()

    async def test_no_brain_returns_error(self):
        result = await save_customer_name(name="Juan", _brain=None, _user_id="u1", _channel_id="c1")
        assert result.startswith("Error")
