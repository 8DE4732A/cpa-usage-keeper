"""Auth files CRUD operations."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from ..models import AuthFile

def replace_auth_files(db: Session, files: list[dict]) -> None:
    seen = set()
    normalized = []
    indexes = []
    for f in files:
        idx = f.get("auth_index", "").strip()
        if not idx or idx in seen:
            continue
        seen.add(idx)
        indexes.append(idx)
        normalized.append(AuthFile(
            auth_index=idx, name=f.get("name", "").strip(),
            email=f.get("email", "").strip(), type=f.get("type", "").strip(),
            provider=f.get("provider", "").strip(), label=f.get("label", "").strip(),
            status=f.get("status", "").strip(), source=f.get("source", "").strip(),
            disabled=f.get("disabled", False), unavailable=f.get("unavailable", False),
            runtime_only=f.get("runtime_only", False)))
    if not normalized:
        db.query(AuthFile).filter(AuthFile.deleted_at == None).update(
            {"deleted_at": datetime.now(timezone.utc)})
        db.commit()
        return
    for af in normalized:
        stmt = sqlite_insert(AuthFile).values(
            auth_index=af.auth_index, name=af.name, email=af.email,
            type=af.type, provider=af.provider, label=af.label,
            status=af.status, source=af.source, disabled=af.disabled,
            unavailable=af.unavailable, runtime_only=af.runtime_only,
            deleted_at=None
        ).on_conflict_do_update(
            index_elements=["auth_index"],
            set_={"name": af.name, "email": af.email, "type": af.type,
                   "provider": af.provider, "label": af.label, "status": af.status,
                   "source": af.source, "disabled": af.disabled, "unavailable": af.unavailable,
                   "runtime_only": af.runtime_only, "updated_at": datetime.now(timezone.utc),
                   "deleted_at": None})
        db.execute(stmt)
    db.query(AuthFile).filter(AuthFile.auth_index.notin_(indexes), AuthFile.deleted_at == None).update(
        {"deleted_at": datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()

def list_auth_files(db: Session) -> list[AuthFile]:
    return db.query(AuthFile).filter(AuthFile.deleted_at == None).order_by(AuthFile.auth_index.asc()).all()
