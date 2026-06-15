"""Configuration loading from config.toml."""

from __future__ import annotations

import os
import posixpath
import time as _time
import tomllib
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_WORK_DIR = Path("./data")
DEFAULT_SQLITE_NAME = "app.db"
DEFAULT_LOG_DIR_NAME = "logs"
DEFAULT_BACKUP_DIR_NAME = "backups"


class Config:
    """Application configuration loaded from config.toml."""

    def __init__(
        self,
        *,
        app_port: str = "8080",
        app_base_path: str = "",
        cpa_base_url: str = "",
        cpa_management_key: str = "",
        poll_interval: timedelta = timedelta(minutes=5),
        usage_sync_mode: str = "auto",
        redis_queue_addr: str = "",
        redis_queue_key: str = "usage",
        redis_queue_batch_size: int = 1000,
        redis_queue_idle_interval: timedelta = timedelta(seconds=1),
        redis_queue_error_backoff: timedelta = timedelta(seconds=10),
        redis_metadata_sync_interval: timedelta = timedelta(seconds=30),
        work_dir: str = str(DEFAULT_WORK_DIR),
        sqlite_path: str = "",
        backup_enabled: bool = True,
        backup_dir: str = "",
        backup_interval: timedelta = timedelta(hours=24),
        backup_retention_days: int = 7,
        request_timeout: timedelta = timedelta(seconds=30),
        log_level: str = "info",
        log_file_enabled: bool = True,
        log_dir: str = "",
        log_retention_days: int = 7,
        auth_enabled: bool = False,
        login_password: str = "",
        auth_session_ttl: timedelta = timedelta(hours=168),
    ):
        self.app_port = app_port
        self.app_base_path = app_base_path
        self.cpa_base_url = cpa_base_url
        self.cpa_management_key = cpa_management_key
        self.poll_interval = poll_interval
        self.usage_sync_mode = usage_sync_mode
        self.redis_queue_addr = redis_queue_addr
        self.redis_queue_key = redis_queue_key
        self.redis_queue_batch_size = redis_queue_batch_size
        self.redis_queue_idle_interval = redis_queue_idle_interval
        self.redis_queue_error_backoff = redis_queue_error_backoff
        self.redis_metadata_sync_interval = redis_metadata_sync_interval
        self.work_dir = work_dir
        self.sqlite_path = sqlite_path or str(Path(work_dir) / DEFAULT_SQLITE_NAME)
        self.backup_enabled = backup_enabled
        self.backup_dir = backup_dir or str(Path(work_dir) / DEFAULT_BACKUP_DIR_NAME)
        self.backup_interval = backup_interval
        self.backup_retention_days = backup_retention_days
        self.request_timeout = request_timeout
        self.log_level = log_level
        self.log_file_enabled = log_file_enabled
        self.log_dir = log_dir or str(Path(work_dir) / DEFAULT_LOG_DIR_NAME)
        self.log_retention_days = log_retention_days
        self.auth_enabled = auth_enabled
        self.login_password = login_password
        self.auth_session_ttl = auth_session_ttl


def _parse_duration(value: str) -> timedelta:
    """Parse Go-style duration string."""
    value = value.strip()
    if not value:
        raise ValueError("empty duration")

    total_seconds = 0.0
    current = ""
    for char in value:
        if char.isdigit() or char == ".":
            current += char
        elif char in ("h", "m", "s"):
            if not current:
                raise ValueError(f"invalid duration: {value}")
            num = float(current)
            if char == "h":
                total_seconds += num * 3600
            elif char == "m":
                total_seconds += num * 60
            elif char == "s":
                total_seconds += num
            current = ""
        else:
            raise ValueError(f"invalid duration character: {char}")

    if current:
        total_seconds += float(current)

    return timedelta(seconds=total_seconds)


def _get_duration(d: Dict[str, Any], key: str, default: timedelta) -> timedelta:
    val = d.get(key)
    if not val:
        return default
    if isinstance(val, (int, float)):
        return timedelta(seconds=float(val))
    return _parse_duration(str(val))


def _normalize_base_path(value: str) -> str:
    value = str(value).strip()
    if not value or value == "/":
        return ""
    if not value.startswith("/"):
        raise ValueError("APP_BASE_PATH must start with '/'")
    normalized = posixpath.normpath(value)
    if normalized == "." or normalized == "/":
        return ""
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized


def _apply_timezone(tz: str):
    tz = tz.strip()
    if not tz:
        tz = DEFAULT_TIMEZONE
    os.environ["TZ"] = tz
    try:
        _time.tzset()
    except AttributeError:
        pass


