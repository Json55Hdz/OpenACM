# Plugin System Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OpenACM's existing plugin system visible and configurable from the dashboard — a `/plugins` page listing every discovered plugin, per-plugin settings via a declared config schema, enable/disable that takes effect on restart, and an iframe escape hatch for plugins needing a richer view without a frontend rebuild.

**Architecture:** A new `plugin_state` SQLite table persists enabled/disabled + a JSON config blob per plugin. `PluginManager` gains an in-memory enabled-state cache loaded once at startup and consulted everywhere it currently iterates `self._plugins` for registration purposes (tools, keywords, skills, `on_start`, nav items, context extension, API routers) — a disabled plugin is skipped everywhere except the raw discovery list, so it still shows up (as "disabled") on the `/plugins` page. Two new optional hooks on the `Plugin` base class (`get_config_schema()`, `has_custom_ui()`) default to "nothing" so every existing plugin (`gmail_classifier`) keeps working unmodified.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, pytest + pytest-asyncio (`asyncio_mode = "auto"`), Next.js 16 (static export) + React Query + Zustand, react-markdown.

## Global Constraints

- Bump `Database._SCHEMA_VERSION` in `src/openacm/storage/database.py:171` from `30` to `31` — every new migration must live inside an `if current < 31:` block per the existing pattern (see `database.py:914-922` for the migration-30 example).
- Every new/modified async DB method must guard `if not self._db: return ...` like every other method in `database.py` (e.g. `get_setting` at `database.py:1398-1406`).
- A plugin with no row in `plugin_state` is enabled by default — never treat "no row" as disabled.
- `get_config_schema()` and `has_custom_ui()` must default to `[]` / `False` on the base `Plugin` class so `gmail_classifier` and any third-party plugin needs zero changes.
- All new FastAPI endpoints go in `src/openacm/web/routers/system.py`, next to the existing `/api/plugins` and `/api/plugins/nav` routes (`system.py:232-251`), and are auto-protected by the existing `TokenAuthMiddleware` (`system.py:44-82`) since they're under `/api/`.
- Frontend: reuse `useAPI()`/`fetchAPI` from `frontend/hooks/use-api.ts` for all new hooks — do not hand-roll `fetch()` calls with manual auth headers (see `frontend/hooks/use-setup.ts:24-35` for the established pattern).
- Test DB fixture is `db` (`Database(":memory:")`, see `tests/conftest.py:108-113`) — reuse it, don't create a new one.

---

### Task 1: `plugin_state` table + Database CRUD methods

**Files:**
- Modify: `src/openacm/storage/database.py:171` (bump `_SCHEMA_VERSION`), `src/openacm/storage/database.py:914-923` (add migration block before the "Save new version" comment), and add new methods near `get_setting`/`set_setting` (`database.py:1398-1417`)
- Test: `tests/unit/test_database_plugin_state.py`

**Interfaces:**
- Produces: `Database.get_all_plugin_states() -> dict[str, dict]` (keys are plugin names present in the table; each value `{"enabled": bool, "config": dict}`), `Database.is_plugin_enabled(name: str) -> bool` (returns `True` if no row exists), `Database.set_plugin_enabled(name: str, enabled: bool) -> None`, `Database.get_plugin_config(name: str) -> dict`, `Database.set_plugin_config(name: str, config: dict) -> None` (full replace of the stored dict, upsert).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_database_plugin_state.py
import pytest
from openacm.storage.database import Database


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


class TestPluginState:
    async def test_unknown_plugin_is_enabled_by_default(self, db):
        assert await db.is_plugin_enabled("never_seen") is True

    async def test_set_and_read_enabled_flag(self, db):
        await db.set_plugin_enabled("gmail_classifier", False)
        assert await db.is_plugin_enabled("gmail_classifier") is False
        await db.set_plugin_enabled("gmail_classifier", True)
        assert await db.is_plugin_enabled("gmail_classifier") is True

    async def test_config_defaults_to_empty_dict(self, db):
        assert await db.get_plugin_config("never_seen") == {}

    async def test_set_and_read_config(self, db):
        await db.set_plugin_config("home_assistant", {"url": "http://ha.local:8123", "token": "abc"})
        assert await db.get_plugin_config("home_assistant") == {
            "url": "http://ha.local:8123",
            "token": "abc",
        }

    async def test_set_plugin_config_overwrites_fully(self, db):
        await db.set_plugin_config("home_assistant", {"url": "http://old", "token": "x"})
        await db.set_plugin_config("home_assistant", {"url": "http://new"})
        assert await db.get_plugin_config("home_assistant") == {"url": "http://new"}

    async def test_get_all_plugin_states_only_lists_rows_that_exist(self, db):
        await db.set_plugin_enabled("gmail_classifier", False)
        await db.set_plugin_config("home_assistant", {"url": "http://ha.local"})
        states = await db.get_all_plugin_states()
        assert states["gmail_classifier"]["enabled"] is False
        assert states["gmail_classifier"]["config"] == {}
        assert states["home_assistant"]["enabled"] is True
        assert states["home_assistant"]["config"] == {"url": "http://ha.local"}
        assert "never_seen" not in states
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_database_plugin_state.py -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'is_plugin_enabled'` (table/methods don't exist yet)

- [ ] **Step 3: Add the migration**

In `src/openacm/storage/database.py`, change line 171:

```python
    _SCHEMA_VERSION = 31
