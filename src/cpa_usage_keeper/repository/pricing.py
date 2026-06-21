"""Pricing CRUD operations."""
from __future__ import annotations

import httpx
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import ModelPriceSetting, UsageEvent

OR_API_URL = "https://openrouter.ai/api/v1/models"
DI_API_URL = "https://api.deepinfra.com/v1/models"

OR_CACHE: dict[str, list[dict]] | None = None
DI_CACHE: list[dict] | None = None


def extract_model_key(full_name: str) -> str:
    """Extract the last /-segment of a model name, stripping any :suffix, lowercased.

    Examples:
        "deepseek/deepseek-v4-flash" -> "deepseek-v4-flash"
        "deepseek-ai/DeepSeek-V4-Flash" -> "deepseek-v4-flash"
        "claude/deepseek/deepseek-v4-flash:floor" -> "deepseek-v4-flash"
        "gpt-4o" -> "gpt-4o"
    """
    name = full_name.split(":")[0]
    seg = name.rsplit("/", 1)[-1] if "/" in name else name
    return seg.lower()


# ── DeepInfra ────────────────────────────────────────────────────────────────

def fetch_deepinfra_models() -> list[dict]:
    """Fetch and cache the DeepInfra model list."""
    global DI_CACHE
    if DI_CACHE is not None:
        return DI_CACHE
    resp = httpx.get(DI_API_URL, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data", body) if isinstance(body, dict) else body
    DI_CACHE = data
    return data


def invalidate_di_cache() -> None:
    global DI_CACHE
    DI_CACHE = None


def _di_price(pricing: dict, key: str) -> float | None:
    """Safely extract a per-1M price from a DeepInfra pricing dict.

    DeepInfra already returns prices in per-1M-token units (unlike OpenRouter
    which returns per-token and needs ×1_000_000).
    """
    raw = pricing.get(key)
    if raw is None:
        return None
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return None
    return val if val >= 0 else None


def _extract_di_pricing(match: dict) -> tuple[str, float | None, float | None, float | None]:
    pricing = (match.get("metadata") or {}).get("pricing") or {}
    return (
        (match.get("id") or "").strip(),
        _di_price(pricing, "input_tokens"),
        _di_price(pricing, "output_tokens"),
        _di_price(pricing, "cache_read_tokens"),
    )


def build_deepinfra_index(di_models: list[dict]) -> dict[str, dict]:
    """Build two lookup indexes from the DeepInfra model list.

    Returns {"by_id": {id: model}, "by_key": {last_segment: [model]}}
    """
    by_id: dict[str, dict] = {}
    by_key: dict[str, list[dict]] = {}
    for m in di_models:
        mid: str = (m.get("id") or "").strip()
        if not mid:
            continue
        by_id[mid] = m
        key = extract_model_key(mid)
        by_key.setdefault(key, []).append(m)
    return {"by_id": by_id, "by_key": by_key}


# ── OpenRouter ────────────────────────────────────────────────────────────────

def fetch_openrouter_models() -> list[dict]:
    """Fetch and cache the OpenRouter model list."""
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


# ── Shared match logic ────────────────────────────────────────────────────────

_ROUTING_PREFIXES = ("openrouter/", "deepinfra/")


def _strip_routing_prefix(model_name: str) -> str:
    for prefix in _ROUTING_PREFIXES:
        if model_name.startswith(prefix):
            return model_name[len(prefix):]
    return model_name


def _match_model(
    model_name: str,
    index: dict[str, dict[str, list[dict]]],
) -> dict | None:
    """Generic model matcher used by both DeepInfra and OpenRouter indexes.

    Strategy:
      1. Exact match on id.
      2. Strip known routing prefixes and try exact match.
      3. Key match (last /-segment, no :suffix) — prefer candidate whose
         variant suffix matches the query, then prefer base (no suffix), then any.
    """
    by_id = index.get("by_id", {})
    by_key = index.get("by_key", {})

    if model_name in by_id:
        return by_id[model_name]

    stripped = _strip_routing_prefix(model_name)
    if stripped != model_name and stripped in by_id:
        return by_id[stripped]

    key = extract_model_key(model_name)
    candidates = by_key.get(key)
    if not candidates:
        return None

    query_variant = model_name.split(":")[-1] if ":" in model_name else ""
    if query_variant:
        for c in candidates:
            cid = (c.get("id") or "")
            if cid.endswith(f":{query_variant}"):
                return c
    for c in candidates:
        last_seg = (c.get("id") or "").rsplit("/", 1)[-1]
        if ":" not in last_seg:
            return c

    return candidates[0]


def match_deepinfra_model(model_name: str, di_index: dict) -> dict | None:
    return _match_model(model_name, di_index)


def match_openrouter_model(model_name: str, or_index: dict) -> dict | None:
    return _match_model(model_name, or_index)


# ── Effective price helpers ────────────────────────────────────────────────────

def effective_prices(entry: ModelPriceSetting) -> tuple[bool, float, float, float]:
    """Return (has_custom, effective_prompt, effective_completion, effective_cache).

    Fallback chain: custom price → DeepInfra → OpenRouter.
    """
    p = entry.prompt_price_per_1m or 0.0
    c = entry.completion_price_per_1m or 0.0
    cc = entry.cache_price_per_1m or 0.0
    has_custom = bool(p or c or cc)

    def _fallback(user: float, di_attr: str, or_attr: str) -> float:
        if user:
            return user
        di = getattr(entry, di_attr, None) or 0.0
        if di:
            return di
        return getattr(entry, or_attr, None) or 0.0

    ep = _fallback(p, "deepinfra_prompt_price_per_1m", "openrouter_prompt_price_per_1m")
    ec = _fallback(c, "deepinfra_completion_price_per_1m", "openrouter_completion_price_per_1m")
    ecc = _fallback(cc, "deepinfra_cache_price_per_1m", "openrouter_cache_price_per_1m")
    return has_custom, ep, ec, ecc


def effective_price(entry: ModelPriceSetting, field: str) -> float:
    _, ep, ec, ecc = effective_prices(entry)
    mapping = {
        "prompt_price_per_1m": ep,
        "completion_price_per_1m": ec,
        "cache_price_per_1m": ecc,
    }
    return mapping.get(field, 0.0)


def has_custom_price(entry: ModelPriceSetting) -> bool:
    return bool(
        (entry.prompt_price_per_1m or 0.0) != 0.0
        or (entry.completion_price_per_1m or 0.0) != 0.0
        or (entry.cache_price_per_1m or 0.0) != 0.0
    )


# ── Sync ───────────────────────────────────────────────────────────────────────

def _collect_all_models(db: Session) -> tuple[dict[str, ModelPriceSetting], set[str]]:
    """Return (existing_rows_by_name, all_model_names)."""
    existing_rows = {
        row.model.strip(): row
        for row in db.query(ModelPriceSetting).all()
    }
    used_rows = (
        db.query(func.distinct(UsageEvent.model))
        .filter(UsageEvent.model != "")
        .all()
    )
    used: set[str] = {m.strip() for (m,) in used_rows if m.strip()}
    return existing_rows, set(existing_rows.keys()) | used


def sync_openrouter_prices(db: Session) -> dict:
    """Fetch both DeepInfra and OpenRouter models and sync prices into all known CPA models.

    DeepInfra is the primary source; OpenRouter fills gaps.
    Returns stats dict with matched/created/total counts and errors.
    """
    result: dict = {
        "deepinfra_matched": 0, "openrouter_matched": 0,
        "created": 0,
        "total_di_models": 0, "total_or_models": 0,
        "errors": [],
    }

    try:
        di_models = fetch_deepinfra_models()
        result["total_di_models"] = len(di_models)
        di_index = build_deepinfra_index(di_models)
    except Exception as exc:
        result["errors"].append(f"deepinfra: {exc}")
        di_index = {"by_id": {}, "by_key": {}}

    try:
        or_models = fetch_openrouter_models()
        result["total_or_models"] = len(or_models)
        or_index = build_openrouter_index(or_models)
    except Exception as exc:
        result["errors"].append(f"openrouter: {exc}")
        or_index = {"by_id": {}, "by_key": {}}

    existing_rows, all_models = _collect_all_models(db)

    for cpa_model in sorted(all_models):
        if not cpa_model:
            continue

        di_match = match_deepinfra_model(cpa_model, di_index)
        or_match = match_openrouter_model(cpa_model, or_index)

        if di_match is None and or_match is None:
            continue

        di_id, di_prompt, di_completion, di_cache = _extract_di_pricing(di_match) if di_match else ("", None, None, None)
        or_id, or_prompt, or_completion, or_cache = _extract_or_pricing(or_match) if or_match else ("", None, None, None)

        if di_match:
            result["deepinfra_matched"] += 1
        if or_match:
            result["openrouter_matched"] += 1

        existing_row = existing_rows.get(cpa_model)
        if existing_row:
            existing_row.deepinfra_model_id = di_id or None
            existing_row.deepinfra_prompt_price_per_1m = di_prompt
            existing_row.deepinfra_completion_price_per_1m = di_completion
            existing_row.deepinfra_cache_price_per_1m = di_cache
            existing_row.openrouter_model_id = or_id or None
            existing_row.openrouter_prompt_price_per_1m = or_prompt
            existing_row.openrouter_completion_price_per_1m = or_completion
            existing_row.openrouter_cache_price_per_1m = or_cache
        else:
            setting = ModelPriceSetting(
                model=cpa_model,
                prompt_price_per_1m=0.0,
                completion_price_per_1m=0.0,
                cache_price_per_1m=0.0,
                deepinfra_model_id=di_id or None,
                deepinfra_prompt_price_per_1m=di_prompt,
                deepinfra_completion_price_per_1m=di_completion,
                deepinfra_cache_price_per_1m=di_cache,
                openrouter_model_id=or_id or None,
                openrouter_prompt_price_per_1m=or_prompt,
                openrouter_completion_price_per_1m=or_completion,
                openrouter_cache_price_per_1m=or_cache,
            )
            db.add(setting)
            result["created"] += 1

    db.commit()
    return result


def list_used_models(db: Session) -> list[str]:
    """List distinct model names from usage events."""
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
    """Reset a model's custom prices to 0 (keep reference prices intact)."""
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
    """Fill missing reference prices without touching existing ones.

    Lightweight periodic check — only queries the APIs when there's something stale.
    Returns {"updated": int, "created": int, "errors": list[str]}.
    """
    result: dict = {"updated": 0, "created": 0, "errors": []}

    all_existing = {
        row[0].strip()
        for row in db.query(ModelPriceSetting.model).all()
    }
    used = list_used_models(db)
    uncached = [m for m in used if m not in all_existing]

    stale_rows = db.query(ModelPriceSetting).filter(
        or_(
            ModelPriceSetting.deepinfra_prompt_price_per_1m.is_(None),
            ModelPriceSetting.deepinfra_completion_price_per_1m.is_(None),
            ModelPriceSetting.openrouter_prompt_price_per_1m.is_(None),
            ModelPriceSetting.openrouter_completion_price_per_1m.is_(None),
        )
    ).all()

    if not stale_rows and not uncached:
        return result

    try:
        invalidate_di_cache()
        di_models = fetch_deepinfra_models()
        di_index = build_deepinfra_index(di_models)
    except Exception as exc:
        result["errors"].append(f"deepinfra: {exc}")
        di_index = {"by_id": {}, "by_key": {}}

    try:
        invalidate_or_cache()
        or_models = fetch_openrouter_models()
        or_index = build_openrouter_index(or_models)
    except Exception as exc:
        result["errors"].append(f"openrouter: {exc}")
        or_index = {"by_id": {}, "by_key": {}}

    def _apply(row: ModelPriceSetting, di_match: dict | None, or_match: dict | None) -> bool:
        changed = False
        if di_match:
            di_id, di_p, di_c, di_cc = _extract_di_pricing(di_match)
            if row.deepinfra_model_id != di_id or row.deepinfra_prompt_price_per_1m != di_p:
                row.deepinfra_model_id = di_id or None
                row.deepinfra_prompt_price_per_1m = di_p
                row.deepinfra_completion_price_per_1m = di_c
                row.deepinfra_cache_price_per_1m = di_cc
                changed = True
        if or_match:
            or_id, or_p, or_c, or_cc = _extract_or_pricing(or_match)
            if row.openrouter_model_id != or_id or row.openrouter_prompt_price_per_1m != or_p:
                row.openrouter_model_id = or_id or None
                row.openrouter_prompt_price_per_1m = or_p
                row.openrouter_completion_price_per_1m = or_c
                row.openrouter_cache_price_per_1m = or_cc
                changed = True
        return changed

    for row in stale_rows:
        di_match = match_deepinfra_model(row.model.strip(), di_index)
        or_match = match_openrouter_model(row.model.strip(), or_index)
        if _apply(row, di_match, or_match):
            result["updated"] += 1

    existing_rows, _ = _collect_all_models(db)
    for clean in uncached:
        di_match = match_deepinfra_model(clean, di_index)
        or_match = match_openrouter_model(clean, or_index)
        if di_match is None and or_match is None:
            continue
        di_id, di_p, di_c, di_cc = _extract_di_pricing(di_match) if di_match else ("", None, None, None)
        or_id, or_p, or_c, or_cc = _extract_or_pricing(or_match) if or_match else ("", None, None, None)
        setting = ModelPriceSetting(
            model=clean,
            prompt_price_per_1m=0.0,
            completion_price_per_1m=0.0,
            cache_price_per_1m=0.0,
            deepinfra_model_id=di_id or None,
            deepinfra_prompt_price_per_1m=di_p,
            deepinfra_completion_price_per_1m=di_c,
            deepinfra_cache_price_per_1m=di_cc,
            openrouter_model_id=or_id or None,
            openrouter_prompt_price_per_1m=or_p,
            openrouter_completion_price_per_1m=or_c,
            openrouter_cache_price_per_1m=or_cc,
        )
        db.add(setting)
        result["created"] += 1

    if result["updated"] > 0 or result["created"] > 0:
        db.commit()

    return result

