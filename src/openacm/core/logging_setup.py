"""
Logging configuration for OpenACM.

Sets up structlog with:
- Console: colored, human-readable output with timestamps and log levels
- File: JSON lines rotating file at data/logs/openacm.log (kept 7 days)
"""

import logging
import logging.handlers
import sys
from pathlib import Path

import structlog


def configure_logging(log_dir: Path | None = None, level: str = "INFO"):
    """Configure structlog + stdlib logging with console and file handlers."""

    log_level = getattr(logging, level.upper(), logging.INFO)

    # ── Shared processors (applied to all outputs) ────────────────────────
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.StackInfoRenderer(),
    ]

    # ── File handler (JSON lines, rotating) ──────────────────────────────
    if log_dir is None:
        log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "openacm.log"

    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )
    file_handler.setFormatter(file_formatter)

    # ── Console handler (colored, human-readable) ─────────────────────────
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        foreign_pre_chain=shared_processors,
    )
    console_handler.setFormatter(console_formatter)

    # ── Root logger ───────────────────────────────────────────────────────
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.setLevel(log_level)

    # Silence noisy third-party loggers — kept at WARNING even in DEBUG mode
    for noisy in (
        "httpx", "httpcore", "uvicorn.access", "multipart",
        "telegram", "telegram.ext", "telegram.ext.ExtBot",
        "apscheduler", "hpack", "h2",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # ── Structlog ─────────────────────────────────────────────────────────
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