```

Then insert this block right before the `# Save new version` comment (currently `database.py:924`, i.e. immediately after the migration-30 block ending at line 922):

```python
        # ── Migration 31: add plugin_state table (Phase 1 plugin dashboard) ──
        if current < 31:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS plugin_state (
                    plugin_name  TEXT PRIMARY KEY,
                    enabled      BOOLEAN NOT NULL DEFAULT 1,
                    config_json  TEXT NOT NULL DEFAULT '{}'
                );
            """)
            await self._db.commit()
            log.info("Migration 31: add plugin_state table")
```

- [ ] **Step 4: Add the CRUD methods**

Add these methods in `database.py` right after `get_all_settings` (immediately following the block at `database.py:1419-1423`):

```python
    # ─── Plugin state (Phase 1 plugin dashboard) ───────────────

    async def is_plugin_enabled(self, name: str) -> bool:
        """A plugin with no row is enabled by default."""
        if not self._db:
            return True
        cursor = await self._db.execute(
            "SELECT enabled FROM plugin_state WHERE plugin_name = ?", (name,)
        )
        row = await cursor.fetchone()
        return bool(row["enabled"]) if row else True

    async def set_plugin_enabled(self, name: str, enabled: bool) -> None:
        if not self._db:
            return
        await self._db.execute(
            "INSERT INTO plugin_state (plugin_name, enabled) VALUES (?, ?) "
            "ON CONFLICT(plugin_name) DO UPDATE SET enabled = excluded.enabled",
            (name, int(enabled)),
        )
        await self._db.commit()

    async def get_plugin_config(self, name: str) -> dict:
        if not self._db:
            return {}
        cursor = await self._db.execute(
            "SELECT config_json FROM plugin_state WHERE plugin_name = ?", (name,)
        )
        row = await cursor.fetchone()
        if not row:
            return {}
        import json
        return json.loads(row["config_json"])

    async def set_plugin_config(self, name: str, config: dict) -> None:
        if not self._db:
            return
        import json
        await self._db.execute(
            "INSERT INTO plugin_state (plugin_name, config_json) VALUES (?, ?) "
            "ON CONFLICT(plugin_name) DO UPDATE SET config_json = excluded.config_json",
            (name, json.dumps(config)),
        )
        await self._db.commit()

    async def get_all_plugin_states(self) -> dict[str, dict]:
        if not self._db:
            return {}
        import json
        cursor = await self._db.execute(
            "SELECT plugin_name, enabled, config_json FROM plugin_state"
        )
        rows = await cursor.fetchall()
        return {
            row["plugin_name"]: {
                "enabled": bool(row["enabled"]),
                "config": json.loads(row["config_json"]),
            }
            for row in rows
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_database_plugin_state.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `pytest`
Expected: PASS (no regressions from the migration bump)

- [ ] **Step 7: Commit**

```bash
git add src/openacm/storage/database.py tests/unit/test_database_plugin_state.py
git commit -m "feat(db): add plugin_state table for Phase 1 plugin dashboard"
```

---

### Task 2: `Plugin` base class — config schema, custom UI flag, settings helper

**Files:**
- Modify: `src/openacm/plugins/__init__.py:52-163` (the `Plugin` class)
- Test: `tests/unit/test_plugin_base.py`

**Interfaces:**
- Consumes: `Database.get_plugin_config(name: str) -> dict` from Task 1.
- Produces: `Plugin.get_config_schema(self) -> list[dict]` (default `[]`), `Plugin.has_custom_ui(self) -> bool` (default `False`), `Plugin.get_setting(self, key: str, default: Any = None) -> Any` (async), base `Plugin.on_start(self, **app_context)` now sets `self._database = app_context.get("database")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_plugin_base.py
import pytest
from unittest.mock import AsyncMock
from openacm.plugins import Plugin


class _BarePlugin(Plugin):
    name = "bare"


class _ConfigurablePlugin(Plugin):
    name = "configurable"

    def get_config_schema(self):
        return [{"key": "url", "label": "URL", "type": "text", "required": True, "help": ""}]

    def has_custom_ui(self):
        return True


class TestPluginDefaults:
    def test_bare_plugin_has_no_config_schema(self):
        assert _BarePlugin().get_config_schema() == []

    def test_bare_plugin_has_no_custom_ui(self):
        assert _BarePlugin().has_custom_ui() is False

    def test_configurable_plugin_overrides(self):
        p = _ConfigurablePlugin()
        assert p.get_config_schema()[0]["key"] == "url"
        assert p.has_custom_ui() is True


