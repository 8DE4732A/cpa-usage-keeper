"""Background pollers for redis drain, notifications, and OpenRouter sync."""
from __future__ import annotations
import asyncio
import threading
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from loguru import logger
from sqlalchemy.orm import Session
from ..service.sync import SyncService
from ..repository.notification import evaluate_rules, send_pending_notifications
from ..repository.pricing import auto_sync_openrouter_prices


class PollerStatus:
    """Thread-safe status tracker shared between pollers and API."""

    def __init__(self):
        self._lock = threading.Lock()
        self.running = True
        self.sync_running = False
        self.last_run_at: Optional[datetime] = None
        self.last_error = ""
        self.last_warning = ""
        self.last_status = ""

    def to_dict(self) -> dict:
        with self._lock:
            result = {
                "running": self.running,
                "sync_running": self.sync_running,
                "timezone": str(_time.tzname),
                "last_error": self.last_error,
                "last_warning": self.last_warning,
                "last_status": self.last_status,
            }
            if self.last_run_at:
                result["last_run_at"] = self.last_run_at.isoformat()
            return result

    def mark_sync_start(self):
        with self._lock:
            self.sync_running = True

    def mark_sync_done(self, status: str = "", error: str = "", warning: str = ""):
        with self._lock:
            self.sync_running = False
            self.last_run_at = datetime.now(timezone.utc)
            self.last_status = status
            self.last_error = error
            self.last_warning = warning


class RedisDrain:
    def __init__(self, sync_service: SyncService, idle_interval: timedelta,
                 error_backoff: timedelta, metadata_interval: timedelta,
                 status: Optional[PollerStatus] = None):
        self.sync_service = sync_service
        self.idle_interval = idle_interval
        self.error_backoff = error_backoff
        self.metadata_interval = metadata_interval
        self.status = status
        self._running = False
        self._last_metadata_sync = None

    async def run(self):
        self._running = True
        logger.info("Redis drain started")
        pull_task = asyncio.create_task(self._pull_loop())
        process_task = asyncio.create_task(self._process_loop())
        try:
            await asyncio.gather(pull_task, process_task)
        except asyncio.CancelledError:
            pull_task.cancel()
            process_task.cancel()
            await asyncio.gather(pull_task, process_task, return_exceptions=True)
            raise
        finally:
            self._running = False

    async def sync_now(self):
        """Trigger a manual pull + process cycle."""
        if self.status:
            self.status.mark_sync_start()
        try:
            self.sync_service.pull_redis_inbox()
            result = self.sync_service.process_redis_inbox(sync_metadata=True)
            self._last_metadata_sync = datetime.now(timezone.utc)
            status_str = result.get("status", "unknown")
            error = result.get("error", "")
            if status_str == "completed":
                if self.status:
                    self.status.mark_sync_done(status=status_str)
            else:
                if self.status:
                    self.status.mark_sync_done(status=status_str, warning=error)
        except Exception as e:
            logger.error(f"Manual redis sync error: {e}")
            if self.status:
                self.status.mark_sync_done(status="failed", error=str(e))

    async def _pull_loop(self):
        logger.info(f"Redis pull loop started, idle_interval={self.idle_interval}")
        while self._running:
            try:
                result = self.sync_service.pull_redis_inbox()
                if result.get("status") == "completed" and not result.get("empty", True):
                    if self.status:
                        self.status.mark_sync_done(status="completed")
                if result.get("empty", True):
                    await asyncio.sleep(self.idle_interval.total_seconds())
            except Exception as e:
                logger.error(f"Redis pull error: {e}")
                if self.status:
                    self.status.mark_sync_done(status="failed", error=str(e))
                await asyncio.sleep(self.error_backoff.total_seconds())

    async def _process_loop(self):
        logger.info("Redis process loop started, interval=5s")
        while self._running:
            await asyncio.sleep(5)
            try:
                sync_meta = self._should_sync_metadata()
                result = self.sync_service.process_redis_inbox(sync_metadata=sync_meta)
                if sync_meta and result.get("status") == "completed":
                    self._last_metadata_sync = datetime.now(timezone.utc)
            except Exception as e:
                logger.error(f"Redis process error: {e}")

    def _should_sync_metadata(self) -> bool:
        if self._last_metadata_sync is None:
            return True
        return datetime.now(timezone.utc) - self._last_metadata_sync >= self.metadata_interval

    def stop(self):
        self._running = False


