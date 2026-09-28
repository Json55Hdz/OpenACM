# Contributing to OpenACM

Thanks for your interest in contributing. Here's how to get started.

## Project author

OpenACM was created by [Jeison Hernandez](https://github.com/Json55Hdz) (JsonProductions).
All contributions are welcome, but the project direction is ultimately the author's call.

## Getting started

```bash
git clone https://github.com/Json55Hdz/OpenACM.git
cd OpenACM

# Backend (Python 3.12)
uv venv --seed
uv pip install -e ".[dev]"
uv run python -m openacm        # or: uv run openacm

# Tests
uv run pytest                   # asyncio_mode = auto

# Frontend (Next.js, static export)
cd frontend
npm install
npm run lint
npm run deploy                  # next build + copy dist/ into src/openacm/web/static
```

The dashboard calls the API with relative URLs and there is no dev proxy configured, so the simplest loop is `npm run deploy` and reload `http://localhost:47821`. (`npm run dev` serves the UI on `:3000`, but its API/WebSocket calls go to `:3000` too.)

Useful project conventions (see `CLAUDE.md` / `AGENTS.md` in the repo root):
- New tools are `async`, end with `**kwargs`, and get shared managers from `_brain.tool_registry`
- User-facing strings and LLM prompts live in `src/openacm/core/messages.py`
- Keyword fallbacks for tool selection live in `src/openacm/tools/intent_keywords.py`
- Tests use the mocked fixtures in `tests/conftest.py`

## How to contribute

1. Fork the repo
2. Create a branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Open a Pull Request with a clear description of what it does and why

## What we're looking for

- Bug fixes
- New built-in tools (add them in `src/openacm/tools/`) or new plugins (`src/openacm/plugins/`)
- New MCP integrations or examples
- Frontend improvements
- Better documentation
- Cross-platform fixes (Linux/macOS compatibility)

## Guidelines

- Keep PRs focused — one thing at a time
- Follow the existing code style (Python: ruff, line length 100; TypeScript: ESLint)
- New API endpoints should be documented in `docs/10-api-reference.md`
- Don't commit `config/.env`, `data/`, or any API keys
- Add a brief description in the PR of how to test the change

## Reporting bugs

Open an issue with:
- What you did
- What you expected
- What happened (include logs if relevant)
- Your OS and Python/Node versions

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
6. On the first publish only, go to GitHub → Packages → openacm → Package
   settings and confirm the visibility is set to **Private** —
   `GITHUB_TOKEN` cannot set this automatically.

## License

By contributing, you agree that your contributions will be licensed under the same [MIT License](../LICENSE) that covers this project.
The copyright of the original codebase remains with Jeison David Hernandez Pena.
