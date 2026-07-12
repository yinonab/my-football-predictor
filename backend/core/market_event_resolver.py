"""Phase 6D — auto-resolve provider_event_id from home/away teams (gated, fail-safe)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import config
from core.market_event_resolver_cache import (
    EventResolverCallBudget,
    MarketEventResolverCache,
    get_default_resolver_cache,
)
from core.market_event_map import (
    make_event_map_key,
    normalize_team_for_event_map,
    normalize_team_for_resolver,
)
from core.providers.rapidapi_odds_feed_client import (
    RapidApiOddsFeedClientError,
    fetch_resolver_discovery_events,
)

logger = logging.getLogger(__name__)

_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"rapidapi_odds_feed"})
_RESOLVER_WINDOW_STATUSES: frozenset[str] = frozenset(
    {"SCHEDULED", "LIVE", "IN_PROGRESS", "STARTED", "FINISHED"}
)


@dataclass(frozen=True)
class EventResolverResult:
    event_id: str | None = None
    cache_status: str = "disabled"  # hit | miss | disabled
    provider_call_count: int = 0
    match_reason: str | None = None


def _norm_fold(name: str) -> str:
    return normalize_team_for_resolver(name).casefold()


def _token_set(name: str) -> frozenset[str]:
    return frozenset(_norm_fold(name).split())


def _parse_event_start_at(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(raw.replace("Z", "+0000"), fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def filter_events_in_resolver_window(
    events: list[dict[str, Any]],
    *,
    lookback_hours: int,
    lookahead_hours: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Keep resolver-relevant events inside the configured start-time window."""
    now_ts = now or datetime.now(timezone.utc)
    window_start = now_ts - timedelta(hours=lookback_hours)
    window_end = now_ts + timedelta(hours=lookahead_hours)
    kept: list[dict[str, Any]] = []
    for event in events:
        status = str(event.get("status") or "").strip().upper()
        if status and status not in _RESOLVER_WINDOW_STATUSES:
            continue
        start_at = _parse_event_start_at(event.get("start_at"))
        if start_at is None:
            if status in _RESOLVER_WINDOW_STATUSES:
                kept.append(event)
            continue
        if window_start <= start_at <= window_end:
            kept.append(event)
    return kept


def _extract_event_id(event: Mapping[str, Any]) -> str | None:
    raw = event.get("id")
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, str) and raw.strip().isdigit():
        return raw.strip()
    return None


def _extract_event_teams(event: Mapping[str, Any]) -> tuple[str, str] | None:
    home = normalize_team_for_resolver((event.get("team_home") or {}).get("name", ""))
    away = normalize_team_for_resolver((event.get("team_away") or {}).get("name", ""))
    if not home or not away:
        return None
    return home, away


def _collect_orientation_matches(
    events: list[dict[str, Any]],
    *,
    want_home: str,
    want_away: str,
    matcher,
) -> tuple[list[str], list[str]]:
    forward_ids: list[str] = []
    reversed_ids: list[str] = []
    for event in events:
        teams = _extract_event_teams(event)
        event_id = _extract_event_id(event)
        if teams is None or event_id is None:
            continue
        event_home, event_away = teams[0], teams[1]
        if matcher(event_home, event_away, want_home, want_away):
            forward_ids.append(event_id)
        elif matcher(event_home, event_away, want_away, want_home):
            reversed_ids.append(event_id)
    return forward_ids, reversed_ids


def _resolve_orientation_ids(forward_ids: list[str], reversed_ids: list[str], *, suffix: str) -> tuple[str | None, str]:
    if len(forward_ids) == 1:
        return forward_ids[0], f"exact_match{suffix}"
    if len(forward_ids) > 1:
        return None, f"ambiguous_forward{suffix}"
    if len(reversed_ids) == 1:
        return reversed_ids[0], f"reversed_match{suffix}"
    if len(reversed_ids) > 1:
        return None, f"ambiguous_reversed{suffix}"
    return None, "no_match"


def _exact_matcher(event_home: str, event_away: str, want_home: str, want_away: str) -> bool:
    return _norm_fold(event_home) == _norm_fold(want_home) and _norm_fold(event_away) == _norm_fold(want_away)


def _fuzzy_token_matcher(event_home: str, event_away: str, want_home: str, want_away: str) -> bool:
    return _token_set(event_home) == _token_set(want_home) and _token_set(event_away) == _token_set(want_away)


