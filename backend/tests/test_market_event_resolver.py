"""Unit tests for provider event-id auto resolver (Phase 6B)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import config
from core.market_event_resolver import (
    auto_resolver_gates_satisfied,
    filter_events_in_resolver_window,
    match_provider_event_from_list,
    try_auto_resolve_provider_event_id,
)
from core.market_event_resolver_cache import (
    EventResolverCallBudget,
    MarketEventResolverCache,
    reset_default_resolver_cache,
)
from core.providers.rapidapi_odds_feed_client import RapidApiOddsFeedClientError


@pytest.fixture(autouse=True)
def _clear_resolver_cache() -> None:
    reset_default_resolver_cache()
    yield
    reset_default_resolver_cache()


def _event(
    event_id: int,
    home: str,
    away: str,
    *,
    status: str = "SCHEDULED",
    start_at: str | None = None,
) -> dict:
    payload = {
        "id": event_id,
        "status": status,
        "team_home": {"name": home},
        "team_away": {"name": away},
    }
    if start_at is not None:
        payload["start_at"] = start_at
    return payload


def test_match_exact_orientation() -> None:
    events = [_event(619963, "Norway", "England")]
    event_id, reason = match_provider_event_from_list(
        events,
        home_team="Norway",
        away_team="England",
    )
    assert event_id == "619963"
    assert reason == "exact_match"


def test_match_strips_parenthetical_suffixes() -> None:
    events = [_event(700001, "Canada", "Argentina")]
    event_id, reason = match_provider_event_from_list(
        events,
        home_team="Canada (קנדה)",
        away_team="Argentina (ארגנטינה)",
    )
    assert event_id == "700001"
    assert reason == "exact_match"


def test_match_case_insensitive() -> None:
    events = [_event(42, "NORWAY", "england")]
    event_id, _ = match_provider_event_from_list(
        events,
        home_team="norway",
        away_team="England",
    )
    assert event_id == "42"


def test_match_reversed_only_when_single_candidate() -> None:
    events = [_event(88, "Argentina", "Canada")]
    event_id, reason = match_provider_event_from_list(
        events,
        home_team="Canada",
        away_team="Argentina",
    )
    assert event_id == "88"
    assert reason == "reversed_match"


def test_match_ambiguous_forward_returns_none() -> None:
    events = [
        _event(1, "Norway", "England"),
        _event(2, "Norway", "England"),
    ]
    event_id, reason = match_provider_event_from_list(
        events,
        home_team="Norway",
        away_team="England",
    )
    assert event_id is None
    assert reason == "ambiguous_forward"


def test_match_ambiguous_reversed_returns_none() -> None:
    events = [
        _event(1, "England", "Norway"),
        _event(2, "England", "Norway"),
    ]
    event_id, reason = match_provider_event_from_list(
        events,
        home_team="Norway",
        away_team="England",
    )
    assert event_id is None
    assert reason == "ambiguous_reversed"


def test_match_no_match() -> None:
    events = [_event(1, "France", "Germany")]
    event_id, reason = match_provider_event_from_list(
        events,
        home_team="Norway",
        away_team="England",
    )
    assert event_id is None
    assert reason == "no_match"


def test_auto_resolver_gates_require_all_flags() -> None:
    base = dict(
        influence_enabled=True,
        shadow_diagnostics_enabled=True,
        live_fetch_enabled=True,
        auto_resolver_enabled=True,
        provider="rapidapi_odds_feed",
        request_event_id=None,
        mapped_event_id=None,
    )
    assert auto_resolver_gates_satisfied(**base) is True
    assert auto_resolver_gates_satisfied(**{**base, "auto_resolver_enabled": False}) is False
    assert auto_resolver_gates_satisfied(**{**base, "request_event_id": "1"}) is False
    assert auto_resolver_gates_satisfied(**{**base, "mapped_event_id": "2"}) is False


def test_try_auto_resolve_cache_hit_skips_provider() -> None:
    cache = MarketEventResolverCache()
    cache.set("Canada|Argentina", "700001", ttl_seconds=3600)
    with patch("core.market_event_resolver.fetch_events_in_match_window") as fetch_mock:
        result = try_auto_resolve_provider_event_id(
            home_team="Canada (קנדה)",
            away_team="Argentina (ארגנטינה)",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            auto_resolver_enabled=True,
            cache=cache,
        )
    assert result.event_id == "700001"
    assert result.cache_status == "hit"
    assert result.provider_call_count == 0
    fetch_mock.assert_not_called()


def test_try_auto_resolve_cache_miss_calls_provider_once() -> None:
    events = [_event(619963, "Norway", "England")]
    with patch(
        "core.market_event_resolver.fetch_events_in_match_window",
        return_value=events,
    ) as fetch_mock:
        result = try_auto_resolve_provider_event_id(
            home_team="Norway",
            away_team="England",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            auto_resolver_enabled=True,
        )
    assert result.event_id == "619963"
    assert result.cache_status == "miss"
    assert result.provider_call_count == 1
    fetch_mock.assert_called_once()


def test_try_auto_resolve_provider_error_fail_safe() -> None:
    with patch(
        "core.market_event_resolver.fetch_events_in_match_window",
        side_effect=RapidApiOddsFeedClientError("rapidapi_auth_failed:secret-key-xyz"),
    ):
        result = try_auto_resolve_provider_event_id(
            home_team="Norway",
            away_team="England",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            auto_resolver_enabled=True,
        )
    assert result.event_id is None
    assert result.match_reason == "provider_error"


def test_try_auto_resolve_budget_exceeded() -> None:
    budget = EventResolverCallBudget(max_calls=0)
    with patch("core.market_event_resolver.fetch_events_in_match_window") as fetch_mock:
        result = try_auto_resolve_provider_event_id(
            home_team="Norway",
            away_team="England",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            auto_resolver_enabled=True,
            call_budget=budget,
        )
    assert result.event_id is None
    assert result.match_reason == "call_budget_exceeded"
    fetch_mock.assert_not_called()


def test_try_auto_resolve_flag_off_no_provider_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MARKET_AUTO_EVENT_RESOLVER_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "market_auto_event_resolver_enabled", lambda: False)
    with patch("core.market_event_resolver.fetch_events_in_match_window") as fetch_mock:
        result = try_auto_resolve_provider_event_id(
            home_team="Norway",
            away_team="England",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            auto_resolver_enabled=False,
        )
    assert result.event_id is None
    fetch_mock.assert_not_called()


def test_filter_live_event_within_window() -> None:
    now = datetime(2026, 7, 11, 23, 0, 0, tzinfo=timezone.utc)
    events = [
        _event(
            619963,
            "Norway",
            "England",
            status="LIVE",
            start_at="2026-07-11 21:00:00",
        )
    ]
    filtered = filter_events_in_resolver_window(
        events, lookback_hours=6, lookahead_hours=72, now=now
    )
    assert len(filtered) == 1


def test_filter_post_kickoff_within_lookback_resolves() -> None:
    now = datetime(2026, 7, 11, 23, 55, 0, tzinfo=timezone.utc)
    events = [
        _event(
            619963,
            "Norway",
            "England",
            status="LIVE",
            start_at="2026-07-11 21:00:00",
        )
    ]
    with patch(
        "core.market_event_resolver.fetch_events_in_match_window",
        return_value=events,
    ) as fetch_mock:
        result = try_auto_resolve_provider_event_id(
            home_team="Norway",
            away_team="England",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            auto_resolver_enabled=True,
            lookback_hours=6,
            lookahead_hours=72,
            now=now.timestamp(),
        )
    assert result.event_id == "619963"
    fetch_mock.assert_called_once()


def test_filter_event_outside_lookback_excluded() -> None:
    now = datetime(2026, 7, 11, 23, 0, 0, tzinfo=timezone.utc)
    events = [
        _event(
            619963,
            "Norway",
            "England",
            status="FINISHED",
            start_at="2026-07-11 10:00:00",
        )
    ]
    filtered = filter_events_in_resolver_window(
        events, lookback_hours=6, lookahead_hours=72, now=now
    )
    assert filtered == []


def test_try_auto_resolve_outside_lookback_no_match() -> None:
    now = datetime(2026, 7, 11, 23, 0, 0, tzinfo=timezone.utc)
    events = [
        _event(
            619963,
            "Norway",
            "England",
            status="FINISHED",
            start_at="2026-07-11 10:00:00",
        )
    ]
    with patch(
        "core.market_event_resolver.fetch_events_in_match_window",
        return_value=events,
    ):
        result = try_auto_resolve_provider_event_id(
            home_team="Norway",
            away_team="England",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            auto_resolver_enabled=True,
            lookback_hours=6,
            now=now.timestamp(),
        )
    assert result.event_id is None
    assert result.match_reason == "outside_window"


def test_resolver_logs_no_match(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="core.market_event_resolver")
    with patch("core.market_event_resolver.fetch_events_in_match_window", return_value=[]):
        try_auto_resolve_provider_event_id(
            home_team="Norway",
            away_team="England",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            auto_resolver_enabled=True,
        )
    assert "resolver_started" in caplog.text
    assert "resolver_no_match" in caplog.text


def test_match_alias_accent_normalization() -> None:
    events = [_event(9001, "Czechia", "Iran")]
    event_id, reason = match_provider_event_from_list(
        events,
        home_team="Czech Republic",
        away_team="IR Iran",
    )
    assert event_id == "9001"
    assert reason == "exact_match"


def test_match_fuzzy_single_candidate() -> None:
    events = [_event(77, "Korea South", "Saudi Arabia")]
    event_id, reason = match_provider_event_from_list(
        events,
        home_team="South Korea",
        away_team="Saudi Arabia",
    )
    assert event_id == "77"
    assert reason == "exact_match_fuzzy"


def test_match_fuzzy_ambiguous_returns_none() -> None:
    events = [
        _event(1, "B A C", "Saudi Arabia"),
        _event(2, "C A B", "Saudi Arabia"),
    ]
    event_id, reason = match_provider_event_from_list(
        events,
        home_team="A B C",
        away_team="Saudi Arabia",
    )
    assert event_id is None
    assert reason == "ambiguous_forward_fuzzy"


def test_try_auto_resolve_passes_configured_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MARKET_EVENT_RESOLVER_PAGES", 2, raising=False)
    monkeypatch.setattr(config, "market_event_resolver_pages", lambda: 2)
    with patch(
        "core.market_event_resolver.fetch_events_in_match_window",
        return_value=[_event(619963, "Norway", "England")],
    ) as fetch_mock:
        try_auto_resolve_provider_event_id(
            home_team="Norway",
            away_team="England",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            auto_resolver_enabled=True,
        )
    fetch_mock.assert_called_once()
    assert fetch_mock.call_args.kwargs["pages"] == 2


def test_try_auto_resolve_fetches_page_two_when_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _side_effect(**kwargs):
        if kwargs.get("pages", 1) >= 2:
            return [_event(999, "France", "Spain")]
        return []

    with patch(
        "core.market_event_resolver.fetch_events_in_match_window",
        side_effect=_side_effect,
    ) as fetch_mock:
        result = try_auto_resolve_provider_event_id(
            home_team="France",
            away_team="Spain",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            auto_resolver_enabled=True,
            pages=2,
        )
    assert result.event_id == "999"
    assert fetch_mock.call_args.kwargs["pages"] == 2


def test_try_auto_resolve_outside_window_reason() -> None:
    now = datetime(2026, 7, 11, 23, 0, 0, tzinfo=timezone.utc)
    events = [
        _event(
            619963,
            "Norway",
            "England",
            status="FINISHED",
            start_at="2026-07-11 10:00:00",
        )
    ]
    with patch(
        "core.market_event_resolver.fetch_events_in_match_window",
        return_value=events,
    ):
        result = try_auto_resolve_provider_event_id(
            home_team="Norway",
            away_team="England",
            influence_enabled=True,
            shadow_diagnostics_enabled=True,
            live_fetch_enabled=True,
            auto_resolver_enabled=True,
            lookback_hours=6,
            now=now.timestamp(),
        )
    assert result.event_id is None
    assert result.match_reason == "outside_window"
