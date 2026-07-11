"""Phase 6B — auto-resolve provider_event_id from home/away teams (gated, fail-safe)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import config
from core.market_event_resolver_cache import (
    EventResolverCallBudget,
    MarketEventResolverCache,
    get_default_resolver_cache,
)
from core.market_event_map import make_event_map_key, normalize_team_for_event_map
from core.providers.rapidapi_odds_feed_client import (
    RapidApiOddsFeedClientError,
    fetch_scheduled_events,
)

_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"rapidapi_odds_feed"})


@dataclass(frozen=True)
class EventResolverResult:
    event_id: str | None = None
    cache_status: str = "disabled"  # hit | miss | disabled
    provider_call_count: int = 0
    match_reason: str | None = None


def _norm_fold(name: str) -> str:
    return normalize_team_for_event_map(name).casefold()


def _extract_event_id(event: Mapping[str, Any]) -> str | None:
    raw = event.get("id")
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, str) and raw.strip().isdigit():
        return raw.strip()
    return None


def _extract_event_teams(event: Mapping[str, Any]) -> tuple[str, str] | None:
    home = normalize_team_for_event_map((event.get("team_home") or {}).get("name", ""))
    away = normalize_team_for_event_map((event.get("team_away") or {}).get("name", ""))
    if not home or not away:
        return None
    return home, away


def match_provider_event_from_list(
    events: list[dict[str, Any]],
    *,
    home_team: str,
    away_team: str,
) -> tuple[str | None, str]:
    """Return (event_id, reason). Ambiguous or missing matches return (None, reason)."""
    want_home = _norm_fold(home_team)
    want_away = _norm_fold(away_team)
    if not want_home or not want_away:
        return None, "invalid_team_names"

    forward_ids: list[str] = []
    reversed_ids: list[str] = []

    for event in events:
        teams = _extract_event_teams(event)
        event_id = _extract_event_id(event)
        if teams is None or event_id is None:
            continue
        event_home, event_away = _norm_fold(teams[0]), _norm_fold(teams[1])
        if event_home == want_home and event_away == want_away:
            forward_ids.append(event_id)
        elif event_home == want_away and event_away == want_home:
            reversed_ids.append(event_id)

    if len(forward_ids) == 1:
        return forward_ids[0], "exact_match"
    if len(forward_ids) > 1:
        return None, "ambiguous_forward"
    if len(reversed_ids) == 1:
        return reversed_ids[0], "reversed_match"
    if len(reversed_ids) > 1:
        return None, "ambiguous_reversed"
    return None, "no_match"


def auto_resolver_gates_satisfied(
    *,
    influence_enabled: bool,
    shadow_diagnostics_enabled: bool,
    live_fetch_enabled: bool,
    auto_resolver_enabled: bool,
    provider: str,
    request_event_id: str | None,
    mapped_event_id: str | None,
) -> bool:
    if not (
        influence_enabled
        and shadow_diagnostics_enabled
        and live_fetch_enabled
        and auto_resolver_enabled
    ):
        return False
    if str(request_event_id or "").strip():
        return False
    if str(mapped_event_id or "").strip():
        return False
    return provider.strip().lower() in _SUPPORTED_PROVIDERS


def try_auto_resolve_provider_event_id(
    *,
    home_team: str,
    away_team: str,
    provider: str | None = None,
    auto_resolver_enabled: bool | None = None,
    influence_enabled: bool | None = None,
    shadow_diagnostics_enabled: bool | None = None,
    live_fetch_enabled: bool | None = None,
    request_event_id: str | None = None,
    mapped_event_id: str | None = None,
    cache_ttl_seconds: int | None = None,
    max_calls_per_request: int | None = None,
    sport_id: int | None = None,
    cache: MarketEventResolverCache | None = None,
    call_budget: EventResolverCallBudget | None = None,
    now: float | None = None,
) -> EventResolverResult:
    """Resolve provider_event_id via provider event list; never raises to caller."""
    provider_name = (
        config.market_event_resolver_provider() if provider is None else provider
    ).strip().lower()
    auto_on = (
        config.market_auto_event_resolver_enabled()
        if auto_resolver_enabled is None
        else auto_resolver_enabled
    )
    influence_on = (
        config.market_influence_enabled() if influence_enabled is None else influence_enabled
    )
    shadow_on = (
        config.market_shadow_diagnostics_enabled()
        if shadow_diagnostics_enabled is None
        else shadow_diagnostics_enabled
    )
    live_on = (
        config.market_live_provider_fetch_enabled()
        if live_fetch_enabled is None
        else live_fetch_enabled
    )

    if not auto_resolver_gates_satisfied(
        influence_enabled=influence_on,
        shadow_diagnostics_enabled=shadow_on,
        live_fetch_enabled=live_on,
        auto_resolver_enabled=auto_on,
        provider=provider_name,
        request_event_id=request_event_id,
        mapped_event_id=mapped_event_id,
    ):
        return EventResolverResult()

    cache_key = make_event_map_key(home_team, away_team)
    ttl = (
        config.market_event_resolver_cache_ttl_seconds()
        if cache_ttl_seconds is None
        else cache_ttl_seconds
    )
    max_calls = (
        config.market_event_resolver_max_calls_per_request()
        if max_calls_per_request is None
        else max_calls_per_request
    )
    cache_store = cache if cache is not None else get_default_resolver_cache()
    budget = (
        call_budget if call_budget is not None else EventResolverCallBudget(max_calls=max_calls)
    )

    if ttl > 0:
        cached = cache_store.get(cache_key, now=now)
        if cached is not None:
            return EventResolverResult(
                event_id=cached,
                cache_status="hit",
                provider_call_count=0,
                match_reason="cache_hit",
            )
        cache_status = "miss"
    else:
        cache_status = "disabled"

    if not budget.try_acquire():
        return EventResolverResult(cache_status=cache_status, match_reason="call_budget_exceeded")

    try:
        if provider_name == "rapidapi_odds_feed":
            events = fetch_scheduled_events(
                sport_id=config.market_event_resolver_sport_id() if sport_id is None else sport_id,
                pages=1,
            )
        else:
            return EventResolverResult(cache_status=cache_status, match_reason="unsupported_provider")
    except RapidApiOddsFeedClientError:
        return EventResolverResult(
            cache_status=cache_status,
            provider_call_count=1,
            match_reason="provider_error",
        )

    event_id, match_reason = match_provider_event_from_list(
        events,
        home_team=home_team,
        away_team=away_team,
    )
    if event_id and ttl > 0:
        cache_store.set(cache_key, event_id, ttl_seconds=ttl, now=now)

    return EventResolverResult(
        event_id=event_id,
        cache_status=cache_status,
        provider_call_count=1,
        match_reason=match_reason,
    )
