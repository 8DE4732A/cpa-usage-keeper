"""In-memory session manager with TTL-based expiration."""

from __future__ import annotations

import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional


class SessionManager:
    """Thread-safe in-memory session store."""

    def __init__(self, ttl: timedelta):
        self._ttl = ttl
        self._sessions: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def create(self) -> tuple[str, datetime]:
        """Create a new session and return (token, expires_at)."""
        token = secrets.token_hex(32)
        with self._lock:
            self._cleanup_expired_locked()
            expires_at = datetime.now(timezone.utc) + self._ttl
            self._sessions[token] = expires_at
        return token, expires_at

    def validate(self, token: str) -> bool:
        """Check if a token is valid and not expired."""
        if not token:
            return False
        with self._lock:
            expires_at = self._sessions.get(token)
        if expires_at is None:
            return False
        if expires_at <= datetime.now(timezone.utc):
            self.delete(token)
            return False
        return True

    def delete(self, token: str) -> None:
        """Remove a session."""
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def cleanup_expired(self) -> None:
        """Remove all expired sessions."""
        with self._lock:
            self._cleanup_expired_locked()

    def _cleanup_expired_locked(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [token for token, expires_at in self._sessions.items() if expires_at <= now]
        for token in expired:
            del self._sessions[token]
