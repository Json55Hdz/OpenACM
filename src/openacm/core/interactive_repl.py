"""
OpenACM Interactive REPL — runs inside the web terminal PTY.

Connects to the already-running OpenACM server via WebSocket and HTTP,
giving a full interactive CLI experience: prompt_toolkit input with history,
rich output rendering, tool call display, and native PTY interactive prompts.

Launch from the web terminal with:  openacm-cli
or directly:  python -m openacm.core.interactive_repl
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

_ENV_FILE = Path("config/.env")
_HISTORY_FILE = Path("data/repl_history")

console = Console()

_STYLE = Style.from_dict({
    "prompt": "ansigreen bold",
    "rprompt": "ansigray",
})


def _get_server_url() -> str:
    load_dotenv(_ENV_FILE)
    port = os.environ.get("WEB_PORT", "47821")
    return f"http://127.0.0.1:{port}"


def _get_token() -> str:
    load_dotenv(_ENV_FILE)
    token = os.environ.get("DASHBOARD_TOKEN", "")
    if not token:
        console.print("[red]No DASHBOARD_TOKEN found in config/.env — is OpenACM running?[/red]")
        sys.exit(1)
    return token


async def _send_message(client: httpx.AsyncClient, base_url: str, token: str, message: str) -> str:
    """POST message to /ws/chat via the REST fallback endpoint."""
    # Use /api/chat/send (standard REST endpoint that returns the full response)
    try:
        r = await client.post(
            f"{base_url}/api/chat/send",
            json={"message": message, "target_user_id": "cli", "target_channel_id": "cli"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=300.0,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("response") or data.get("content") or str(data)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            # Fallback: use websocket-style endpoint
            return await _send_via_ws(base_url, token, message)
        raise


async def _send_via_ws(base_url: str, token: str, message: str) -> str:
    """Send message via WebSocket and wait for response."""
    import websockets

    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    response_parts: list[str] = []
    tool_calls: list[str] = []

    try:
        async with websockets.connect(
            f"{ws_url}/ws/chat?token={token}",
            open_timeout=10,
        ) as ws:
            await ws.send(json.dumps({
                "message": message,
                "target_user_id": "cli",
                "target_channel_id": "cli",
            }))

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=180.0)
                    data = json.loads(raw)
                    msg_type = data.get("type")

                    if msg_type == "response":
                        response_parts.append(data.get("content", ""))
                        break
                    elif msg_type == "message.thinking":
                        status = data.get("status")
                        label = data.get("message", "")
                        if status == "tool_running" and label:
                            console.print(f"  [dim cyan]⚙ {label}[/dim cyan]")
                        elif status == "start":
                            console.print("  [dim]thinking…[/dim]")
                    elif msg_type == "tool.called":
                        tool = data.get("tool", "")
                        args = data.get("arguments", "")
                        tool_calls.append(tool)
                        console.print(f"  [magenta]▶ {tool}[/magenta] [dim]{args[:80]}[/dim]")
                    elif msg_type == "tool.result":
                        tool = data.get("tool", "")
                        console.print(f"  [green]✓ {tool}[/green]")
                    elif msg_type == "error":
                        return f"[error] {data.get('content', 'unknown error')}"
                    elif msg_type == "message.sent":
                        # partial text emitted before tool calls
                        content = data.get("content", "")
                        if data.get("partial") and content:
                            console.print(f"[dim cyan]{content}[/dim cyan]")

                except asyncio.TimeoutError:
                    return "[timeout] No response after 3 minutes."

    except Exception as e:
        return f"[connection error] {e}"

    return "".join(response_parts)


def _render_response(text: str) -> None:
    """Render LLM response — markdown if it looks like it, plain text otherwise."""
    if any(marker in text for marker in ["```", "**", "##", "- ", "* ", "1. "]):
        console.print(Panel(Markdown(text), border_style="cyan", padding=(0, 1)))
    else:
        console.print(Text(text, style="cyan"))


async def _check_server(base_url: str, token: str) -> bool:
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{base_url}/api/ping", timeout=3.0)
            return r.status_code == 200
        except Exception:
            try:
                r = await client.post(
                    f"{base_url}/api/auth/check",
                    json={"token": token},
                    timeout=3.0,
                )
                return r.status_code == 200
            except Exception:
                return False


async def repl() -> None:
    base_url = _get_server_url()
    token = _get_token()

    console.print(Rule("[bold cyan]OpenACM CLI[/bold cyan]"))

    if not await _check_server(base_url, token):
        console.print(f"[red]Cannot reach OpenACM server at {base_url}[/red]")
        console.print("[yellow]Make sure OpenACM is running first.[/yellow]")
        sys.exit(1)

    console.print(f"[green]Connected to[/green] [bold]{base_url}[/bold]")
    console.print("[dim]Type your message and press Enter. Ctrl+C or /exit to quit.[/dim]\n")

    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    session: PromptSession = PromptSession(
        history=FileHistory(str(_HISTORY_FILE)),
        auto_suggest=AutoSuggestFromHistory(),
        style=_STYLE,
    )

    async with httpx.AsyncClient() as client:
        while True:
            try:
                user_input: str = await session.prompt_async(
                    HTML("<prompt>you</prompt> <b>›</b> "),
                    style=_STYLE,
                )
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Goodbye.[/yellow]")
                break

            user_input = user_input.strip()
            if not user_input:
                continue
            if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
                console.print("[yellow]Goodbye.[/yellow]")
                break

            # Slash commands — forward to command processor
            if user_input.startswith("/"):
                try:
                    r = await client.post(
                        f"{base_url}/api/chat/command",
                        json={"command": user_input[1:], "user_id": "cli", "channel_id": "cli"},
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=30.0,
                    )
                    data = r.json()
                    text = data.get("text") or str(data)
                    console.print(f"[yellow]{text}[/yellow]")
                except Exception as e:
                    console.print(f"[red]Command error: {e}[/red]")
                continue

            try:
                response = await _send_via_ws(base_url, token, user_input)
                console.print()
                _render_response(response)
                console.print()
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")


def main() -> None:
    try:
        asyncio.run(repl())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
