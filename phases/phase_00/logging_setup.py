"""structlog JSON logging — console + persistent log files for failure review."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

from phases.phase_00.config import get_settings

_CONFIGURED = False


def _ensure_log_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.DEBUG)

    log_dir = Path(settings.log_dir)
    _ensure_log_dir(log_dir)

    app_log_path = log_dir / settings.log_file_name
    errors_log_path = log_dir / settings.log_errors_file_name

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = logging.Formatter("%(message)s")
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    app_file = RotatingFileHandler(
        app_log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    app_file.setLevel(level)
    app_file.setFormatter(formatter)
    root.addHandler(app_file)

    errors_file = RotatingFileHandler(
        errors_log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    errors_file.setLevel(logging.WARNING)
    errors_file.setFormatter(formatter)
    root.addHandler(errors_file)

    structlog.get_logger(__name__).info(
        "logging_configured",
        log_dir=str(log_dir.resolve()),
        app_log=str(app_log_path.resolve()),
        errors_log=str(errors_log_path.resolve()),
        log_level=settings.log_level,
        phase=0,
    )

    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name)


def get_log_paths() -> dict[str, str]:
    settings = get_settings()
    log_dir = Path(settings.log_dir).resolve()
    return {
        "log_dir": str(log_dir),
        "app_log": str(log_dir / settings.log_file_name),
        "errors_log": str(log_dir / settings.log_errors_file_name),
    }
