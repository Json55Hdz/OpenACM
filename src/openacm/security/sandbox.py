"""
Sandbox — secure command execution environment.

Executes system commands with security checks, timeouts,
output limits, and logging.
"""

import asyncio
import platform
import shlex
import time
from typing import Any

import structlog

from openacm.core.events import EventBus
from openacm.security.policies import SecurityPolicy, SecurityViolation

log = structlog.get_logger()


class SandboxResult:
    """Result of a sandboxed command execution."""

    def __init__(
        self,
        command: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        elapsed_ms: int,
        truncated: bool = False,
    ):
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.elapsed_ms = elapsed_ms
        self.truncated = truncated

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        """Combined stdout + stderr."""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"[stderr] {self.stderr}")
        if self.truncated:
            parts.append("[output truncated]")
        return "\n".join(parts) if parts else "(no output)"

    def __str__(self) -> str:
        status = "✓" if self.success else f"✗ (exit code {self.exit_code})"
        return f"{status} {self.command}\n{self.output}"


class Sandbox:
    """Secure command executor with policy enforcement."""

    def __init__(self, policy: SecurityPolicy, event_bus: EventBus):
        self.policy = policy
        self.event_bus = event_bus
        self._is_windows = platform.system() == "Windows"

    async def execute(
        self,
        command: str,
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        on_output=None,  # async callable(chunk: str) for real-time streaming
    ) -> SandboxResult:
        """
        Execute a command in the sandbox.
        
        Checks security policies, runs with timeout, captures output.
        Raises SecurityViolation if the command is not allowed.
        """
        # Check security policy
        allowed, reason = self.policy.check_command(command)
        if not allowed:
            raise SecurityViolation(f"Command blocked: {reason}")

        # Use provided timeout, fall back to config, 0/None means no limit
        configured = self.policy.config.max_command_timeout
        if timeout is None:
            timeout = configured if configured else None
        elif timeout <= 0:
            timeout = None  # explicit 0 = no limit
        max_output = self.policy.config.max_output_length

        start_time = time.time()
        truncated = False

        try:
            # Inject CI=true so npm/yarn/npx and many other tools skip interactive prompts
            import os as _os
            proc_env = {**(_os.environ if env is None else env), "CI": "true", "npm_config_yes": "true"}

            if self._is_windows:
                # On Windows, use cmd.exe /c
                process = await asyncio.create_subprocess_exec(
                    "cmd.exe", "/c", command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=proc_env,
                )
            else:
                # On Linux/macOS, parse and execute directly
                args = shlex.split(command)
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=proc_env,
                )

            # Auto-answer any initial "proceed? (y)" prompts
            if process.stdin:
                process.stdin.write(b"y\n")
                try:
                    await process.stdin.drain()
                except Exception:
                    pass
                process.stdin.close()

            # Stream stdout and stderr concurrently, calling on_output per chunk
            stdout_parts: list[str] = []
            stderr_parts: list[str] = []

            async def _read_stream(stream, parts: list[str], is_stderr: bool = False):
                while True:
                    chunk = await stream.read(512)
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    parts.append(text)
                    if on_output:
                        try:
                            await on_output(text)
                        except Exception:
                            pass

            coro = asyncio.gather(
                _read_stream(process.stdout, stdout_parts),
                _read_stream(process.stderr, stderr_parts, is_stderr=True),
            )
            if timeout:
                await asyncio.wait_for(coro, timeout=timeout)
            else:
                await coro  # no timeout — wait until the command finishes
            await process.wait()

            stdout = "".join(stdout_parts)
            stderr = "".join(stderr_parts)

            # Truncate output if too long
            if len(stdout) > max_output:
                stdout = stdout[:max_output]
                truncated = True
            if len(stderr) > max_output:
                stderr = stderr[:max_output]
                truncated = True

            elapsed_ms = int((time.time() - start_time) * 1000)

            result = SandboxResult(
                command=command,
                stdout=stdout.strip(),
                stderr=stderr.strip(),
                exit_code=process.returncode or 0,
                elapsed_ms=elapsed_ms,
                truncated=truncated,
            )

            log.info(
                "Command executed",
                command=command,
                exit_code=result.exit_code,
                elapsed_ms=elapsed_ms,
            )

            return result

        except asyncio.TimeoutError:
            elapsed_ms = int((time.time() - start_time) * 1000)
            # Kill the process
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass

            return SandboxResult(
                command=command,
                stdout="",
                stderr=f"Command timed out after {timeout} seconds",
                exit_code=-1,
                elapsed_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return SandboxResult(
                command=command,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                elapsed_ms=elapsed_ms,
            )

    async def execute_with_confirmation(
        self,
        command: str,
        confirm_callback=None,
        **kwargs,
    ) -> SandboxResult:
        """
        Execute with optional confirmation step.
        
        If policies require confirmation and confirm_callback is provided,
        calls it first. For console usage, this is handled in the brain/channel layer.
        """
        if self.policy.needs_confirmation(command):
            if confirm_callback:
                approved = await confirm_callback(command)
                if not approved:
                    return SandboxResult(
                        command=command,
                        stdout="",
                        stderr="Command was not approved by user",
                        exit_code=-2,
                        elapsed_ms=0,
                    )
        
        return await self.execute(command, **kwargs)
