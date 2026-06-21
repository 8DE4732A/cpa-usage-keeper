"""Pricing CRUD operations."""
from __future__ import annotations

import httpx
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import ModelPriceSetting, UsageEvent

OR_API_URL = "https://openrouter.ai/api/v1/models"

OR_CACHE: dict[str, list[dict]] | None = None


def extract_model_key(full_name: str) -> str:
    """Extract the last /-segment of a model name, stripping any :suffix.

    Examples:
        "deepseek/deepseek-v4-flash" -> "deepseek-v4-flash"
        "claude/deepseek/deepseek-v4-flash:floor" -> "deepseek-v4-flash"
        "gpt-4o" -> "gpt-4o"
    """
    name = full_name.split(":")[0]
    return name.rsplit("/", 1)[-1] if "/" in name else name


def fetch_openrouter_models() -> list[dict]:
    """Fetch and cache the OpenRouter model list.

    Cache lives in memory for the lifetime of the process (refreshed on next
    call when the webhook triggers a re-sync). Returns a list of dicts with
    keys: id, pricing (prompt, completion, input_cache_read strs), name.
    """
    global OR_CACHE
    if OR_CACHE is not None:
        return OR_CACHE
    resp = httpx.get(OR_API_URL, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data", body) if isinstance(body, dict) else body
    OR_CACHE = data
    return data


def invalidate_or_cache() -> None:
    """Drop the in-memory OpenRouter cache so the next fetch hits the API."""
    global OR_CACHE
    OR_CACHE = None


def or_price(px: dict, key: str) -> float | None:
    """Safely extract a per-token price from OpenRouter pricing dict and
    convert to per-1M-tokens. Returns None if missing / negative / not a number."""
    raw = px.get(key)
    if raw is None:
        return None
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return None
    if val < 0:
        return None
    return val * 1_000_000


def _extract_or_pricing(match: dict) -> tuple[str, float | None, float | None, float | None]:
    """Extract OpenRouter model id and per-1M prices from a matched model dict."""
    pricing = match.get("pricing", {})
    return (
        (match.get("id") or "").strip(),
        or_price(pricing, "prompt"),
        or_price(pricing, "completion"),
        or_price(pricing, "input_cache_read"),
    )


def build_openrouter_index(or_models: list[dict]) -> dict[str, dict]:
    """Build two lookup indexes from the OpenRouter model list.

    Returns {"by_id": {id: model}, "by_key": {last_segment: [model]}}
    """
    by_id: dict[str, dict] = {}
    by_key: dict[str, list[dict]] = {}
    for m in or_models:
        mid: str = (m.get("id") or "").strip()
        if not mid:
            continue
        by_id[mid] = m
        key = extract_model_key(mid)
        by_key.setdefault(key, []).append(m)
    return {"by_id": by_id, "by_key": by_key}


def match_openrouter_model(
    model_name: str,
    or_index: dict[str, dict[str, list[dict]]],
) -> dict | None:
    """Try to match a CPA model name (full) against the OpenRouter model list.

    Strategy:
      1. Exact match on OpenRouter id.
      2. Extract last /-segment, match against that segment.
    Returns the first matching OpenRouter model dict, or None.
    """
    by_id = or_index.get("by_id", {})
    by_key = or_index.get("by_key", {})

    # 1. Exact match
    if model_name in by_id:
        return by_id[model_name]

    # 2. Key match
    key = extract_model_key(model_name)
    candidates = by_key.get(key)
    if candidates:
        return candidates[0]

    return None


def sync_openrouter_prices(db: Session) -> dict:
    """Fetch OpenRouter models and sync prices into *all* known CPA models.

    Updates existing ModelPriceSetting rows' openrouter_* columns and creates
    new rows for UsageEvent models that don't have a pricing entry yet.

    Returns {"matched": int, "created": int, "total_or_models": int, "errors": list[str]}.
    """
    result: dict = {"matched": 0, "created": 0, "total_or_models": 0, "errors": []}

    try:
        or_models = fetch_openrouter_models()
    except Exception as exc:
        result["errors"].append(str(exc))
        return result

    result["total_or_models"] = len(or_models)
    or_index = build_openrouter_index(or_models)

    # --- Collect all known CPA model names ---
    # Existing price settings — load all into a dict for O(1) lookup
    existing_rows = {
        row.model.strip(): row
        for row in db.query(ModelPriceSetting).all()
    }
    existing: set[str] = set(existing_rows.keys())

    # Used models from usage events (not yet in price settings)
    used_rows = (
        db.query(func.distinct(UsageEvent.model))
        .filter(UsageEvent.model != "")
        .all()
    )
    used: set[str] = set()
    for (m,) in used_rows:
        clean = m.strip()
        if clean:
            used.add(clean)

    all_models = existing | used

    for cpa_model in sorted(all_models):
        if not cpa_model:
            continue
        match = match_openrouter_model(cpa_model, or_index)
        if match is None:
            continue

        or_id, or_prompt, or_completion, or_cache = _extract_or_pricing(match)

        existing_row: ModelPriceSetting | None = existing_rows.get(cpa_model)

        if existing_row:
            existing_row.openrouter_model_id = or_id
            existing_row.openrouter_prompt_price_per_1m = or_prompt
            existing_row.openrouter_completion_price_per_1m = or_completion
            existing_row.openrouter_cache_price_per_1m = or_cache
        else:
            setting = ModelPriceSetting(
                model=cpa_model,
                prompt_price_per_1m=0.0,
                completion_price_per_1m=0.0,
                cache_price_per_1m=0.0,
                openrouter_model_id=or_id,
                openrouter_prompt_price_per_1m=or_prompt,
                openrouter_completion_price_per_1m=or_completion,
                openrouter_cache_price_per_1m=or_cache,
            )
            db.add(setting)
            result["created"] += 1

        result["matched"] += 1

    db.commit()
    return result

def list_used_models(db: Session) -> list[str]:
    """List distinct model names from usage events.

    Strips whitespace in Python after fetching so the query can use the model
    column index — SQLite's func.trim() inside the query prevents index usage
    and causes a full table scan on every invocation.
    """
    rows = (
        db.query(func.distinct(UsageEvent.model))
        .filter(UsageEvent.model != "")
        .order_by(UsageEvent.model.asc())
        .all()
    )
    seen: set[str] = set()
    result: list[str] = []
    for (m,) in rows:
        clean = m.strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result

def list_pricing(db: Session) -> list[ModelPriceSetting]:
    return db.query(ModelPriceSetting).order_by(ModelPriceSetting.model.asc()).all()


def effective_price(entry: ModelPriceSetting, field: str) -> float:
    """Return the effective price for a given field.

    If the user has set a non-zero value, that is returned.
    Otherwise we fall back to the OpenRouter price (if available).
    """
    user_val = getattr(entry, field, 0) or 0
    or_val = getattr(entry, f"openrouter_{field}", None) or 0
    if user_val != 0:
        return user_val
    return or_val

def upsert_pricing(db: Session, model: str, prompt: float, completion: float, cache: float) -> ModelPriceSetting:
    model = model.strip()
    if not model:
        raise ValueError("model is required")
    existing = db.query(ModelPriceSetting).filter(ModelPriceSetting.model == model).first()
    if existing:
        existing.prompt_price_per_1m = prompt
        existing.completion_price_per_1m = completion
        existing.cache_price_per_1m = cache
        db.commit()
        db.refresh(existing)
        return existing
    setting = ModelPriceSetting(model=model, prompt_price_per_1m=prompt,
                                completion_price_per_1m=completion, cache_price_per_1m=cache)
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting

def delete_pricing(db: Session, model: str) -> None:
    """Reset a model's custom prices to 0 (keep OpenRouter prices intact).

    The row is never deleted — OpenRouter-reference prices must always persist.
    If the model has no custom price set (all zeros), this is a no-op.
    """
    model = model.strip()
    if not model:
        raise ValueError("model is required")
    existing = db.query(ModelPriceSetting).filter(ModelPriceSetting.model == model).first()
    if existing is None:
        return
    existing.prompt_price_per_1m = 0.0
    existing.completion_price_per_1m = 0.0
    existing.cache_price_per_1m = 0.0
    db.commit()


def auto_sync_openrouter_prices(db: Session) -> dict:
    """Fill missing OpenRouter prices without touching existing ones.

    Lightweight periodic check (run every 30 min) — only queries the API
    when there's actually something stale to fix.

    Returns {"updated": int, "created": int, "errors": list[str]}.
    """
    result: dict = {"updated": 0, "created": 0, "errors": []}

    # Also check for usage models without a pricing row.
    all_existing = {
        row[0].strip()
        for row in db.query(ModelPriceSetting.model).all()
    }
    used = list_used_models(db)
    uncached = [m for m in used if m not in all_existing]

    # Query stale rows full, reusing the same fetch as the cheap guard
    # (single round-trip instead of two).
    stale_rows = db.query(ModelPriceSetting).filter(
        or_(
            ModelPriceSetting.openrouter_prompt_price_per_1m.is_(None),
            ModelPriceSetting.openrouter_completion_price_per_1m.is_(None),
            ModelPriceSetting.openrouter_cache_price_per_1m.is_(None),
        )
    ).all()

    if not stale_rows and not uncached:
        return result

    try:
        invalidate_or_cache()
        or_models = fetch_openrouter_models()
    except Exception as exc:
        result["errors"].append(str(exc))
        return result

    or_index = build_openrouter_index(or_models)

    # ── 1) Existing rows with missing OR prices ──
    for row in stale_rows:
            match = match_openrouter_model(row.model.strip(), or_index)
            if match is None:
                continue
            or_id, or_prompt, or_completion, or_cache = _extract_or_pricing(match)
            if (
                row.openrouter_model_id == or_id
                and row.openrouter_prompt_price_per_1m == or_prompt
                and row.openrouter_completion_price_per_1m == or_completion
                and row.openrouter_cache_price_per_1m == or_cache
            ):
                continue
            row.openrouter_model_id = or_id
            row.openrouter_prompt_price_per_1m = or_prompt
            row.openrouter_completion_price_per_1m = or_completion
            row.openrouter_cache_price_per_1m = or_cache
            result["updated"] += 1

    # ── 2) Usage models that have no pricing row yet ──
    for clean in uncached:
        match = match_openrouter_model(clean, or_index)
        if match is None:
            continue
        or_id, or_prompt, or_completion, or_cache = _extract_or_pricing(match)
        setting = ModelPriceSetting(
            model=clean,
            prompt_price_per_1m=0.0,
            completion_price_per_1m=0.0,
            cache_price_per_1m=0.0,
            openrouter_model_id=or_id,
            openrouter_prompt_price_per_1m=or_prompt,
            openrouter_completion_price_per_1m=or_completion,
            openrouter_cache_price_per_1m=or_cache,
        )
        db.add(setting)
        result["created"] += 1

    if result["updated"] > 0 or result["created"] > 0:
        db.commit()

    return result
