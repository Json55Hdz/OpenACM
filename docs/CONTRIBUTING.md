# Contributing to OpenACM

Thanks for your interest in contributing. Here's how to get started.

## Project author

OpenACM was created by [Jeison Hernandez](https://github.com/Json55Hdz) (JsonProductions).
All contributions are welcome, but the project direction is ultimately the author's call.

## Getting started

```bash
git clone https://github.com/Json55Hdz/OpenACM.git
cd OpenACM

# Backend (Python)
uv sync
uv run python -m openacm

# Frontend (in a separate terminal)
cd frontend
npm install
npm run dev
```

The frontend dev server runs on `http://localhost:3000` and proxies API calls to the backend on `http://localhost:47821`.

## How to contribute

1. Fork the repo
2. Create a branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Open a Pull Request with a clear description of what it does and why

## What we're looking for

- Bug fixes
- New built-in tools (add them in `src/openacm/tools/`)
- New MCP integrations or examples
- Frontend improvements
- Better documentation
- Cross-platform fixes (Linux/macOS compatibility)

## Guidelines

- Keep PRs focused — one thing at a time
- Follow the existing code style (Python: ruff/black, TypeScript: ESLint)
- Don't commit `config/.env`, `data/`, or any API keys
- Add a brief description in the PR of how to test the change

## Reporting bugs

Open an issue with:
- What you did
- What you expected
- What happened (include logs if relevant)
- Your OS and Python/Node versions

## License

By contributing, you agree that your contributions will be licensed under the same [MIT License](LICENSE) that covers this project.
The copyright of the original codebase remains with Jeison David Hernandez Pena.
