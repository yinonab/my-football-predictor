"""In-memory TTL cache and per-request call budget for provider event-id resolution (Phase 6B)."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _ResolverCacheEntry:
    event_id: str
    expires_at: float


@dataclass
class EventResolverCallBudget:
    """Per-request provider event-list call budget; no retries beyond max_calls."""

    max_calls: int
    calls_made: int = 0

    def try_acquire(self) -> bool:
        if self.calls_made >= self.max_calls:
            return False
        self.calls_made += 1
        return True


class MarketEventResolverCache:
    """Process-local TTL cache keyed by normalized home|away team pair."""

    def __init__(self) -> None:
        self._entries: dict[str, _ResolverCacheEntry] = {}

    @staticmethod
    def make_key(*, home_team: str, away_team: str) -> str:
        return f"{home_team.strip()}|{away_team.strip()}"

    def get(self, key: str, *, now: float | None = None) -> str | None:
        now_ts = time.time() if now is None else now
        entry = self._entries.get(key)
        if entry is None:
            return None
        if now_ts >= entry.expires_at:
            del self._entries[key]
            return None
        return entry.event_id

    def set(
        self,
        key: str,
        event_id: str,
        *,
        ttl_seconds: int,
        now: float | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            return
        event_id = str(event_id or "").strip()
        if not event_id:
            return
        now_ts = time.time() if now is None else now
        self._entries[key] = _ResolverCacheEntry(
            event_id=event_id,
            expires_at=now_ts + ttl_seconds,
        )

    def clear(self) -> None:
        self._entries.clear()


_default_cache = MarketEventResolverCache()


def get_default_resolver_cache() -> MarketEventResolverCache:
    return _default_cache


def reset_default_resolver_cache() -> None:
    _default_cache.clear()
