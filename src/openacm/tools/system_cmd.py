"""
System Command Tool — execute OS commands securely.
"""

from openacm.tools.base import tool


@tool(
    name="run_command",
    description=(
        "[OpenACM Tool] Execute commands directly in the operating system terminal. "
        "ALWAYS AVAILABLE. Use for: ls, dir, git, python, pip, etc. "
        "Command runs in a secure sandbox. "
        "EXAMPLES: 'dir', 'ls -la', 'git status', 'python script.py'"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Command to execute (e.g.: 'dir', 'ls -la', 'git status')",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum time in seconds (default: 30)",
                "default": 30,
            },
            "working_directory": {
                "type": "string",
                "description": "Optional working directory",
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
