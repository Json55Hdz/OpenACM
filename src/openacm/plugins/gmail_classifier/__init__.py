"""Gmail Classifier Plugin — AI-powered email categorization."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from openacm.plugins import Plugin

log = structlog.get_logger()


# Defaults seeded on first run. Users can edit/delete them freely afterwards.
DEFAULT_CATEGORIES: list[dict] = [
    {
        "name": "Importantes",
        "description": "Correos críticos que requieren atención prioritaria.",
        "color": "#ef4444",
        "icon": "Star",
        "context": (
            "Esta categoría agrupa correos de alta prioridad para el usuario: "
            "comunicaciones personales urgentes, mensajes de jefes/clientes directos, "
            "facturas próximas a vencer, alertas de seguridad de cuentas (login sospechoso, "
            "cambio de contraseña), confirmaciones de pago, vuelos o reservas, citas médicas, "
            "y cualquier mensaje cuya postergación tenga costo real. Si el correo es "
            "promocional, newsletter, notificación social o marketing, NO va aquí."
        ),
        "known_senders": [],
        "patterns": [
            {"type": "subject_contains", "value": "urgente"},
            {"type": "subject_contains", "value": "acción requerida"},
            {"type": "subject_contains", "value": "factura vencida"},
        ],
    },
    {
        "name": "Legales",
        "description": "Notificaciones judiciales, entidades de control y trámites legales.",
        "color": "#8b5cf6",
        "icon": "Landmark",
        "context": (
            "Esta categoría agrupa correos de entidades del Estado, judiciales o de control "
            "(Procuraduría, Fiscalía, Contraloría, Defensoría del Pueblo, Rama Judicial, "
            "Superintendencias, DIAN, Notarías, ICBF, Migración Colombia, etc.), "
            "así como notificaciones de tutelas, demandas, citaciones, sentencias, "
            "requerimientos, autos, procesos disciplinarios o cualquier comunicación "
            "con implicaciones legales. NO incluye correos comerciales de abogados a "
            "menos que sean sobre un proceso activo del usuario."
        ),
        "known_senders": [],
        "patterns": [
            {"type": "sender_domain", "value": "procuraduria.gov.co"},
            {"type": "sender_domain", "value": "fiscalia.gov.co"},
            {"type": "sender_domain", "value": "contraloria.gov.co"},
            {"type": "sender_domain", "value": "defensoria.gov.co"},
            {"type": "sender_domain", "value": "ramajudicial.gov.co"},
            {"type": "sender_domain", "value": "cendoj.ramajudicial.gov.co"},
            {"type": "sender_domain", "value": "sic.gov.co"},
            {"type": "sender_domain", "value": "superfinanciera.gov.co"},
            {"type": "sender_domain", "value": "supersalud.gov.co"},
            {"type": "sender_domain", "value": "supersociedades.gov.co"},
            {"type": "sender_domain", "value": "dian.gov.co"},
            {"type": "sender_domain", "value": "icbf.gov.co"},
            {"type": "sender_domain", "value": "migracioncolombia.gov.co"},
            {"type": "sender_domain", "value": "minjusticia.gov.co"},
            {"type": "sender_domain", "value": "policia.gov.co"},
            {"type": "subject_contains", "value": "notificación judicial"},
            {"type": "subject_contains", "value": "tutela"},
            {"type": "subject_contains", "value": "demanda"},
            {"type": "subject_contains", "value": "citación"},
            {"type": "subject_contains", "value": "requerimiento"},
            {"type": "subject_contains", "value": "sentencia"},
            {"type": "subject_contains", "value": "proceso disciplinario"},
            {"type": "subject_contains", "value": "expediente"},
        ],
    },
]


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

            # Seed default categories (Importantes, Legales) once. We gate on a
            # settings flag so that if the user later deletes them on purpose,
            # we don't re-create them on the next restart.
            seeded_cursor = await database._db.execute(
                "SELECT value FROM gmail_classifier_settings WHERE key = 'default_categories_seeded'"
            )
            seeded_row = await seeded_cursor.fetchone()
            already_seeded = bool(seeded_row and seeded_row["value"] == "true")
            if not already_seeded:
                for cat in DEFAULT_CATEGORIES:
                    await database._db.execute(
                        "INSERT OR IGNORE INTO gmail_categories "
                        "(name, description, color, icon, context, known_senders, patterns) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            cat["name"],
                            cat["description"],
                            cat["color"],
                            cat["icon"],
                            cat["context"],
                            json.dumps(cat["known_senders"], ensure_ascii=False),
                            json.dumps(cat["patterns"], ensure_ascii=False),
                        ),
                    )
                await database._db.execute(
                    "INSERT INTO gmail_classifier_settings (key, value) VALUES ('default_categories_seeded', 'true') "
                    "ON CONFLICT(key) DO UPDATE SET value = 'true'"
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

        log.info("Gmail cron loop started", schedule=schedule)
        while True:
            now = _dt.datetime.now(_dt.timezone.utc)
            try:
                next_run = _next_cron_datetime(schedule, now)
            except ValueError:
                log.warning("Invalid gmail cron schedule, stopping", schedule=schedule)
                return

            wait_seconds = (next_run - now).total_seconds()
            # If wait is non-positive (clock skew / Windows resume from sleep)
            # we must NOT spin: sleep a full minute and re-evaluate. Without this
            # guard the loop would fire process() every 1s after the OS wakes up,
            # which is the cause of the "PC slow until I close openacm" symptom.
            if wait_seconds <= 0:
                log.warning(
                    "Gmail cron computed non-positive wait — likely clock skew "
                    "after OS resume. Backing off 60s.",
                    next_run=str(next_run), wait_seconds=round(wait_seconds),
                )
                await asyncio.sleep(60)
                continue

            log.info("Gmail cron next run", next_run=str(next_run), wait_seconds=round(wait_seconds))
            await asyncio.sleep(wait_seconds)

            if not self._processor:
                continue

            # Incremental window: prefer last_sync_at (minus 1 day for timezone
            # safety) over since_date_default. The de-dup skip in the processor
            # makes sure we never re-process the overlap.
            since_date = ""
            if self._db:
                try:
                    cursor = await self._db._db.execute(
                        "SELECT key, value FROM gmail_classifier_settings "
                        "WHERE key IN ('last_sync_at', 'since_date_default')"
                    )
                    rows = {r["key"]: r["value"] for r in await cursor.fetchall()}
                    last_sync = (rows.get("last_sync_at") or "").strip()
                    default = (rows.get("since_date_default") or "").strip()
                    if last_sync:
                        try:
                            sync_dt = _dt.datetime.fromisoformat(last_sync)
                            since_date = (sync_dt - _dt.timedelta(days=1)).strftime("%Y/%m/%d")
                        except Exception:
                            since_date = default
                    else:
                        since_date = default
                except Exception:
                    pass

            if not since_date:
                since_date = (
                    _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=30)
                ).strftime("%Y/%m/%d")

            log.info("Gmail cron firing", since_date=since_date)
            try:
                await self._processor.process(since_date)
                log.info("Gmail cron completed")
            except Exception as exc:
                log.error("Gmail cron classification failed", error=str(exc))
                # Continue loop — don't die on one failure

    async def on_stop(self) -> None:
        if self._cron_task and not self._cron_task.done():
            self._cron_task.cancel()
            try:
                await self._cron_task
            except asyncio.CancelledError:
                pass


PLUGIN = GmailClassifierPlugin()