class TestGetSetting:
    async def test_get_setting_returns_default_before_on_start(self):
        p = _BarePlugin()
        assert await p.get_setting("missing", default="fallback") == "fallback"

    async def test_get_setting_reads_from_database_after_on_start(self):
        mock_db = AsyncMock()
        mock_db.get_plugin_config.return_value = {"url": "http://ha.local"}
        p = _BarePlugin()
        await p.on_start(database=mock_db)
        assert await p.get_setting("url") == "http://ha.local"
        mock_db.get_plugin_config.assert_awaited_once_with("bare")

    async def test_get_setting_returns_default_for_missing_key(self):
        mock_db = AsyncMock()
        mock_db.get_plugin_config.return_value = {}
        p = _BarePlugin()
        await p.on_start(database=mock_db)
        assert await p.get_setting("missing", default=42) == 42
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_plugin_base.py -v`
Expected: FAIL — `AttributeError: 'Plugin' object has no attribute 'get_setting'` (and `has_custom_ui`)

- [ ] **Step 3: Implement the new hooks**

In `src/openacm/plugins/__init__.py`, add `_database: Any = None` as a class attribute right after `author: str = ""` (currently line 62), then add these methods after `get_nav_items` (currently ending at `plugins/__init__.py:145`), and replace the existing `on_start`/`on_stop` block (`plugins/__init__.py:149-160`):

```python
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

    # ── Declare a custom UI (Phase 1 iframe escape hatch) ───────

    def has_custom_ui(self) -> bool:
        """
        If True, this plugin's get_api_router() is expected to serve a
        GET /ui route (self-contained HTML) that the dashboard opens in
        an iframe — used for plugins needing a richer view than the
        generic config form without ever touching the Next.js frontend.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_plugin_base.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest`
Expected: PASS — in particular confirm no existing plugin test assumed `on_start` was a no-op stub with zero side effects.

- [ ] **Step 6: Commit**

```bash
git add src/openacm/plugins/__init__.py tests/unit/test_plugin_base.py
git commit -m "feat(plugins): add get_config_schema, has_custom_ui, get_setting to Plugin base class"
```

---

### Task 3: `PluginManager` enabled-state filtering

**Files:**
- Modify: `src/openacm/plugins/__init__.py:166-311` (the `PluginManager` class)
- Test: `tests/unit/test_plugin_manager_enabled.py`

**Interfaces:**
- Consumes: `Database.is_plugin_enabled(name) -> bool`, `Database.get_all_plugin_states() -> dict` from Task 1.
- Produces: `PluginManager.load_enabled_state(database) -> None` (async), `PluginManager.is_enabled(name: str) -> bool`. Modifies behavior (not signature) of `start_all()`, `get_context_extensions()`, `get_nav_items()`, `get_api_routers()` to skip disabled plugins. `plugins` property still returns ALL discovered plugins (enabled or not) — the `/plugins` page needs to see disabled ones too.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_plugin_manager_enabled.py
import pytest
from unittest.mock import AsyncMock
from openacm.plugins import Plugin, PluginManager


class _NavPlugin(Plugin):
    name = "nav_plugin"

    def get_nav_items(self):
        return [{"path": "/nav-plugin", "label": "Nav Plugin", "icon": "Puzzle"}]

    def get_context_extension(self):
        return "Nav plugin context."

    def get_api_router(self):
        from fastapi import APIRouter
        router = APIRouter(prefix="/nav-plugin")
        return router


class TestPluginManagerEnabledState:
    async def test_plugins_property_lists_disabled_plugins_too(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = False
        await pm.load_enabled_state(mock_db)
        assert [p.name for p in pm.plugins] == ["nav_plugin"]

    async def test_disabled_plugin_excluded_from_nav_items(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = False
        await pm.load_enabled_state(mock_db)
        assert pm.get_nav_items() == []

    async def test_disabled_plugin_excluded_from_context_extensions(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = False
        await pm.load_enabled_state(mock_db)
        assert pm.get_context_extensions() == []

    async def test_disabled_plugin_excluded_from_api_routers(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = False
        await pm.load_enabled_state(mock_db)
        assert pm.get_api_routers() == []

    async def test_enabled_plugin_included_everywhere(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = True
        await pm.load_enabled_state(mock_db)
        assert len(pm.get_nav_items()) == 1
        assert len(pm.get_context_extensions()) == 1
        assert len(pm.get_api_routers()) == 1

    async def test_start_all_skips_on_start_for_disabled_plugin(self):
        pm = PluginManager()
        plugin = _NavPlugin()
        plugin.on_start = AsyncMock()
        pm.register(plugin)
        mock_db = AsyncMock()
        mock_db.is_plugin_enabled.return_value = False
        await pm.load_enabled_state(mock_db)
        await pm.start_all(database=mock_db)
        plugin.on_start.assert_not_awaited()

    def test_is_enabled_defaults_true_before_load_enabled_state(self):
        pm = PluginManager()
        pm.register(_NavPlugin())
        assert pm.is_enabled("nav_plugin") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_plugin_manager_enabled.py -v`
Expected: FAIL — `AttributeError: 'PluginManager' object has no attribute 'load_enabled_state'`

- [ ] **Step 3: Implement enabled-state tracking**

In `src/openacm/plugins/__init__.py`, modify `PluginManager.__init__` (currently `plugins/__init__.py:172-173`):

```python
    def __init__(self):
        self._plugins: list[Plugin] = []
        self._enabled: dict[str, bool] = {}
```

Add this method right after `register()` (currently ending at `plugins/__init__.py:181`):

```python
    async def load_enabled_state(self, database: Any) -> None:
        """Load each discovered plugin's enabled flag from the DB. Call this
        after load_builtin_plugins() and before start_all()."""
        for plugin in self._plugins:
            self._enabled[plugin.name] = await database.is_plugin_enabled(plugin.name)

    def is_enabled(self, name: str) -> bool:
        """Defaults to True if load_enabled_state() hasn't run for this plugin yet."""
        return self._enabled.get(name, True)
