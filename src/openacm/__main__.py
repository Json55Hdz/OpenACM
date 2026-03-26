"""OpenACM entry point — run with `python -m openacm`."""

import asyncio
import sys

from rich.console import Console

from openacm.app import OpenACM

console = Console()


def main():
    """Main entry point."""
    try:
        app = OpenACM()
        asyncio.run(app.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]⚡ OpenACM shutting down...[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]💀 Fatal error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
