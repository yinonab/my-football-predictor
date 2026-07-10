"""Unit tests for live provider cache + quota guard (Phase 5B)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.market_live_cache import LiveCallBudget, MarketLiveCache, reset_default_cache
from core.market_live_fetch import LiveFetchResult, MarketLiveFetchError, fetch_live_market_audit_report

RAW_H2H_MARKET = {
    "id": 50679030,
    "market_name": "1X2",
    "period": "FULL_TIME",
    "placing": "PREMATCH",
    "bet_type": "BACK",
    "value": None,
    "market_books": [
        {
            "book": "BET365",
            "outcome_0": 4.09,
            "outcome_1": 3.7,
            "outcome_2": 1.85,
            "is_open": True,
        }
    ],
}

MOCK_PROVIDER_PAYLOAD = {
    "provider": "rapidapi_odds_feed",
    "event_id": "619963",
    "placing": "PREMATCH",
    "http_status": 200,
    "markets": [RAW_H2H_MARKET],
}


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_default_cache()
    yield
    reset_default_cache()


def test_cache_miss_calls_provider_once() -> None:
    cache = MarketLiveCache()
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=MOCK_PROVIDER_PAYLOAD,
    ) as fetch_mock:
        result = fetch_live_market_audit_report(
            provider="rapidapi_odds_feed",
            provider_event_id="619963",
            home_team="Norway",
            away_team="England",
            cache=cache,
            cache_ttl_seconds=600,
            now=1000.0,
        )
    fetch_mock.assert_called_once_with("619963")
    assert result.cache_status == "miss"
    assert result.provider_call_count == 1
    assert result.audit_report["selected_event"]["event_id"] == "619963"


def test_cache_hit_avoids_provider_call() -> None:
    cache = MarketLiveCache()
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=MOCK_PROVIDER_PAYLOAD,
    ) as fetch_mock:
        fetch_live_market_audit_report(
            provider="rapidapi_odds_feed",
            provider_event_id="619963",
            home_team="Norway",
            away_team="England",
            cache=cache,
            cache_ttl_seconds=600,
            now=1000.0,
        )
        result = fetch_live_market_audit_report(
            provider="rapidapi_odds_feed",
            provider_event_id="619963",
            home_team="Norway",
            away_team="England",
            cache=cache,
            cache_ttl_seconds=600,
            now=1100.0,
        )
    fetch_mock.assert_called_once()
    assert result.cache_status == "hit"
    assert result.provider_call_count == 0


def test_ttl_expiry_triggers_new_provider_call() -> None:
    cache = MarketLiveCache()
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=MOCK_PROVIDER_PAYLOAD,
    ) as fetch_mock:
        fetch_live_market_audit_report(
            provider="rapidapi_odds_feed",
            provider_event_id="619963",
            home_team="Norway",
            away_team="England",
            cache=cache,
            cache_ttl_seconds=600,
            now=1000.0,
        )
        result = fetch_live_market_audit_report(
            provider="rapidapi_odds_feed",
            provider_event_id="619963",
            home_team="Norway",
            away_team="England",
            cache=cache,
            cache_ttl_seconds=600,
            now=1601.0,
        )
    assert fetch_mock.call_count == 2
    assert result.cache_status == "miss"
    assert result.provider_call_count == 1


def test_max_live_calls_per_request_enforced() -> None:
    cache = MarketLiveCache()
    budget = LiveCallBudget(max_calls=0)
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=MOCK_PROVIDER_PAYLOAD,
    ) as fetch_mock:
        with pytest.raises(MarketLiveFetchError, match="live_provider_call_budget_exceeded"):
            fetch_live_market_audit_report(
                provider="rapidapi_odds_feed",
                provider_event_id="619963",
                home_team="Norway",
                away_team="England",
                cache=cache,
                cache_ttl_seconds=0,
                call_budget=budget,
            )
    fetch_mock.assert_not_called()


def test_live_fetch_disabled_raises_without_provider_call() -> None:
    with patch("core.market_live_fetch.fetch_event_markets") as fetch_mock:
        with pytest.raises(MarketLiveFetchError, match="market_live_provider_fetch_disabled"):
            fetch_live_market_audit_report(
                provider="rapidapi_odds_feed",
                provider_event_id="619963",
                home_team="Norway",
                away_team="England",
                live_fetch_enabled=False,
            )
    fetch_mock.assert_not_called()


def test_provider_errors_sanitized_no_key_leak() -> None:
    from core.providers.rapidapi_odds_feed_client import RapidApiOddsFeedClientError

    with patch(
        "core.market_live_fetch.fetch_event_markets",
        side_effect=RapidApiOddsFeedClientError("rapidapi_auth_failed"),
    ):
        with pytest.raises(MarketLiveFetchError, match="rapidapi_auth_failed") as exc_info:
            fetch_live_market_audit_report(
                provider="rapidapi_odds_feed",
                provider_event_id="619963",
                home_team="Norway",
                away_team="England",
                cache_ttl_seconds=0,
            )
    assert "RAPIDAPI_KEY" not in str(exc_info.value)


def test_cache_disabled_when_ttl_zero() -> None:
    cache = MarketLiveCache()
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=MOCK_PROVIDER_PAYLOAD,
    ) as fetch_mock:
        result = fetch_live_market_audit_report(
            provider="rapidapi_odds_feed",
            provider_event_id="619963",
            home_team="Norway",
            away_team="England",
            cache=cache,
            cache_ttl_seconds=0,
            now=1000.0,
        )
        fetch_live_market_audit_report(
            provider="rapidapi_odds_feed",
            provider_event_id="619963",
            home_team="Norway",
            away_team="England",
            cache=cache,
            cache_ttl_seconds=0,
            now=1000.0,
        )
    assert fetch_mock.call_count == 2
    assert result.cache_status == "disabled"
    assert result.provider_call_count == 1


def test_cache_key_includes_region_when_provided() -> None:
    key_a = MarketLiveCache.make_key(
        provider="rapidapi_odds_feed",
        provider_event_id="619963",
    )
    key_b = MarketLiveCache.make_key(
        provider="rapidapi_odds_feed",
        provider_event_id="619963",
        region="eu",
    )
    assert key_a != key_b


def test_live_fetch_result_type() -> None:
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=MOCK_PROVIDER_PAYLOAD,
    ):
        result = fetch_live_market_audit_report(
            provider="rapidapi_odds_feed",
            provider_event_id="619963",
            home_team="Norway",
            away_team="England",
            cache_ttl_seconds=0,
        )
    assert isinstance(result, LiveFetchResult)