def _resolve_relative(base_dir: str, value: str) -> str:
    if not value or os.path.isabs(value):
        return value
    return str(Path(base_dir) / value)


def load_config(config_file: str = "config.toml") -> Config:
    """Load configuration from a TOML file."""
    config_path = Path(config_file)
    if not config_path.exists():
        if config_file == "config.toml":
            # If default doesn't exist, we can either error out or use absolute defaults.
            # However, CPA_BASE_URL and CPA_MANAGEMENT_KEY are required, so it will error anyway.
            data = {}
        else:
            raise FileNotFoundError(f"config file not found: {config_file}")
    else:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)

    base_dir = str(config_path.parent.resolve()) if config_path.exists() else str(Path.cwd())

    app_sec = data.get("app", {})
    cpa_sec = data.get("cpa", {})
    sync_sec = data.get("sync", {})
    redis_sec = data.get("redis", {})
    storage_sec = data.get("storage", {})
    log_sec = data.get("log", {})
    auth_sec = data.get("auth", {})

    _apply_timezone(str(app_sec.get("timezone", DEFAULT_TIMEZONE)))

    usage_sync_mode = str(sync_sec.get("mode", "auto"))
    if usage_sync_mode not in ("auto", "redis", "legacy_export"):
        raise ValueError("sync.mode must be one of auto, redis, legacy_export")

    cpa_base_url = str(cpa_sec.get("base_url", "")).strip()
    cpa_management_key = str(cpa_sec.get("management_key", "")).strip()

    if not cpa_base_url:
        raise ValueError("cpa.base_url is required")
    if not cpa_management_key:
        raise ValueError("cpa.management_key is required")

    auth_enabled = bool(auth_sec.get("enabled", False))
    login_password = str(auth_sec.get("password", "")).strip()
    if auth_enabled and not login_password:
        raise ValueError("auth.password is required when auth.enabled is true")

    queue_batch_size = int(redis_sec.get("queue_batch_size", 1000))
    if queue_batch_size <= 0:
        raise ValueError("redis.queue_batch_size must be positive")

    backup_retention_days = int(storage_sec.get("backup_retention_days", 7))
    if backup_retention_days < 0:
        raise ValueError("storage.backup_retention_days must be non-negative")

    log_retention_days = int(log_sec.get("retention_days", 7))
    if log_retention_days < 0:
        raise ValueError("log.retention_days must be non-negative")

    work_dir = str(storage_sec.get("work_dir", str(DEFAULT_WORK_DIR)))

    cfg = Config(
        app_port=str(app_sec.get("port", "8080")),
        app_base_path=_normalize_base_path(app_sec.get("base_path", "")),
        cpa_base_url=cpa_base_url,
        cpa_management_key=cpa_management_key,
        poll_interval=_get_duration(sync_sec, "poll_interval", timedelta(minutes=5)),
        usage_sync_mode=usage_sync_mode,
        redis_queue_addr=str(redis_sec.get("queue_addr", "")).strip(),
        redis_queue_key=str(redis_sec.get("queue_key", "usage")).strip() or "usage",
        redis_queue_batch_size=queue_batch_size,
        redis_queue_idle_interval=_get_duration(redis_sec, "queue_idle_interval", timedelta(seconds=1)),
        redis_queue_error_backoff=timedelta(seconds=10),
        redis_metadata_sync_interval=timedelta(seconds=30),
        work_dir=work_dir,
        backup_enabled=bool(storage_sec.get("backup_enabled", True)),
        backup_interval=_get_duration(storage_sec, "backup_interval", timedelta(hours=24)),
        backup_retention_days=backup_retention_days,
        request_timeout=_get_duration(cpa_sec, "request_timeout", timedelta(seconds=30)),
        log_level=str(log_sec.get("level", "info")),
        log_file_enabled=bool(log_sec.get("file_enabled", True)),
        log_retention_days=log_retention_days,
        auth_enabled=auth_enabled,
        login_password=login_password,
        auth_session_ttl=_get_duration(auth_sec, "session_ttl", timedelta(hours=168)),
    )

    if base_dir:
        cfg.work_dir = _resolve_relative(base_dir, cfg.work_dir)
        cfg.sqlite_path = _resolve_relative(base_dir, cfg.sqlite_path)
        cfg.log_dir = _resolve_relative(base_dir, cfg.log_dir)
        cfg.backup_dir = _resolve_relative(base_dir, cfg.backup_dir)

    return cfg
