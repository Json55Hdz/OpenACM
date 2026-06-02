"""Gmail Classifier Plugin — AI-powered email categorization."""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from openacm.plugins import Plugin

log = structlog.get_logger()


class GmailClassifierPlugin(Plugin):
    name = "gmail_classifier"
    version = "1.0.0"
    description = "Classifies Gmail emails into user-defined categories using AI"
    author = "JsonProductions / OpenACM"

    def __init__(self):
        self._db = None
        self._processor = None
        self._cron_task: asyncio.Task | None = None

    # ── API router ─────────────────────────────────────────────

    def get_api_router(self):
        from openacm.plugins.gmail_classifier import router as _r
        return _r.router

    # ── Nav items ──────────────────────────────────────────────

    def get_nav_items(self) -> list[dict]:
        return [
            {
                "path": "/gmail-classifier",
                "label": "Gmail",
                "icon": "Mail",
                "section": "main",
            }
        ]

    # ── Lifecycle ──────────────────────────────────────────────

    async def on_start(self, *, database=None, llm_router=None, event_bus=None, **_) -> None:
        from openacm.plugins.gmail_classifier import processor as _proc_mod
        from openacm.plugins.gmail_classifier import router as _router_mod

        self._db = database

        # Seed default settings if not present
        if database:
            defaults = {
                "auto_mark_read": "false",
                "auto_apply_label": "false",
                "cron_schedule": "",
                "since_date_default": "",
            }
            for key, value in defaults.items():
                await database._db.execute(
                    "INSERT OR IGNORE INTO gmail_classifier_settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
            await database._db.commit()

        # Initialize processor and wire router
        self._processor = _proc_mod.GmailBatchProcessor(
            db=database,
            llm_router=llm_router,
            event_bus=event_bus,
        )
        _proc_mod._processor = self._processor
        _router_mod._db = database
        _router_mod._processor = self._processor

        # Start cron loop if a schedule is configured
        if database:
            cursor = await database._db.execute(
                "SELECT value FROM gmail_classifier_settings WHERE key = 'cron_schedule'"
            )
            row = await cursor.fetchone()
            schedule = row["value"] if row else ""
            if schedule:
                self._start_cron(schedule)

        log.info("GmailClassifierPlugin started")

    def _start_cron(self, schedule: str) -> None:
        if self._cron_task and not self._cron_task.done():
            self._cron_task.cancel()
        self._cron_task = asyncio.create_task(self._cron_loop(schedule))

    async def _cron_loop(self, schedule: str) -> None:
        from openacm.watchers.cron_scheduler import _next_cron_datetime
        import datetime as _dt

        while True:
            now = _dt.datetime.now(_dt.timezone.utc)
            try:
                next_run = _next_cron_datetime(schedule, now)
            except ValueError:
                log.warning("Invalid cron schedule, stopping cron loop", schedule=schedule)
                return
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(max(wait_seconds, 1))
            if self._processor:
                since_date = ""
                if self._db:
                    cursor = await self._db._db.execute(
                        "SELECT value FROM gmail_classifier_settings WHERE key = 'since_date_default'"
                    )
                    row = await cursor.fetchone()
                    since_date = row["value"] if row else ""
                if not since_date:
                    since_date = (
                        _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=30)
                    ).strftime("%Y/%m/%d")
                try:
                    await self._processor.process(since_date)
                except Exception as exc:
                    log.error("Cron gmail classification failed", error=str(exc))

    async def on_stop(self) -> None:
        if self._cron_task and not self._cron_task.done():
            self._cron_task.cancel()
            try:
                await self._cron_task
            except asyncio.CancelledError:
                pass


PLUGIN = GmailClassifierPlugin()
