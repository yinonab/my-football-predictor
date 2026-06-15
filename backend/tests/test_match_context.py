"""Match context gatherer tests (no live API)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.match_context import MatchContextGatherer
from core.weather import WeatherSnapshot


def test_gather_disabled() -> None:
    api = MagicMock()
    api.is_available = False
    g = MatchContextGatherer(api)
    info = g.gather("Spain (ספרד)", "France (צרפת)", enabled=False)
    assert info.data_source == "disabled"


def test_gather_with_venue_weather_only() -> None:
    api = MagicMock()
    api.is_available = False
    g = MatchContextGatherer(api)

    weather = WeatherSnapshot(
        city="Miami",
        match_date="2026-06-15",
        temperature_c=31.0,
        rain_mm=0.0,
        summary_he="Miami: 31°C, חום",
    )
    with patch("core.match_context.fetch_match_weather", return_value=weather):
        info = g.gather(
            "Spain (ספרד)",
            "France (צרפת)",
            match_date="2026-06-15",
            venue_city="Miami",
        )

    assert info.venue_city == "Miami"
    assert info.weather_temp_c == 31.0
    assert info.data_source == "weather"


def test_gather_rest_from_api_cache() -> None:
    api = MagicMock()
    api.is_available = True
    api.search_national_team.return_value = {"id": 9}
    madrid_fx = {
        "fixture": {"date": "2026-06-10T18:00:00+00:00", "venue": {"city": "Madrid"}},
        "league": {"round": "Group A", "name": "World Cup"},
    }
    boston_fx = {
        "fixture": {"date": "2026-06-11T18:00:00+00:00", "venue": {"city": "Boston"}},
        "league": {"round": "Group A", "name": "World Cup"},
    }
    api.fetch_last_finished_fixture.side_effect = [madrid_fx, boston_fx]
    api.find_scheduled_h2h_fixture.return_value = None
    api.extract_fixture_context.side_effect = lambda fx: {
        "date": (fx.get("fixture", {}).get("date") or "")[:10],
        "city": fx.get("fixture", {}).get("venue", {}).get("city"),
        "round": fx.get("league", {}).get("round"),
        "league": fx.get("league", {}).get("name"),
    }

    g = MatchContextGatherer(api)
    with patch("core.match_context.fetch_match_weather", return_value=None):
        with patch("core.match_context._cache_get_team", return_value=None):
            with patch("core.match_context._cache_put_team"):
                info = g.gather(
                    "Spain (ספרד)",
                    "France (צרפת)",
                    match_date="2026-06-15",
                    venue_city="Miami",
                )

    assert info.home_rest_days == 5
    assert info.away_rest_days == 4
    assert info.home_last_city == "Madrid"
    assert info.away_last_city == "Boston"
    assert info.away_travel_km is not None
    assert info.away_travel_km >= 2000