def match_provider_event_from_list(
    events: list[dict[str, Any]],
    *,
    home_team: str,
    away_team: str,
) -> tuple[str | None, str]:
    """Return (event_id, reason). Ambiguous or missing matches return (None, reason)."""
    want_home = normalize_team_for_resolver(home_team)
    want_away = normalize_team_for_resolver(away_team)
    if not want_home or not want_away:
        return None, "invalid_team_names"

    forward_ids, reversed_ids = _collect_orientation_matches(
        events,
        want_home=want_home,
        want_away=want_away,
        matcher=_exact_matcher,
    )
    event_id, reason = _resolve_orientation_ids(forward_ids, reversed_ids, suffix="")
    if event_id or reason != "no_match":
        return event_id, reason

    fuzzy_forward, fuzzy_reversed = _collect_orientation_matches(
        events,
        want_home=want_home,
        want_away=want_away,
        matcher=_fuzzy_token_matcher,
    )
    return _resolve_orientation_ids(fuzzy_forward, fuzzy_reversed, suffix="_fuzzy")


def _find_event_by_id(events: list[dict[str, Any]], event_id: str | None) -> dict[str, Any] | None:
    if not event_id:
        return None
    for event in events:
        if _extract_event_id(event) == str(event_id):
            return event
    return None


def event_in_client_window(
    event: Mapping[str, Any],
    *,
    lookback_hours: int,
    lookahead_hours: int,
    now: datetime | None = None,
) -> bool:
    """Whether event start_at falls inside the configured client acceptance window."""
    now_ts = now or datetime.now(timezone.utc)
    window_start = now_ts - timedelta(hours=lookback_hours)
    window_end = now_ts + timedelta(hours=lookahead_hours)
    start_at = _parse_event_start_at(event.get("start_at"))
    if start_at is None:
        status = str(event.get("status") or "").strip().upper()
        return status in _RESOLVER_WINDOW_STATUSES
    return window_start <= start_at <= window_end


def _apply_client_window_to_match(
    *,
    event_id: str | None,
    match_reason: str,
    raw_events: list[dict[str, Any]],
    lookback_hours: int,
    lookahead_hours: int,
    now: datetime | None,
) -> tuple[str | None, str]:
    """Keep resolved id only when the matched event is inside the client window."""
    if event_id is None:
        return None, match_reason
    if match_reason in {
        "ambiguous_forward",
        "ambiguous_reversed",
        "ambiguous_forward_fuzzy",
        "ambiguous_reversed_fuzzy",
        "invalid_team_names",
        "provider_error",
        "call_budget_exceeded",
    }:
        return event_id, match_reason
    matched = _find_event_by_id(raw_events, event_id)
    if matched is None:
        return None, "no_match"
    if event_in_client_window(
        matched,
        lookback_hours=lookback_hours,
        lookahead_hours=lookahead_hours,
        now=now,
    ):
        return event_id, match_reason
    return None, "outside_window"


def auto_resolver_gates_satisfied(
    *,
    influence_enabled: bool,
    shadow_diagnostics_enabled: bool,
    live_fetch_enabled: bool,
    auto_resolver_enabled: bool,
    provider: str,
    request_event_id: str | None,
    mapped_event_id: str | None,
    for_diagnostics: bool = False,
) -> bool:
    if not (live_fetch_enabled and auto_resolver_enabled):
        return False
    if for_diagnostics:
        if str(request_event_id or "").strip():
            return False
        if str(mapped_event_id or "").strip():
            return False
        return provider.strip().lower() in _SUPPORTED_PROVIDERS
    if not (influence_enabled and shadow_diagnostics_enabled):
        return False
    if str(request_event_id or "").strip():
        return False
    if str(mapped_event_id or "").strip():
        return False
    return provider.strip().lower() in _SUPPORTED_PROVIDERS


