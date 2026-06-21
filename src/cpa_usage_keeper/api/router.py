"""API route registration - assembles all endpoint routers."""
from __future__ import annotations
import asyncio
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy.orm import Session


def _utc_isoformat(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
from ..database import get_db
from ..repository import usage as repo_usage
from ..repository import notification as repo_notify
from ..repository import pricing as repo_pricing
from ..repository import auth_files as repo_auth
from ..repository import provider_metadata as repo_pm
from ..repository.usage import UsageQueryFilter
from ..redact.redact import api_alias, api_key_display_name, redact_usage_snapshot
from ..auth.session import SessionManager

PRESET_DURATIONS = {"4h": 4*3600, "8h": 8*3600, "12h": 12*3600, "24h": 24*3600, "7d": 7*86400}
ALLOWED_PAGE_SIZES = {20, 50, 100, 500, 1000}


def _parse_custom_boundary(value: str, end_of_day: bool) -> datetime:
    try:
        d = datetime.strptime(value, "%Y-%m-%d")
        import time as _time
        d = d.astimezone()
        if end_of_day:
            d = d.replace(hour=23, minute=59, second=59, microsecond=999999)
        return d
    except ValueError:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_filter(request: Request) -> UsageQueryFilter:
    params = request.query_params
    range_ = (params.get("range") or "all").strip()
    page = int(params.get("page", "1"))
    if page < 1:
        raise HTTPException(400, f"invalid page {page}")
    ps_val = params.get("page_size") or params.get("limit") or "100"
    page_size = int(ps_val)
    if page_size not in ALLOWED_PAGE_SIZES:
        raise HTTPException(400, f"invalid page_size {page_size}")
    model = (params.get("model") or "").strip()
    source = (params.get("source") or "").strip()
    auth_index = (params.get("auth_index") or "").strip()
    result = (params.get("result") or "").strip()
    if result and result not in ("success", "failed"):
        raise HTTPException(400, f"invalid result {result}")

    anchor = datetime.now(timezone.utc)
    start_time = end_time = None

    if range_ == "all":
        pass
    elif range_ == "today":
        local_now = anchor.astimezone()
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_time = local_start.astimezone(timezone.utc)
        end_time = (local_start + timedelta(days=1) - timedelta(microseconds=1)).astimezone(timezone.utc)
    elif range_ == "custom":
        sv = (params.get("start") or "").strip()
        ev = (params.get("end") or "").strip()
        if not sv or not ev:
            raise HTTPException(400, "custom range requires start and end")
        start_time = _parse_custom_boundary(sv, False).astimezone(timezone.utc)
        end_time = _parse_custom_boundary(ev, True).astimezone(timezone.utc)
        if start_time > end_time:
            raise HTTPException(400, "start must be before end")
    elif range_ in PRESET_DURATIONS:
        end_time = anchor
        start_time = anchor - timedelta(seconds=PRESET_DURATIONS[range_])
    else:
        raise HTTPException(400, f"unsupported range {range_}")

    if start_time and start_time.tzinfo is not None:
        start_time = start_time.astimezone(timezone.utc).replace(tzinfo=None)
    if end_time and end_time.tzinfo is not None:
        end_time = end_time.astimezone(timezone.utc).replace(tzinfo=None)

    return UsageQueryFilter(
        range_=range_, start_time=start_time, end_time=end_time,
        limit=page_size, page=page, page_size=page_size,
        offset=(page - 1) * page_size, model=model, source=source,
        auth_index=auth_index, result=result)


def _source_resolution(source: str, auth_index: str, auth_files, provider_metadata):
    """Resolve source display info from auth files and provider metadata."""
    s = source.strip() if source else ""
    ai = auth_index.strip() if auth_index else ""

    # Check provider metadata first
    if s:
        for pm in provider_metadata:
            if pm.lookup_key.strip() == s:
                dn = pm.display_name or pm.provider_type or api_key_display_name(s)
                pk = pm.provider_key or (f"provider:{pm.id}" if pm.id else f"provider:{pm.provider_type or dn}")
                return {"display_name": dn, "source_type": pm.provider_type or "", "source_key": pk}

    # Check auth files
    if ai:
        for af in auth_files:
            if af.auth_index.strip() == ai:
                dn = af.email or af.label or af.name or ai
                return {"display_name": dn, "source_type": af.type or af.provider or "",
                        "source_key": f"auth:{ai}"}

    if not s:
        return {"display_name": "-", "source_type": "", "source_key": "raw:-"}
    if "@" in s and "." in s.split("@", 1)[1]:
        return {"display_name": s, "source_type": "", "source_key": f"email:{s}"}
    masked = api_key_display_name(s)
    return {"display_name": masked, "source_type": "", "source_key": f"raw:{masked}"}


def create_api_router(session_manager: Optional[SessionManager] = None,
                       auth_enabled: bool = False, login_password: str = "",
                       poller_status=None, app=None) -> APIRouter:
    _sync_last_time = [0.0]  # rate limiter
    router = APIRouter()

    # -- Health --
    @router.get("/healthz")
    def healthz():
        return {"status": "ok"}

    # -- Auth --
    @router.post("/api/v1/auth/login")
    async def api_login(request: Request):
        if not auth_enabled or not session_manager:
            raise HTTPException(404)
        body = await request.json()
        password = body.get("password", "")
        if password != login_password:
            raise HTTPException(401, detail="invalid password")
        token, expires_at = session_manager.create()
        max_age = int((expires_at - datetime.now(timezone.utc)).total_seconds())
        response = JSONResponse(content={"authenticated": True})
        response.set_cookie(
            key="session_token", value=token, max_age=max_age,
            path="/", httponly=True, samesite="lax",
        )
        return response

    @router.get("/api/v1/auth/session")
    def auth_session(request: Request):
        if not auth_enabled:
            return {"authenticated": True}
        if not session_manager:
            return {"authenticated": False}
        token = _extract_token(request)
        return {"authenticated": session_manager.validate(token)}

    @router.post("/api/v1/auth/logout")
    def logout(request: Request):
        if session_manager:
            token = _extract_token(request)
            if token:
                session_manager.delete(token)
        response = JSONResponse(content={"status": "ok"})
        response.delete_cookie(key="session_token", path="/")
        return response

    # -- Status --
    @router.get("/api/v1/status")
    def status(request: Request):
        _check_auth(request, session_manager, auth_enabled)
        if poller_status:
            return poller_status.to_dict()
        return {"running": True, "sync_running": False,
                "timezone": str(_time.tzname)}

    # -- Sync --
    @router.post("/api/v1/sync")
    async def sync(request: Request):
        _check_auth(request, session_manager, auth_enabled)
        now = _time.time()
        if now - _sync_last_time[0] < 1.0:
            raise HTTPException(429, detail="sync rate limit exceeded")
        _sync_last_time[0] = now
        active_poller = getattr(app.state, 'active_poller', None) if app else None
        if active_poller is None:
            raise HTTPException(500, detail="sync runner is not configured")
        if poller_status and poller_status.sync_running:
            raise HTTPException(409, detail="sync already running")
        await active_poller.sync_now()
        if poller_status:
            return poller_status.to_dict()
        return {"sync_running": False}

    # -- Usage Overview --
    @router.get("/api/v1/usage/overview")
    def usage_overview(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        f = _parse_filter(request)
        overview = repo_usage.build_usage_overview(db, f)
        snap = overview["usage"]
        auth_files = repo_auth.list_auth_files(db)
        pm = repo_pm.list_provider_metadata(db)
        _apply_source_resolution(snap, auth_files, pm)
        redacted = redact_usage_snapshot(snap)
        ov = overview.copy()
        ov["usage"] = _snapshot_to_dict(redacted)
        ov["service_health"]["window_start"] = ov["service_health"]["window_start"].isoformat()
        ov["service_health"]["window_end"] = ov["service_health"]["window_end"].isoformat()
        for b in ov["service_health"]["block_details"]:
            b["start_time"] = b["start_time"].isoformat()
            b["end_time"] = b["end_time"].isoformat()
        return ov

    # -- Usage Events --
    @router.get("/api/v1/usage/events/filters")
    def usage_event_filters(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        f = _parse_filter(request)
        f.model = ""; f.source = ""; f.auth_index = ""; f.result = ""
        opts = repo_usage.list_usage_event_filter_options(db, f)
        auth_files = repo_auth.list_auth_files(db)
        pm = repo_pm.list_provider_metadata(db)
        sources = [_source_filter_option(s, auth_files, pm) for s in opts["sources"]]
        return {"models": opts["models"], "sources": sources}

    @router.get("/api/v1/usage/events")
    def usage_events(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        f = _parse_filter(request)
        auth_files = repo_auth.list_auth_files(db)
        pm = repo_pm.list_provider_metadata(db)
        # Resolve source filter
        if f.source:
            f.source = _raw_source_for_public(f.source, pm)
        rows = repo_usage.list_usage_events(db, f)
        events_payload = []
        for ev in rows["events"]:
            resolved = _source_resolution(ev.source or "", ev.auth_index or "", auth_files, pm)
            events_payload.append({
                "id": ev.id, "timestamp": _utc_isoformat(ev.timestamp),
                "model": (ev.model or "").strip(), "source": resolved["display_name"],
                "source_type": resolved["source_type"], "source_key": resolved["source_key"],
                "auth_index": (ev.auth_index or "").strip(), "failed": ev.failed or False,
                "latency_ms": ev.latency_ms or 0,
                "tokens": {"input_tokens": ev.input_tokens or 0, "output_tokens": ev.output_tokens or 0,
                           "reasoning_tokens": ev.reasoning_tokens or 0, "cached_tokens": ev.cached_tokens or 0,
                           "total_tokens": ev.total_tokens or 0}})
        sources = [_source_filter_option(s, auth_files, pm) for s in rows["sources"]]
        return {"events": events_payload, "models": rows["models"], "sources": sources,
                "total_count": rows["total_count"], "page": rows["page"],
                "page_size": rows["page_size"], "total_pages": rows["total_pages"]}

    # -- Usage Analysis --
    @router.get("/api/v1/usage/analysis")
    def usage_analysis(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        f = _parse_filter(request)
        result = repo_usage.list_analysis_stats(db, f)
        apis = []
        for api in result["apis"]:
            ak = api_alias(api["api_group_key"])
            dn = api_key_display_name(api["api_group_key"])
            apis.append({
                "api_key": ak, "display_name": dn,
                "total_requests": api["total_requests"], "success_count": api["success_count"],
                "failure_count": api["failure_count"], "input_tokens": api["input_tokens"],
                "output_tokens": api["output_tokens"], "reasoning_tokens": api["reasoning_tokens"],
                "cached_tokens": api["cached_tokens"], "total_tokens": api["total_tokens"],
                "models": api["models"]})
        return {"apis": apis, "models": result["models"]}

    # -- Usage Credentials --
    @router.get("/api/v1/usage/credentials")
    def usage_credentials(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        f = _parse_filter(request)
        rows = repo_usage.list_credential_stats(db, f)
        auth_files = repo_auth.list_auth_files(db)
        pm = repo_pm.list_provider_metadata(db)
        buckets = {}
        ordered = []
        for r in rows:
            resolved = _source_resolution(r["source"], r["auth_index"], auth_files, pm)
            bk = resolved["source_key"] or resolved["display_name"]
            if bk not in buckets:
                buckets[bk] = {"source": resolved["display_name"], "source_type": resolved["source_type"],
                               "source_key": resolved["source_key"], "success_count": 0, "failure_count": 0, "total_count": 0}
                ordered.append(bk)
            if r["failed"]:
                buckets[bk]["failure_count"] += r["request_count"]
            else:
                buckets[bk]["success_count"] += r["request_count"]
            buckets[bk]["total_count"] = buckets[bk]["success_count"] + buckets[bk]["failure_count"]
        return {"credentials": [buckets[k] for k in ordered]}

    # -- Pricing --
    @router.get("/api/v1/models/used")
    def used_models(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        return {"models": repo_pricing.list_used_models(db)}

    @router.get("/api/v1/pricing")
    def list_pricing(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        settings = repo_pricing.list_pricing(db)
        rows = []
        for s in settings:
            has_custom, ep, ec, ecc = repo_pricing.effective_prices(s)
            rows.append({
                "model": s.model,
                "prompt_price_per_1m": s.prompt_price_per_1m,
                "completion_price_per_1m": s.completion_price_per_1m,
                "cache_price_per_1m": s.cache_price_per_1m,
                "deepinfra_model_id": s.deepinfra_model_id,
                "deepinfra_prompt_price_per_1m": s.deepinfra_prompt_price_per_1m,
                "deepinfra_completion_price_per_1m": s.deepinfra_completion_price_per_1m,
                "deepinfra_cache_price_per_1m": s.deepinfra_cache_price_per_1m,
                "openrouter_model_id": s.openrouter_model_id,
                "openrouter_prompt_price_per_1m": s.openrouter_prompt_price_per_1m,
                "openrouter_completion_price_per_1m": s.openrouter_completion_price_per_1m,
                "openrouter_cache_price_per_1m": s.openrouter_cache_price_per_1m,
                "has_custom_price": has_custom,
                "effective_prompt_price_per_1m": ep,
                "effective_completion_price_per_1m": ec,
                "effective_cache_price_per_1m": ecc,
            })
        return {"pricing": rows}

    @router.put("/api/v1/pricing")
    async def update_pricing(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        body = await request.json()
        model = (body.get("model") or "").strip()
        if not model:
            raise HTTPException(400, "model is required")
        s = repo_pricing.upsert_pricing(db, model, body.get("prompt_price_per_1m", 0),
                                         body.get("completion_price_per_1m", 0), body.get("cache_price_per_1m", 0))
        return {"model": s.model, "prompt_price_per_1m": s.prompt_price_per_1m,
                "completion_price_per_1m": s.completion_price_per_1m, "cache_price_per_1m": s.cache_price_per_1m}

    @router.delete("/api/v1/pricing")
    def delete_pricing(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        model = (request.query_params.get("model") or "").strip()
        if not model:
            raise HTTPException(400, "model is required")
        repo_pricing.delete_pricing(db, model)
        return Response(status_code=204)

    @router.get("/api/v1/pricing/openrouter-models")
    def get_openrouter_models(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        # NOTE: db session is still obtained for auth check compatibility,
        # but fetch_openrouter_models() reads from in-memory cache, not DB.
        try:
            or_models = repo_pricing.fetch_openrouter_models()
        except Exception as exc:
            raise HTTPException(502, f"Failed to fetch OpenRouter models: {exc}")
        return {"models": [{
            "id": m.get("id", ""),
            "name": m.get("name", ""),
            "prompt_price_per_1m": repo_pricing.or_price(m.get("pricing", {}), "prompt"),
            "completion_price_per_1m": repo_pricing.or_price(m.get("pricing", {}), "completion"),
            "cache_price_per_1m": repo_pricing.or_price(m.get("pricing", {}), "input_cache_read"),
        } for m in or_models]}

    @router.post("/api/v1/pricing/sync-openrouter")
    def sync_openrouter(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        result = repo_pricing.sync_openrouter_prices(db)
        # Only fail if both sources errored; partial success is still useful.
        if len(result.get("errors", [])) >= 2:
            raise HTTPException(502, "; ".join(result["errors"]))
        return result

    # -- Notification Channels & Rules --
    @router.get("/api/v1/notification/channels")
    def list_notification_channels(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        return {"channels": repo_notify.list_channels(db)}

    @router.post("/api/v1/notification/channels")
    async def create_notification_channel(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        body = await request.json()
        name = (body.get("name") or "").strip()
        channel_type = (body.get("channel_type") or "").strip()
        config = body.get("config", {})
        enabled = body.get("enabled", True)
        if not name:
            raise HTTPException(400, "name is required")
        if not channel_type:
            raise HTTPException(400, "channel_type is required")
        if not config.get("webhook_url"):
            raise HTTPException(400, "config.webhook_url is required")
        ch = repo_notify.create_channel(db, name, channel_type, config, enabled)
        return ch

    @router.put("/api/v1/notification/channels/{channel_id}")
    async def update_notification_channel(
        request: Request, channel_id: int, db: Session = Depends(get_db)
    ):
        _check_auth(request, session_manager, auth_enabled)
        body = await request.json()
        ch = repo_notify.update_channel(
            db, channel_id,
            name=body.get("name"),
            channel_type=body.get("channel_type"),
            config=body.get("config"),
            enabled=body.get("enabled"),
        )
        if ch is None:
            raise HTTPException(404, "channel not found")
        return ch

    @router.delete("/api/v1/notification/channels/{channel_id}")
    def delete_notification_channel(
        request: Request, channel_id: int, db: Session = Depends(get_db)
    ):
        _check_auth(request, session_manager, auth_enabled)
        ok = repo_notify.delete_channel(db, channel_id)
        if not ok:
            raise HTTPException(404, "channel not found")
        return Response(status_code=204)

    @router.post("/api/v1/notification/channels/{channel_id}/test")
    def test_notification_channel(
        request: Request, channel_id: int, db: Session = Depends(get_db)
    ):
        _check_auth(request, session_manager, auth_enabled)
        try:
            repo_notify.test_webhook(db, channel_id)
            return {"status": "ok"}
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            raise HTTPException(502, f"Webhook test failed: {e}")

    @router.get("/api/v1/notification/rules")
    def list_notification_rules(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        return {"rules": repo_notify.list_rules(db)}

    @router.post("/api/v1/notification/rules")
    async def create_notification_rule(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        body = await request.json()
        name = (body.get("name") or "").strip()
        channel_id = body.get("channel_id")
        rule_type = (body.get("rule_type") or "").strip()
        config = body.get("config", {})
        enabled = body.get("enabled", True)
        cooldown_minutes = body.get("cooldown_minutes", 30)
        if not name:
            raise HTTPException(400, "name is required")
        if not channel_id:
            raise HTTPException(400, "channel_id is required")
        if not rule_type:
            raise HTTPException(400, "rule_type is required")
        if rule_type not in ("token_threshold", "connection_failure"):
            raise HTTPException(400, f"unsupported rule_type: {rule_type}")
        try:
            rule = repo_notify.create_rule(
                db, name, channel_id, rule_type, config, enabled, cooldown_minutes
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        return rule

    @router.put("/api/v1/notification/rules/{rule_id}")
    async def update_notification_rule(
        request: Request, rule_id: int, db: Session = Depends(get_db)
    ):
        _check_auth(request, session_manager, auth_enabled)
        body = await request.json()
        try:
            rule = repo_notify.update_rule(
                db, rule_id,
                name=body.get("name"),
                channel_id=body.get("channel_id"),
                rule_type=body.get("rule_type"),
                config=body.get("config"),
                enabled=body.get("enabled"),
                cooldown_minutes=body.get("cooldown_minutes"),
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        if rule is None:
            raise HTTPException(404, "rule not found")
        return rule

    @router.delete("/api/v1/notification/rules/{rule_id}")
    def delete_notification_rule(
        request: Request, rule_id: int, db: Session = Depends(get_db)
    ):
        _check_auth(request, session_manager, auth_enabled)
        ok = repo_notify.delete_rule(db, rule_id)
        if not ok:
            raise HTTPException(404, "rule not found")
        return Response(status_code=204)

    # -- Provider Metadata --
    @router.get("/api/v1/provider-metadata")
    def provider_metadata(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        items = repo_pm.list_provider_metadata(db)
        result = []
        for item in items:
            resolved = _source_resolution(item.lookup_key, "", [], [item])
            result.append({"lookup_key": resolved["source_key"],
                           "provider_type": item.provider_type or "",
                           "display_name": resolved["display_name"],
                           "provider_key": resolved["source_key"]})
        return {"items": result}

    # -- Auth Files --
    @router.get("/api/v1/auth-files")
    def auth_files(request: Request, db: Session = Depends(get_db)):
        _check_auth(request, session_manager, auth_enabled)
        files = repo_auth.list_auth_files(db)
        return {"files": [{"auth_index": f.auth_index, "name": f.name or "",
                           "email": f.email or "", "type": f.type or "",
                           "provider": f.provider or ""} for f in files]}

    return router


def _extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("session_token", "")


def _check_auth(request: Request, session_manager: Optional[SessionManager], auth_enabled: bool):
    if not auth_enabled or not session_manager:
        return
    token = _extract_token(request)
    if not session_manager.validate(token):
        raise HTTPException(401, detail="unauthorized")


def _source_filter_option(source: str, auth_files, pm):
    resolved = _source_resolution(source, "", auth_files, pm)
    return {"value": resolved["source_key"], "label": resolved["display_name"]}


def _raw_source_for_public(value: str, provider_metadata) -> str:
    v = value.strip()
    if not v:
        return ""
    for pm in provider_metadata:
        resolved = _source_resolution(pm.lookup_key, "", [], [pm])
        if resolved["source_key"] == v:
            return pm.lookup_key.strip()
    return v


def _apply_source_resolution(snap, auth_files, pm):
    if snap is None:
        return
    for api_name, api_snap in snap.apis.items():
        for model_name, model_snap in api_snap.models.items():
            for d in model_snap.details:
                resolved = _source_resolution(d.source, d.auth_index, auth_files, pm)
                d.source_raw = d.source
                d.source = resolved["display_name"]
                d.source_display = resolved["display_name"]
                d.source_type = resolved["source_type"]
                d.source_key = resolved["source_key"]


def _snapshot_to_dict(snap) -> dict:
    if snap is None:
        return {}
    apis = {}
    for k, a in snap.apis.items():
        models = {}
        for mk, ms in a.models.items():
            models[mk] = {
                "total_requests": ms.total_requests, "success_count": ms.success_count,
                "failure_count": ms.failure_count, "total_tokens": ms.total_tokens,
                "details": [{"timestamp": _utc_isoformat(d.timestamp),
                             "latency_ms": d.latency_ms, "source": d.source,
                             "source_raw": d.source_raw, "source_display": getattr(d, 'source_display', ''),
                             "source_type": getattr(d, 'source_type', ''),
                             "source_key": getattr(d, 'source_key', ''),
                             "auth_index": d.auth_index, "failed": d.failed,
                             "tokens": {"input_tokens": d.tokens.input_tokens,
                                        "output_tokens": d.tokens.output_tokens,
                                        "reasoning_tokens": d.tokens.reasoning_tokens,
                                        "cached_tokens": d.tokens.cached_tokens,
                                        "total_tokens": d.tokens.total_tokens}}
                            for d in ms.details]}
        apis[k] = {"display_name": a.display_name, "total_requests": a.total_requests,
                    "success_count": a.success_count, "failure_count": a.failure_count,
                    "total_tokens": a.total_tokens, "models": models}
    return {"total_requests": snap.total_requests, "success_count": snap.success_count,
            "failure_count": snap.failure_count, "total_tokens": snap.total_tokens,
            "apis": apis, "requests_by_day": snap.requests_by_day,
            "requests_by_hour": snap.requests_by_hour,
            "tokens_by_day": snap.tokens_by_day, "tokens_by_hour": snap.tokens_by_hour}
