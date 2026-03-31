"""OpenACM entry point — run with `python -m openacm`."""

import asyncio
import sys
from pathlib import Path

from rich.console import Console

from openacm.core.logging_setup import configure_logging
from openacm.app import OpenACM

console = Console()

_debug_file = Path("data/debug_mode")
_startup_level = "DEBUG" if (_debug_file.exists() and _debug_file.read_text().strip() == "true") else "INFO"
configure_logging(log_dir=Path("data/logs"), level=_startup_level)


def _suppress_connection_reset(loop, context):
    """Silence WinError 10054 noise from abrupt client disconnects (Windows-only)."""
    exc = context.get("exception")
    if isinstance(exc, ConnectionResetError):
        return
    loop.default_exception_handler(context)


def main():
    """Main entry point."""
    try:
        app = OpenACM()
        loop = asyncio.new_event_loop()
        loop.set_exception_handler(_suppress_connection_reset)
        asyncio.set_event_loop(loop)
        loop.run_until_complete(app.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]⚡ OpenACM shutting down...[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]💀 Fatal error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
