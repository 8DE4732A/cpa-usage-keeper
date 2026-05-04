"""Redis usage inbox CRUD operations."""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from ..models import RedisUsageInbox

STATUS_PENDING = "pending"
STATUS_PROCESSED = "processed"
STATUS_DECODE_FAILED = "decode_failed"
STATUS_PROCESS_FAILED = "process_failed"
STATUS_DISCARDED = "discarded"
MAX_ERROR_LEN = 1024

def insert_inbox_messages(db: Session, messages: list[dict]) -> list[RedisUsageInbox]:
    if not messages:
        return []
    rows = []
    for m in messages:
        h = hashlib.sha256(m["raw_message"].encode()).hexdigest()
        rows.append(RedisUsageInbox(
            queue_key=m.get("queue_key", "").strip(), message_hash=h,
            raw_message=m["raw_message"], status=STATUS_PENDING,
            attempt_count=0, popped_at=m.get("popped_at", datetime.now(timezone.utc))))
    db.add_all(rows)
    db.commit()
    return rows

def mark_processed(db: Session, id_: int, event_key: str, processed_at: datetime):
    updates = {"status": STATUS_PROCESSED, "usage_event_key": event_key,
               "processed_at": processed_at, "last_error": ""}
    db.query(RedisUsageInbox).filter(RedisUsageInbox.id == id_).update(updates)

def mark_decode_failed(db: Session, id_: int, error: str):
    _mark_failed(db, id_, STATUS_DECODE_FAILED, error)

def mark_process_failed(db: Session, id_: int, error: str):
    _mark_failed(db, id_, STATUS_PROCESS_FAILED, error)

def _mark_failed(db: Session, id_: int, status: str, error: str):
    err_msg = error[:MAX_ERROR_LEN] if len(error) > MAX_ERROR_LEN else error
    row = db.query(RedisUsageInbox).filter(RedisUsageInbox.id == id_).first()
    if row:
        row.status = status
        row.attempt_count = (row.attempt_count or 0) + 1
        row.last_error = err_msg
        if row.attempt_count >= 5 and status == STATUS_PROCESS_FAILED:
            row.status = STATUS_DISCARDED
        db.commit()

def list_processable(db: Session, limit: int = 0) -> list[RedisUsageInbox]:
    q = db.query(RedisUsageInbox).filter(
        RedisUsageInbox.status.in_([STATUS_PENDING, STATUS_PROCESS_FAILED])
    ).order_by(RedisUsageInbox.id.asc())
    if limit > 0:
        q = q.limit(limit)
    return q.all()

def cleanup_inbox(db: Session, now: datetime) -> tuple[int, int]:
    local_now = now.astimezone()
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    processed_cutoff = day_start.astimezone(timezone.utc)
    failed_cutoff = now.astimezone(timezone.utc) - timedelta(days=7)
    p = db.query(RedisUsageInbox).filter(
        RedisUsageInbox.status == STATUS_PROCESSED,
        RedisUsageInbox.processed_at != None,
        RedisUsageInbox.processed_at < processed_cutoff).delete()
    f = db.query(RedisUsageInbox).filter(
        RedisUsageInbox.status.in_([STATUS_DECODE_FAILED, STATUS_PROCESS_FAILED, STATUS_DISCARDED]),
        RedisUsageInbox.updated_at < failed_cutoff).delete()
    db.commit()
    return p, f
