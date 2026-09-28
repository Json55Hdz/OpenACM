# Changelog

All notable changes to OpenACM are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security
- Updated dependencies flagged by Dependabot: litellm, starlette, Pillow,
  pypdf, python-multipart, cryptography, mcp (kept on 1.x), urllib3, anyio,
  aiohttp, tornado, transformers, torch, PyJWT, idna, accelerate, chromadb
  and others. Minimum versions are now enforced in `pyproject.toml`
  (including `[tool.uv] constraint-dependencies` for transitive packages).
- Frontend: forced `sharp` to `^0.35.5`; `npm audit` is clean.
- The dashboard SPA catch-all only serves files that resolve inside the
  static directory.
- API/SSE error responses no longer include raw exception messages; the
  details are written to the server log.
- Fixed a polynomial-time regex (ReDoS) in the voice TTS text cleaner.
- Dashboard tokens are compared in constant time, and WebSocket endpoints
  now reject connections when `DASHBOARD_TOKEN` is unset, matching the
  HTTP API.

## [0.3.0] - 2026-08-18

### Added
- `features.browser_agent` and `features.voice` config toggles to disable
  the browser agent tool and the Voice daemon entirely for deployments that
  don't need them.
- GitHub Actions workflow that builds and pushes a versioned Docker image to
  a private GHCR registry on every `vX.Y.Z` tag push.

### Fixed
- Removed `xdotool` from the Docker image — it's an X11 GUI tool with no
  function in a headless container.
