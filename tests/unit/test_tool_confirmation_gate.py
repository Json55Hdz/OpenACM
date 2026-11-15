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


class TestApprovalKeysAreExact:
    def test_two_snippets_with_the_same_start_get_different_keys(self):
        head = "x = 1\n" * 60  # longer than the 300 characters shown
        assert confirmation_text("run_python", {"code": head + "print('a')"}) != \
               confirmation_text("run_python", {"code": head + "import os; os.system('x')"})

    def test_the_same_code_gets_the_same_key(self):
        assert confirmation_text("run_python", {"code": "print(1)"}) == confirmation_text("run_python", {"code": "print(1)"})

    def test_dotdot_and_symlink_style_paths_resolve_to_the_real_folder(self, tmp_path):
        (tmp_path / "a").mkdir()
        direct = confirmation_text("write_file", {"path": str(tmp_path / "x.txt")})
        sneaky = confirmation_text("write_file", {"path": str(tmp_path / "a" / ".." / "x.txt")})
        assert direct == sneaky


class TestFollowsTheSecurityMode:
    DANGEROUS = [("run_python", {"code": "1"}), ("delete_swarm", {"swarm_id": 1}), ("update_security_mode", {"mode": "x"})]

    def test_yolo_never_asks(self):
        for tool, args in self.DANGEROUS + [("write_file", {"path": "a/b"})]:
            assert confirmation_text(tool, args, "yolo") is None

    def test_auto_trusts_file_writes_but_asks_for_the_rest(self):
        assert confirmation_text("write_file", {"path": "a/b"}, "auto") is None
        assert confirmation_text("edit_file", {"path": "a/b"}, "auto") is None
        for tool, args in self.DANGEROUS:
            assert confirmation_text(tool, args, "auto")

    def test_confirmation_mode_asks_for_everything(self):
        for tool, args in self.DANGEROUS + [("write_file", {"path": "a/b"})]:
            assert confirmation_text(tool, args, "confirmation")


async def test_the_registry_reads_the_mode_from_its_sandbox_policy():
    reg, handler = _registry(approve=False)
    reg.sandbox = SimpleNamespace(policy=SimpleNamespace(execution_mode="yolo"))
    assert await reg.execute("write_file", ARGS, channel_id="web") == "done"
    reg.confirm_callback.assert_not_awaited()
