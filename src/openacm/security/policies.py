"""
Security policies for OpenACM.

Defines what commands can be executed, which paths are accessible,
and what patterns are blocked.
"""

import re
import platform
from pathlib import Path

import structlog

from openacm.core.config import SecurityConfig

log = structlog.get_logger()

# Commands that are ALWAYS blocked regardless of user config.
# These either escalate privileges (triggering UAC / su dialogs that hang the
# subprocess forever) or are otherwise too dangerous to allow the AI to run.
_ALWAYS_BLOCKED_PATTERNS: list[re.Pattern] = [
    # Windows privilege escalation
    re.compile(r"\brunas\b", re.IGNORECASE),
    re.compile(r"\bgsudo\b", re.IGNORECASE),
    # net user/localgroup modifications (adding accounts, granting admin)
    re.compile(r"\bnet\s+user\b.*/add\b", re.IGNORECASE),
    re.compile(r"\bnet\s+localgroup\s+administrators\b.*/add\b", re.IGNORECASE),
    # Linux/macOS privilege escalation
    re.compile(r"\bsudo\s+-s\b", re.IGNORECASE),      # sudo shell
    re.compile(r"\bsudo\s+-i\b", re.IGNORECASE),      # sudo login shell
    re.compile(r"\bsu\s+-\b", re.IGNORECASE),          # su root
    re.compile(r"\bchmod\s+[0-9]*[46][0-9]*\s", re.IGNORECASE),  # setuid/setgid
    re.compile(r"\bchown\s+root\b", re.IGNORECASE),
    # History/credential file exfil attempts
    re.compile(r"/etc/shadow", re.IGNORECASE),
    re.compile(r"/etc/passwd", re.IGNORECASE),
]


class SecurityViolation(Exception):
    """Raised when a security policy is violated."""
    pass


class SecurityPolicy:
    """Evaluates operations against security rules."""

    def __init__(self, config: SecurityConfig):
        self.config = config
        self._compiled_patterns: list[re.Pattern] = []
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile blocked patterns into regex for fast matching."""
        for pattern in self.config.blocked_patterns:
            try:
                escaped = re.escape(pattern)
                self._compiled_patterns.append(re.compile(escaped, re.IGNORECASE))
            except re.error:
                log.warning("Invalid blocked pattern", pattern=pattern)

    @property
    def execution_mode(self) -> str:
        """Current execution mode."""
        return self.config.execution_mode

    def check_command(self, command: str) -> tuple[bool, str]:
        """
        Check if a command is allowed.
        
        Returns: (allowed, reason)
        - If allowed: (True, "")
        - If blocked: (False, "reason why blocked")
        """
        # Check always-blocked patterns (hardcoded, cannot be overridden by config)
        for pattern in _ALWAYS_BLOCKED_PATTERNS:
            if pattern.search(command):
                reason = f"Command blocked: privilege escalation is not allowed"
                log.warning("Command blocked (always-blocked)", command=command, pattern=pattern.pattern)
                return False, reason

        # Check user-configured blocked patterns
        for pattern in self._compiled_patterns:
            if pattern.search(command):
                reason = f"Command matches blocked pattern: {pattern.pattern}"
                log.warning("Command blocked", command=command, reason=reason)
                return False, reason

        # Check if command executable is whitelisted (in auto mode)
        if self.config.execution_mode == "auto":
            cmd_parts = command.split()
            if cmd_parts:
                base_cmd = cmd_parts[0].lower()
                # Strip path to get just the executable name
                base_cmd = Path(base_cmd).name
                # Remove extension on Windows
                if platform.system() == "Windows" and "." in base_cmd:
                    base_cmd = base_cmd.rsplit(".", 1)[0]
                
                if base_cmd not in [c.lower() for c in self.config.whitelisted_commands]:
                    return False, f"Command '{base_cmd}' is not in the whitelist (auto mode)"

        return True, ""

    def check_path(self, path: str) -> tuple[bool, str]:
        """
        Check if a file path is allowed for access.
        
        Returns: (allowed, reason)
        """
        resolved = str(Path(path).resolve())
        
        for blocked_path in self.config.blocked_paths:
            blocked_resolved = str(Path(blocked_path).resolve())
            if resolved.startswith(blocked_resolved):
                reason = f"Path is in blocked area: {blocked_path}"
                log.warning("Path blocked", path=path, reason=reason)
                return False, reason

        return True, ""

    def needs_confirmation(self, command: str) -> bool:
        """
        Check if a command needs user confirmation before execution.
        """
        if self.config.execution_mode == "yolo":
            return False
        
        if self.config.execution_mode == "confirmation":
            return True
        
        # Auto mode: whitelisted commands don't need confirmation
        if self.config.execution_mode == "auto":
            cmd_parts = command.split()
            if cmd_parts:
                base_cmd = Path(cmd_parts[0]).name.lower()
                if platform.system() == "Windows" and "." in base_cmd:
                    base_cmd = base_cmd.rsplit(".", 1)[0]
                return base_cmd not in [c.lower() for c in self.config.whitelisted_commands]
        
        return True
