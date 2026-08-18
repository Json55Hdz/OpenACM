# Client Deployment Strategy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OpenACM ready to be distributed to client deployments as versioned, private Docker images, and give client deployments a config-driven way to disable heavy/optional subsystems (starting with the browser agent and voice daemon) without forking the core.

**Architecture:** Add a `features` config section following the exact pattern the codebase already uses for channels (`ChannelsConfig.discord.enabled`, etc.), wire it into `AppConfig`/`load_config`, and gate the two currently-unconditional heavy subsystems (`browser_agent` tool registration, Voice daemon instantiation) behind it in `app.py`. Separately, add a GitHub Actions workflow that builds the existing `docker/Dockerfile` into a versioned image and pushes it to a **private** GHCR registry on every semver tag push, so client servers only ever `docker pull` — never `git clone` the public repo. Clean up the one Dockerfile issue already flagged in `docs/DEPLOY_VPS.md` (`xdotool`, an X11 GUI tool with no purpose in a headless container).

**Tech Stack:** Python 3.12, Pydantic v2 (`openacm.core.config`), pytest (`asyncio_mode = auto`), Docker, GitHub Actions, GHCR (GitHub Container Registry).

**Spec:** `docs/superpowers/specs/2026-08-18-client-deployment-strategy-design.md`

## Global Constraints

- New config fields must default to today's behavior (`browser_agent: true`, `voice: true`) — existing deployments (including the general/dev repo itself) must see zero behavior change.
- Follow the existing `enabled: bool` naming/placement convention used by `DiscordConfig`, `TelegramConfig`, `WhatsAppConfig` — do not invent a new naming style.
- Any new top-level YAML key must be explicitly copied in `load_config()`'s mapping block (`src/openacm/core/config.py:243-273`) — Pydantic defaults silently swallow unmapped keys, so forgetting this makes the YAML value a no-op.
- Docker images are pushed to a **private** GHCR registry, never a public registry — this is the whole point of the spec's distribution model (public MIT source, private release artifacts).
- Tags follow semver: `vX.Y.Z`, matching the `version` field in `pyproject.toml`.
- Do not push a real git tag or trigger the release workflow against the live GitHub remote as part of this plan — that pushes a container image to a shared registry, which is a "visible to others" action requiring the user's own explicit go-ahead, done by them later, not automated here.

---

### Task 1: `features` config section (browser_agent / voice toggles)

**Files:**
- Modify: `src/openacm/core/config.py:150-163` (add `FeaturesConfig` model, add `features` field to `AppConfig`)
- Modify: `src/openacm/core/config.py:243-273` (map `features` YAML key in `load_config`)
- Modify: `config/default.yaml` (document the new section, defaults commented like the `client_profile` block)
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `FeaturesConfig` (Pydantic model) with fields `browser_agent: bool = True`, `voice: bool = True`. Exposed as `AppConfig.features` (instance of `FeaturesConfig`). Later tasks read `self.config.features.browser_agent` and `self.config.features.voice` in `app.py`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_config.py`, in the "Pydantic model defaults" section (after `TestLocalRouterConfigDefaults`, before `TestAppConfigDefaults`):

```python
class TestFeaturesConfigDefaults:
    def test_browser_agent_enabled_by_default(self):
        cfg = FeaturesConfig()
        assert cfg.browser_agent is True

    def test_voice_enabled_by_default(self):
        cfg = FeaturesConfig()
        assert cfg.voice is True
```

Add `FeaturesConfig` to the import block at the top of the file:

```python
from openacm.core.config import (
    AppConfig,
    AssistantConfig,
    WebConfig,
    WhatsAppConfig,
    LocalRouterConfig,
    FeaturesConfig,
    _deep_merge,
    _resolve_env_vars,
    _find_project_root,
)
```

Add to `TestAppConfigDefaults`:

```python
    def test_features_present_by_default(self):
        cfg = AppConfig()
        assert cfg.features is not None
        assert cfg.features.browser_agent is True
        assert cfg.features.voice is True
