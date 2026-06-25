"""Market diagnostics and multi-bookmaker odds parsing."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.market_diagnostics import build_market_diagnostics
from core.odds_ensemble import (
    BookmakerOddsLine,
    OddsClient,
    OddsLookupResult,
    OddsMarketFetch,
    _consensus_from_bookmakers,
)
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_consensus_averages_bookmakers() -> None:
    lines = [
        BookmakerOddsLine(
            id="a",
            display_name="A",
            region="eu",
            home_decimal_odds=2.0,
            draw_decimal_odds=3.0,
            away_decimal_odds=4.0,
            implied_1x2_percent={"home_win": 50.0, "draw": 33.33, "away_win": 25.0},
        ),
        BookmakerOddsLine(
            id="b",
            display_name="B",
            region="uk",
            home_decimal_odds=2.2,
            draw_decimal_odds=3.2,
            away_decimal_odds=3.8,
            implied_1x2_percent={"home_win": 45.45, "draw": 31.25, "away_win": 26.32},
        ),
    ]
    consensus = _consensus_from_bookmakers(lines)
    assert consensus is not None
    assert abs(sum(consensus.values()) - 100.0) < 0.2


def test_build_market_diagnostics_not_configured() -> None:
    client_mock = OddsClient(api_key="")
    diag = build_market_diagnostics(
        home_team="Brazil",
        away_team="France",
        odds_client=client_mock,
    )
    assert diag.status == "not_configured"
    assert diag.available is False


def test_build_market_diagnostics_with_fetch() -> None:
    fetch = OddsMarketFetch(
        sport_key="soccer_fifa_world_cup",
        bookmakers=[
            BookmakerOddsLine(
                id="bet365",
                display_name="Bet365",
                region="eu",
                home_decimal_odds=2.5,
                draw_decimal_odds=3.2,
                away_decimal_odds=2.9,
                implied_1x2_percent={
                    "home_win": 40.0,
                    "draw": 31.25,
                    "away_win": 34.48,
                },
            )
        ],
        consensus_1x2_percent={
            "home_win": 40.0,
            "draw": 31.25,
            "away_win": 28.75,
        },
    )
    diag = build_market_diagnostics(
        home_team="Brazil",
        away_team="France",
        odds_client=OddsClient(api_key="test"),
        fetch=fetch,
    )
    assert diag.available is True
    assert diag.status == "ok"
    assert len(diag.bookmakers) == 1
    assert diag.bookmakers[0]["display_name"] == "Bet365"


def test_predict_includes_market_diagnostics_block() -> None:
    fetch = OddsMarketFetch(
        sport_key="soccer_fifa_world_cup",
        bookmakers=[
            BookmakerOddsLine(
                id="pinnacle",
                display_name="Pinnacle",
                region="eu",
                home_decimal_odds=2.1,
                draw_decimal_odds=3.4,
                away_decimal_odds=3.5,
                implied_1x2_percent={
                    "home_win": 47.62,
                    "draw": 29.41,
                    "away_win": 28.57,
                },
            )
        ],
        consensus_1x2_percent={
            "home_win": 47.6,
            "draw": 29.4,
            "away_win": 23.0,
        },
    )
    mock_client = MagicMock()
    mock_client.is_available = True
    mock_client.lookup_match_market.return_value = OddsLookupResult(
        fetch=fetch,
        status="ok",
        odds_key_configured=True,
    )
    mock_client.fetch_match_market.return_value = fetch
    mock_client.fetch_match_odds.return_value = fetch.legacy_consensus_percent()

    with patch("api.main._odds_client", mock_client):
        response = client.post(
            "/api/predict",
            json={
                "home_team": "Brazil (ברזיל)",
                "away_team": "France (צרפת)",
                "neutral_ground": True,
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert "market_diagnostics" in data
    market = data["market_diagnostics"]
    assert market["available"] is True
    assert market["bookmakers"][0]["display_name"] == "Pinnacle"
    assert data["probability_diagnostics"]["odds_available"] is True
