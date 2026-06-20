"""Usage query repository with filtering, aggregation, and overview building."""
from __future__ import annotations
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import case, func, literal_column
from sqlalchemy.orm import Session
from ..models import UsageEvent, ModelPriceSetting
from .pricing import effective_price
from ..cpa.types import StatisticsSnapshot, APISnapshot, ModelSnapshot, RequestDetail, TokenStats

class UsageQueryFilter:
    def __init__(self, *, range_: str = "all", start_time: Optional[datetime] = None,
                 end_time: Optional[datetime] = None, limit: int = 100,
                 page: int = 1, page_size: int = 100, offset: int = 0,
                 model: str = "", source: str = "", auth_index: str = "", result: str = ""):
        self.range_ = range_
        self.start_time = start_time
        self.end_time = end_time
        self.limit = limit
        self.page = page
        self.page_size = page_size
        self.offset = offset
        self.model = model
        self.source = source
        self.auth_index = auth_index
        self.result = result

def _apply_list_filter(query, f: UsageQueryFilter):
    return query.filter(*_build_filters(f))

def list_usage_events(db: Session, f: UsageQueryFilter):
    base = _apply_list_filter(db.query(UsageEvent), f)
    total = base.count()
    models = _facet_values(db, f, "model")
    sources = _facet_values(db, f, "source")
    page = max(f.page, 1)
    page_size = f.page_size if f.page_size > 0 else f.limit if f.limit > 0 else 100
    offset = f.offset if f.offset > 0 else (page - 1) * page_size
    events = base.order_by(
        UsageEvent.timestamp.desc(), UsageEvent.id.desc()
    ).limit(page_size).offset(offset).all()
    total_pages = int((total + page_size - 1) / page_size) if total > 0 else 0
    return {"events": events, "models": models, "sources": sources,
            "total_count": total, "page": page, "page_size": page_size, "total_pages": total_pages}

def list_usage_event_filter_options(db: Session, f: UsageQueryFilter):
    return {"models": _facet_values(db, f, "model"), "sources": _facet_values(db, f, "source")}

def _facet_values(db: Session, f: UsageQueryFilter, column: str) -> list[str]:
    col = getattr(UsageEvent, column)
    q = _apply_list_filter(db.query(func.distinct(func.trim(col))), f)
    q = q.filter(func.trim(col) != "").order_by(func.trim(col).asc())
    return [r[0] for r in q.all()]

def list_credential_stats(db: Session, f: UsageQueryFilter):
    q = _apply_list_filter(db.query(
        func.trim(UsageEvent.source).label("source"),
        func.trim(UsageEvent.auth_index).label("auth_index"),
        UsageEvent.failed,
        func.count().label("request_count"),
    ), f).group_by(
        func.trim(UsageEvent.source), func.trim(UsageEvent.auth_index), UsageEvent.failed
    ).order_by(func.count().desc())
    return [{"source": r.source, "auth_index": r.auth_index, "failed": r.failed,
             "request_count": r.request_count} for r in q.all()]

