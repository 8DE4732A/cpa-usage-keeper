"""Logging configuration using loguru."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

from .config import Config


def configure_logging(cfg: Config) -> None:
    """Configure loguru logging with optional daily rotating file output."""
    # Remove default handler
    logger.remove()

    level = cfg.log_level.upper()
    if level not in ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"):
        level = "INFO"

    fmt = "<green>{time:YYYY-MM-DDTHH:mm:ss.SSSZ}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"

    # Always output to stderr
    logger.add(sys.stderr, level=level, format=fmt, colorize=True)

    if cfg.log_file_enabled:
        log_dir = Path(cfg.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = str(log_dir / "cpa-usage-keeper-{time:YYYY-MM-DD}.log")
        logger.add(
            log_file,
            level=level,
            format=fmt,
            rotation="00:00",
            retention=f"{cfg.log_retention_days} days" if cfg.log_retention_days > 0 else None,
            compression=None,
            enqueue=True,
        )

    logger.info(f"Logging configured: level={level}, file_enabled={cfg.log_file_enabled}")
