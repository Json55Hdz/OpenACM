# Plugin System

OpenACM's plugin system lets you bundle tools, intent keywords, LLM context, and frontend nav items into a single self-contained package — without touching core source files. Plugins are auto-discovered at startup and can also be installed as regular pip packages.

---

## How It Works

At startup, `app.py` calls:

```
PluginManager.load_builtin_plugins()   ← scans openacm/plugins/*/
PluginManager.start_all(...)           ← calls on_start() on each plugin
```

Each plugin subdirectory inside `src/openacm/plugins/` that exposes a module-level `PLUGIN` instance is loaded automatically. No registration code needed in `app.py`.

---

## Plugin Base Class

All plugins inherit from `openacm.plugins.Plugin`:

```python
from openacm.plugins import Plugin

class MyPlugin(Plugin):
    name        = "my_feature"   # unique, snake_case
    version     = "1.0.0"
    description = "Short description"
    author      = "You"

    # ── Tools ──────────────────────────────────────────────
    def get_tool_modules(self) -> list:
        """Return Python modules that contain @tool-decorated functions."""
        from openacm.plugins.my_feature import tools
        return [tools]

    # ── Skills ─────────────────────────────────────────────
    def get_skills(self) -> list[dict]:
        """Skill definitions auto-loaded into the DB at startup (skipped if name exists)."""
        return [
            {
                "name":        "my-skill",
                "description": "What it does",
                "content":     "# My Skill\n...",
                "category":    "general",
            }
        ]

    # ── API routes ──────────────────────────────────────────
    def get_api_router(self):
        """Return a FastAPI APIRouter mounted under /api/."""
        from fastapi import APIRouter
        router = APIRouter(prefix="/my-feature")

        @router.get("/status")
        async def status():
            return {"ok": True}

        return router

    # ── LLM system prompt ──────────────────────────────────
    def get_context_extension(self) -> str:
        """Short markdown snippet appended to the system prompt on every message."""
        return (
            "## My Feature\n"
            "When the user asks about X, call `my_tool`."
        )

    # ── Intent routing ─────────────────────────────────────
    def get_intent_keywords(self) -> dict[str, list[str]]:
        """Keywords that trigger inclusion of this plugin's tools in LLM calls."""
        return {
            "my_feature": ["keyword1", "keyword2", "palabra clave"],
        }

    # ── Frontend sidebar ───────────────────────────────────
    def get_nav_items(self) -> list[dict]:
        """Sidebar navigation items added to the frontend automatically."""
        return [
            {
                "path":    "/my-page",
                "label":   "My Feature",
                "icon":    "Star",          # any lucide-react icon name
                "section": "main",          # "main" or "bottom"
            }
        ]

    # ── Lifecycle ──────────────────────────────────────────
    async def on_start(self, *, tool_registry, database, event_bus,
                       llm_router, brain, skill_manager,
                       activity_watcher, cron_scheduler, swarm_manager,
                       workspace_root, config, **_) -> None:
        """Called after all core systems are up. Inject dependencies here."""

    async def on_stop(self) -> None:
        """Called on shutdown. Clean up connections, background tasks, etc."""


PLUGIN = MyPlugin()
```

Every method has a safe default (returns `[]`, `""`, `None`, or does nothing), so you only override what you need.

---

## Creating a Plugin (Step by Step)

### 1. Create the package

```
src/openacm/plugins/
└── my_feature/
    ├── __init__.py      ← defines PLUGIN
    └── tools.py         ← @tool-decorated functions
```

### 2. Write your tools (`tools.py`)

```python
from openacm.tools.base import tool

@tool(
    name="my_tool",
    description="Does something useful",
    parameters={
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "The input value"},
        },
        "required": ["input"],
    },
    risk_level="low",
    category="my_feature",
)
async def my_tool(input: str, _sandbox=None, _brain=None, **_) -> str:
    return f"Processed: {input}"
```

### 3. Define the plugin (`__init__.py`)

```python
from openacm.plugins import Plugin

class MyFeaturePlugin(Plugin):
    name = "my_feature"
    version = "1.0.0"
    description = "Example plugin"

    def get_tool_modules(self):
        from openacm.plugins.my_feature import tools
        return [tools]

    def get_intent_keywords(self):
        return {"my_feature": ["my keyword", "mi palabra"]}

    def get_nav_items(self):
        return [{"path": "/my-feature", "label": "My Feature", "icon": "Star"}]

    async def on_start(self, *, database=None, event_bus=None, **_):
        # Store references your tools need
        from openacm.plugins.my_feature import tools
        tools._database = database

    async def on_stop(self):
        pass


PLUGIN = MyFeaturePlugin()
```

### 4. Done — no registration needed

OpenACM auto-discovers your plugin on next startup. The tools are registered, keywords are merged into the intent router, and the nav item appears in the sidebar.

---

## Skills

Skills are markdown documents that get injected into the LLM system prompt when active. Plugins can ship skills that auto-load into the DB at startup:

```python
def get_skills(self) -> list[dict]:
    return [
        {
            "name":        "my-skill",           # unique name — skipped if already exists
            "description": "Enables X behavior",
            "content":     "# My Skill\n\nWhen the user asks about X, do Y.",
            "category":    "development",         # freeform label shown in dashboard
        }
    ]
```

- Skills are inserted once (on first load). If the name already exists in the DB it is not overwritten, so users can edit them freely.
- Users can activate/deactivate them from the dashboard Skills page like any other skill.

---

## API Routes

Plugins can expose their own FastAPI endpoints, mounted automatically under `/api/`:

