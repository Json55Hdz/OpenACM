"""
Content Session Watcher.

Passively tracks the currently active window/app so tools have context.
Screenshots are captured ON DEMAND via capture_now() — called by the LLM
when it detects a content-worthy moment, NOT on a timer.

Flow:
    User works on something interesting
    → LLM (brain) recognises a content opportunity
    → calls capture_content_moment tool
    → tool calls ContentSessionWatcher.capture_now(context, moment_type)
    → screenshot saved to workspace/content/moments/<date>/<id>/
    → event "content:moment_captured" emitted with metadata
    → generate_content_for_moment tool picks it up and generates social posts
    → posts queued for user approval at /content dashboard
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from openacm.core.events import EventBus
    from openacm.watchers.activity_watcher import ActivityWatcher

log = structlog.get_logger()

# How often to poll the active window for context (seconds) — no screenshots here
POLL_INTERVAL = 5


class ContentSessionWatcher:
    """
    Tracks active window context passively.
    Provides capture_now() for on-demand screenshot capture by the LLM.
    """

    def __init__(
        self,
        activity_watcher: Optional["ActivityWatcher"] = None,
        event_bus: Optional["EventBus"] = None,
        workspace_root: Optional[Path] = None,
    ):
        self._activity = activity_watcher
        self._event_bus = event_bus
        self._workspace = Path(workspace_root) if workspace_root else Path("workspace")
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Current window context (updated by poll loop, used to enrich moments)
        self.current_app: str = ""
        self.current_title: str = ""
        self.current_exe: str = ""

    # ── Lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="content_session_watcher")
        log.info("ContentSessionWatcher started (passive window tracking)")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── Passive window tracking loop ───────────────────────────

    async def _loop(self) -> None:
        """Just keeps current_app / current_title fresh. No screenshots."""
        while self._running:
            try:
                if self._activity:
                    # Pull context from ActivityWatcher if available
                    self.current_app = getattr(self._activity, "current_app", "") or ""
                    self.current_title = getattr(self._activity, "current_title", "") or ""
                    proc = getattr(self._activity, "_current", None)
                    if proc:
                        self.current_exe = getattr(proc, "exe_path", "") or ""
            except asyncio.CancelledError:
                break
            except Exception:
                pass
            await asyncio.sleep(POLL_INTERVAL)

    # ── On-demand screenshot capture ───────────────────────────

    async def capture_now(
        self,
        context: str,
        moment_type: str = "achievement",
        tags: list[str] | None = None,
    ) -> dict:
        """
        Capture a screenshot of the current screen and save it as a content moment.

        Args:
            context:     Why this moment is interesting (provided by the LLM).
            moment_type: 'achievement', 'problem_solved', 'demo', 'progress', 'funny', 'tutorial'
            tags:        Optional topic tags for later filtering.

        Returns:
            Metadata dict with moment_id, image_path, timestamp, etc.
        """
        ts = datetime.now(timezone.utc)
        date_str = ts.strftime("%Y-%m-%d")
        moment_id = secrets.token_hex(6)

        moment_dir = self._workspace / "content" / "moments" / date_str / moment_id
        moment_dir.mkdir(parents=True, exist_ok=True)

        img_path = moment_dir / "screenshot.png"
        thumb_path = moment_dir / "thumb.jpg"

        # Take screenshot
        capture_error: str | None = None
        try:
            import mss
            from PIL import Image
            import io

            with mss.mss() as sct:
                # Primary monitor only (index 1 = first real monitor; 0 = combined)
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

                # Save full PNG
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                img_path.write_bytes(buf.getvalue())

                # Save small JPEG thumbnail for quick preview
                thumb = img.copy()
                thumb.thumbnail((640, 360))
                thumb.save(thumb_path, format="JPEG", quality=75)

        except ImportError:
            capture_error = "mss or Pillow not installed"
        except Exception as exc:
            capture_error = str(exc)
            log.warning("ContentSessionWatcher: screenshot failed", error=capture_error)

        # Enrich with current window context
        meta = {
            "moment_id": moment_id,
            "timestamp": ts.isoformat(),
            "date": date_str,
            "moment_type": moment_type,
            "context": context,
            "tags": tags or [],
            "active_app": self.current_app,
            "active_title": self.current_title,
            "active_exe": self.current_exe,
            "image_path": str(img_path) if not capture_error else None,
            "thumb_path": str(thumb_path) if not capture_error else None,
            "capture_error": capture_error,
        }

        meta_path = moment_dir / "meta.json"
        meta_path.write_text(json.dumps(meta, indent=2))

        log.info(
            "ContentSessionWatcher: moment captured",
            moment_id=moment_id,
            type=moment_type,
            has_screenshot=capture_error is None,
        )

        if self._event_bus:
            await self._event_bus.emit("content:moment_captured", meta)

        return meta

    # ── Query helpers ──────────────────────────────────────────

    def get_moment(self, moment_id: str, date_str: str | None = None) -> dict | None:
        """Load metadata for a specific moment."""
        base = self._workspace / "content" / "moments"
        if date_str:
            meta_path = base / date_str / moment_id / "meta.json"
            if meta_path.exists():
                try:
                    return json.loads(meta_path.read_text())
                except Exception:
                    return None
        # Search all dates if date not provided
        for date_dir in sorted(base.iterdir(), reverse=True) if base.exists() else []:
            meta_path = date_dir / moment_id / "meta.json"
            if meta_path.exists():
                try:
                    return json.loads(meta_path.read_text())
                except Exception:
                    return None
        return None

    def list_moments(self, date_str: str | None = None, limit: int = 20) -> list[dict]:
        """Return recent moment metadata dicts, newest first."""
        base = self._workspace / "content" / "moments"
        if not base.exists():
            return []

        dates = (
            [date_str] if date_str
            else sorted((d.name for d in base.iterdir() if d.is_dir()), reverse=True)
        )

        results: list[dict] = []
        for d in dates:
            day_dir = base / d
            if not day_dir.exists():
                continue
            for moment_dir in sorted(day_dir.iterdir(), reverse=True):
                meta_path = moment_dir / "meta.json"
                if meta_path.exists():
                    try:
                        results.append(json.loads(meta_path.read_text()))
                    except Exception:
                        pass
                if len(results) >= limit:
                    return results
        return results

    def list_dates(self) -> list[str]:
        """Return sorted list of dates that have captured moments."""
        base = self._workspace / "content" / "moments"
        if not base.exists():
            return []
        return sorted((d.name for d in base.iterdir() if d.is_dir()), reverse=True)
