"""list_tools answers from the live registry (one call), optionally for one agent."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from openacm.tools import list_tools as lt
from openacm.tools.tool_creator import list_custom_tools  # noqa: F401  (renamed: no name clash)


def tool(name, desc="Does a thing. More text.", cat="general", risk="low"):
    return SimpleNamespace(name=name, description=desc, category=cat, risk_level=risk)


def brain(agent_policy=None):
    registry = SimpleNamespace(tools={t.name: t for t in [tool("read_file", cat="file"), tool("write_file", cat="file", risk="high"), tool("web_search", "Search the web. x", "web")]})
    db = SimpleNamespace(get_agent=AsyncMock(return_value={"name": "Ana", "allowed_tools": agent_policy} if agent_policy else None))
    return SimpleNamespace(tool_registry=registry, database=db)


async def test_lists_everything_in_one_call():
    out = await lt.list_tools(_brain=brain())
    assert "3 registered" in out and "`write_file`" in out and "[high]" in out


async def test_query_filters_by_word():
    out = await lt.list_tools(query="search", _brain=brain())
    assert "web_search" in out and "read_file" not in out


async def test_agent_with_an_explicit_list():
    out = await lt.list_tools(agent_id=1, _brain=brain(json.dumps(["read_file", "ghost"])))
    assert "read_file" in out and "write_file" not in out and "explicit list" in out


async def test_agent_with_no_tools_and_unknown_agent():
    assert "none registered" in await lt.list_tools(agent_id=1, _brain=brain("none"))
    assert "No agent" in await lt.list_tools(agent_id=9, _brain=brain())
