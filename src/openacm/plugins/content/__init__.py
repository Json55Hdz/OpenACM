"""
OpenACM Content Automation Plugin.

Automatically detects interesting moments during work sessions and generates
social media post drafts (Facebook, Reddit) for user approval.

Features:
  - capture_content_moment  — LLM calls this when something notable happens
  - generate_content_for_moment — vision analysis + platform-specific copy
  - list_content_moments    — browse captured moments
  - generate_meme           — Pillow / image-gen API meme creation
  - create_slideshow_video  — ffmpeg video from screenshots
  - Social media publishing (Facebook Graph API, Reddit praw)

Install (add to OpenACM):
    from openacm.plugins.content import PLUGIN
    from openacm.plugins import plugin_manager
    plugin_manager.register(PLUGIN)

Or just import this package — it auto-registers via PLUGIN at module bottom.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openacm.plugins import Plugin


class ContentAutomationPlugin(Plugin):
    name = "content_automation"
    version = "0.1.0"
    description = "Auto-generates social media content from work sessions"
    author = "JsonProductions / OpenACM"

    def __init__(self):
        self._watcher = None

    # ── Tools ──────────────────────────────────────────────────

    def get_tool_modules(self) -> list[Any]:
        from openacm.tools import content_gen_tool, social_media_tool
        return [content_gen_tool, social_media_tool]

    # ── Brain context ──────────────────────────────────────────

    def get_context_extension(self) -> str:
        return (
            "## Content & Social Media\n"
            "When the user achieves something notable (problem solved, feature works, "
            "cool demo, funny moment), call `capture_content_moment` silently — "
            "it takes one screenshot, analyses it with vision, and queues a post draft "
            "for approval. The user reviews at /content before anything is published.\n"
            "Only call it for genuinely share-worthy moments. Skip routine messages."
        )

    # ── Intent routing ─────────────────────────────────────────

    def get_intent_keywords(self) -> dict[str, list[str]]:
        return {
            "content": [
                # Explicit content requests
                "post", "publish", "publicar", "publicación",
                "facebook", "reddit", "redes sociales", "social media",
                "content", "contenido", "meme", "story", "historia",
                # Achievement / completion — KEY triggers for auto-capture
                "done", "listo", "terminé", "terminado",
                "funcionó", "funciona", "it works", "ya funciona",
                "lo arreglé", "arreglado", "fixed", "solved", "resuelto",
                "completado", "completed", "finished",
                "lo logré", "lo hice", "conseguí", "salió", "salió bien",
                "look at this", "mira esto", "ya quedó",
            ],
        }

    # ── Frontend nav items ─────────────────────────────────────

    def get_nav_items(self) -> list[dict]:
        return [
            {
                "path": "/content",
                "label": "Content",
                "icon": "Newspaper",
                "section": "main",
            }
        ]

    # ── Lifecycle ──────────────────────────────────────────────

    async def on_start(
        self,
        *,
        database=None,
        event_bus=None,
        llm_router=None,
        activity_watcher=None,
        workspace_root: Path | None = None,
        **_,
    ) -> None:
        from openacm.watchers.content_session_watcher import ContentSessionWatcher
        from openacm.tools import content_gen_tool as _cgt, social_media_tool as _smt

        ws = workspace_root or Path("workspace")
        self._watcher = ContentSessionWatcher(
            activity_watcher=activity_watcher,
            event_bus=event_bus,
            workspace_root=ws,
        )
        await self._watcher.start()

        # Inject dependencies into tool modules
        _cgt._content_watcher = self._watcher
        _cgt._database = database
        _cgt._llm_router = llm_router
        _smt._database = database

    async def on_stop(self) -> None:
        if self._watcher:
            await self._watcher.stop()
            self._watcher = None


# Module-level singleton — importable by app.py or any integrator
PLUGIN = ContentAutomationPlugin()
