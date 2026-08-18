"""
Tests for OpenACM._init_tools — verifies feature-flagged tools are only
registered when their config toggle is enabled.
"""
from unittest.mock import MagicMock

from openacm.app import OpenACM
from openacm.core.config import AppConfig


async def _make_app(db, event_bus, browser_agent_enabled: bool) -> OpenACM:
    app = OpenACM()
    app.config = AppConfig()
    app.config.features.browser_agent = browser_agent_enabled
    app.sandbox = MagicMock()
    app.event_bus = event_bus
    app.database = db
    app.brain = MagicMock()  # _init_tools sets self.brain.tool_registry at the end
    await app._init_tools()
    return app


class TestBrowserAgentToggle:
    async def test_registered_when_enabled(self, db, event_bus):
        app = await _make_app(db, event_bus, browser_agent_enabled=True)
        assert "browser_agent" in app.tool_registry.tools

    async def test_not_registered_when_disabled(self, db, event_bus):
        app = await _make_app(db, event_bus, browser_agent_enabled=False)
        assert "browser_agent" not in app.tool_registry.tools

    async def test_other_tools_unaffected_when_disabled(self, db, event_bus):
        app = await _make_app(db, event_bus, browser_agent_enabled=False)
        assert "run_command" in app.tool_registry.tools
        assert "read_file" in app.tool_registry.tools


class TestVoiceDaemonToggle:
    async def test_not_instantiated_when_disabled(self, db, event_bus):
        app = OpenACM()
        app.config = AppConfig()
        app.config.features.voice = False
        app.database = db
        app.event_bus = event_bus
        app.brain = MagicMock()
        # _init_watchers also starts ActivityWatcher/ResurrectionWatcher/CronScheduler/
        # SwarmManager — each wrapped in its own try/except in the source, so they
        # fail silently against the unset self.llm_router/tool_registry/memory/
        # skill_manager (all None by default from OpenACM.__init__) and don't
        # affect this assertion.
        await app._init_watchers()
        assert app._voice_daemon is None
