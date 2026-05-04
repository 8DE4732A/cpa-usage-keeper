"""CPA HTTP client for fetching usage data and metadata."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

import httpx
from loguru import logger

from .endpoints import (
    CPA_MANAGEMENT_AUTH_FILES,
    CPA_MANAGEMENT_CLAUDE_API_KEY,
    CPA_MANAGEMENT_CODEX_API_KEY,
    CPA_MANAGEMENT_GEMINI_API_KEY,
    CPA_MANAGEMENT_OPENAI_COMPATIBILITY,
    CPA_MANAGEMENT_USAGE_EXPORT,
    CPA_MANAGEMENT_VERTEX_API_KEY,
)
from .types import (
    AuthFileInfo,
    AuthFilesResult,
    ExportResult,
    OpenAICompatibilityResult,
    ProviderKeyConfig,
    ProviderKeyConfigResult,
    parse_auth_files_response,
    parse_openai_compatibility_configs,
    parse_provider_key_configs,
    parse_usage_export,
)


class CPAClient:
    """HTTP client for CPA management API."""

    def __init__(self, base_url: str, management_key: str, timeout: timedelta):
        self.base_url = base_url.rstrip("/")
        self.management_key = management_key.strip()
        self.timeout = timeout.total_seconds()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.management_key}"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def fetch_usage_export(self) -> ExportResult:
        """Fetch the usage export from CPA."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(self._url(CPA_MANAGEMENT_USAGE_EXPORT), headers=self._headers())
                result = ExportResult(status_code=resp.status_code, body=resp.content)
                if resp.status_code == 200:
                    data = resp.json()
                    result.payload = parse_usage_export(data)
                return result
        except Exception as e:
            logger.error(f"fetch usage export failed: {e}")
            raise

    def fetch_auth_files(self) -> AuthFilesResult:
        """Fetch auth files from CPA."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(self._url(CPA_MANAGEMENT_AUTH_FILES), headers=self._headers())
                result = AuthFilesResult(status_code=resp.status_code, body=resp.content)
                if resp.status_code == 200:
                    data = resp.json()
                    result.files = parse_auth_files_response(data)
                return result
        except Exception as e:
            logger.error(f"fetch auth files failed: {e}")
            raise

    def _fetch_provider_key_configs(self, path: str) -> ProviderKeyConfigResult:
        """Fetch provider key configs from CPA."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(self._url(path), headers=self._headers())
                result = ProviderKeyConfigResult(status_code=resp.status_code, body=resp.content)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        result.payload = parse_provider_key_configs(data)
                return result
        except Exception as e:
            logger.error(f"fetch provider key configs from {path} failed: {e}")
            raise

    def fetch_gemini_api_keys(self) -> ProviderKeyConfigResult:
        return self._fetch_provider_key_configs(CPA_MANAGEMENT_GEMINI_API_KEY)

    def fetch_claude_api_keys(self) -> ProviderKeyConfigResult:
        return self._fetch_provider_key_configs(CPA_MANAGEMENT_CLAUDE_API_KEY)

    def fetch_codex_api_keys(self) -> ProviderKeyConfigResult:
        return self._fetch_provider_key_configs(CPA_MANAGEMENT_CODEX_API_KEY)

    def fetch_vertex_api_keys(self) -> ProviderKeyConfigResult:
        return self._fetch_provider_key_configs(CPA_MANAGEMENT_VERTEX_API_KEY)

    def fetch_openai_compatibility(self) -> OpenAICompatibilityResult:
        """Fetch OpenAI compatibility config from CPA."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(self._url(CPA_MANAGEMENT_OPENAI_COMPATIBILITY), headers=self._headers())
                result = OpenAICompatibilityResult(status_code=resp.status_code, body=resp.content)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        result.payload = parse_openai_compatibility_configs(data)
                return result
        except Exception as e:
            logger.error(f"fetch openai compatibility failed: {e}")
            raise