```

Modify `start_all()` (currently `plugins/__init__.py:226-272`) to skip disabled plugins entirely — add this as the first line inside the `for plugin in self._plugins:` loop body:

```python
        for plugin in self._plugins:
            if not self.is_enabled(plugin.name):
                log.info("Plugin disabled, skipping start", name=plugin.name)
                continue
            try:
                # Register tools
                ...  # (rest of the existing loop body unchanged)
```

Modify `get_context_extensions()`, `get_nav_items()`, `get_api_routers()` (currently `plugins/__init__.py:282-303`) to filter by `self.is_enabled(p.name)`:

```python
    def get_context_extensions(self) -> list[str]:
        """Collect context snippets from all ENABLED plugins (for brain.py)."""
        return [
            ext for p in self._plugins
            if self.is_enabled(p.name) and (ext := p.get_context_extension())
        ]

    def get_nav_items(self) -> list[dict]:
        """Collect frontend nav items from all ENABLED plugins (for /api/plugins/nav)."""
        items = []
        for p in self._plugins:
            if self.is_enabled(p.name):
                items.extend(p.get_nav_items())
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
```

Leave the `plugins` property (`plugins/__init__.py:305-307`) unchanged — it must keep returning every discovered plugin, disabled or not, since the `/plugins` page needs to list disabled ones too.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_plugin_manager_enabled.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/openacm/plugins/__init__.py tests/unit/test_plugin_manager_enabled.py
git commit -m "feat(plugins): skip disabled plugins in start_all/nav/context/routers"
```

---

### Task 4: Wire `load_enabled_state` into app startup

**Files:**
- Modify: `src/openacm/app.py:551-579` (`_start_plugins`)

**Interfaces:**
- Consumes: `PluginManager.load_enabled_state(database)` from Task 3.

- [ ] **Step 1: Update `_start_plugins`**

In `src/openacm/app.py`, modify `_start_plugins` (currently `app.py:551-579`) to call `load_enabled_state` between discovery and `start_all`:

```python
    async def _start_plugins(self) -> None:
        """Load builtin plugins and start them all."""
        from openacm.plugins import plugin_manager
        from pathlib import Path as _Path

        self._plugin_manager = plugin_manager

        # Auto-discover plugins in openacm.plugins.*
        plugin_manager.load_builtin_plugins()

        # Load each plugin's enabled/disabled flag from the DB
        await plugin_manager.load_enabled_state(self.database)

        # Start each plugin with the full app context
        await plugin_manager.start_all(
            config=self.config,
            database=self.database,
            event_bus=self.event_bus,
            llm_router=self.llm_router,
            brain=self.brain,
            tool_registry=self.tool_registry,
            skill_manager=self.skill_manager,
            activity_watcher=self._activity_watcher,
            cron_scheduler=self._cron_scheduler,
            swarm_manager=self._swarm_manager,
            workspace_root=_Path(self.config.storage.workspace_path),
        )

        loaded = [p.name for p in plugin_manager.plugins if plugin_manager.is_enabled(p.name)]
        if loaded:
            console.print(f"  [green]✓[/green] Plugins: {', '.join(loaded)}")
```

- [ ] **Step 2: Manually verify the app still boots**

Run: `python -m openacm` locally (or however you normally smoke-test this repo) and confirm the startup banner still prints and no plugin-related exception appears in the logs.

- [ ] **Step 3: Commit**

```bash
git add src/openacm/app.py
git commit -m "feat(app): load plugin enabled-state before starting plugins"
```

---

### Task 5: Backend API endpoints — list/toggle/config/docs

**Files:**
- Modify: `src/openacm/web/routers/system.py:241-251` (extend `list_plugins`), and add new routes right after it
- Test: `tests/unit/test_plugins_api.py`

**Interfaces:**
- Consumes: `Database.is_plugin_enabled`, `set_plugin_enabled`, `get_plugin_config`, `set_plugin_config` (Task 1); `Plugin.get_config_schema()`, `has_custom_ui()` (Task 2); `PluginManager.is_enabled()` (Task 3); the existing `client` fixture from `tests/conftest.py:157-183` (an async `httpx.AsyncClient` wired to `openacm.web.server.create_web_server(...)`, itself depending on `app_config, brain, db, tool_registry, event_bus`).

