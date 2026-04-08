"""
Routine Executor for OpenACM.

Launches the apps listed in a detected routine using platform-specific
open commands.

Windows resolution order (per app):
  1. exe_path stored in routine (full path captured at watcher time)
  2. Windows App Paths registry lookup  (HKLM + HKCU)
  3. `where {process_name}` shell command (searches PATH)
  4. os.startfile fallback (ShellExecute — works for registered associations)
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
from typing import Any

import structlog

log = structlog.get_logger()
_SYSTEM = platform.system()


class RoutineExecutor:
    """Executes a routine by launching its configured apps."""

    async def execute(self, routine: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Launch every app in the routine.
        Returns a per-app result list: [{app, status, error?}].
        """
        raw_apps = routine.get("apps", "[]")
        if isinstance(raw_apps, str):
            try:
                apps = json.loads(raw_apps)
            except json.JSONDecodeError:
                apps = []
        else:
            apps = raw_apps

        results: list[dict[str, Any]] = []
        for app_info in apps:
            result = await asyncio.to_thread(self._launch, app_info)
            results.append(result)
            await asyncio.sleep(0.5)

        return results

    # ─── Platform dispatch ────────────────────────────────────

    def _launch(self, app_info: dict[str, Any]) -> dict[str, Any]:
        app_name: str = app_info.get("app_name", "")
        process_name: str = app_info.get("process_name", "")
        exe_path: str = app_info.get("exe_path", "")

        if not app_name and not process_name and not exe_path:
            return {"app": "unknown", "status": "skipped", "error": "no app name"}

        try:
            if _SYSTEM == "Windows":
                return self._launch_windows(app_name, process_name, exe_path)
            elif _SYSTEM == "Darwin":
                return self._launch_macos(app_name)
            else:
                return self._launch_linux(app_name, process_name, exe_path)
        except Exception as exc:
            log.warning("Routine launch error", app=app_name, error=str(exc))
            return {"app": app_name, "status": "error", "error": str(exc)}

    # ─── Windows ─────────────────────────────────────────────

    def _launch_windows(self, app_name: str, process_name: str, exe_path: str) -> dict[str, Any]:
        # Strategy 1: stored exe_path is a valid file
        if exe_path and os.path.isfile(exe_path):
            subprocess.Popen(
                [exe_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"app": app_name, "status": "launched", "via": "exe_path"}

        # Strategy 2: Windows App Paths registry
        resolved = self._resolve_via_registry(process_name)
        if resolved:
            subprocess.Popen(
                [resolved],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"app": app_name, "status": "launched", "via": "registry"}

        # Strategy 3: `where` command (searches PATH)
        resolved = self._resolve_via_where(process_name)
        if resolved:
            subprocess.Popen(
                [resolved],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"app": app_name, "status": "launched", "via": "where"}

        # Strategy 4: os.startfile (ShellExecute — handles registered associations)
        target = process_name if process_name else app_name
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return {"app": app_name, "status": "launched", "via": "startfile"}
        except OSError:
            pass

        # Strategy 5: start "" shell command (last resort)
        subprocess.Popen(
            f'start "" "{target}"',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"app": app_name, "status": "launched", "via": "start_shell"}

    def _resolve_via_registry(self, process_name: str) -> str:
        """Look up the App Paths registry key for the given exe name."""
        if not process_name:
            return ""
        try:
            import winreg  # type: ignore[import]
        except ImportError:
            return ""

        exe = process_name if process_name.lower().endswith(".exe") else process_name + ".exe"
        sub_key = f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{exe}"

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(hive, sub_key)
                path, _ = winreg.QueryValueEx(key, "")
                winreg.CloseKey(key)
                if path and os.path.isfile(path):
                    return path
            except OSError:
                continue
        return ""

    def _resolve_via_where(self, process_name: str) -> str:
        """Use `where` to find the executable on PATH."""
        if not process_name:
            return ""
        target = process_name if process_name.lower().endswith(".exe") else process_name + ".exe"
        try:
            result = subprocess.run(
                ["where", target],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                first_line = result.stdout.strip().splitlines()[0]
                if first_line and os.path.isfile(first_line):
                    return first_line
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return ""

    # ─── macOS ───────────────────────────────────────────────

    def _launch_macos(self, app_name: str) -> dict[str, Any]:
        subprocess.Popen(
            ["open", "-a", app_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"app": app_name, "status": "launched"}

    # ─── Linux ───────────────────────────────────────────────

    def _launch_linux(self, app_name: str, process_name: str, exe_path: str) -> dict[str, Any]:
        # Use stored path if valid
        if exe_path and os.path.isfile(exe_path):
            subprocess.Popen(
                [exe_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"app": app_name, "status": "launched", "via": "exe_path"}

        target = process_name if process_name else app_name.lower().replace(" ", "-")
        subprocess.Popen(
            [target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"app": app_name, "status": "launched"}
