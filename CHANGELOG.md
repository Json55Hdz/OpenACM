# Changelog

All notable changes to OpenACM are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Agents can split one reply into several WhatsApp messages by writing `<<MSG>>`
  where it should be cut (e.g. legal notice first, then the greeting). Other
  channels turn the marker into a blank line.
- `send_file_to_chat` accepts an optional `display_name`; WhatsApp delivers the
  document with that name instead of `upload_<hex>.ext`.

### Fixed
- WhatsApp Cloud: replies longer than Meta's 1024-char caption limit are now
  sent as text before the file, instead of the upload failing and the file
  being silently dropped. Documents are uploaded with their real MIME type.

### Security
- Agents with a restricted `allowed_tools` list can no longer execute tools
  outside it (previously only the schema shown to the model was filtered); a
  malformed policy now exposes no tools instead of all of them.
- Agent channels (`*_a<id>`) cannot send secrets or internal state through
  `send_file_to_chat` (`config/`, `data/` except `media/` and `assets/`, `.env`,
  keys, databases).
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
