"""Per-chat toolset: tools a chat has used stay available, with their whole plugin family."""
from types import SimpleNamespace

from openacm.core.brain_loop import BrainLoopMixin
from openacm.tools.registry import ToolRegistry


def _td(name, module):
    async def handler(**kw):
        return ""
    handler.__module__ = module
    return SimpleNamespace(name=name, handler=handler)


def _registry():
    reg = ToolRegistry.__new__(ToolRegistry)
    reg.tools = {
        "run_command": _td("run_command", "openacm.tools.system"),
        "browser_click": _td("browser_click", "my_plugin.tools_browser"),
        "audio_transcribe": _td("audio_transcribe", "my_plugin.tools_audio"),
        "other_tool": _td("other_tool", "other_plugin.tools"),
    }
    return reg


def test_using_one_plugin_tool_brings_its_whole_family():
    reg = _registry()
    assert reg.family_of("run_command") is None
    assert reg.expand_families(["browser_click"]) == ["browser_click", "audio_transcribe"]
    assert reg.expand_families(["run_command", "ghost"]) == ["run_command"]  # core: no expansion


class _DB:
    def __init__(self):
        self.data = {}

    async def get_setting(self, k):
        return self.data.get(k)

    async def set_setting(self, k, v):
        self.data[k] = v


class _Loop(BrainLoopMixin):
    def __init__(self, db):
        self.memory = SimpleNamespace(database=db)


async def test_chat_tools_are_remembered_per_chat_and_survive_a_restart():
    db = _DB()
    a = _Loop(db)
    await a._remember_chat_tool("chat1", "web", "audio_transcribe")
    await a._remember_chat_tool("chat1", "web", "audio_transcribe")
    await a._remember_chat_tool("chat1", "web", "browser_click")
    assert await a._load_chat_tools("chat1", "web") == ["audio_transcribe", "browser_click"]
    assert await a._load_chat_tools("chat2", "web") == []
    assert await _Loop(db)._load_chat_tools("chat1", "web") == ["audio_transcribe", "browser_click"]
