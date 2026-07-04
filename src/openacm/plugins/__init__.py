"""
OpenACM Plugin System.

Plugins are self-contained feature packages that extend OpenACM without
modifying its core. Each plugin can provide:
  - Tools (registered in ToolRegistry)
  - Intent keywords (merged into ToolRegistry routing)
  - Brain context extension (injected into LLM system prompt)
  - API routes (mounted on FastAPI app)
  - Frontend nav items (returned to sidebar via /api/plugins/nav)

Usage — define a plugin:

    from openacm.plugins import Plugin, plugin_registry

    class MyPlugin(Plugin):
        name = "my_feature"
        version = "1.0.0"
        description = "Does something cool"

        def get_tool_modules(self): ...
        def get_context_extension(self) -> str: ...
        def get_intent_keywords(self) -> dict: ...
        def get_nav_items(self) -> list[dict]: ...
        async def on_start(self, *, tool_registry, database, event_bus, ...): ...
        async def on_stop(self): ...

    plugin_registry.register(MyPlugin())

Then in app.py (or pyproject.toml entry_points for pip-installable plugins):
    import my_package  # registers the plugin on import

The plugin system is intentionally simple: just Python imports.
No framework magic needed.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from openacm.tools.registry import ToolRegistry

log = structlog.get_logger()


class Plugin:
    """
    Base class for OpenACM plugins.

    Override the methods you need — everything has a safe default.
    """

    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    _database: Any = None

    # ── Provide tools ──────────────────────────────────────────

    def get_tool_modules(self) -> list[Any]:
        """
        Return Python modules that contain @tool-decorated functions.
        These will be passed to tool_registry.register_module().
        """
        return []

    # ── Provide skills ─────────────────────────────────────────

    def get_skills(self) -> list[dict]:
        """
        Return skill definitions to auto-load into the database at startup.
        Existing skills (by name) are not overwritten.

        Each dict:
            {
                "name":        "my-skill",           # unique, kebab-case
                "description": "What it does",
                "content":     "# My Skill\\n...",   # markdown skill body
                "category":    "general",            # freeform category label
            }
        """
        return []

    # ── Provide API routes ─────────────────────────────────────

    def get_api_router(self) -> Any | None:
        """
        Return a FastAPI APIRouter to mount on the web server under /api/.
        Routes defined here are available at /api/<prefix>/<route>.

        Example:
            from fastapi import APIRouter
            router = APIRouter(prefix="/my-feature")

            @router.get("/status")
            async def status():
                return {"ok": True}

            def get_api_router(self):
                return router
        """
        return None

    # ── Extend LLM system prompt ───────────────────────────────

    def get_context_extension(self) -> str:
        """
        Return a markdown string to append to the LLM system prompt.
        Use this to tell the AI about new capabilities or behaviours the plugin adds.
        Keep it short — it's injected on every message.
        """
        return ""

    # ── Extend intent routing ──────────────────────────────────

    def get_intent_keywords(self) -> dict[str, list[str]]:
        """
        Return a dict of {category: [keywords]} to register with the ToolRegistry
        so the intent router sends this plugin's tools to the LLM when relevant.

        Example:
            return {"content": ["post", "publish", "funcionó", "it works"]}
        """
        return {}

    # ── Frontend nav items ─────────────────────────────────────

    def get_nav_items(self) -> list[dict]:
        """
        Return sidebar navigation items to add to the frontend.

        Each item: {
            "path":  "/my-page",          # Next.js route
            "label": "My Feature",         # display name
            "icon":  "IconName",           # lucide-react icon name
            "section": "main" | "bottom",  # sidebar placement (default "main")
        }
        """
        return []

    # ── Provide a settings schema (Phase 1 dashboard config form) ──

    def get_config_schema(self) -> list[dict]:
        """
        Return field definitions for the dashboard's generic plugin
        settings form. Each field:
            {
                "key":      "url",              # dict key used to store the value
                "label":    "Home Assistant URL",
                "type":     "text" | "password" | "number" | "boolean",
                "required": True,
                "help":     "e.g. http://homeassistant.local:8123",
            }
        """
        return []

    # ── Declare a custom UI (Phase 1 new-tab escape hatch) ──────

    def has_custom_ui(self) -> bool:
        """
        If True, this plugin's get_api_router() is expected to serve a
        GET /ui route (self-contained HTML) that the dashboard opens in
        a new browser tab — used for plugins needing a richer view than
        the generic config form without ever touching the Next.js frontend.
        """
        return False

    # ── Read this plugin's saved settings ───────────────────────

    async def get_setting(self, key: str, default: Any = None) -> Any:
        """Read a value this plugin saved via the dashboard config form."""
        if not self._database:
            return default
        config = await self._database.get_plugin_config(self.name)
        return config.get(key, default)

    # ── Lifecycle hooks ────────────────────────────────────────

    async def on_start(self, **app_context: Any) -> None:
        """
        Called after all core systems are up. Subclasses that override
        this MUST call `await super().on_start(**app_context)` first —
        it's what makes get_setting() work.

        Available kwargs:
            config, database, event_bus, llm_router, brain, tool_registry,
            skill_manager, activity_watcher, cron_scheduler, swarm_manager,
            workspace_root (Path)
        """
        self._database = app_context.get("database")

    async def on_stop(self) -> None:
        """Called when OpenACM is shutting down."""

    def __repr__(self) -> str:
        return f"<Plugin {self.name} v{self.version}>"


class PluginManager:
    """
    Manages all registered plugins.
    Used by app.py and brain.py to integrate plugin contributions.
    """

    def __init__(self):
        self._plugins: list[Plugin] = []
        self._enabled: dict[str, bool] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin instance."""
        if any(p.name == plugin.name for p in self._plugins):
            log.warning("Plugin already registered, skipping", plugin=plugin.name)
            return
        self._plugins.append(plugin)
        log.info("Plugin registered", name=plugin.name, version=plugin.version)

    async def load_enabled_state(self, database: Any) -> None:
        """Load each discovered plugin's enabled flag from the DB. Call this
        after load_builtin_plugins() and before start_all()."""
        for plugin in self._plugins:
            self._enabled[plugin.name] = await database.is_plugin_enabled(plugin.name)

    def is_enabled(self, name: str) -> bool:
        """Defaults to True if load_enabled_state() hasn't run for this plugin yet."""
        return self._enabled.get(name, True)

    def load_builtin_plugins(self) -> None:
        """
        Auto-discover and register plugins from two sources:

        1. openacm.plugins.* subpackages — built-in plugins shipped with OpenACM.
           Each subpackage must expose a module-level PLUGIN instance.

        2. Python entry points group "openacm.plugins" — pip-installable plugins.
           Declare in your package's pyproject.toml:
               [project.entry-points."openacm.plugins"]
               my_plugin = "my_package:PLUGIN"
        """
        # 1. Built-in plugins (subpackages of openacm.plugins)
        plugins_dir = Path(__file__).parent
        for finder, pkg_name, is_pkg in pkgutil.iter_modules([str(plugins_dir)]):
            if not is_pkg:
                continue
            try:
                mod = importlib.import_module(f"openacm.plugins.{pkg_name}")
                plugin: Plugin | None = getattr(mod, "PLUGIN", None)
                if isinstance(plugin, Plugin):
                    self.register(plugin)
                else:
                    log.debug("Plugin package has no PLUGIN instance", package=pkg_name)
            except Exception as exc:
                log.warning("Failed to load plugin", package=pkg_name, error=str(exc))

        # 2. pip-installed plugins via entry points
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group="openacm.plugins")
            for ep in eps:
                try:
                    plugin = ep.load()
                    if isinstance(plugin, Plugin):
                        self.register(plugin)
                    else:
                        log.warning("Entry point is not a Plugin instance", entry_point=ep.name)
                except Exception as exc:
                    log.warning("Failed to load entry-point plugin", entry_point=ep.name, error=str(exc))
        except Exception as exc:
            log.debug("Entry point discovery skipped", error=str(exc))

    async def start_all(self, **app_context: Any) -> None:
        """Start all plugins, registering their tools, skills, and keywords."""
        tool_registry: ToolRegistry | None = app_context.get("tool_registry")
        database = app_context.get("database")

        for plugin in self._plugins:
            if not self.is_enabled(plugin.name):
                log.info("Plugin disabled, skipping start", name=plugin.name)
                continue
            try:
                # Register tools
                if tool_registry:
                    for module in plugin.get_tool_modules():
                        tool_registry.register_module(module)
                    # Register intent keywords
                    kws = plugin.get_intent_keywords()
                    if kws:
                        tool_registry.register_plugin_keywords(kws)

                # Register skills (skip if name already exists)
                if database:
                    for skill_def in plugin.get_skills():
                        try:
                            existing = await database.get_skill_by_name(skill_def["name"])
                            if not existing:
                                await database.create_skill(
                                    name=skill_def["name"],
                                    description=skill_def.get("description", ""),
                                    content=skill_def.get("content", ""),
                                    category=skill_def.get("category", "general"),
                                )
                                log.info(
                                    "Plugin skill registered",
                                    plugin=plugin.name,
                                    skill=skill_def["name"],
                                )
                        except Exception as exc:
                            log.warning(
                                "Failed to register plugin skill",
                                plugin=plugin.name,
                                skill=skill_def.get("name"),
                                error=str(exc),
                            )

                # Run startup hook
                await plugin.on_start(**app_context)
                log.info("Plugin started", name=plugin.name)

            except Exception as exc:
                log.error("Plugin failed to start", name=plugin.name, error=str(exc))

    async def stop_all(self) -> None:
        """Stop all plugins in reverse order."""
        for plugin in reversed(self._plugins):
            try:
                await plugin.on_stop()
            except Exception as exc:
                log.warning("Plugin stop error", name=plugin.name, error=str(exc))

    def get_context_extensions(self) -> list[str]:
        """Collect context snippets from all ENABLED plugins (for brain.py)."""
        return [
            ext for p in self._plugins
            if self.is_enabled(p.name) and (ext := p.get_context_extension())
        ]

    def get_nav_items(self) -> list[dict]:
        """Collect frontend nav items from all ENABLED plugins (for /api/plugins/nav).

        Each item is tagged with the owning plugin's `name`, so the
        dashboard's /plugins page can link a plugin card straight to its
        own page when one exists.
        """
        items = []
        for p in self._plugins:
            if self.is_enabled(p.name):
                items.extend({**item, "plugin": p.name} for item in p.get_nav_items())
        return items

    def get_api_routers(self) -> list[Any]:
        """Collect FastAPI APIRouter instances from all ENABLED plugins (mounted by server.py)."""
        routers = []
        for p in self._plugins:
            if not self.is_enabled(p.name):
                continue
            try:
                router = p.get_api_router()
                if router is not None:
                    routers.append(router)
            except Exception as exc:
                log.warning("Failed to get API router from plugin", plugin=p.name, error=str(exc))
        return routers

    @property
    def plugins(self) -> list[Plugin]:
        return list(self._plugins)


# Global singleton — plugins register themselves here on import
plugin_manager = PluginManager()
