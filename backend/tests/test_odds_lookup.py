"""Odds API lookup, cache, and quota diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.odds_ensemble import OddsClient, _EVENTS_CACHE


@pytest.fixture(autouse=True)
def _clear_events_cache() -> None:
    _EVENTS_CACHE.clear()


def test_lookup_uses_cached_events_for_second_match() -> None:
    client = OddsClient(api_key="test-key")
    events = [
        {
            "home_team": "Tunisia",
            "away_team": "Netherlands",
            "bookmakers": [
                {
                    "key": "bet365",
                    "title": "Bet365",
                    "region": "eu",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Tunisia", "price": 8.0},
                                {"name": "Draw", "price": 5.0},
                                {"name": "Netherlands", "price": 1.35},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = events
    mock_response.headers = {"x-requests-remaining": "42"}
    mock_response.raise_for_status = MagicMock()

    with patch("core.odds_ensemble.requests.get", return_value=mock_response) as get:
        first = client.lookup_match_market("Tunisia (תוניסיה)", "Netherlands (הולנד)")
        second = client.lookup_match_market("Tunisia (תוניסיה)", "Netherlands (הולנד)")

    assert first.status == "ok"
    assert second.status == "ok"
    assert get.call_count == 1


def test_lookup_reports_quota_exceeded() -> None:
    client = OddsClient(api_key="test-key")
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Usage quota has been exceeded"
    mock_response.headers = {}

    with patch("core.odds_ensemble.requests.get", return_value=mock_response):
        result = client.lookup_match_market("Germany", "Ecuador")

    assert result.status == "quota_exceeded"
    assert result.odds_key_configured is True


def test_lookup_swapped_home_away_event() -> None:
    client = OddsClient(api_key="test-key")
    events = [
        {
            "home_team": "Ecuador",
            "away_team": "Germany",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "title": "Pinnacle",
                    "region": "eu",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Ecuador", "price": 4.5},
                                {"name": "Draw", "price": 3.8},
                                {"name": "Germany", "price": 1.75},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = events
    mock_response.headers = {}
    mock_response.raise_for_status = MagicMock()

    with patch("core.odds_ensemble.requests.get", return_value=mock_response):
        result = client.lookup_match_market("Germany (גרמניה)", "Ecuador (אקוודור)")

    assert result.status == "ok"
    assert result.fetch is not None
    assert result.fetch.consensus_1x2_percent is not None
    assert result.fetch.consensus_1x2_percent["home_win"] > 50
