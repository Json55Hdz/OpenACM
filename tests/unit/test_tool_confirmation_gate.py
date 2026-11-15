"""Powerful tools ask the owner first; agents and swarms are not asked (the owner already chose them)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from openacm.tools.registry import ToolRegistry, confirmation_text


class TestWhatAsks:
    @pytest.mark.parametrize("tool,args", [
        ("write_file", {"path": "a/b.txt", "content": "x"}),
        ("edit_file", {"path": "a/b.py"}),
        ("run_python", {"code": "print(1)"}),
        ("create_tool", {"name": "t", "apply": True}),
        ("edit_tool", {"name": "t"}),
        ("delete_tool", {"name": "t"}),
        ("update_security_mode", {"mode": "yolo"}),
        ("post_to_facebook", {"message": "hola"}),
        ("delete_swarm", {"swarm_id": 3}),
    ])
    def test_these_ask(self, tool, args):
        assert confirmation_text(tool, args)

    @pytest.mark.parametrize("tool,args", [
        ("read_file", {"path": "x"}), ("create_tool", {"name": "t"}), ("web_search", {"query": "q"}),
    ])
    def test_these_do_not(self, tool, args):
        assert confirmation_text(tool, args) is None

    def test_approving_a_write_covers_its_folder_not_one_file(self):
        a = confirmation_text("write_file", {"path": "proj/a.txt"})
        b = confirmation_text("write_file", {"path": "proj/b.txt"})
        assert a == b


def _registry(approve):
    reg = ToolRegistry.__new__(ToolRegistry)
    handler = AsyncMock(return_value="done")
    reg.tools = {"write_file": SimpleNamespace(handler=handler, timeout_s=0)}
    reg.sandbox = reg.event_bus = None
    reg.database = SimpleNamespace(log_tool_execution=AsyncMock())
    reg.confirm_callback = AsyncMock(return_value=approve)
    return reg, handler


ARGS = {"path": "p/x.txt", "content": "c"}


async def test_a_denied_call_does_not_run():
    reg, handler = _registry(approve=False)
    out = await reg.execute("write_file", ARGS, channel_id="web")
    assert out.startswith("Not run") and not handler.await_count


async def test_an_approved_call_runs():
    reg, handler = _registry(approve=True)
    assert await reg.execute("write_file", ARGS, channel_id="web") == "done"
    reg.confirm_callback.assert_awaited_once()


async def test_swarm_workers_are_not_asked():
    reg, handler = _registry(approve=False)
    assert await reg.execute("write_file", ARGS, channel_id="swarm_3__w") == "done"
    reg.confirm_callback.assert_not_awaited()


async def test_agents_are_not_asked():
    reg, handler = _registry(approve=False)
    brain = SimpleNamespace(config=SimpleNamespace(is_agent=True))
    assert await reg.execute("write_file", ARGS, channel_id="c", _brain=brain) == "done"
    reg.confirm_callback.assert_not_awaited()


async def test_without_a_callback_nothing_blocks():
    reg, handler = _registry(approve=False)
    reg.confirm_callback = None
    assert await reg.execute("write_file", ARGS, channel_id="web") == "done"