def list_analysis_stats(db: Session, f: UsageQueryFilter):
    api_rows = db.query(
        func.trim(UsageEvent.api_group_key).label("api_group_key"),
        func.count().label("total_requests"),
        func.sum(case((UsageEvent.failed == False, 1), else_=0)).label("success_count"),
        func.sum(case((UsageEvent.failed == True, 1), else_=0)).label("failure_count"),
        func.sum(UsageEvent.input_tokens).label("input_tokens"),
        func.sum(UsageEvent.output_tokens).label("output_tokens"),
        func.sum(UsageEvent.reasoning_tokens).label("reasoning_tokens"),
        func.sum(UsageEvent.cached_tokens).label("cached_tokens"),
        func.sum(UsageEvent.total_tokens).label("total_tokens"),
    ).filter(*_build_filters(f)).group_by(func.trim(UsageEvent.api_group_key)).order_by(func.count().desc()).all()

    model_rows = db.query(
        func.trim(UsageEvent.model).label("model"),
        func.count().label("total_requests"),
        func.sum(case((UsageEvent.failed == False, 1), else_=0)).label("success_count"),
        func.sum(case((UsageEvent.failed == True, 1), else_=0)).label("failure_count"),
        func.sum(UsageEvent.input_tokens).label("input_tokens"),
        func.sum(UsageEvent.output_tokens).label("output_tokens"),
        func.sum(UsageEvent.reasoning_tokens).label("reasoning_tokens"),
        func.sum(UsageEvent.cached_tokens).label("cached_tokens"),
        func.sum(UsageEvent.total_tokens).label("total_tokens"),
        func.sum(UsageEvent.latency_ms).label("total_latency_ms"),
        func.sum(case((UsageEvent.latency_ms > 0, 1), else_=0)).label("latency_sample_count"),
    ).filter(*_build_filters(f)).group_by(func.trim(UsageEvent.model)).order_by(func.count().desc()).all()

    api_model_rows = db.query(
        func.trim(UsageEvent.api_group_key).label("api_group_key"),
        func.trim(UsageEvent.model).label("model"),
        func.count().label("total_requests"),
        func.sum(case((UsageEvent.failed == False, 1), else_=0)).label("success_count"),
        func.sum(case((UsageEvent.failed == True, 1), else_=0)).label("failure_count"),
        func.sum(UsageEvent.input_tokens).label("input_tokens"),
        func.sum(UsageEvent.output_tokens).label("output_tokens"),
        func.sum(UsageEvent.reasoning_tokens).label("reasoning_tokens"),
        func.sum(UsageEvent.cached_tokens).label("cached_tokens"),
        func.sum(UsageEvent.total_tokens).label("total_tokens"),
        func.sum(UsageEvent.latency_ms).label("total_latency_ms"),
        func.sum(case((UsageEvent.latency_ms > 0, 1), else_=0)).label("latency_sample_count"),
    ).filter(*_build_filters(f)).group_by(
        func.trim(UsageEvent.api_group_key), func.trim(UsageEvent.model)
    ).order_by(func.trim(UsageEvent.api_group_key).asc(), func.count().desc()).all()

    models_by_api = {}
    for r in api_model_rows:
        key = (r.api_group_key or "").strip() or "unknown"
        models_by_api.setdefault(key, []).append(_model_row_to_dict(r))

    apis = []
    for r in api_rows:
        key = (r.api_group_key or "").strip() or "unknown"
        apis.append({
            "api_group_key": key, "display_name": key,
            "total_requests": r.total_requests, "success_count": r.success_count,
            "failure_count": r.failure_count, "input_tokens": r.input_tokens or 0,
            "output_tokens": r.output_tokens or 0, "reasoning_tokens": r.reasoning_tokens or 0,
            "cached_tokens": r.cached_tokens or 0, "total_tokens": r.total_tokens or 0,
            "models": models_by_api.get(key, []),
        })

    models = [_model_row_to_dict(r) for r in model_rows]
    return {"apis": apis, "models": models}

def _model_row_to_dict(r):
    return {
        "model": (r.model or "").strip() or "unknown",
        "total_requests": r.total_requests, "success_count": r.success_count,
        "failure_count": r.failure_count, "input_tokens": r.input_tokens or 0,
        "output_tokens": r.output_tokens or 0, "reasoning_tokens": r.reasoning_tokens or 0,
        "cached_tokens": r.cached_tokens or 0, "total_tokens": r.total_tokens or 0,
        "total_latency_ms": r.total_latency_ms or 0,
        "latency_sample_count": r.latency_sample_count or 0,
    }

def _build_filters(f: UsageQueryFilter):
    filters = []
    if f.start_time:
        filters.append(UsageEvent.timestamp >= f.start_time)
    if f.end_time:
        filters.append(UsageEvent.timestamp <= f.end_time)
    if f.model and f.model.strip():
        filters.append(func.trim(UsageEvent.model) == f.model.strip())
    if f.source and f.source.strip():
        filters.append(func.trim(UsageEvent.source) == f.source.strip())
    if f.auth_index and f.auth_index.strip():
        filters.append(func.trim(UsageEvent.auth_index) == f.auth_index.strip())
    if f.result == "success":
        filters.append(UsageEvent.failed == False)
    elif f.result == "failed":
        filters.append(UsageEvent.failed == True)
    return filters if filters else [literal_column("1=1")]

