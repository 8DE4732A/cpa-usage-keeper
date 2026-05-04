"""SQLite database backup management."""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, time
from pathlib import Path
from typing import Optional

from loguru import logger


class BackupWriter:
    """Writes SQLite database backups and manages retention."""

    def __init__(self, directory: str):
        self.directory = directory.strip()

    def write_database(self, db_path: str, backup_at: Optional[datetime] = None) -> str:
        """Create a backup of the SQLite database."""
        if not self.directory:
            raise ValueError("backup directory is required")
        if not db_path:
            raise ValueError("database path is required")

        stamp = (backup_at or datetime.now()).astimezone()
        day_dir = Path(self.directory) / stamp.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(str(day_dir), 0o700)

        file_name = f"database_{stamp.strftime('%Y%m%dT%H%M%S.%f')}.db"
        full_path = day_dir / file_name
        temp_path = str(full_path) + ".tmp"

        try:
            source_conn = sqlite3.connect(db_path)
            dest_conn = sqlite3.connect(temp_path)
            source_conn.backup(dest_conn)
            dest_conn.close()
            source_conn.close()
            os.chmod(temp_path, 0o600)
            os.rename(temp_path, str(full_path))
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

        return str(full_path)

    def cleanup(self, retention_days: int, now: Optional[datetime] = None) -> int:
        """Remove backup directories older than retention_days."""
        if not self.directory or retention_days <= 0:
            return 0

        now = now or datetime.now()
        local_now = now.astimezone()
        cutoff = datetime(local_now.year, local_now.month, local_now.day).astimezone()
        from datetime import timedelta
        cutoff -= timedelta(days=retention_days)

        backup_dir = Path(self.directory)
        if not backup_dir.exists():
            return 0

        removed = 0
        for entry in sorted(backup_dir.iterdir()):
            if not entry.is_dir():
                continue
            try:
                backup_day = datetime.strptime(entry.name, "%Y-%m-%d")
                backup_day = backup_day.replace(tzinfo=local_now.tzinfo)
            except ValueError:
                continue
            if backup_day < cutoff:
                shutil.rmtree(str(entry))
                removed += 1

        return removed

    def last_backup_at(self) -> Optional[datetime]:
        """Find the modification time of the most recent backup file."""
        backup_dir = Path(self.directory)
        if not backup_dir.exists():
            return None
        latest = None
        for root, dirs, files in os.walk(str(backup_dir)):
            for f in files:
                if f.endswith(".db"):
                    file_path = Path(root) / f
                    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if latest is None or mtime > latest:
                        latest = mtime
        return latest
