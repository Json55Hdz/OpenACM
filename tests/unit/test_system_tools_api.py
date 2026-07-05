"""Test GET /api/tools includes each tool's category."""
from unittest.mock import MagicMock
import pytest


async def test_get_tools_includes_category(client, tool_registry):
    """Verify GET /api/tools includes a category field for each tool."""
    # Mock a single tool with a category
    tool = MagicMock()
    tool.name = "ha_control"
    tool.description = "control devices"
    tool.risk_level = "low"
    tool.parameters = {}
    tool.category = "iot"

    # Replace the tool registry's tools dict with our mock
    original_tools = tool_registry.tools
    tool_registry.tools = {"ha_control": tool}

    try:
        resp = await client.get("/api/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "ha_control"
        assert data[0]["category"] == "iot"
    finally:
        # Restore original tools
        tool_registry.tools = original_tools
