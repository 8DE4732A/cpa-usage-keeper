"""Sync service: orchestrates data ingestion from CPA via redis."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from typing import Optional
from loguru import logger
from sqlalchemy.orm import Session
from ..cpa.client import CPAClient
from ..cpa.redis_queue import RedisQueueClient
from ..config import Config
from ..database import get_session
from ..models import UsageEvent
from ..repository import db as repo_db
from ..repository import auth_files as repo_auth
from ..repository import provider_metadata as repo_pm
from ..repository import redis_inbox as repo_inbox

def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

class SyncService:
    def __init__(self, cfg: Config, cpa_client: CPAClient,
                 redis_client: Optional[RedisQueueClient] = None):
        self.cfg = cfg
        self.cpa_client = cpa_client
        self.redis_client = redis_client
        self.sync_mode = cfg.usage_sync_mode

    def detect_sync_mode(self) -> str:
        if self.sync_mode != "auto":
            return self.sync_mode
        if self.redis_client:
            try:
                self.redis_client.probe()
                self.sync_mode = "redis"
                logger.info("Sync mode auto-detected: redis")
                return "redis"
            except Exception as e:
                logger.warning(f"Redis probe failed, falling back to legacy_export: {e}")
        self.sync_mode = "legacy_export"
        logger.info("Sync mode auto-detected: legacy_export")
        return "legacy_export"

    def pull_redis_inbox(self) -> dict:
        if not self.redis_client:
            return {"status": "failed", "error": "redis client not configured"}
        db = get_session()
        try:
            messages = self.redis_client.pop_usage()
            if not messages:
                return {"status": "completed", "empty": True, "count": 0}
            inputs = [{"queue_key": self.cfg.redis_queue_key, "raw_message": _mask_raw_message(m),
                        "popped_at": datetime.now(timezone.utc)} for m in messages]
            rows = repo_inbox.insert_inbox_messages(db, inputs)
            return {"status": "completed", "empty": False, "count": len(rows)}
        except Exception as e:
            logger.error(f"redis pull failed: {e}")
            return {"status": "failed", "error": str(e)}
        finally:
            db.close()

    def process_redis_inbox(self, sync_metadata: bool = False) -> dict:
        db = get_session()
        try:
            rows = repo_inbox.list_processable(db, limit=self.cfg.redis_queue_batch_size)
            if not rows:
                if sync_metadata:
                    self._sync_metadata(db)
                return {"status": "completed", "empty": True, "inserted_events": 0, "deduped_events": 0}
            events = []
            for row in rows:
                try:
                    ev = self._decode_redis_message(row.raw_message, row.popped_at)
                    events.append((row, ev))
                except Exception as e:
                    repo_inbox.mark_decode_failed(db, row.id, str(e))
            if not events:
                return {"status": "completed", "empty": True, "inserted_events": 0, "deduped_events": 0}
            usage_events = [ev for _, ev in events]
            inserted, deduped = repo_db.insert_usage_events(db, usage_events)
            now = datetime.now(timezone.utc)
            for row, ev in events:
                repo_inbox.mark_processed(db, row.id, ev.event_key, now)
            db.commit()
            if sync_metadata:
                self._sync_metadata(db)
            return {"status": "completed", "empty": False,
                    "inserted_events": inserted, "deduped_events": deduped}
        except Exception as e:
            logger.error(f"redis process failed: {e}")
            return {"status": "failed", "error": str(e)}
        finally:
            db.close()

    def sync_metadata_only(self) -> None:
        db = get_session()
        try:
            self._sync_metadata(db)
        finally:
            db.close()

    def cleanup_storage(self) -> None:
        db = get_session()
        try:
            p, f = repo_inbox.cleanup_inbox(db, datetime.now(timezone.utc))
            if p > 0 or f > 0:
                logger.info(f"Cleaned up redis inbox: {p} processed, {f} failed")
        except Exception as e:
            logger.error(f"storage cleanup failed: {e}")
        finally:
            db.close()

    def _sync_metadata(self, db: Session):
        try:
            auth_result = self.cpa_client.fetch_auth_files()
            if auth_result.status_code == 200:
                inputs = [{"auth_index": f.auth_index, "name": f.name, "email": f.email,
                           "type": f.type, "provider": f.provider, "label": f.label,
                           "status": f.status, "source": f.source, "disabled": f.disabled,
                           "unavailable": f.unavailable, "runtime_only": f.runtime_only}
                          for f in auth_result.files]
                repo_auth.replace_auth_files(db, inputs)
        except Exception as e:
            logger.warning(f"sync auth files failed: {e}")

        pm_items, provider_types = self._fetch_provider_metadata()
        if pm_items:
            try:
                repo_pm.replace_provider_metadata_for_types(db, pm_items, provider_types)
            except Exception as e:
                logger.warning(f"sync provider metadata failed: {e}")

    def _fetch_provider_metadata(self) -> tuple[list[dict], list[str]]:
        items = []
        types = []
        seen = set()
        def _add(lookup_key, ptype, display_name, pkey, match_kind):
            if not all([lookup_key.strip(), ptype.strip(), display_name.strip(),
                        pkey.strip(), match_kind.strip()]):
                return
            lk = lookup_key.strip()
            if lk in seen:
                return
            seen.add(lk)
            items.append({"lookup_key": lk, "provider_type": ptype.strip(),
                          "display_name": display_name.strip(), "provider_key": pkey.strip(),
                          "match_kind": match_kind.strip()})
        def _process_keys(ptype, fetch_fn):
            try:
                r = fetch_fn()
                if r.status_code == 200:
                    types.append(ptype)
                    for cfg in r.payload:
                        dn = cfg.prefix or cfg.name or ptype
                        pk = f"{ptype}:{dn}"
                        _add(cfg.api_key, ptype, dn, pk, "api_key")
                        _add(cfg.prefix, ptype, dn, pk, "prefix")
            except Exception as e:
                logger.warning(f"fetch {ptype} api keys failed: {e}")
        _process_keys("gemini", self.cpa_client.fetch_gemini_api_keys)
        _process_keys("claude", self.cpa_client.fetch_claude_api_keys)
        _process_keys("codex", self.cpa_client.fetch_codex_api_keys)
        _process_keys("vertex", self.cpa_client.fetch_vertex_api_keys)
        try:
            r = self.cpa_client.fetch_openai_compatibility()
            if r.status_code == 200:
                types.append("openai")
                for p in r.payload:
                    dn = p.name or p.prefix or "openai"
                    pk = f"openai:{dn}"
                    _add(p.prefix, "openai", dn, pk, "prefix")
                    for entry in p.api_key_entries:
                        _add(entry.api_key, "openai", dn, pk, "api_key")
        except Exception as e:
            logger.warning(f"fetch openai compatibility failed: {e}")
        return items, types

    def _decode_redis_message(self, message: str, popped_at: datetime) -> UsageEvent:
        data = json.loads(message)
        ts_str = data.get("timestamp", "")
        ts = None
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        if not ts:
            ts = popped_at
        ts = _to_naive_utc(ts)
        tokens_data = data.get("tokens", {})
        normalized = _normalize_tokens(tokens_data)
        api_key = data.get("api_key") or data.get("provider") or data.get("endpoint") or "unknown"
        provider = (data.get("provider") or "").strip()
        model_raw = (data.get("model") or "").strip()
        model = f"{provider}/{model_raw}" if provider and model_raw else model_raw or "unknown"
        source = (data.get("source") or "").strip()
        auth_index = (data.get("auth_index") or "").strip()
        request_id = (data.get("request_id") or "").strip()
        failed = data.get("failed", False)
        event_key = request_id or _build_event_key(
            api_key, model, ts, source, auth_index, failed, normalized)
        return UsageEvent(
            event_key=event_key, api_group_key=_mask(api_key), model=model,
            timestamp=ts, source=_mask(source), auth_index=auth_index,
            failed=failed, latency_ms=max(data.get("latency_ms", 0), 0),
            input_tokens=normalized["input_tokens"],
            output_tokens=normalized["output_tokens"],
            reasoning_tokens=normalized["reasoning_tokens"],
            cached_tokens=normalized["cached_tokens"],
            total_tokens=normalized["total_tokens"])


def _normalize_tokens(tokens) -> dict:
    get = tokens.get if isinstance(tokens, dict) else lambda k, d=0: getattr(tokens, k, d)
    it = max(get("input_tokens", 0), 0)
    ot = max(get("output_tokens", 0), 0)
    rt = max(get("reasoning_tokens", 0), 0)
    ct = max(get("cached_tokens", 0), 0)
    tt = max(get("total_tokens", 0), it + ot)
    return {"input_tokens": it, "output_tokens": ot, "reasoning_tokens": rt,
            "cached_tokens": ct, "total_tokens": tt}

def _mask(value: str) -> str:
    if len(value) <= 6:
        return value
    return value[:3] + "***" + value[-3:]


def _mask_raw_message(raw: str) -> str:
    try:
        data = json.loads(raw)
        for field in ("source", "api_key"):
            v = data.get(field)
            if isinstance(v, str) and v:
                data[field] = _mask(v)
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return raw


def _build_event_key(api_key, model, ts, source, auth_index, failed, tokens) -> str:
    parts = [str(api_key), str(model), ts.isoformat() if ts else "",
             str(source), str(auth_index), str(failed),
             str(tokens.get("input_tokens", 0)), str(tokens.get("output_tokens", 0)),
             str(tokens.get("total_tokens", 0))]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()
