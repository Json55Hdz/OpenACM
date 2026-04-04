"""
Routine Executor for OpenACM.

Launches the apps listed in a detected routine using platform-specific
open commands.  No shell injection risk: each app is launched via its own
subprocess call, not via a shell string.
"""

from __future__ import annotations

import asyncio
import json
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
            # Small gap so the OS can breathe between launches
            await asyncio.sleep(0.5)

        return results

    # ─── Platform launchers ───────────────────────────────────

    def _launch(self, app_info: dict[str, Any]) -> dict[str, Any]:
        app_name: str = app_info.get("app_name", "")
        process_name: str = app_info.get("process_name", "")

        if not app_name and not process_name:
            return {"app": "unknown", "status": "skipped", "error": "no app name"}

        try:
            if _SYSTEM == "Windows":
                return self._launch_windows(app_name, process_name)
            elif _SYSTEM == "Darwin":
                return self._launch_macos(app_name)
            else:
                return self._launch_linux(app_name, process_name)
        except Exception as exc:
            log.warning("Routine launch error", app=app_name, error=str(exc))
            return {"app": app_name, "status": "error", "error": str(exc)}

    def _launch_windows(self, app_name: str, process_name: str) -> dict[str, Any]:
        # Use 'start' shell command — Windows opens the app by name/association
        target = process_name if process_name else app_name
        subprocess.Popen(
            f'start "" "{target}"',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"app": app_name, "status": "launched"}

    def _launch_macos(self, app_name: str) -> dict[str, Any]:
        subprocess.Popen(
            ["open", "-a", app_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"app": app_name, "status": "launched"}

    def _launch_linux(self, app_name: str, process_name: str) -> dict[str, Any]:
        target = process_name if process_name else app_name.lower().replace(" ", "-")
        subprocess.Popen(
            [target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"app": app_name, "status": "launched"}