```

Add a new class in the `TestLoadConfig` section (after `test_local_yaml_overrides_default`):

```python
class TestLoadConfigFeatures:
    def _load_isolated(self, monkeypatch, tmp_path, cfg_file):
        import openacm.core.config as cfg_module
        monkeypatch.setattr(cfg_module, "_find_project_root", lambda: tmp_path)
        from openacm.core.config import load_config
        return load_config(config_path=cfg_file)

    def test_features_disabled_via_yaml(self, monkeypatch, tmp_path):
        cfg_file = tmp_path / "default.yaml"
        cfg_file.write_text(textwrap.dedent("""\
            features:
              browser_agent: false
              voice: false
        """))
        cfg = self._load_isolated(monkeypatch, tmp_path, cfg_file)
        assert cfg.features.browser_agent is False
        assert cfg.features.voice is False

    def test_features_default_true_when_omitted(self, monkeypatch, tmp_path):
        cfg_file = tmp_path / "default.yaml"
        cfg_file.write_text("assistant:\n  name: Minimal\n")
        cfg = self._load_isolated(monkeypatch, tmp_path, cfg_file)
        assert cfg.features.browser_agent is True
        assert cfg.features.voice is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_config.py -v -k "Features"`
Expected: FAIL — `ImportError: cannot import name 'FeaturesConfig'` (or `AttributeError: 'AppConfig' object has no attribute 'features'` once the import is fixed manually to isolate the next failure).

- [ ] **Step 3: Add `FeaturesConfig` model and wire it into `AppConfig`**

In `src/openacm/core/config.py`, add this class right before `class ClientProfileConfig` (around line 137):

```python
class FeaturesConfig(BaseModel):
    """Toggles for heavy/optional subsystems, off-by-default-capable per client deployment.

    Unlike ChannelsConfig entries these default to True — the general repo and
    existing deployments must see no behavior change. A client deployment
    disables what it doesn't need via config/local.yaml.
    """

    browser_agent: bool = True  # Playwright-based `browser_agent` tool
    voice: bool = True          # Voice daemon (STT/TTS)
