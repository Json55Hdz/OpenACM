# Plugin System Phase 1 — Design

## Context

OpenACM already has a working plugin system (`src/openacm/plugins/`): `PluginManager` discovers plugins by scanning `src/openacm/plugins/` (directory drop-in, no core edits) and via pip `entry_points`, then calls each plugin's hooks (`get_tool_modules`, `get_skills`, `get_api_router`, `get_context_extension`, `get_intent_keywords`, `get_nav_items`, `on_start`/`on_stop`) once at startup (`app.py`). This is genuinely "drop a folder in and it works" for the backend.

This is Phase 1 of a 3-phase plan:
- **Phase 1 (this spec):** make the plugin system visible and configurable from the dashboard.
- **Phase 2 (later):** build a Home Assistant integration plugin on top of this, retiring the hardcoded `tools/iot/drivers/` (Tuya, LG TV, Miio) in favor of one plugin that talks to Home Assistant's API.
- **Phase 3 (later, separate project):** a public plugin gallery hosted on the user's own domain to publish/install plugins from.

Phase 1 does **not** include: hot enable/disable without a restart (evaluated, decided against for complexity vs. benefit — see Decisions below), a UI-based plugin installer/uploader, or a public gallery.

## Goals

1. A dashboard page listing every discovered plugin (enabled or not, with metadata).
2. A way to enable/disable a plugin and configure its settings (API keys, URLs, etc.) from the dashboard instead of hand-editing `.env`.
3. A visible link to the plugin-authoring guide for anyone who wants to write a new one.
4. A mechanism so a future plugin can ship a richer custom view without ever requiring a Next.js rebuild.

## Decisions

- **Enable/disable applies on next restart, not live.** A true hot-toggle would require: an `unregister_by_plugin()` on `ToolRegistry` (currently absent), untangling the shared `INTENT_KEYWORDS` dict which merges plugin keywords in irreversibly today, and manually removing mounted FastAPI routes from `app.router.routes` plus resetting the cached OpenAPI schema. Given the container restarts in seconds (`restart: unless-stopped`, confirmed in production use), this complexity isn't worth it for Phase 1. The dashboard restart is one click away (existing `POST /api/system/restart` endpoint).
- **Plugin settings live in SQLite, not `.env`.** Consistent with how custom LLM providers are already stored (JSON blob, not env vars) — avoids programmatically editing a hand-maintained `.env` file.
- **Config schema, not per-plugin frontend code.** A plugin declares its settings fields (`get_config_schema()`); one generic React form renders any plugin's settings. Plugins needing a genuinely custom view use the iframe escape hatch (see below), never a hand-written `.tsx` page.

## Data model

New table, migration `_SCHEMA_VERSION` 30 → 31 in `src/openacm/storage/database.py`:

```sql
CREATE TABLE IF NOT EXISTS plugin_state (
    plugin_name  TEXT PRIMARY KEY,
    enabled      BOOLEAN NOT NULL DEFAULT 1,
    config_json  TEXT NOT NULL DEFAULT '{}'
);
```

A plugin with no row is treated as enabled by default (so existing plugins like `gmail_classifier` aren't silently disabled after this ships).

## Backend changes

**`src/openacm/plugins/__init__.py` (`Plugin` base class):**
- New optional hook: `get_config_schema(self) -> list[dict]`. Each field: `{"key": str, "label": str, "type": "text"|"password"|"number"|"boolean", "required": bool, "help": str}`. Default implementation returns `[]` (no configurable settings).
- New optional hook: `has_custom_ui(self) -> bool`, default `False`. If a plugin returns `True`, its `get_api_router()` is expected to serve a `GET /ui` route (self-contained HTML) at whatever prefix its router mounts under.
- Plugins read their own saved settings via a new helper, `self.get_setting(key, default=None)`, implemented on the base `Plugin` class. It reads `plugin_state.config_json` using a `self._database` reference the base class captures in `on_start(**app_context)` before delegating to the subclass's override — subclasses that override `on_start` must call `super().on_start(**app_context)` first (documented in the plugin guide update) so this keeps working.

**`PluginManager.load_builtin_plugins()`:** before registering a discovered plugin's tools/routes/nav/keywords, read its `enabled` flag from `plugin_state` (default `True` if no row). If disabled, skip registration entirely for this process lifetime — same effect as the plugin not existing, no new "unregister" code needed.

**New API endpoints** (`src/openacm/web/routers/system.py`, alongside the existing `/api/plugins` and `/api/plugins/nav`):
- `GET /api/plugins` — extend existing response with `enabled`, `has_config_schema`, `has_custom_ui` per plugin.
- `POST /api/plugins/{name}/toggle` — flips `enabled` in `plugin_state` (upserting a row if none exists). Returns the new state; does not restart anything itself.
- `GET /api/plugins/{name}/config` — returns the plugin's `get_config_schema()` plus current saved values, with any field of `type: "password"` masked (same convention as the existing custom-providers endpoint: return `"***"` if set, blank if not).
- `POST /api/plugins/{name}/config` — validates keys against the schema, merges into `config_json` (a blank/unsent password field means "leave unchanged," matching the custom-providers pattern already in `config.py`).

## Frontend changes

**New page `frontend/app/plugins/page.tsx`** (added to the core dashboard nav, not a plugin-provided nav item):
- Table/list of all plugins from `GET /api/plugins`: name, version, author, description, enabled toggle.
- Toggling calls `POST /api/plugins/{name}/toggle`, then shows a toast + inline banner: "Reinicia para aplicar" with a button that calls the existing `POST /api/system/restart`.
- "Configurar" button (shown only if `has_config_schema`) opens a modal with a form generated purely from the schema response — one generic component (`PluginConfigForm`), reused for every plugin, no plugin-specific frontend code ever needed for settings.
- "Abrir vista completa" button (shown only if `has_custom_ui`) opens `/api/plugins/{name}/ui` in an iframe/modal or new tab.
- A "¿Cómo creo un plugin?" tab/section that fetches and renders `docs/24-plugins.md` via `react-markdown` (already a frontend dependency). Needs one small new endpoint, e.g. `GET /api/plugins/docs`, returning the raw markdown file content (read from disk, no auth complexity beyond the existing dashboard token).

**Docs update:** `docs/24-plugins.md` gets a new section documenting `get_config_schema()` and `has_custom_ui()`/the `/ui` convention, since these are new hooks plugin authors need to know about.

## Error handling

- Plugin discovery failures already log-and-skip per plugin (existing pattern) — unaffected by this change.
- `POST /api/plugins/{name}/config` validates required fields server-side before saving; the frontend surfaces field-level errors from a 400 response.
- If a plugin is disabled and its `plugin_state` row is later deleted/DB reset, it reverts to enabled-by-default rather than erroring.
- `/ui` routes are plugin-owned; if a plugin declares `has_custom_ui=True` but doesn't actually serve `/ui`, the iframe shows FastAPI's normal 404 — no special handling needed in Phase 1.

## Testing

- Unit tests (pytest, existing `conftest.py` fixtures) for: `plugin_state` migration applies cleanly on a fresh DB and on an existing v30 DB; `load_builtin_plugins()` skips a plugin with `enabled=0`; `get_config_schema()` defaults to `[]` when a plugin doesn't override it; the config save/read round-trip masks password fields correctly and preserves unset ones on partial updates.
- No new integration/browser testing planned beyond manually exercising the new `/plugins` page against the existing `gmail_classifier` plugin (a real plugin to validate against, even though it won't declare a config schema initially).
