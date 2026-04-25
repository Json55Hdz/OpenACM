"""
Cross-platform OS Activity Watcher.

Polls the active window every 2 seconds and records focus sessions
into the database when the user switches apps.

Supported platforms:
  - Windows: ctypes (user32) + psutil — no extra deps needed
  - macOS:   osascript subprocess — no extra deps needed
  - Linux:   xdotool subprocess + psutil (xdotool must be installed)
"""

from __future__ import annotations

import asyncio
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import psutil
import structlog

from openacm.watchers.project_extractor import extract_project

if TYPE_CHECKING:
    from openacm.storage.database import Database

log = structlog.get_logger()
_SYSTEM = platform.system()  # 'Windows', 'Darwin', 'Linux'

# Apps to ignore (system UI, lock screens, etc.)
_IGNORE_APPS = {
    "explorer", "dwm", "winlogon", "csrss", "systemsettings",
    "searchhost", "startmenuexperiencehost", "shellexperiencehost",
    "lockapp", "screensaver", "logonui",
    "dock", "finder", "loginwindow", "systemuiserver",
    "xfwm4", "mutter", "kwin", "openbox",
}


@dataclass
class WindowInfo:
    app_name: str
    window_title: str
    process_name: str
    exe_path: str = field(default="")
    project_name: str = field(default="")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WindowInfo):
            return False
        return self.process_name.lower() == other.process_name.lower()


class ActivityWatcher:
    """Monitors active window changes and records focus sessions."""

    def __init__(self, db: "Database"):
        self._db = db
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._current: Optional[WindowInfo] = None
        self._session_start: Optional[datetime] = None
        self._poll_interval = 2.0

        # Public status fields
        self.current_app: str = "Unknown"
        self.current_title: str = ""
        self.current_project: str = ""
        self.is_running: bool = False
        self.sessions_recorded: int = 0

    # ─── Lifecycle ────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.is_running = True
        self._task = asyncio.create_task(self._loop(), name="activity_watcher")
        log.info("ActivityWatcher started", platform=_SYSTEM)

    async def stop(self) -> None:
        self._running = False
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Flush last session
        if self._current and self._session_start:
            await self._flush_session(datetime.now(timezone.utc))

    # ─── Main loop ────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            try:
                info = await asyncio.to_thread(self._get_active_window)
                now = datetime.now(timezone.utc)

                if info is None:
                    # Ignored app (lock screen, system UI) — flush current session
                    # so its time is not incorrectly attributed to the previous app.
                    if self._current and self._session_start:
                        await self._flush_session(now)
                        self._current = None
                        self._session_start = None
                        self.current_app = ""
                        self.current_title = ""
                        self.current_project = ""
                else:
                    self.current_app = info.app_name
                    self.current_title = info.window_title
                    self.current_project = info.project_name

                    if self._current is None:
                        self._current = info
                        self._session_start = now
                    elif info != self._current:
                        await self._flush_session(now)
                        self._current = info
                        self._session_start = now

            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.debug("ActivityWatcher poll error", error=str(exc))

            await asyncio.sleep(self._poll_interval)

    async def _flush_session(self, end: datetime) -> None:
        if not self._current or not self._session_start:
            return
        focus_seconds = (end - self._session_start).total_seconds()
        if focus_seconds < 5:
            return
        try:
            await self._db.log_app_activity(
                app_name=self._current.app_name,
                window_title=self._current.window_title,
                process_name=self._current.process_name,
                exe_path=self._current.exe_path,
                focus_seconds=focus_seconds,
                session_start=self._session_start.isoformat(),
                session_end=end.isoformat(),
                day_of_week=self._session_start.weekday(),
                hour_of_day=self._session_start.hour,
                project_name=self._current.project_name,
            )
            self.sessions_recorded += 1
        except Exception as exc:
            log.warning("ActivityWatcher flush error", error=str(exc))

    # ─── Platform-specific active-window detection ────────────

    def _get_active_window(self) -> Optional[WindowInfo]:
        try:
            if _SYSTEM == "Windows":
                return self._get_windows()
            elif _SYSTEM == "Darwin":
                return self._get_macos()
            else:
                return self._get_linux()
        except Exception:
            return None

    def _get_windows(self) -> Optional[WindowInfo]:
        import ctypes
        import ctypes.wintypes as wt

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        # Window title
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        window_title = buf.value or ""

        # PID → process name
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe_path = ""
        try:
            proc = psutil.Process(pid.value)
            process_name = proc.name()
            # Skip ignored system processes
            if process_name.lower().replace(".exe", "") in _IGNORE_APPS:
                return None
            app_name = process_name.replace(".exe", "").replace("_", " ").title()
            try:
                exe_path = proc.exe()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            app_name = "Unknown"
            process_name = "unknown"

        project_name = extract_project(process_name, window_title)
        return WindowInfo(app_name=app_name, window_title=window_title,
                          process_name=process_name, exe_path=exe_path, project_name=project_name)

    def _get_macos(self) -> Optional[WindowInfo]:
        import subprocess

        # Get frontmost app
        script = (
            'tell application "System Events" '
            'to name of first application process whose frontmost is true'
        )
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2)
        app_name = r.stdout.strip() if r.returncode == 0 else "Unknown"
        if not app_name or app_name.lower() in _IGNORE_APPS:
            return None

        # Try to get window title
        try:
            r2 = subprocess.run(
                ["osascript", "-e", f'tell application "{app_name}" to get name of front window'],
                capture_output=True, text=True, timeout=2,
            )
            window_title = r2.stdout.strip() if r2.returncode == 0 else ""
        except Exception:
            window_title = ""

        project_name = extract_project(app_name, window_title)
        return WindowInfo(app_name=app_name, window_title=window_title,
                          process_name=app_name.lower(), project_name=project_name)

    def _get_linux(self) -> Optional[WindowInfo]:
        import subprocess

        try:
            # Try xdotool first
            r = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=2,
            )
            window_title = r.stdout.strip() if r.returncode == 0 else ""

            # Get PID via xdotool
            r2 = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowpid"],
                capture_output=True, text=True, timeout=2,
            )
            pid_str = r2.stdout.strip()
            if pid_str.isdigit():
                proc = psutil.Process(int(pid_str))
                process_name = proc.name()
                if process_name.lower() in _IGNORE_APPS:
                    return None
                app_name = process_name.replace("-", " ").replace("_", " ").title()
                project_name = extract_project(process_name, window_title)
                return WindowInfo(app_name=app_name, window_title=window_title,
                                  process_name=process_name, project_name=project_name)
        except FileNotFoundError:
            pass  # xdotool not installed
        except Exception:
            pass

        # Fallback: use /proc/$(xprop _NET_ACTIVE_WINDOW) — skip on error
        return None
