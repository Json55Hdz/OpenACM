"""
System Command Tool — execute OS commands securely.
"""

from openacm.tools.base import tool


@tool(
    name="run_command",
    description=(
        "Execute a command on the operating system's terminal/shell. "
        "Use this to run system commands like ls, dir, ping, git, python, etc. "
        "The command runs in a secure sandbox with timeout protection."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The command to execute (e.g., 'dir', 'ls -la', 'ping google.com')",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum execution time in seconds (default: 30)",
                "default": 30,
            },
            "working_directory": {
                "type": "string",
                "description": "Optional working directory for the command",
            },
        },
        "required": ["command"],
    },
    risk_level="high",
    needs_sandbox=True,
)
async def run_command(
    command: str,
    timeout: int = 30,
    working_directory: str | None = None,
    _sandbox=None,
    **kwargs,
) -> str:
    """Execute a system command in the sandbox."""
    if not _sandbox:
        return "Error: Sandbox not available"

    result = await _sandbox.execute(
        command=command,
        timeout=timeout,
        cwd=working_directory,
    )
    return result.output
