# Changelog

All notable changes to OpenACM are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
