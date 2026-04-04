"""
System Command Tool — execute OS commands securely.
"""

import asyncio

from openacm.tools.base import tool

# Registry of background processes: pid -> asyncio.subprocess.Process
_bg_processes: dict[int, asyncio.subprocess.Process] = {}

# GUI launchers that open a window and never produce stdout/stderr.
# Matched against the start of the command (case-insensitive).
# These are launched fire-and-forget so the agent never hangs.
_GUI_PREFIXES = (
    "rundll32",
    "explorer",
    "mspaint",
    "notepad",
    "calc",
    "control",
    "msconfig",
    "mmc",
    "regedit",
    "taskmgr",
    "msinfo32",
    "dxdiag",
    "winver",
    "charmap",
    "snippingtool",
    "magnify",
    "osk",           # on-screen keyboard
    "narrator",
    "eventvwr",
    "devmgmt.msc",
    "diskmgmt.msc",
    "compmgmt.msc",
    "services.msc",
    "gpedit.msc",
    "secpol.msc",
    "lusrmgr.msc",
    "certmgr.msc",
    "wmplayer",
    "msiexec",
    "wscript",
    "cscript",
    "start ",        # `start <something>` always opens a window
)


def _is_gui_command(command: str) -> bool:
    """Return True if the command opens a GUI window and never exits on its own."""
    cmd = command.strip().lower()
    return any(cmd.startswith(p) for p in _GUI_PREFIXES)


@tool(
    name="run_command",
    description=(
        "[OpenACM Tool] Execute commands directly in the operating system terminal. "
        "ALWAYS AVAILABLE. Use for: ls, dir, git, python, pip, npm run dev, servers, tunnels, etc. "
        "Command runs in a secure sandbox. Default timeout is 60s. "
        "IMPORTANT: Use background=true for ANY long-running or blocking process — "
        "servers, proxies, watchers, tunnels, mitmproxy, mitmweb, ngrok, etc. "
        "If background=false and the command never exits, the entire agent will hang forever. "
        "— background mode captures startup output for ~6 seconds then detaches, returning the PID. "
        "EXAMPLES: 'dir', 'ls -la', 'git status', 'python script.py', "
        "'npm run dev' (background=true), 'mitmweb --listen-port 8888' (background=true)"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait (0 = no limit). Ignored when background=true.",
                "default": 0,
            },
            "working_directory": {
                "type": "string",
                "description": "Optional working directory",
            },
            "background": {
                "type": "boolean",
                "description": (
                    "Run the process in the background (fire-and-forget). "
                    "Use this for servers, tunnels, watch tasks — anything that runs forever. "
                    "Captures up to 6 seconds of startup output then returns the PID."
                ),
                "default": False,
            },
        },
        "required": ["command"],
    },
    risk_level="high",
    needs_sandbox=True,
    category="general",
)
async def run_command(
    command: str,
    timeout: int = 0,
    working_directory: str | None = None,
    background: bool = False,
    _sandbox=None,
    **kwargs,
) -> str:
    """Execute a system command in the sandbox."""
    if not _sandbox:
        return "Error: Sandbox not available"

    _channel_id = kwargs.get("_channel_id", "web")

    # GUI / background commands don't need PTY — launch detached as before.
    if _is_gui_command(command) or background:
        if _is_gui_command(command):
            return await _run_gui_detached(command, working_directory)
        brain = kwargs.get("_brain")
        on_output = None
        if brain and hasattr(brain, "event_bus"):
            from openacm.core.events import EVENT_TOOL_OUTPUT_STREAM
            async def on_output(chunk: str):
                await brain.event_bus.emit(
                    EVENT_TOOL_OUTPUT_STREAM,
                    {"tool": "run_command", "chunk": chunk, "channel_id": _channel_id},
                )
        return await _run_background(command, working_directory, on_output, _sandbox)

    # For interactive / regular commands: route through the channel's PTY shell so
    # everything (prompts, passwords, colors, current path) shows in the web terminal.
    if working_directory:
        # cd first, then run — PTY doesn't have a per-call cwd option
        full_command = f'cd /d "{working_directory}" && {command}'
    else:
        full_command = command

    try:
        from openacm.web.server import _channel_shells, ChannelShell
        shell = _channel_shells.get(_channel_id)
        if not shell or not shell._alive:
            # Terminal panel may not be open yet — create the PTY shell on demand
            shell = ChannelShell(_channel_id)
            await shell.start()
            _channel_shells[_channel_id] = shell
        return await shell.run_command_capture(full_command, timeout=float(timeout) if timeout > 0 else 30.0)
    except Exception:
        pass

    # Fallback: sandbox subprocess (no PTY, but still works)
    brain = kwargs.get("_brain")
    on_output = None
    if brain and hasattr(brain, "event_bus"):
        from openacm.core.events import EVENT_TOOL_OUTPUT_STREAM
        async def on_output(chunk: str):
            await brain.event_bus.emit(
                EVENT_TOOL_OUTPUT_STREAM,
                {"tool": "run_command", "chunk": chunk, "channel_id": _channel_id},
            )
    result = await _sandbox.execute(
        command=command,
        timeout=timeout if timeout > 0 else None,
        cwd=working_directory,
        on_output=on_output,
    )
    return result.output