def build_usage_overview(db: Session, f: UsageQueryFilter):
    events = _apply_list_filter(db.query(UsageEvent), f).order_by(UsageEvent.timestamp.asc()).all()
    pricing_map = _load_pricing_map(db)
    window_minutes = _compute_window_minutes(f)
    bucket_by_day = _should_bucket_by_day(f, window_minutes)
    latest_hourly_start = _latest_hourly_start(f)

    snapshot = StatisticsSnapshot(apis={}, requests_by_day={}, requests_by_hour={},
                                  tokens_by_day={}, tokens_by_hour={})
    summary = {"request_count": 0, "token_count": 0, "window_minutes": window_minutes,
               "rpm": 0.0, "tpm": 0.0, "total_cost": 0.0, "cost_available": True,
               "cached_tokens": 0, "reasoning_tokens": 0}
    series = _new_series()
    hourly_series = _new_series()
    daily_series = _new_series()
    health = _build_health(f)

    for ev in events:
        _apply_event_to_snapshot(snapshot, ev, False)
        model_name = (ev.model or "").strip() or "unknown"
        pricing = pricing_map.get(model_name)
        if pricing is None:
            summary["cost_available"] = False
            cost = 0.0
        else:
            cost = _calc_cost(ev, pricing)
        summary["total_cost"] += cost
        summary["cached_tokens"] += ev.cached_tokens or 0
        summary["reasoning_tokens"] += ev.reasoning_tokens or 0

        if ev.failed:
            health["total_failure"] += 1
        else:
            health["total_success"] += 1

        bk, bm = _bucket(ev.timestamp, bucket_by_day)
        _apply_to_series(series, ev, cost, bk, bm)
        hk, hm = _bucket(ev.timestamp, False)
        if latest_hourly_start is None or ev.timestamp >= latest_hourly_start:
            _apply_to_series(hourly_series, ev, cost, hk, hm)
        dk, dm = _bucket(ev.timestamp, True)
        _apply_to_series(daily_series, ev, cost, dk, dm)
        _update_health_block(health["block_details"], ev, health["_start"], health["_span_s"])

    summary["request_count"] = snapshot.total_requests
    summary["token_count"] = snapshot.total_tokens
    if window_minutes > 0:
        summary["rpm"] = summary["request_count"] / window_minutes
        summary["tpm"] = summary["token_count"] / window_minutes
    total_h = health["total_success"] + health["total_failure"]
    if total_h > 0:
        health["success_rate"] = (health["total_success"] / total_h) * 100

    return {"usage": snapshot, "summary": summary, "series": series,
            "hourly_series": hourly_series, "daily_series": daily_series, "service_health": health,
            "timezone": str(_time.tzname),
            "range_start": f.start_time.isoformat() if f.start_time else None,
            "range_end": f.end_time.isoformat() if f.end_time else None}

def build_usage_snapshot(db: Session, f: UsageQueryFilter) -> StatisticsSnapshot:
    events = _apply_list_filter(db.query(UsageEvent), f).order_by(UsageEvent.timestamp.asc()).all()
    snapshot = StatisticsSnapshot(apis={}, requests_by_day={}, requests_by_hour={},
                                  tokens_by_day={}, tokens_by_hour={})
    for ev in events:
        _apply_event_to_snapshot(snapshot, ev, True)
    _finalize_snapshot(snapshot)
    return snapshot

