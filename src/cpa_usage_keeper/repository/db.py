"""Core database operations: snapshot runs, usage events, storage cleanup."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import SnapshotRun, UsageEvent


def create_snapshot_run(db: Session, *, fetched_at: datetime, cpa_base_url: str = "",
                        exported_at: Optional[datetime] = None, version: str = "",
                        status: str = "pending", http_status: int = 0,
                        payload_hash: str = "", raw_payload: Optional[bytes] = None,
                        error_message: str = "") -> SnapshotRun:
    run = SnapshotRun(fetched_at=fetched_at, cpa_base_url=cpa_base_url,
                      exported_at=exported_at, version=version, status=status,
                      http_status=http_status, payload_hash=payload_hash,
                      raw_payload=raw_payload, error_message=error_message)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_snapshot_run(db: Session, run_id: int, **kwargs) -> None:
    kwargs["updated_at"] = datetime.now(timezone.utc)
    db.query(SnapshotRun).filter(SnapshotRun.id == run_id).update(kwargs)
    db.commit()


def insert_usage_events(db: Session, events: list[UsageEvent]) -> tuple[int, int]:
    if not events:
        return 0, 0
    inserted = deduped = 0
    for ev in events:
        stmt = sqlite_insert(UsageEvent).values(
            event_key=ev.event_key, snapshot_run_id=ev.snapshot_run_id,
            api_group_key=ev.api_group_key, model=ev.model,
            timestamp=ev.timestamp, source=ev.source, auth_index=ev.auth_index,
            failed=ev.failed, latency_ms=ev.latency_ms,
            input_tokens=ev.input_tokens, output_tokens=ev.output_tokens,
            reasoning_tokens=ev.reasoning_tokens, cached_tokens=ev.cached_tokens,
            total_tokens=ev.total_tokens,
        ).on_conflict_do_nothing(index_elements=["event_key"])
        r = db.execute(stmt)
        if r.rowcount > 0:
            inserted += 1
        else:
            deduped += 1
    db.commit()
    return inserted, deduped


def find_latest_usage_event_timestamp(db: Session) -> Optional[datetime]:
    return db.query(func.max(UsageEvent.timestamp)).scalar()


def cleanup_snapshot_runs(db: Session, retention_count: int = 100) -> int:
    count = db.query(func.count(SnapshotRun.id)).scalar() or 0
    if count <= retention_count:
        return 0
    threshold = db.query(SnapshotRun.id).order_by(SnapshotRun.id.desc()).offset(retention_count).limit(1).scalar()
    if threshold is None:
        return 0
    deleted = db.query(SnapshotRun).filter(SnapshotRun.id <= threshold).delete()
    db.commit()
    return deleted