async def _run_gui_detached(command: str, cwd: str | None) -> str:
    """
    Launch a GUI command completely detached — fire-and-forget.
    Returns immediately without waiting for the window to close.
    Used for commands like rundll32, explorer, notepad, etc. that open
    a window and never write to stdout/stderr.
    """
    import platform
    import os as _os
    import subprocess

    try:
        if platform.system() == "Windows":
            subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(
                    subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                ),
            )
        else:
            import shlex
            subprocess.Popen(
                shlex.split(command),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return f"GUI command launched: `{command}`. The window should now be open."
    except Exception as e:
        return f"Error launching GUI command: {e}"


async def _run_background(
    command: str,
    cwd: str | None,
    on_output,
    sandbox,
) -> str:
    """
    Launch a command in the background.
    Reads stdout/stderr for up to 6 seconds to capture startup output (URLs, errors, etc.),
    then detaches and returns the PID so the AI can continue.
    """
    import platform
    import os as _os

    proc_env = {**_os.environ, "CI": "true", "npm_config_yes": "true"}

    if platform.system() == "Windows":
        process = await asyncio.create_subprocess_exec(
            "cmd.exe", "/c", command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=proc_env,
        )
    else:
        import shlex
        args = shlex.split(command)
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=proc_env,
        )

    pid = process.pid
    _bg_processes[pid] = process

    # Collect startup output for up to 6 seconds
    startup_lines: list[str] = []

    async def _drain(stream):
        try:
            while True:
                chunk = await asyncio.wait_for(stream.read(512), timeout=0.2)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                startup_lines.append(text)
                if on_output:
                    try:
                        await on_output(text)
                    except Exception:
                        pass
        except (asyncio.TimeoutError, Exception):
            pass

    deadline = asyncio.get_event_loop().time() + 6.0
    while asyncio.get_event_loop().time() < deadline:
        # Check if process already died (error at startup)
        if process.returncode is not None:
            break
        await _drain(process.stdout)
        await _drain(process.stderr)
        await asyncio.sleep(0.3)

    # One last drain
    await _drain(process.stdout)
    await _drain(process.stderr)

    startup_output = "".join(startup_lines).strip()

    if process.returncode is not None and process.returncode != 0:
        return (
            f"Process exited immediately with code {process.returncode}.\n"
            + (startup_output or "(no output)")
        )

    # Keep draining stdout/stderr to prevent pipe buffer from filling up.
    # Still forward to on_output so the terminal panel stays live,
    # but the AI never sees this — it already got the startup summary.
    async def _discard_forever(stream):
        try:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break  # process exited
                if on_output:
                    try:
                        text = chunk.decode("utf-8", errors="replace")
                        await on_output(text)
                    except Exception:
                        pass
        except Exception:
            pass

    if process.returncode is None:
        asyncio.ensure_future(_discard_forever(process.stdout))
        asyncio.ensure_future(_discard_forever(process.stderr))

    return (
        f"Process started in background (PID {pid}).\n"
        f"Startup output:\n{startup_output or '(no output yet)'}\n\n"
        f"The process is still running. To stop it: run_command('taskkill /PID {pid} /F') on Windows or run_command('kill {pid}') on Linux/Mac."
    )