```python
def get_api_router(self):
    from fastapi import APIRouter
    router = APIRouter(prefix="/my-feature")

    @router.get("/status")
    async def status():
        return {"ok": True}

    @router.post("/do-thing")
    async def do_thing(body: dict):
        ...
        return {"result": "done"}

    return router
```

Routes defined with `prefix="/my-feature"` are available at `/api/my-feature/status`, `/api/my-feature/do-thing`, etc.

Plugin routers are mounted when the FastAPI app is created, after all plugins have started — so dependencies injected in `on_start()` are available inside route handlers via closure.

---

## Intent Keywords

Intent keywords control when your plugin's tools are sent to the LLM. The tool router matches them against the user's message before calling the LLM — only relevant tools are included in each call (cheaper, faster, less noise).

```python
def get_intent_keywords(self):
    return {
        # Category name (new or existing)
        "my_feature": [
            "keyword",          # English
            "palabra clave",    # Spanish — multi-language supported
            "action verb",
        ],
    }
```

If you use an existing category name (e.g. `"system"`, `"file"`, `"web"`), your keywords are **merged** into that category's list. If you use a new name, a new category is created.

---

## LLM Context Extension

The string returned by `get_context_extension()` is appended to the system prompt on every message. Keep it short — it costs tokens on every call.

```python
def get_context_extension(self) -> str:
    return (
        "## My Feature\n"
        "Call `my_tool` when the user asks about X. "
        "Never call it for Y."
    )
```

Use it to tell the LLM:
- When to call your tools
- Any constraints or caveats
- Output format expectations

---

## Frontend Nav Items

The sidebar fetches `/api/plugins/nav` on mount and renders any items returned:

```python
def get_nav_items(self) -> list[dict]:
    return [
        {
            "path":    "/my-page",     # Must match a Next.js route under frontend/app/
            "label":   "My Page",      # Display name
            "icon":    "Zap",          # lucide-react icon (https://lucide.dev/icons)
            "section": "main",         # "main" (top area) or "bottom" (settings area)
        }
    ]
```

The frontend page itself (`frontend/app/my-page/page.tsx`) still needs to be created manually.

---

## Lifecycle Hooks

### `on_start(**app_context)`

Called once, after all core systems are initialized. Use it to:
- Start background watchers or schedulers
- Inject `database`, `event_bus`, `llm_router`, etc. into your tool modules
- Subscribe to EventBus events

Available kwargs:

| Name | Type | Description |
|---|---|---|
| `config` | `dict` | Full app config |
| `database` | `Database` | SQLite database instance |
| `event_bus` | `EventBus` | Pub/sub event system |
| `llm_router` | `LLMRouter` | LLM call interface |
| `brain` | `Brain` | Message processing core |
| `tool_registry` | `ToolRegistry` | Live tool registry |
| `skill_manager` | `SkillManager` | Skills system |
| `activity_watcher` | `ActivityWatcher` | OS activity watcher |
| `cron_scheduler` | `CronScheduler` | Cron job scheduler |
| `swarm_manager` | `SwarmManager` | Multi-agent swarm system |
| `workspace_root` | `Path` | Base workspace directory |

### `on_stop()`

Called on graceful shutdown. Stop your background tasks here.

---

## Real Example: Content Automation Plugin

`src/openacm/plugins/content/` is the first built-in plugin. It:

- Registers `capture_content_moment`, `generate_content_for_moment`, `list_content_moments`, etc. from `content_gen_tool.py` and `social_media_tool.py`
- Adds achievement keywords (`"funcionó"`, `"it works"`, `"listo"`, etc.) to trigger content tools
- Injects a system prompt hint telling the LLM to call `capture_content_moment` silently when something share-worthy happens
- Adds a `/content` nav item to the sidebar
- Starts a `ContentSessionWatcher` background task in `on_start()`

---

## pip-Installable Plugins

Plugins can be distributed as pip packages and registered via Python entry points — no code changes to OpenACM required:

```toml
# pyproject.toml of your package
[project.entry-points."openacm.plugins"]
my_feature = "my_package:PLUGIN"
```

After `pip install my-package`, OpenACM discovers and loads it automatically on next startup alongside built-in plugins.

---

## Frontend Pages

Plugin frontend pages (Next.js routes) must currently be placed physically inside `frontend/app/`. There is no dynamic frontend loading — Next.js compiles pages at build time.

**Recommended workflow:**
1. Create `frontend/app/my-feature/page.tsx`
2. Register the nav item via `get_nav_items()` — the sidebar picks it up automatically at runtime
3. The page fetches data from your plugin's API routes (`/api/my-feature/...`)

This keeps the backend fully plug-and-play while the frontend requires a project rebuild when adding new pages.

---

## Summary

| What | Where | Status |
|---|---|---|
| Tools | `get_tool_modules()` → `@tool` modules | ✅ Plug-and-play |
| Skills | `get_skills()` → auto-loaded to DB | ✅ Plug-and-play |
| API routes | `get_api_router()` → mounted under `/api/` | ✅ Plug-and-play |
| LLM behavior | `get_context_extension()` | ✅ Plug-and-play |
| Intent routing | `get_intent_keywords()` | ✅ Plug-and-play |
| Frontend nav | `get_nav_items()` → `/api/plugins/nav` | ✅ Plug-and-play |
| Frontend pages | `frontend/app/my-page/page.tsx` | ⚠️ Manual (requires rebuild) |
| PyPI install | `entry-points."openacm.plugins"` | ✅ Supported |
| Startup/shutdown | `on_start()` / `on_stop()` | ✅ Plug-and-play |
