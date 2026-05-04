"""Core database operations: usage events."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import UsageEvent


def insert_usage_events(db: Session, events: list[UsageEvent]) -> tuple[int, int]:
    if not events:
        return 0, 0
    inserted = deduped = 0
    for ev in events:
        stmt = sqlite_insert(UsageEvent).values(
            event_key=ev.event_key,
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
