"""Provider metadata CRUD operations."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from ..models import ProviderMetadata

def replace_provider_metadata_for_types(db: Session, items: list[dict], provider_types: list[str]) -> None:
    allowed = {t.strip() for t in provider_types if t.strip()}
    if not allowed:
        return
    seen = set()
    normalized = []
    keys = []
    for item in items:
        lk = item.get("lookup_key", "").strip()
        pt = item.get("provider_type", "").strip()
        if not lk or pt not in allowed or lk in seen:
            continue
        seen.add(lk)
        keys.append(lk)
        normalized.append(item)
    for item in normalized:
        stmt = sqlite_insert(ProviderMetadata).values(
            lookup_key=item["lookup_key"].strip(),
            provider_type=item.get("provider_type", "").strip(),
            display_name=item.get("display_name", "").strip(),
            provider_key=item.get("provider_key", "").strip(),
            match_kind=item.get("match_kind", "").strip(),
            deleted_at=None,
        ).on_conflict_do_update(
            index_elements=["lookup_key"],
            set_={"provider_type": item.get("provider_type", "").strip(),
                   "display_name": item.get("display_name", "").strip(),
                   "provider_key": item.get("provider_key", "").strip(),
                   "match_kind": item.get("match_kind", "").strip(),
                   "updated_at": datetime.now(timezone.utc), "deleted_at": None})
        db.execute(stmt)
    q = db.query(ProviderMetadata).filter(
        ProviderMetadata.provider_type.in_(list(allowed)),
        ProviderMetadata.deleted_at == None)
    if keys:
        q = q.filter(ProviderMetadata.lookup_key.notin_(keys))
    q.update({"deleted_at": datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()

def list_provider_metadata(db: Session) -> list[ProviderMetadata]:
    return db.query(ProviderMetadata).filter(ProviderMetadata.deleted_at == None).order_by(
        ProviderMetadata.provider_type.asc(), ProviderMetadata.display_name.asc()).all()