def _log_resolver_outcome(
    *,
    home_team: str,
    away_team: str,
    result: EventResolverResult,
    matched_event: Mapping[str, Any] | None = None,
    list_count: int | None = None,
    pages: int | None = None,
) -> None:
    home = normalize_team_for_event_map(home_team)
    away = normalize_team_for_event_map(away_team)
    reason = result.match_reason or ""
    if result.event_id:
        start_at = (matched_event or {}).get("start_at")
        status = (matched_event or {}).get("status")
        tournament = ((matched_event or {}).get("tournament") or {}).get("name")
        logger.info(
            "resolver_resolved home=%s away=%s event_id=%s reason=%s cache=%s "
            "start_at=%s status=%s tournament=%s",
            home,
            away,
            result.event_id,
            reason,
            result.cache_status,
            start_at,
            status,
            tournament,
        )
        return
    if reason in {"ambiguous_forward", "ambiguous_reversed", "ambiguous_forward_fuzzy", "ambiguous_reversed_fuzzy"}:
        logger.warning("resolver_ambiguous home=%s away=%s reason=%s", home, away, reason)
    elif reason == "provider_error":
        logger.warning("resolver_provider_error home=%s away=%s", home, away)
    elif reason == "outside_window":
        logger.info("resolver_outside_window home=%s away=%s", home, away)
    elif reason == "no_match":
        if list_count is not None and pages is not None:
            logger.info(
                "resolver_no_match home=%s away=%s list_count=%s pages=%s",
                home,
                away,
                list_count,
                pages,
            )
        else:
            logger.info("resolver_no_match home=%s away=%s", home, away)
    elif reason == "call_budget_exceeded":
        logger.warning("resolver_call_budget_exceeded home=%s away=%s", home, away)


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
    lookback_hours: int | None = None,
    lookahead_hours: int | None = None,
    pages: int | None = None,
    cache: MarketEventResolverCache | None = None,
    call_budget: EventResolverCallBudget | None = None,
    now: float | None = None,
    for_diagnostics: bool = False,
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
        for_diagnostics=for_diagnostics,
    ):
        return EventResolverResult()

    home = normalize_team_for_event_map(home_team)
    away = normalize_team_for_event_map(away_team)
    logger.info("resolver_started home=%s away=%s", home, away)

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
    lookback = (
        config.market_event_resolver_lookback_hours()
        if lookback_hours is None
        else lookback_hours
    )
    lookahead = (
        config.market_event_resolver_lookahead_hours()
        if lookahead_hours is None
        else lookahead_hours
    )
    page_count = config.market_event_resolver_pages() if pages is None else max(1, pages)
    cache_store = cache if cache is not None else get_default_resolver_cache()
    budget = (
        call_budget if call_budget is not None else EventResolverCallBudget(max_calls=max_calls)
    )
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc) if now is not None else None

    if ttl > 0:
        cached = cache_store.get(cache_key, now=now)
        if cached is not None:
            result = EventResolverResult(
                event_id=cached,
                cache_status="hit",
                provider_call_count=0,
                match_reason="cache_hit",
            )
            _log_resolver_outcome(home_team=home_team, away_team=away_team, result=result)
            return result
        cache_status = "miss"
    else:
        cache_status = "disabled"

    if not budget.try_acquire():
        result = EventResolverResult(cache_status=cache_status, match_reason="call_budget_exceeded")
        _log_resolver_outcome(home_team=home_team, away_team=away_team, result=result)
        return result

    try:
        if provider_name == "rapidapi_odds_feed":
            discovery_status = config.market_event_resolver_discovery_status()
            api_lookback = config.market_event_resolver_api_lookback_hours()
            api_lookahead = config.market_event_resolver_api_lookahead_hours()
            raw_events = fetch_resolver_discovery_events(
                sport_id=config.market_event_resolver_sport_id() if sport_id is None else sport_id,
                status=discovery_status or None,
                api_lookback_hours=api_lookback,
                api_lookahead_hours=api_lookahead,
                pages=page_count,
                now=now_dt,
            )
            logger.info(
                "resolver_list_fetched count=%s pages=%s status=%s",
                len(raw_events),
                page_count,
                discovery_status or "none",
            )
        else:
            result = EventResolverResult(cache_status=cache_status, match_reason="unsupported_provider")
            _log_resolver_outcome(home_team=home_team, away_team=away_team, result=result)
            return result
    except RapidApiOddsFeedClientError:
        result = EventResolverResult(
            cache_status=cache_status,
            provider_call_count=1,
            match_reason="provider_error",
        )
        _log_resolver_outcome(home_team=home_team, away_team=away_team, result=result)
        return result

    event_id, match_reason = match_provider_event_from_list(
        raw_events,
        home_team=home_team,
        away_team=away_team,
    )
    event_id, match_reason = _apply_client_window_to_match(
        event_id=event_id,
        match_reason=match_reason,
        raw_events=raw_events,
        lookback_hours=lookback,
        lookahead_hours=lookahead,
        now=now_dt,
    )
    matched_event = _find_event_by_id(raw_events, event_id)

    if event_id and ttl > 0:
        cache_store.set(cache_key, event_id, ttl_seconds=ttl, now=now)

    result = EventResolverResult(
        event_id=event_id,
        cache_status=cache_status,
        provider_call_count=1,
        match_reason=match_reason,
    )
    _log_resolver_outcome(
        home_team=home_team,
        away_team=away_team,
        result=result,
        matched_event=matched_event,
        list_count=len(raw_events),
        pages=page_count,
    )
    return result