class MaintenanceRunner:
    def __init__(self, sync_service: SyncService):
        self.sync_service = sync_service
        self._running = False

    async def run(self):
        self._running = True
        logger.info("Maintenance runner started")
        while self._running:
            now = datetime.now()
            local_now = now.astimezone()
            next_cleanup = local_now.replace(hour=3, minute=0, second=0, microsecond=0)
            if local_now >= next_cleanup:
                next_cleanup += timedelta(days=1)
            delay = (next_cleanup - local_now).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
            if not self._running:
                break
            try:
                self.sync_service.cleanup_storage()
                logger.info("Daily storage cleanup completed")
            except Exception as e:
                logger.error(f"Storage cleanup failed: {e}")

    def stop(self):
        self._running = False


class BackupRunner:
    def __init__(self, backup_writer, db_path: str, interval: timedelta, retention_days: int):
        self.backup_writer = backup_writer
        self.db_path = db_path
        self.interval = interval
        self.retention_days = retention_days
        self._running = False
        self._last_backup = None
        self._retry_count = 0

    async def run(self):
        self._running = True
        logger.info(f"Backup runner started, interval={self.interval}")
        last = self.backup_writer.last_backup_at()
        if last:
            self._last_backup = last

        while self._running:
            delay = self._next_delay()
            if delay > 0:
                await asyncio.sleep(delay)
            if not self._running:
                break
            try:
                path = self.backup_writer.write_database(self.db_path)
                logger.info(f"Database backup created: {path}")
                self._last_backup = datetime.now()
                self._retry_count = 0
                self.backup_writer.cleanup(self.retention_days)
            except Exception as e:
                logger.error(f"Database backup failed: {e}")
                self._retry_count += 1

    def _next_delay(self) -> float:
        if self._retry_count > 0 and self._retry_count <= 3:
            return 15 * 60  # 15 min retry
        if self._last_backup is None:
            return 0
        elapsed = (datetime.now() - self._last_backup).total_seconds()
        remaining = self.interval.total_seconds() - elapsed
        return max(remaining, 0)

    def stop(self):
        self._running = False


class NotificationRunner:
    """Periodically evaluate notification rules and send alerts."""

    def __init__(self, session_factory: Callable[[], Session], interval: timedelta):
        self.session_factory = session_factory
        self.interval = interval
        self._running = False

    async def run(self):
        self._running = True
        logger.info(f"Notification runner started, interval={self.interval}")
        while self._running:
            pending = []
            try:
                db = self.session_factory()
                try:
                    pending = evaluate_rules(db)
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Notification rule evaluation failed: {e}")

            # Send webhooks outside the DB session so a slow HTTP call doesn't
            # block other requests on the single SQLite connection (pool_size=1).
            if pending:
                try:
                    db = self.session_factory()
                    try:
                        triggered = send_pending_notifications(db, pending)
                        for t in triggered:
                            status = "sent" if t.get("sent") else "failed"
                            logger.info(
                                f"Notification rule '{t['rule_name']}' triggered, "
                                f"status={status}"
                            )
                    finally:
                        db.close()
                except Exception as e:
                    logger.error(f"Notification delivery failed: {e}")

            await asyncio.sleep(self.interval.total_seconds())

    def stop(self):
        self._running = False


class OpenRouterSyncRunner:
    """Periodically auto-sync OpenRouter prices for rows that are missing them.

    Runs every N minutes and fills in openrouter_* columns for any
    ModelPriceSetting row where they are NULL (e.g. because the model is new
    or the initial sync failed).
    """

    def __init__(self, session_factory: Callable[[], Session], interval: timedelta):
        self.session_factory = session_factory
        self.interval = interval
        self._running = False

    async def run(self):
        self._running = True
        logger.info(f"OpenRouter auto-sync runner started, interval={self.interval}")
        while self._running:
            try:
                db = self.session_factory()
                try:
                    result = auto_sync_openrouter_prices(db)
                    di = result.get("deepinfra_matched", 0)
                    or_ = result.get("openrouter_matched", 0)
                    created = result.get("created", 0)
                    if di > 0 or or_ > 0 or created > 0:
                        logger.info(f"Price auto-sync: DeepInfra={di} OR={or_} created={created}")
                    if result.get("errors"):
                        logger.warning(
                            f"Price auto-sync errors: {'; '.join(result['errors'])}"
                        )
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"OpenRouter auto-sync failed: {e}")
            await asyncio.sleep(self.interval.total_seconds())

    def stop(self):
        self._running = False
