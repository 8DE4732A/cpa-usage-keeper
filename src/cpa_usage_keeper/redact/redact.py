"""API key redaction and display name masking."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from ..cpa.types import APISnapshot, ModelSnapshot, StatisticsSnapshot

API_ALIAS_PREFIX = "redacted_api_"


def api_alias(value: str) -> str:
    """Generate a stable, redacted alias for an API key."""
    trimmed = value.strip()
    if not trimmed:
        return "unknown"
    if trimmed == "unknown" or trimmed.startswith(API_ALIAS_PREFIX):
        return trimmed
    digest = hashlib.sha256(trimmed.encode()).hexdigest()[:12]
    return f"{API_ALIAS_PREFIX}{digest}"


def api_key_display_name(value: str) -> str:
    """Mask an API key for display."""
    trimmed = value.strip()
    if not trimmed or trimmed == "unknown":
        return "unknown"
    rune_count = len(trimmed)
    if rune_count <= 4:
        return "*" * rune_count
    if rune_count <= 8:
        return trimmed[0] + "*" * (rune_count - 2) + trimmed[-1]
    return trimmed[:4] + "*" * (rune_count - 8) + trimmed[-4:]


def redact_usage_snapshot(snapshot: StatisticsSnapshot | None) -> StatisticsSnapshot | None:
    """Return a deep copy of the snapshot with API keys redacted."""
    if snapshot is None:
        return None

    redacted = StatisticsSnapshot(
        total_requests=snapshot.total_requests,
        success_count=snapshot.success_count,
        failure_count=snapshot.failure_count,
        total_tokens=snapshot.total_tokens,
        apis={},
        requests_by_day=dict(snapshot.requests_by_day),
        requests_by_hour=dict(snapshot.requests_by_hour),
        tokens_by_day=dict(snapshot.tokens_by_day),
        tokens_by_hour=dict(snapshot.tokens_by_hour),
    )

    for api_key, api_snap in snapshot.apis.items():
        alias = api_alias(api_key)
        cloned = _clone_api_snapshot(api_snap)
        cloned.display_name = api_key_display_name(api_key)
        redacted.apis[alias] = cloned

    return redacted


def _clone_api_snapshot(src: APISnapshot) -> APISnapshot:
    return APISnapshot(
        display_name=src.display_name,
        total_requests=src.total_requests,
        success_count=src.success_count,
        failure_count=src.failure_count,
        total_tokens=src.total_tokens,
        models={k: _clone_model_snapshot(v) for k, v in src.models.items()},
    )


def _clone_model_snapshot(src: ModelSnapshot) -> ModelSnapshot:
    return ModelSnapshot(
        total_requests=src.total_requests,
        success_count=src.success_count,
        failure_count=src.failure_count,
        total_tokens=src.total_tokens,
        details=[replace(d) for d in src.details],
    )