```

In `AppConfig` (around line 151-162), add the field:

```python
class AppConfig(BaseModel):
    """Root application configuration."""

    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    local_router: LocalRouterConfig = Field(default_factory=LocalRouterConfig)
    resurrection_paths: list[str] = Field(default_factory=list)
    client_profile: ClientProfileConfig = Field(default_factory=ClientProfileConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
```

In `load_config()` (around line 272, right after the `client_profile` mapping), add:

```python
    if "client_profile" in data:
        config_data["client_profile"] = data["client_profile"]
    if "features" in data:
        config_data["features"] = data["features"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_config.py -v`
Expected: PASS (all tests in the file, not just the new ones — confirms nothing else broke).

- [ ] **Step 5: Document the section in `config/default.yaml`**

Add this block at the end of `config/default.yaml`, after the existing `# ─── Client Profile ───` commented block:

```yaml

# ─── Features ─────────────────────────────────────────────────
# Disable heavy/optional subsystems for a client deployment that doesn't
# need them. Both default to true (no change from today's behavior).
# To activate: add the block below to config/local.yaml and restart.
#
# features:
#   browser_agent: false   # disables the Playwright-based browser_agent tool
#   voice: false            # disables the Voice daemon (STT/TTS) entirely
```

- [ ] **Step 6: Commit**

```bash
git add src/openacm/core/config.py config/default.yaml tests/unit/test_config.py
git commit -m "feat(config): add features.browser_agent and features.voice toggles"
```

---

### Task 2: Gate `browser_agent` tool registration

**Files:**
- Modify: `src/openacm/app.py:271-302` (`_init_tools` method)
- Test: `tests/unit/test_app_init_tools.py` (new file)

**Interfaces:**
- Consumes: `self.config.features.browser_agent` (from Task 1, `FeaturesConfig.browser_agent`), `ToolRegistry.register_module(module)` and `ToolRegistry.tools: dict[str, ToolDefinition]` (both already exist in `src/openacm/tools/registry.py`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_app_init_tools.py`. It uses the `db` and `event_bus`
fixtures from `tests/conftest.py` — a real in-memory `Database` and a real
`EventBus` — rather than `MagicMock()`, because `_init_tools` (via `app.py`'s
plugin startup path reachable from the same `OpenACM` instance in Task 3)
awaits real async methods on `database`; a plain `MagicMock()` is not
awaitable and would raise `TypeError` instead of exercising the code path.
`sandbox` and `brain` are only ever attribute-set (never awaited) by
`_init_tools`, so `MagicMock()` is fine for those two:

```python
"""
Tests for OpenACM._init_tools — verifies feature-flagged tools are only
registered when their config toggle is enabled.
"""
from unittest.mock import MagicMock

import pytest

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_app_init_tools.py -v`
Expected: FAIL on `test_not_registered_when_disabled` — `browser_agent` is registered unconditionally today.

- [ ] **Step 3: Gate the registration in `_init_tools`**

In `src/openacm/app.py`, change line 298 from:

```python
        self.tool_registry.register_module(browser_agent)
```

to:

```python
        if self.config.features.browser_agent:
            self.tool_registry.register_module(browser_agent)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_app_init_tools.py -v`
Expected: PASS

Also run the full unit suite to confirm no regression:
Run: `pytest tests/unit -v`
Expected: PASS (same pass count as before this task, plus the 3 new tests)

- [ ] **Step 5: Commit**

```bash
git add src/openacm/app.py tests/unit/test_app_init_tools.py
git commit -m "feat(tools): gate browser_agent registration behind features.browser_agent"
```

---

### Task 3: Gate Voice daemon instantiation

**Files:**
- Modify: `src/openacm/app.py:436-501` (`_init_watchers` method, voice daemon block at lines 485-501)
- Test: `tests/unit/test_app_init_tools.py` (extend from Task 2)

**Interfaces:**
- Consumes: `self.config.features.voice` (from Task 1). Produces: `self._voice_daemon` stays `None` when disabled — this is an existing, already-exercised code path (the surrounding `try/except` already leaves it `None` on any instantiation failure), so no downstream code needs to change.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_app_init_tools.py`. Same reasoning as `TestBrowserAgentToggle`
applies here, even more so: `_init_watchers` unconditionally calls
`_start_plugins()`, which does `await database.is_plugin_enabled(...)` for every
auto-discovered plugin with no surrounding `try/except` — so `database` must be
the real `db` fixture, not a `MagicMock()`:

```python
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
```

Note: this test only asserts the disabled case. The enabled case already requires real `sounddevice`/`faster-whisper` deps (the `voice` extra) to produce a non-`None` `VoiceDaemon` with `engine_available=True` — that's out of scope here; Task 1's config-default tests already cover that `voice: true` is the default.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_app_init_tools.py -v -k voice`
Expected: FAIL — today the Voice daemon block runs unconditionally, so
`VoiceDaemon(...)` is instantiated and assigned to `self._voice_daemon`
regardless of `check_deps()`/`engine_available` (those only affect the log
line, not whether the object is created). `app._voice_daemon` ends up a real
`VoiceDaemon` instance, not `None`, so the assertion fails.

- [ ] **Step 3: Gate the instantiation in `_init_watchers`**

In `src/openacm/app.py`, change the block at lines 485-501 from:

```python
        # Voice daemon — always instantiated so API endpoints are available;
        # engine_available property reflects whether optional deps are installed.
        try:
            from openacm.voice.voice_daemon import VoiceDaemon
            self._voice_daemon = VoiceDaemon(
                database=self.database,
                event_bus=self.event_bus,
                brain=self.brain,
            )
            deps = self._voice_daemon.check_deps()
            if self._voice_daemon.engine_available:
                console.print("  [green]✓[/green] Voice daemon ready (sounddevice + faster-whisper)")
            else:
                missing = [k for k, v in deps.items() if not v and k != "pyttsx3"]
                console.print(f"  [dim]~[/dim] Voice daemon available (missing: {', '.join(missing)})")
        except Exception as e:
            console.print(f"  [yellow]~[/yellow] Voice daemon skipped: {e}")
```

to:

```python
        # Voice daemon — instantiated (when enabled) so API endpoints are
        # available; engine_available property reflects whether optional
        # deps are installed. Disabled entirely via config.features.voice
        # for client deployments that don't want it at all.
        if self.config.features.voice:
            try:
                from openacm.voice.voice_daemon import VoiceDaemon
                self._voice_daemon = VoiceDaemon(
                    database=self.database,
                    event_bus=self.event_bus,
                    brain=self.brain,
                )
                deps = self._voice_daemon.check_deps()
                if self._voice_daemon.engine_available:
                    console.print("  [green]✓[/green] Voice daemon ready (sounddevice + faster-whisper)")
                else:
                    missing = [k for k, v in deps.items() if not v and k != "pyttsx3"]
                    console.print(f"  [dim]~[/dim] Voice daemon available (missing: {', '.join(missing)})")
            except Exception as e:
                console.print(f"  [yellow]~[/yellow] Voice daemon skipped: {e}")
        else:
            console.print("  [dim]~[/dim] Voice daemon disabled (features.voice: false)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_app_init_tools.py -v`
Expected: PASS

Run the full unit suite:
Run: `pytest tests/unit -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/openacm/app.py tests/unit/test_app_init_tools.py
git commit -m "feat(voice): gate Voice daemon instantiation behind features.voice"
```

---

### Task 4: Dockerfile cleanup for headless deployment

**Files:**
- Modify: `docker/Dockerfile:14-17`

**Interfaces:**
- None (build-time only change, no runtime interface).

- [ ] **Step 1: Remove `xdotool` from the apt-get install line**

`xdotool` is an X11 GUI-automation tool; it has no function in a headless container (no X11 display exists there) and was already flagged as dead weight in `docs/DEPLOY_VPS.md`'s "Alternativa: Deploy con Docker" section. Change `docker/Dockerfile:14-17` from:

```dockerfile
# Instalar utilidades de sistema necesarias
RUN apt-get update && apt-get install -y \
    curl build-essential xdotool \
    && rm -rf /var/lib/apt/lists/*
```

to:

```dockerfile
# Instalar utilidades de sistema necesarias
RUN apt-get update && apt-get install -y \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Verify the image still builds**

Run: `docker build -f docker/Dockerfile -t openacm-test .` (from the repo root)
Expected: build completes successfully (same as before, just without installing `xdotool`). This step takes several minutes (Chromium install via Playwright) — run with a generous timeout.

- [ ] **Step 3: Commit**

```bash
git add docker/Dockerfile
git commit -m "fix(docker): drop xdotool from the image, it's an X11 GUI tool unusable headless"
```

---

### Task 5: GitHub Actions release workflow (build + push to private GHCR)

**Files:**
- Create: `.github/workflows/release-image.yml`
- Modify: `docs/DEPLOY_VPS.md` (document the new distribution path alongside the existing bare-metal/local-Docker instructions)

**Interfaces:**
- None consumed from earlier tasks. Produces: on any `git push` of a tag matching `v*.*.*`, a Docker image built from `docker/Dockerfile` is pushed to `ghcr.io/<owner-lowercase>/openacm:<version>` and `ghcr.io/<owner-lowercase>/openacm:latest`. Client-repo Dockerfiles (future `openacm-clients` repo, out of scope here) will do `FROM ghcr.io/<owner-lowercase>/openacm:<version>`.

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/release-image.yml`:

```yaml
name: Release Docker image

on:
  push:
    tags:
      - 'v*.*.*'

permissions:
  contents: read
  packages: write

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Lowercase repository owner
        id: owner
        run: echo "owner=$(echo '${{ github.repository_owner }}' | tr '[:upper:]' '[:lower:]')" >> "$GITHUB_OUTPUT"

      - name: Extract version from tag
        id: meta
        run: echo "version=${GITHUB_REF_NAME#v}" >> "$GITHUB_OUTPUT"

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile
          push: true
          tags: |
            ghcr.io/${{ steps.owner.outputs.owner }}/openacm:${{ steps.meta.outputs.version }}
            ghcr.io/${{ steps.owner.outputs.owner }}/openacm:latest
```

- [ ] **Step 2: Validate the workflow YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/release-image.yml', encoding='utf-8'))"`
Expected: no output, exit code 0 (confirms valid YAML — this does not validate GitHub Actions schema, only syntax, since running the workflow requires an actual tag push, which is explicitly out of scope for this plan per the Global Constraints).

- [ ] **Step 3: Document the release flow in `docs/DEPLOY_VPS.md`**

Add a new section right after the existing "## Alternativa: Deploy con Docker" section (end of the file), documenting the client-deployment path this workflow enables:

```markdown

---

## Distribución para clientes: imagen privada versionada

Para deployments de cliente (ver `docs/superpowers/specs/2026-08-18-client-deployment-strategy-design.md`),
el server del cliente **nunca** clona este repo ni corre `git pull` en producción.
En su lugar:

1. Se etiqueta un release en este repo: `git tag vX.Y.Z && git push origin vX.Y.Z`.
2. El workflow `.github/workflows/release-image.yml` construye la imagen y la
   sube a `ghcr.io/<owner>/openacm:X.Y.Z` (registry **privado** — verifica en
   GitHub → Packages → openacm → Package settings que la visibilidad quedó en
   Private la primera vez que se publica).
3. El `Dockerfile` del cliente (en su propio repo privado, fuera de este repo)
   hace `FROM ghcr.io/<owner>/openacm:X.Y.Z`, copia su plugin package y su
   config, y construye su propia imagen.
4. El server del cliente solo hace `docker pull` de la imagen de **su** cliente,
   nunca de este repo.

Actualizar un cliente = subir el tag base que usa su `Dockerfile` a mano,
reconstruir su imagen, hacer push, y que el server haga `docker pull` del tag
nuevo. Nunca automático, nunca sigue `main`.
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release-image.yml docs/DEPLOY_VPS.md
git commit -m "ci: build and push a private GHCR image on semver tag push"
```

---

### Task 6: Document the versioning/changelog convention

**Files:**
- Create: `CHANGELOG.md`
- Modify: `docs/CONTRIBUTING.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Create `CHANGELOG.md`**

Create `CHANGELOG.md` at the repo root, using the [Keep a Changelog](https://keepachangelog.com/) format, seeded with the work from this plan:

```markdown
# Changelog

All notable changes to OpenACM are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `features.browser_agent` and `features.voice` config toggles to disable
  the browser agent tool and the Voice daemon entirely for deployments that
  don't need them.
- GitHub Actions workflow that builds and pushes a versioned Docker image to
  a private GHCR registry on every `vX.Y.Z` tag push.

### Fixed
- Removed `xdotool` from the Docker image — it's an X11 GUI tool with no
  function in a headless container.
```

- [ ] **Step 2: Add a "Releasing" section to `docs/CONTRIBUTING.md`**

Append this section to the end of `docs/CONTRIBUTING.md`, before the `## License` section:

```markdown
## Releasing

Releases follow [Semantic Versioning](https://semver.org/) (`vMAJOR.MINOR.PATCH`).

1. Bump `version` in `pyproject.toml`.
2. Move the `[Unreleased]` entries in `CHANGELOG.md` under a new `## [X.Y.Z] - YYYY-MM-DD`
   heading, and start a fresh empty `[Unreleased]` section above it.
3. Commit: `git commit -m "chore: release vX.Y.Z"`.
4. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
5. Pushing the tag triggers `.github/workflows/release-image.yml`, which
   builds and pushes `ghcr.io/<owner>/openacm:X.Y.Z` to the private GHCR
   registry. Client deployments pin to this tag — see
   `docs/DEPLOY_VPS.md` → "Distribución para clientes".
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md docs/CONTRIBUTING.md
git commit -m "docs: document semver release + changelog convention"
```

---

## Out of scope (tracked separately, per the spec)

- Creating the actual `openacm-clients` private repo/monorepo and its per-client
  template (plugin package skeleton, client `Dockerfile`, config template).
- Auditing/toggling any other heavy subsystem beyond `browser_agent` and `voice`
  — per the spec's extension hierarchy, add a toggle for a given subsystem only
  when a real client deployment needs it disabled.
- The security hardening track (plaintext tokens in SQLite, dashboard token in
  boot logs, WebSocket auth via query param) — separate spec/track.
- Actually pushing a `vX.Y.Z` tag to the live GitHub remote — that's a real,
  visible release action the user triggers themselves when ready.
