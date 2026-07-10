"""Unit tests for live provider diagnostics fetch (Phase 5A)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.market_live_cache import reset_default_cache
from core.market_live_fetch import (
    MarketLiveFetchError,
    build_rapidapi_audit_report,
    fetch_live_market_audit_report,
    summarize_markets,
)


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


@pytest.fixture(autouse=True)
def _clear_live_cache() -> None:
    reset_default_cache()
    yield
    reset_default_cache()


def test_summarize_markets_maps_h2h_family() -> None:
    rows = summarize_markets([RAW_H2H_MARKET])
    assert len(rows) == 1
    assert rows[0]["mapped_family"] == "h2h"
    assert rows[0]["provider_market_name"] == "1X2"
    assert rows[0]["sample_odds"][0]["book"] == "BET365"


def test_build_rapidapi_audit_report_shape() -> None:
    report = build_rapidapi_audit_report(
        provider_event_id="619963",
        home_team="Norway",
        away_team="England",
        raw_markets=[RAW_H2H_MARKET],
        tournament="World Championship",
    )
    assert report["selected_event"]["event_id"] == "619963"
    assert "Norway vs England" in report["selected_event"]["label"]
    assert report["market_coverage_table"]


def test_fetch_live_rejects_unsupported_provider() -> None:
    with pytest.raises(MarketLiveFetchError, match="unsupported_provider"):
        fetch_live_market_audit_report(
            provider="unknown_provider",
            provider_event_id="1",
            home_team="A",
            away_team="B",
        )


def test_fetch_live_requires_provider_event_id() -> None:
    with pytest.raises(MarketLiveFetchError, match="provider_event_id_required"):
        fetch_live_market_audit_report(
            provider="rapidapi_odds_feed",
            provider_event_id="",
            home_team="A",
            away_team="B",
        )


def test_fetch_live_uses_mocked_rapidapi_client() -> None:
    mock_payload = {
        "provider": "rapidapi_odds_feed",
        "event_id": "619963",
        "placing": "PREMATCH",
        "http_status": 200,
        "markets": [RAW_H2H_MARKET],
    }
    with patch(
        "core.market_live_fetch.fetch_event_markets",
        return_value=mock_payload,
    ) as fetch_mock:
        report = fetch_live_market_audit_report(
            provider="rapidapi_odds_feed",
            provider_event_id="619963",
            home_team="Norway",
            away_team="England",
            cache_ttl_seconds=0,
        )
    fetch_mock.assert_called_once_with("619963")
    assert report.audit_report["selected_event"]["event_id"] == "619963"
    assert report.audit_report["market_coverage_table"][0]["mapped_family"] == "h2h"


def test_fetch_live_missing_key_maps_safe_error() -> None:
    from core.providers.rapidapi_odds_feed_client import RapidApiOddsFeedClientError

    with patch(
        "core.market_live_fetch.fetch_event_markets",
        side_effect=RapidApiOddsFeedClientError("rapidapi_key_not_configured"),
    ):
        with pytest.raises(MarketLiveFetchError, match="rapidapi_key_not_configured"):
            fetch_live_market_audit_report(
                provider="rapidapi_odds_feed",
                provider_event_id="619963",
                home_team="Norway",
                away_team="England",
            )


def test_live_fetch_default_flag_false(monkeypatch: pytest.MonkeyPatch) -> None:
    import config

    monkeypatch.setattr(config, "MARKET_LIVE_PROVIDER_FETCH_ENABLED", False, raising=False)
    assert config.market_live_provider_fetch_enabled() is False
