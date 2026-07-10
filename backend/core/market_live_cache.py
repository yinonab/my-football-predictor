"""In-memory TTL cache and per-request call budget for live provider diagnostics (Phase 5B)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class _CacheEntry:
    audit_report: dict[str, Any]
    expires_at: float


@dataclass
class LiveCallBudget:
    """Per-request provider call budget; no retries beyond max_calls."""

    max_calls: int
    calls_made: int = 0

    def try_acquire(self) -> bool:
        if self.calls_made >= self.max_calls:
            return False
        self.calls_made += 1
        return True


class MarketLiveCache:
    """Process-local TTL cache keyed by provider + event (+ optional region)."""

    def __init__(self) -> None:
        self._entries: dict[str, _CacheEntry] = {}

    @staticmethod
    def make_key(
        *,
        provider: str,
        provider_event_id: str,
        region: str | None = None,
    ) -> str:
        parts = [provider.strip().lower(), str(provider_event_id).strip()]
        if region:
            parts.append(region.strip().lower())
        return "|".join(parts)

    def get(self, key: str, *, now: float | None = None) -> dict[str, Any] | None:
        now_ts = time.time() if now is None else now
        entry = self._entries.get(key)
        if entry is None:
            return None
        if now_ts >= entry.expires_at:
            del self._entries[key]
            return None
        return entry.audit_report

    def set(
        self,
        key: str,
        audit_report: dict[str, Any],
        *,
        ttl_seconds: int,
        now: float | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            return
        now_ts = time.time() if now is None else now
        self._entries[key] = _CacheEntry(
            audit_report=audit_report,
            expires_at=now_ts + ttl_seconds,
        )

    def clear(self) -> None:
        self._entries.clear()


_default_cache = MarketLiveCache()


def get_default_cache() -> MarketLiveCache:
    return _default_cache


def reset_default_cache() -> None:
    _default_cache.clear()