def _apply_event_to_snapshot(snap: StatisticsSnapshot, ev: UsageEvent, include_details: bool):
    api_key = (ev.api_group_key or "").strip() or "unknown"
    model_name = (ev.model or "").strip() or "unknown"
    if api_key not in snap.apis:
        snap.apis[api_key] = APISnapshot(models={})
    api = snap.apis[api_key]
    if model_name not in api.models:
        api.models[model_name] = ModelSnapshot(details=[])
    ms = api.models[model_name]
    if include_details:
        ms.details.append(RequestDetail(
            timestamp=ev.timestamp, latency_ms=ev.latency_ms or 0,
            source=(ev.source or "").strip(), auth_index=(ev.auth_index or "").strip(),
            failed=ev.failed or False,
            tokens=TokenStats(input_tokens=ev.input_tokens or 0, output_tokens=ev.output_tokens or 0,
                              reasoning_tokens=ev.reasoning_tokens or 0, cached_tokens=ev.cached_tokens or 0,
                              total_tokens=ev.total_tokens or 0)))
    ms.total_requests += 1
    ms.total_tokens += ev.total_tokens or 0
    api.total_requests += 1
    api.total_tokens += ev.total_tokens or 0
    snap.total_requests += 1
    snap.total_tokens += ev.total_tokens or 0
    if ev.failed:
        ms.failure_count += 1; api.failure_count += 1; snap.failure_count += 1
    else:
        ms.success_count += 1; api.success_count += 1; snap.success_count += 1
    ts = ev.timestamp
    day_key = ts.astimezone().strftime("%Y-%m-%d") if ts else ""
    hour_key = ts.strftime("%Y-%m-%dT%H:00:00Z") if ts else ""
    if day_key:
        snap.requests_by_day[day_key] = snap.requests_by_day.get(day_key, 0) + 1
        snap.tokens_by_day[day_key] = snap.tokens_by_day.get(day_key, 0) + (ev.total_tokens or 0)
    if hour_key:
        snap.requests_by_hour[hour_key] = snap.requests_by_hour.get(hour_key, 0) + 1
        snap.tokens_by_hour[hour_key] = snap.tokens_by_hour.get(hour_key, 0) + (ev.total_tokens or 0)

def _finalize_snapshot(snap: StatisticsSnapshot):
    for api in snap.apis.values():
        for ms in api.models.values():
            ms.details.sort(key=lambda d: d.timestamp)

def _load_pricing_map(db: Session) -> dict:
    settings = db.query(ModelPriceSetting).all()
    return {s.model.strip(): s for s in settings}

def _calc_cost(ev: UsageEvent, pricing: ModelPriceSetting) -> float:
    input_t = max(ev.input_tokens or 0, 0)
    output_t = max(ev.output_tokens or 0, 0)
    cached_t = max(ev.cached_tokens or 0, 0)
    prompt_t = max(input_t - cached_t, 0)
    prompt_px = effective_price(pricing, "prompt_price_per_1m")
    completion_px = effective_price(pricing, "completion_price_per_1m")
    cache_px = effective_price(pricing, "cache_price_per_1m")
    return ((prompt_t / 1_000_000) * prompt_px +
            (output_t / 1_000_000) * completion_px +
            (cached_t / 1_000_000) * cache_px)

def _compute_window_minutes(f: UsageQueryFilter) -> int:
    if not f.start_time or not f.end_time:
        return 0
    diff = f.end_time - f.start_time
    minutes = int(diff.total_seconds() / 60)
    if diff.total_seconds() % 60 != 0:
        minutes += 1
    return max(minutes, 1)

def _should_bucket_by_day(f: UsageQueryFilter, window_minutes: int) -> bool:
    if f.range_ in ("all", "7d"):
        return True
    return window_minutes >= 7 * 24 * 60

def _bucket(timestamp: datetime, by_day: bool) -> tuple[str, int]:
    if by_day:
        return timestamp.astimezone().strftime("%Y-%m-%d"), 24 * 60
    return timestamp.strftime("%Y-%m-%dT%H:00:00Z"), 60

def _latest_hourly_start(f: UsageQueryFilter) -> Optional[datetime]:
    if not f.end_time:
        return None
    hour = f.end_time.replace(minute=0, second=0, microsecond=0)
    return hour - timedelta(hours=23)

