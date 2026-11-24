# Changelog

All notable changes to OpenACM are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.5.6]

### Fixed
- After an image was seen, the placeholder that replaces it in later turns now tells the model to answer from its earlier reading
  when the user refers to it ("¿tienes este teléfono?") instead of saying it cannot see the image and asking for it again.
- Product search results are smaller: variations are listed for the 3 best variable matches (was 5), so several parallel searches
  no longer push the model's context past the point where it slows down.

## [0.5.5]

### Added
- The WooCommerce product search now returns each variable product's options (colors, capacities…) and its variations with their
  own price and stock, so agents can answer "does it come in burgundy?" or "how much is the 512 GB?" instead of saying they
  cannot know. Only published variations are listed (what the shop really sells), the first 5 variable matches are expanded, and
  a failing variations request never breaks the search. Descriptions also get their HTML entities decoded.

## [0.5.4]

### Fixed
- WhatsApp Cloud channels now receive customers' images, audios and documents. Before, anything that was not text reached the
  agent as the placeholder `[image recibido]` (the file was never downloaded, the caption was lost) and the bot answered that it
  could not see it. The file is now downloaded from Meta, saved and handed over as an attachment — the same way the Telegram
  channel does it — with the caption as the message.

## [0.5.3]

### Fixed
- Product search no longer fails: 0.5.1/0.5.2 sent `orderby=relevance`, which the WooCommerce products API rejects with a 400,
  so every search errored. The name-match ranking does the ordering now.

## [0.5.2]

### Fixed
- Docker image and dashboard release builds no longer fail on `npm ci`: onnxruntime-node tried to download a GPU binary that is
  gone upstream (404); the install now skips the CUDA download. Includes everything in 0.5.1 (its image never built).

## [0.5.1]

### Fixed
- WooCommerce search no longer loses the exact product: it asks for 30 results ordered by relevance and ranks them by name match
  before handing the best 10 to the agent (a search for "x8 pro" used to return a camera and other unrelated items and cut off
  the Poco X8 Pro, so the bot said it did not exist).
- Agents now receive today's date and weekday (Colombia time), so warranty windows, "are you open today" and delivery promises
  are computed against the real date instead of a guess.

## [0.5.0]

### Added
- Skill marketplace: community catalog, install by link/file/paste with full preview, a reading aid for risky content and SHA-256 pinning; skills now show their source (system, plugin, marketplace).
- Model failover with an errors/costs panel; redesigned models configuration.
- Per-channel access control (owner / guest / blocked) with per-chat profiles.
- In-chat media viewer (image zoom, audio/video, PDF and document preview) and WhatsApp-style date separators.
- Tools show their real source (built-in, plugin, MCP).

### Changed
- Faster install: the dashboard is rebuilt only when the code changed, a prebuilt copy is downloaded on tagged releases (no Node needed), Chromium downloads in the background and redundant reinstall steps were removed.
- Blender, Flutter and Unity skills moved to the marketplace.
- Webhook connectors no longer take a place in the main menu (the page and API remain).
- Routines explain why they cannot run on a machine without a screen.

### Fixed
- Compaction no longer leaves orphan tool results.

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