**Important:** `system.py:40` reads `DASHBOARD_TOKEN` from the environment once, inside `register_routes(app)`, which runs when `create_web_server()` builds the app — i.e. when the `client` fixture is instantiated. The env var must be set *before* `client` runs, so add a small fixture that sets it and list it **before** `client` in every test signature (pytest instantiates same-scope fixtures with no dependency between them in the order they're listed).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_plugins_api.py
import pytest
from openacm.plugins import Plugin, plugin_manager

TEST_TOKEN = "test-dashboard-token"


@pytest.fixture
def dashboard_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", TEST_TOKEN)
    return TEST_TOKEN


@pytest.fixture
def auth_headers(dashboard_token):
    return {"Authorization": f"Bearer {dashboard_token}"}


class _ConfigPlugin(Plugin):
    name = "config_plugin"
    version = "1.0.0"
    description = "Test plugin"
    author = "test"

    def get_config_schema(self):
        return [
            {"key": "url", "label": "URL", "type": "text", "required": True, "help": ""},
            {"key": "token", "label": "Token", "type": "password", "required": True, "help": ""},
        ]


@pytest.fixture(autouse=True)
def _register_test_plugin():
    plugin_manager._plugins = [p for p in plugin_manager._plugins if p.name != "config_plugin"]
    plugin_manager.register(_ConfigPlugin())
    plugin_manager._enabled["config_plugin"] = True
    yield
    plugin_manager._plugins = [p for p in plugin_manager._plugins if p.name != "config_plugin"]
    plugin_manager._enabled.pop("config_plugin", None)


class TestPluginsListEndpoint:
    async def test_list_includes_enabled_and_schema_flags(self, dashboard_token, client, auth_headers):
        resp = await client.get("/api/plugins", headers=auth_headers)
        assert resp.status_code == 200
        entry = next(p for p in resp.json() if p["name"] == "config_plugin")
        assert entry["enabled"] is True
        assert entry["has_config_schema"] is True
        assert entry["has_custom_ui"] is False


class TestPluginToggleEndpoint:
    async def test_toggle_disables_plugin(self, dashboard_token, client, auth_headers):
        resp = await client.post("/api/plugins/config_plugin/toggle", json={"enabled": False}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    async def test_toggle_unknown_plugin_404s(self, dashboard_token, client, auth_headers):
        resp = await client.post("/api/plugins/does_not_exist/toggle", json={"enabled": False}, headers=auth_headers)
        assert resp.status_code == 404


class TestPluginConfigEndpoints:
    async def test_get_config_returns_schema_and_masks_password(self, dashboard_token, client, auth_headers):
        await client.post(
            "/api/plugins/config_plugin/config",
            json={"url": "http://ha.local:8123", "token": "secret123"},
            headers=auth_headers,
        )
        resp = await client.get("/api/plugins/config_plugin/config", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["values"]["url"] == "http://ha.local:8123"
        assert body["values"]["token"] == "***"

    async def test_post_config_missing_required_field_400s(self, dashboard_token, client, auth_headers):
        resp = await client.post(
            "/api/plugins/config_plugin/config",
            json={"url": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_post_config_unchanged_password_marker_preserves_existing(self, dashboard_token, client, auth_headers):
        await client.post(
            "/api/plugins/config_plugin/config",
            json={"url": "http://ha.local:8123", "token": "secret123"},
            headers=auth_headers,
        )
        await client.post(
            "/api/plugins/config_plugin/config",
            json={"url": "http://ha.local:9999", "token": "***"},
            headers=auth_headers,
        )
        resp = await client.get("/api/plugins/config_plugin/config", headers=auth_headers)
        assert resp.json()["values"]["url"] == "http://ha.local:9999"
        assert resp.json()["values"]["token"] == "***"  # still set, still masked


class TestPluginDocsEndpoint:
    async def test_docs_returns_markdown_text(self, dashboard_token, client, auth_headers):
        resp = await client.get("/api/plugins/docs", headers=auth_headers)
        assert resp.status_code == 200
        assert "plugin" in resp.text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_plugins_api.py -v`
Expected: FAIL — 404s / `AttributeError` for the routes that don't exist yet (`/toggle`, `/config`, `/docs`), and the list endpoint test fails because `enabled`/`has_config_schema`/`has_custom_ui` keys are missing.

- [ ] **Step 3: Extend the list endpoint and add the new routes**

In `src/openacm/web/routers/system.py`, replace the existing `list_plugins` (currently `system.py:241-251`) and add the new endpoints right after it:

```python
    @app.get("/api/plugins")
    async def list_plugins():
        """Return metadata for all loaded plugins, enabled or not."""
        try:
            from openacm.plugins import plugin_manager
            return [
                {
                    "name": p.name,
                    "version": p.version,
                    "description": p.description,
                    "author": p.author,
                    "enabled": plugin_manager.is_enabled(p.name),
                    "has_config_schema": bool(p.get_config_schema()),
                    "has_custom_ui": p.has_custom_ui(),
                }
                for p in plugin_manager.plugins
            ]
        except Exception:
            return []

    def _get_plugin_or_404(name: str):
        from openacm.plugins import plugin_manager
        for p in plugin_manager.plugins:
            if p.name == name:
                return p
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")

    @app.post("/api/plugins/{name}/toggle")
    async def toggle_plugin(name: str, request: Request):
        """Enable or disable a plugin. Takes effect on next restart."""
        from openacm.plugins import plugin_manager
        _get_plugin_or_404(name)
        data = await request.json()
        enabled = bool(data.get("enabled", True))
        await _state.database.set_plugin_enabled(name, enabled)
        return {"name": name, "enabled": enabled}

    @app.get("/api/plugins/{name}/config")
    async def get_plugin_config(name: str):
        """Return this plugin's config schema plus current values (passwords masked)."""
        plugin = _get_plugin_or_404(name)
        schema = plugin.get_config_schema()
        saved = await _state.database.get_plugin_config(name)
        values = {}
        for field in schema:
            key = field["key"]
            if field.get("type") == "password":
                values[key] = "***" if saved.get(key) else ""
            else:
                values[key] = saved.get(key, "")
        return {"schema": schema, "values": values}

    @app.post("/api/plugins/{name}/config")
    async def save_plugin_config(name: str, request: Request):
        """Save this plugin's config. A password field sent as '***' keeps its existing value."""
        plugin = _get_plugin_or_404(name)
        schema = plugin.get_config_schema()
        incoming = await request.json()
        existing = await _state.database.get_plugin_config(name)

        merged = dict(existing)
        for field in schema:
            key = field["key"]
            if key not in incoming:
                continue
            value = incoming[key]
            if field.get("type") == "password" and value == "***":
                continue  # unchanged marker — keep existing value
            merged[key] = value

        missing = [
            f["label"] for f in schema
            if f.get("required") and not merged.get(f["key"])
        ]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required field(s): {', '.join(missing)}",
            )

        await _state.database.set_plugin_config(name, merged)
        return {"status": "ok"}

    @app.get("/api/plugins/docs")
    async def get_plugin_docs():
        """Return the plugin-authoring guide as raw markdown for the dashboard's docs viewer."""
        from openacm.core.config import _find_project_root
        root = _find_project_root()
        doc_path = root / "docs" / "24-plugins.md"
        if not doc_path.exists():
            raise HTTPException(status_code=404, detail="Plugin docs not found")
        return PlainTextResponse(doc_path.read_text(encoding="utf-8"))
```

`system.py:18` currently imports `from fastapi.responses import HTMLResponse, FileResponse, Response, JSONResponse` — add `PlainTextResponse` to that line. `HTTPException` and `Request` are already imported at `system.py:14-17`, no change needed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_plugins_api.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/openacm/web/routers/system.py tests/unit/test_plugins_api.py
git commit -m "feat(api): add plugin toggle/config/docs endpoints"
```

---

### Task 6: Frontend hooks for the plugins API

**Files:**
- Create: `frontend/hooks/use-plugins.ts`
- Modify: `frontend/hooks/use-api.ts:7-47` (`FetchOptions` interface and `fetchAPI`)

**Interfaces:**
- Consumes: `useAPI()` / `fetchAPI` from `frontend/hooks/use-api.ts`, `useIsAuthenticated` (same pattern as `frontend/hooks/use-setup.ts:24-34`).
- Produces: `usePlugins()`, `useTogglePlugin()`, `useRestartSystem()`, `usePluginConfig(name: string)`, `useSavePluginConfig(name: string)`, `usePluginDocs()` — all React Query hooks. Also a new `raw?: boolean` option on `fetchAPI`'s `FetchOptions`.

- [ ] **Step 1: Add a `raw` text-response option to `fetchAPI`**

`fetchAPI` (`use-api.ts:12-47`) always calls `response.json()` — the new docs endpoint returns plain markdown text, which isn't valid JSON and would throw. Modify `use-api.ts`:

```typescript
interface FetchOptions extends RequestInit {
  requiresAuth?: boolean;
  raw?: boolean; // if true, return response.text() instead of response.json()
}
```

And change the return line (`use-api.ts:42`) from `return await response.json();` to:

```typescript
      return options.raw ? await response.text() : await response.json();
```

- [ ] **Step 2: Create the hooks file**

```typescript
// frontend/hooks/use-plugins.ts
'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAPI, useIsAuthenticated } from '@/hooks/use-api';
import { toast } from 'sonner';

export interface PluginInfo {
  name: string;
  version: string;
  description: string;
  author: string;
  enabled: boolean;
  has_config_schema: boolean;
  has_custom_ui: boolean;
}

export interface PluginConfigField {
  key: string;
  label: string;
  type: 'text' | 'password' | 'number' | 'boolean';
  required: boolean;
  help: string;
}

export interface PluginConfigResponse {
  schema: PluginConfigField[];
  values: Record<string, string>;
}

export function usePlugins() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<PluginInfo[]>({
    queryKey: ['plugins'],
    queryFn: () => fetchAPI('/api/plugins'),
    enabled: isAuthenticated,
    staleTime: 0,
    refetchOnMount: 'always',
  });
}

export function useTogglePlugin() {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      fetchAPI(`/api/plugins/${name}/toggle`, {
        method: 'POST',
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plugins'] });
    },
    onError: () => toast.error('Failed to toggle plugin'),
  });
}

export function useRestartSystem() {
  const { fetchAPI } = useAPI();

  return useMutation({
    mutationFn: () => fetchAPI('/api/system/restart', { method: 'POST' }),
    onSuccess: () => toast.success('Reiniciando... el dashboard volverá en unos segundos'),
    onError: () => toast.error('Failed to restart'),
  });
}

export function usePluginConfig(name: string) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<PluginConfigResponse>({
    queryKey: ['plugin-config', name],
    queryFn: () => fetchAPI(`/api/plugins/${name}/config`),
    enabled: isAuthenticated && !!name,
    staleTime: 0,
  });
}

export function useSavePluginConfig(name: string) {
  const { fetchAPI } = useAPI();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (values: Record<string, string>) =>
      fetchAPI(`/api/plugins/${name}/config`, {
        method: 'POST',
        body: JSON.stringify(values),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plugin-config', name] });
      toast.success('Configuración guardada');
    },
    onError: (err: Error) => toast.error(err.message || 'Failed to save config'),
  });
}

export function usePluginDocs() {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<string>({
    queryKey: ['plugin-docs'],
    queryFn: () => fetchAPI('/api/plugins/docs', { raw: true }),
    enabled: isAuthenticated,
    staleTime: Infinity,
  });
}
```

- [ ] **Step 3: Manually verify the hooks compile**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new type errors introduced by `use-api.ts` or `use-plugins.ts`

- [ ] **Step 4: Commit**

```bash
git add frontend/hooks/use-api.ts frontend/hooks/use-plugins.ts
git commit -m "feat(frontend): add plugin API hooks and a raw-text fetchAPI option"
```

---

### Task 7: `PluginConfigForm` generic component

**Files:**
- Create: `frontend/components/plugins/plugin-config-form.tsx`

**Interfaces:**
- Consumes: `PluginConfigField`, `usePluginConfig`, `useSavePluginConfig` from Task 6.
- Produces: `<PluginConfigForm pluginName={string} onSaved={() => void} />` React component.

- [ ] **Step 1: Create the component**

```tsx
// frontend/components/plugins/plugin-config-form.tsx
'use client';

import { useState, useEffect } from 'react';
import { usePluginConfig, useSavePluginConfig } from '@/hooks/use-plugins';
import { Loader2 } from 'lucide-react';

export function PluginConfigForm({
  pluginName,
  onSaved,
}: {
  pluginName: string;
  onSaved?: () => void;
}) {
  const { data, isLoading } = usePluginConfig(pluginName);
  const saveConfig = useSavePluginConfig(pluginName);
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (data?.values) setValues(data.values);
  }, [data]);

  if (isLoading || !data) {
    return <Loader2 size={20} className="animate-spin" style={{ color: 'var(--acm-fg-4)' }} />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await saveConfig.mutateAsync(values);
    onSaved?.();
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {data.schema.map((field) => (
        <div key={field.key}>
          <label className="label" style={{ display: 'block', marginBottom: 6 }}>
            {field.label}
            {field.required && <span style={{ color: 'var(--acm-err)' }}> *</span>}
          </label>
          {field.type === 'boolean' ? (
            <input
              type="checkbox"
              checked={values[field.key] === 'true'}
              onChange={(e) =>
                setValues((v) => ({ ...v, [field.key]: e.target.checked ? 'true' : 'false' }))
              }
            />
          ) : (
            <input
              type={field.type === 'password' ? 'password' : field.type === 'number' ? 'number' : 'text'}
              value={values[field.key] ?? ''}
              onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
              placeholder={field.help}
              className="acm-input"
              required={field.required}
            />
          )}
          {field.help && (
            <p style={{ fontSize: 12, color: 'var(--acm-fg-4)', marginTop: 4 }}>{field.help}</p>
          )}
        </div>
      ))}
      <button type="submit" disabled={saveConfig.isPending} className="btn-primary">
        {saveConfig.isPending ? <Loader2 size={16} className="animate-spin" /> : 'Guardar'}
      </button>
    </form>
  );
}
```

- [ ] **Step 2: Manually verify it compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new type errors

- [ ] **Step 3: Commit**

```bash
git add frontend/components/plugins/plugin-config-form.tsx
git commit -m "feat(frontend): add generic PluginConfigForm component"
```

---

### Task 8: `/plugins` dashboard page

**Files:**
- Create: `frontend/app/plugins/page.tsx`
- Modify: `frontend/components/layout/sidebar.tsx` (add a static nav entry — this is core dashboard functionality, not a plugin-provided nav item)
- Modify: `frontend/lib/translations.ts` (add a `plugins` key under `navigation`, matching the existing `config: 'Configuration'` entry at `translations.ts:47`)

**Interfaces:**
- Consumes: `usePlugins`, `useTogglePlugin`, `usePluginDocs` (Task 6), `PluginConfigForm` (Task 7).

- [ ] **Step 1: Add the nav label**

In `frontend/lib/translations.ts`, add this line right after `config: 'Configuration',` (currently `translations.ts:47`):

```typescript
    plugins: 'Plugins',
```

- [ ] **Step 2: Add the sidebar entry**

In `frontend/components/layout/sidebar.tsx`, add this line right after the `/config` entry (currently `sidebar.tsx:57`) — check the top of the file for the `Puzzle` icon import from `lucide-react` and add it if missing, alongside the other icon imports (`Settings`, `Wrench`, etc.):

```typescript
  { href: '/plugins', label: t.plugins, icon: Puzzle },
```

- [ ] **Step 3: Create the plugins page**

```tsx
// frontend/app/plugins/page.tsx
'use client';

import { useState } from 'react';
import { usePlugins, useTogglePlugin, usePluginDocs, useRestartSystem } from '@/hooks/use-plugins';
import { PluginConfigForm } from '@/components/plugins/plugin-config-form';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Loader2, Puzzle, ExternalLink } from 'lucide-react';

export default function PluginsPage() {
  const { data: plugins, isLoading } = usePlugins();
  const togglePlugin = useTogglePlugin();
  const restartSystem = useRestartSystem();
  const [configOpen, setConfigOpen] = useState<string | null>(null);
  const [showDocs, setShowDocs] = useState(false);
  const [needsRestart, setNeedsRestart] = useState(false);

  const handleToggle = (name: string, enabled: boolean) => {
    togglePlugin.mutate({ name, enabled });
    setNeedsRestart(true);
  };

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1 className="font-bold" style={{ fontSize: 24, color: 'var(--acm-fg)' }}>Plugins</h1>
        <button className="btn-secondary" onClick={() => setShowDocs((s) => !s)}>
          {showDocs ? 'Ver plugins' : '¿Cómo creo un plugin?'}
        </button>
      </div>

      {needsRestart && (
        <div
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: 'var(--acm-accent-soft)', border: '1px solid oklch(0.84 0.16 82 / 0.18)',
            borderRadius: 8, padding: '10px 16px', marginBottom: 16, fontSize: 13,
          }}
        >
          <span>Reinicia el contenedor para aplicar los cambios de plugins.</span>
          <button
            className="btn-primary"
            disabled={restartSystem.isPending}
            onClick={() => restartSystem.mutate()}
          >
            {restartSystem.isPending ? <Loader2 size={14} className="animate-spin" /> : 'Reiniciar ahora'}
          </button>
        </div>
      )}

      {showDocs ? (
        <PluginDocsViewer />
      ) : isLoading ? (
        <Loader2 size={24} className="animate-spin" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {(plugins ?? []).map((p) => (
            <div
              key={p.name}
              style={{
                background: 'var(--acm-card)',
                border: '1px solid var(--acm-border)',
                borderRadius: 10,
                padding: 20,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <Puzzle size={18} style={{ color: 'var(--acm-accent)' }} />
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--acm-fg)' }}>
                    {p.name} <span style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>v{p.version}</span>
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--acm-fg-3)' }}>{p.description}</div>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {p.has_custom_ui && (
                  <a href={`/api/plugins/${p.name}/ui`} target="_blank" rel="noopener noreferrer">
                    <ExternalLink size={16} style={{ color: 'var(--acm-fg-4)' }} />
                  </a>
                )}
                {p.has_config_schema && (
                  <button className="btn-secondary" onClick={() => setConfigOpen(p.name)}>
                    Configurar
                  </button>
                )}
                <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <input
                    type="checkbox"
                    checked={p.enabled}
                    onChange={(e) => handleToggle(p.name, e.target.checked)}
                  />
                  {p.enabled ? 'Activo' : 'Desactivado'}
                </label>
              </div>
            </div>
          ))}
        </div>
      )}

      {configOpen && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
          }}
          onClick={() => setConfigOpen(null)}
        >
          <div
            style={{ background: 'var(--acm-card)', borderRadius: 12, padding: 28, width: 480 }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ marginBottom: 16, color: 'var(--acm-fg)' }}>Configurar {configOpen}</h3>
            <PluginConfigForm pluginName={configOpen} onSaved={() => setConfigOpen(null)} />
          </div>
        </div>
      )}
    </div>
  );
}

function PluginDocsViewer() {
  const { data: markdown, isLoading } = usePluginDocs();
  if (isLoading) return <Loader2 size={24} className="animate-spin" />;
  return (
    <div className="mono" style={{ color: 'var(--acm-fg-2)', lineHeight: 1.7 }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown ?? ''}</ReactMarkdown>
    </div>
  );
}
```

Check whether `remark-gfm` is already a frontend dependency (`frontend/package.json` lists `react-markdown` per earlier exploration, confirm `remark-gfm` too — if it's missing, add it: `cd frontend && npm install remark-gfm`).

- [ ] **Step 4: Build the frontend to verify no errors**

Run: `cd frontend && npm run build`
Expected: build succeeds, `dist/plugins/index.html` (or similar, matching the `trailingSlash: true` export convention) is produced.

- [ ] **Step 5: Manually verify in a browser**

Run the app locally (however this repo is normally run for manual checks) and visit `/plugins/` — confirm the plugin list renders (at minimum `gmail_classifier` should show up), the enable/disable checkbox calls the toggle endpoint (check Network tab), and "¿Cómo creo un plugin?" renders the markdown doc.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/plugins/page.tsx frontend/components/layout/sidebar.tsx frontend/lib/translations.ts
git commit -m "feat(frontend): add /plugins dashboard page"
```

---

### Task 9: Update the plugin-authoring guide

**Files:**
- Modify: `docs/24-plugins.md`

- [ ] **Step 1: Add documentation for the two new hooks**

Read the current `docs/24-plugins.md` in full first (it documents the existing hooks — match its existing tone/format exactly). Add a new section documenting:
- `get_config_schema()` — the field dict format (`key`, `label`, `type`, `required`, `help`), and that values are read back via `await self.get_setting(key, default=None)`.
- `has_custom_ui()` — that returning `True` means the plugin's `get_api_router()` must serve a `GET /ui` route with self-contained HTML, and the dashboard will open it in a new tab/iframe from the `/plugins` page.
- The requirement that any plugin overriding `on_start()` must call `await super().on_start(**app_context)` first, or `get_setting()` won't work.
- That enabling/disabling a plugin from the `/plugins` page takes effect on the next restart, not immediately.

- [ ] **Step 2: Commit**

```bash
git add docs/24-plugins.md
git commit -m "docs: document get_config_schema, has_custom_ui, and the /plugins dashboard page"
```

---

### Task 10: Full regression pass

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest`
Expected: PASS, no regressions

- [ ] **Step 2: Run the frontend build**

Run: `cd frontend && npm run build`
Expected: builds clean

- [ ] **Step 3: Rebuild and run the Docker image end-to-end**

Since this project is deployed via Docker on a NAS (see `docker/Dockerfile`, `docker/docker-compose.yml`), rebuild the image and confirm: the app boots (no crash from the `plugin_state` migration on an existing DB), `/plugins` loads in the browser, toggling `gmail_classifier` off + restarting the container actually removes it from the sidebar nav, and toggling it back on + restarting brings it back with its existing data intact (categories, digest settings, etc. — confirming Task 1's migration didn't disturb anything).

- [ ] **Step 4: Final commit if any fixups were needed**

```bash
git add -A
git commit -m "fix: address issues found in full regression pass"
```
