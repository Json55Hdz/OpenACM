"""list_tools is promised to be always visible, so app.py must actually register it."""
from pathlib import Path

from openacm.tools.registry import ALWAYS_INCLUDE_TOOLS


def test_every_always_included_tool_is_registered_in_app():
    src = (Path(__file__).parents[2] / "src" / "openacm" / "app.py").read_text(encoding="utf-8")
    from openacm.tools.base import get_registered_tools

    import openacm.tools  # noqa: F401  (imports the decorated modules)
    known = {t.name for t in get_registered_tools()}
    for name in ALWAYS_INCLUDE_TOOLS & known:
        module = next(t.handler.__module__.rsplit(".", 1)[-1] for t in get_registered_tools() if t.name == name)
        assert f"register_module({module})" in src, f"{name} ({module}) is never registered in app.py"


def test_list_tools_handler_is_the_real_function_and_accepts_its_arguments():
    import inspect

    import openacm.tools  # noqa: F401
    from openacm.tools.base import get_registered_tools

    tool = next(t for t in get_registered_tools() if t.name == "list_tools")
    assert tool.handler.__name__ == "list_tools"
    params = inspect.signature(tool.handler).parameters
    assert {"what", "category", "query", "agent_id"} <= set(params)