def _new_series():
    return {"requests": {}, "tokens": {}, "rpm": {}, "tpm": {}, "cost": {},
            "input_tokens": {}, "output_tokens": {}, "cached_tokens": {},
            "reasoning_tokens": {}, "models": {}}

def _apply_to_series(s, ev, cost, bk, bm):
    s["requests"][bk] = s["requests"].get(bk, 0) + 1
    s["tokens"][bk] = s["tokens"].get(bk, 0) + (ev.total_tokens or 0)
    s["cost"][bk] = s["cost"].get(bk, 0) + cost
    s["input_tokens"][bk] = s["input_tokens"].get(bk, 0) + (ev.input_tokens or 0)
    s["output_tokens"][bk] = s["output_tokens"].get(bk, 0) + (ev.output_tokens or 0)
    s["cached_tokens"][bk] = s["cached_tokens"].get(bk, 0) + (ev.cached_tokens or 0)
    s["reasoning_tokens"][bk] = s["reasoning_tokens"].get(bk, 0) + (ev.reasoning_tokens or 0)
    s["rpm"][bk] = s["requests"][bk] / bm
    s["tpm"][bk] = s["tokens"][bk] / bm
    mn = (ev.model or "").strip() or "unknown"
    if mn not in s["models"]:
        s["models"][mn] = _new_series()
    ms = s["models"][mn]
    ms["requests"][bk] = ms["requests"].get(bk, 0) + 1
    ms["tokens"][bk] = ms["tokens"].get(bk, 0) + (ev.total_tokens or 0)
    ms["cost"][bk] = ms["cost"].get(bk, 0) + cost
    ms["input_tokens"][bk] = ms["input_tokens"].get(bk, 0) + (ev.input_tokens or 0)
    ms["output_tokens"][bk] = ms["output_tokens"].get(bk, 0) + (ev.output_tokens or 0)
    ms["cached_tokens"][bk] = ms["cached_tokens"].get(bk, 0) + (ev.cached_tokens or 0)
    ms["reasoning_tokens"][bk] = ms["reasoning_tokens"].get(bk, 0) + (ev.reasoning_tokens or 0)
    ms["rpm"][bk] = ms["requests"][bk] / bm
    ms["tpm"][bk] = ms["tokens"][bk] / bm

def _build_health(f: UsageQueryFilter):
    rows, columns = 7, 96
    if _is_short_range(f.range_):
        span_s = (24 * 3600) / (rows * columns)
    else:
        span_s = 15 * 60
    span = timedelta(seconds=span_s)
    end = datetime.now(timezone.utc)
    if f.end_time:
        end = f.end_time
    total = rows * columns
    if _is_short_range(f.range_):
        start = end - timedelta(hours=24)
    else:
        bucket_start = end.replace(second=0, microsecond=0)
        minutes = int(span.total_seconds() / 60) if span.total_seconds() >= 60 else 1
        bucket_start = bucket_start.replace(minute=bucket_start.minute - bucket_start.minute % minutes)
        window_end = bucket_start + span
        start = window_end - span * total
        end = window_end
    blocks = []
    for i in range(total):
        st = start + span * i
        blocks.append({"start_time": st, "end_time": st + span, "success": 0, "failure": 0, "rate": -1.0})
    return {"total_success": 0, "total_failure": 0, "success_rate": 0.0, "rows": rows,
            "columns": columns, "bucket_seconds": int(span.total_seconds()),
            "window_start": start, "window_end": end, "block_details": blocks,
            "_span_s": span_s, "_start": start}

def _is_short_range(r: str) -> bool:
    return r in ("4h", "8h", "12h", "24h", "today")

def _update_health_block(blocks, ev, window_start, span_s):
    ts = ev.timestamp
    if ts is None:
        return
    idx = int((ts - window_start).total_seconds() / span_s)
    if 0 <= idx < len(blocks):
        b = blocks[idx]
        if ev.failed:
            b["failure"] += 1
        else:
            b["success"] += 1
        total = b["success"] + b["failure"]
        b["rate"] = b["success"] / total if total > 0 else -1.0
