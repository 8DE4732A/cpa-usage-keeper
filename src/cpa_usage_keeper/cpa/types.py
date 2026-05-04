"""CPA data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class TokenStats:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0


@dataclass
class RequestDetail:
    timestamp: datetime = field(default_factory=datetime.utcnow)
    latency_ms: int = 0
    source: str = ""
    source_raw: str = ""
    source_display: str = ""
    source_type: str = ""
    source_key: str = ""
    auth_index: str = ""
    failed: bool = False
    tokens: TokenStats = field(default_factory=TokenStats)


@dataclass
class ModelSnapshot:
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_tokens: int = 0
    details: list[RequestDetail] = field(default_factory=list)


@dataclass
class APISnapshot:
    display_name: str = ""
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_tokens: int = 0
    models: dict[str, ModelSnapshot] = field(default_factory=dict)


@dataclass
class StatisticsSnapshot:
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_tokens: int = 0
    apis: dict[str, APISnapshot] = field(default_factory=dict)
    requests_by_day: dict[str, int] = field(default_factory=dict)
    requests_by_hour: dict[str, int] = field(default_factory=dict)
    tokens_by_day: dict[str, int] = field(default_factory=dict)
    tokens_by_hour: dict[str, int] = field(default_factory=dict)


@dataclass
class UsageExport:
    version: int = 0
    exported_at: Optional[datetime] = None
    usage: StatisticsSnapshot = field(default_factory=StatisticsSnapshot)


@dataclass
class ExportResult:
    status_code: int = 0
    body: bytes = b""
    payload: UsageExport = field(default_factory=UsageExport)


@dataclass
class AuthFileInfo:
    auth_index: str = ""
    name: str = ""
    email: str = ""
    type: str = ""
    provider: str = ""
    label: str = ""
    status: str = ""
    source: str = ""
    disabled: bool = False
    unavailable: bool = False
    runtime_only: bool = False


@dataclass
class AuthFilesResult:
    status_code: int = 0
    body: bytes = b""
    files: list[AuthFileInfo] = field(default_factory=list)


@dataclass
class ProviderKeyConfig:
    api_key: str = ""
    prefix: str = ""
    name: str = ""


@dataclass
class ProviderKeyConfigResult:
    status_code: int = 0
    body: bytes = b""
    payload: list[ProviderKeyConfig] = field(default_factory=list)


@dataclass
class OpenAIApiKeyEntry:
    api_key: str = ""


@dataclass
class OpenAICompatibilityConfig:
    name: str = ""
    prefix: str = ""
    api_key_entries: list[OpenAIApiKeyEntry] = field(default_factory=list)


@dataclass
class OpenAICompatibilityResult:
    status_code: int = 0
    body: bytes = b""
    payload: list[OpenAICompatibilityConfig] = field(default_factory=list)


@dataclass
class ProviderMetadataConfig:
    gemini_api_keys: list[ProviderKeyConfig] = field(default_factory=list)
    claude_api_keys: list[ProviderKeyConfig] = field(default_factory=list)
    codex_api_keys: list[ProviderKeyConfig] = field(default_factory=list)
    vertex_api_keys: list[ProviderKeyConfig] = field(default_factory=list)
    openai_compatibility: list[OpenAICompatibilityConfig] = field(default_factory=list)


@dataclass
class ModelInfo:
    id: str = ""
    object: str = ""
    created: int = 0
    owned_by: str = ""


@dataclass
class ModelsResult:
    status_code: int = 0
    body: bytes = b""
    data: list[ModelInfo] = field(default_factory=list)


def _parse_isoformat(ts_str: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def parse_usage_export(data: dict[str, Any]) -> UsageExport:
    """Parse usage export JSON into typed structure."""
    export = UsageExport()
    export.version = data.get("version", 0)
    exported_at = data.get("exported_at")
    if exported_at:
        export.exported_at = _parse_isoformat(exported_at)

    usage_data = data.get("usage", {})
    snapshot = StatisticsSnapshot()
    snapshot.total_requests = usage_data.get("total_requests", 0)
    snapshot.success_count = usage_data.get("success_count", 0)
    snapshot.failure_count = usage_data.get("failure_count", 0)
    snapshot.total_tokens = usage_data.get("total_tokens", 0)
    snapshot.requests_by_day = usage_data.get("requests_by_day", {})
    snapshot.requests_by_hour = usage_data.get("requests_by_hour", {})
    snapshot.tokens_by_day = usage_data.get("tokens_by_day", {})
    snapshot.tokens_by_hour = usage_data.get("tokens_by_hour", {})

    apis_data = usage_data.get("apis", {})
    for api_key, api_data in apis_data.items():
        api_snap = APISnapshot()
        api_snap.display_name = api_data.get("display_name", "")
        api_snap.total_requests = api_data.get("total_requests", 0)
        api_snap.success_count = api_data.get("success_count", 0)
        api_snap.failure_count = api_data.get("failure_count", 0)
        api_snap.total_tokens = api_data.get("total_tokens", 0)

        models_data = api_data.get("models", {})
        for model_key, model_data in models_data.items():
            model_snap = ModelSnapshot()
            model_snap.total_requests = model_data.get("total_requests", 0)
            model_snap.success_count = model_data.get("success_count", 0)
            model_snap.failure_count = model_data.get("failure_count", 0)
            model_snap.total_tokens = model_data.get("total_tokens", 0)

            for detail_data in model_data.get("details", []):
                ts_str = detail_data.get("timestamp", "")
                ts = _parse_isoformat(ts_str) if ts_str else None
                tokens_data = detail_data.get("tokens", {})
                detail = RequestDetail(
                    timestamp=ts or datetime.utcnow(),
                    latency_ms=detail_data.get("latency_ms", 0),
                    source=detail_data.get("source", ""),
                    auth_index=detail_data.get("auth_index", ""),
                    failed=detail_data.get("failed", False),
                    tokens=TokenStats(
                        input_tokens=tokens_data.get("input_tokens", 0),
                        output_tokens=tokens_data.get("output_tokens", 0),
                        reasoning_tokens=tokens_data.get("reasoning_tokens", 0),
                        cached_tokens=tokens_data.get("cached_tokens", 0),
                        total_tokens=tokens_data.get("total_tokens", 0),
                    ),
                )
                model_snap.details.append(detail)

            api_snap.models[model_key] = model_snap
        snapshot.apis[api_key] = api_snap

    export.usage = snapshot
    return export


def parse_auth_files_response(data: dict[str, Any]) -> list[AuthFileInfo]:
    """Parse auth files response JSON."""
    files = []
    for f in data.get("files", []):
        files.append(AuthFileInfo(
            auth_index=f.get("auth_index", ""),
            name=f.get("name", ""),
            email=f.get("email", ""),
            type=f.get("type", ""),
            provider=f.get("provider", ""),
            label=f.get("label", ""),
            status=f.get("status", ""),
            source=f.get("source", ""),
            disabled=f.get("disabled", False),
            unavailable=f.get("unavailable", False),
            runtime_only=f.get("runtime_only", False),
        ))
    return files


def _first_string(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value and isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def parse_provider_key_configs(data: list[dict[str, Any]]) -> list[ProviderKeyConfig]:
    """Parse provider key config JSON."""
    result = []
    for raw in data:
        result.append(ProviderKeyConfig(
            api_key=_first_string(raw, "apiKey", "api-key", "key"),
            prefix=_first_string(raw, "prefix"),
            name=_first_string(raw, "name"),
        ))
    return result


def parse_openai_compatibility_configs(data: list[dict[str, Any]]) -> list[OpenAICompatibilityConfig]:
    """Parse OpenAI compatibility config JSON."""
    result = []
    for raw in data:
        name = _first_string(raw, "name", "id")
        prefix = _first_string(raw, "prefix")
        entries = []
        for entries_key in ("apiKeyEntries", "api-key-entries", "api-keys"):
            raw_entries = raw.get(entries_key)
            if raw_entries and isinstance(raw_entries, list):
                for entry in raw_entries:
                    if isinstance(entry, str):
                        entries.append(OpenAIApiKeyEntry(api_key=entry))
                    elif isinstance(entry, dict):
                        entries.append(OpenAIApiKeyEntry(api_key=_first_string(entry, "apiKey", "api-key", "key")))
                break
        result.append(OpenAICompatibilityConfig(name=name, prefix=prefix, api_key_entries=entries))
    return result
