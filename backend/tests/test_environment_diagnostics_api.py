"""Phase W1+W2 — environment and provider diagnostics on /api/predict."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.recent_form_fusion import FUSION_SCHEMA_VERSION
from core.weather import WeatherSnapshot
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

BRAZIL = "Brazil (ברזיל)"
CANADA = "Canada (קנדה)"


def _sofascore_fusion_cache(tmp_path: Path) -> Path:
    payload = {
        "schema_version": FUSION_SCHEMA_VERSION,
        "last_updated_utc": "2026-06-20T06:00:00+00:00",
        "sources": {"sofascore": {"role": "recent_nt_matches"}},
        "refresh_summary": {"teams_requested": 1, "teams_with_coverage": 1, "errors": []},
        "teams": {
            BRAZIL: {
                "english_name": "Brazil",
                "provider_ids": {"sofascore": 4748},
                "fusion": {
                    "coverage_count": 10,
                    "last_10_finished": [{"date": "2026-05-01"}] * 10,
                    "source_mix": {"sofascore_recent_form": 8, "football_data_recent_form": 2},
                    "coverage_quality": "high",
                },
            },
            CANADA: {
                "english_name": "Canada",
                "provider_ids": {"sofascore": 4751},
                "fusion": {
                    "coverage_count": 10,
                    "last_10_finished": [{"date": "2026-05-01"}] * 10,
                    "source_mix": {"sofascore_recent_form": 7, "static": 3},
                    "coverage_quality": "medium",
                },
            },
        },
    }
    path = tmp_path / "recent_form_fusion_cache.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_predict_includes_environment_diagnostics() -> None:
    with patch("core.match_context.fetch_match_weather", return_value=None):
        response = client.post(
            "/api/predict",
            json={
                "home_team": CANADA,
                "away_team": "Bosnia (בוסניה)",
                "neutral_ground": True,
                "venue_city": "Mexico City",
                "match_date": "2026-06-15",
                "use_match_context": False,
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert "environment_diagnostics" in data
    env = data["environment_diagnostics"]
    assert env["venue_stadium"] == "Estadio Azteca"
    assert env["venue_altitude_m"] == 2240
    assert env["altitude_bucket"] == "very_high"
    assert env["automatic_altitude_adjustment_mode"] == "active_when_resolved"
    assert env["shadow_altitude_power_multiplier"] == 0.96


def test_auto_altitude_affects_prediction_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with patch("core.match_context.fetch_match_weather", return_value=None):
        monkeypatch.setattr(
            "core.venue_environment.config.AUTO_STADIUM_ALTITUDE_AFFECT_PREDICTION",
            False,
        )
        baseline = client.post(
            "/api/predict",
            json={
                "home_team": CANADA,
                "away_team": "Bosnia (בוסניה)",
                "neutral_ground": True,
                "use_match_context": False,
            },
        )
        with_venue = client.post(
            "/api/predict",
            json={
                "home_team": CANADA,
                "away_team": "Bosnia (בוסניה)",
                "neutral_ground": True,
                "venue_city": "Guadalajara",
                "use_match_context": False,
            },
        )
    assert baseline.status_code == 200
    assert with_venue.status_code == 200
    b = baseline.json()
    w = with_venue.json()
    assert b["probabilities_1x2"] == w["probabilities_1x2"]
    assert b["home_xg"] == w["home_xg"]
    assert w["environment_diagnostics"]["altitude_bucket"] == "high"

    monkeypatch.setattr(
        "core.venue_environment.config.AUTO_STADIUM_ALTITUDE_AFFECT_PREDICTION",
        True,
    )
    with patch("core.match_context.fetch_match_weather", return_value=None):
        low_venue = client.post(
            "/api/predict",
            json={
                "home_team": CANADA,
                "away_team": "Bosnia (בוסניה)",
                "neutral_ground": True,
                "venue_city": "Miami",
                "use_match_context": False,
            },
        )
        high_venue = client.post(
            "/api/predict",
            json={
                "home_team": CANADA,
                "away_team": "Bosnia (בוסניה)",
                "neutral_ground": True,
                "venue_city": "Guadalajara",
                "use_match_context": False,
            },
        )
    assert low_venue.status_code == 200
    assert high_venue.status_code == 200
    assert (
        high_venue.json()["home_power"]
        < low_venue.json()["home_power"]
    )


def test_manual_altitude_applied_preserved() -> None:
    with patch("core.match_context.fetch_match_weather", return_value=None):
        low = client.post(
            "/api/predict",
            json={
                "home_team": CANADA,
                "away_team": "Bosnia (בוסניה)",
                "neutral_ground": True,
                "altitude": 0,
                "use_match_context": False,
            },
        )
        high = client.post(
            "/api/predict",
            json={
                "home_team": CANADA,
                "away_team": "Bosnia (בוסניה)",
                "neutral_ground": True,
                "altitude": 2000,
                "use_match_context": False,
            },
        )
    assert low.status_code == 200
    assert high.status_code == 200
    low_data = low.json()
    high_data = high.json()
    assert low_data["environment_diagnostics"]["manual_altitude_applied"] is False
    assert high_data["environment_diagnostics"]["manual_altitude_applied"] is True
    assert high_data["match_context_diagnostics"]["altitude_applied"] is True
    assert high_data["home_power"] < low_data["home_power"]


def test_use_match_context_false_weather_disabled() -> None:
    with patch("core.match_context.fetch_match_weather") as mock_weather:
        response = client.post(
            "/api/predict",
            json={
                "home_team": CANADA,
                "away_team": "Bosnia (בוסניה)",
                "neutral_ground": True,
                "venue_city": "Miami",
                "match_date": "2026-06-15",
                "use_match_context": False,
            },
        )
    assert response.status_code == 200
    mock_weather.assert_not_called()
    env = response.json()["environment_diagnostics"]
    assert env["weather_source"] == "disabled"
    assert env["weather_adjustment_mode"] == "disabled"


def test_mocked_weather_populates_diagnostics() -> None:
    weather = WeatherSnapshot(
        city="Miami",
        match_date="2026-06-15",
        temperature_c=31.0,
        rain_mm=2.5,
        summary_he="Miami: 31°C",
        fetched_at="2026-06-15T12:00:00+00:00",
    )
    with patch("core.match_context.fetch_match_weather", return_value=weather):
        response = client.post(
            "/api/predict",
            json={
                "home_team": CANADA,
                "away_team": "Bosnia (בוסניה)",
                "neutral_ground": True,
                "venue_city": "Miami",
                "match_date": "2026-06-15",
                "use_match_context": True,
            },
        )
    assert response.status_code == 200
    env = response.json()["environment_diagnostics"]
    assert env["weather_source"] == "open-meteo"
    assert env["temperature_c"] == 31.0
    assert env["precipitation_mm"] == 2.5
    assert env["weather_fetched_at"] == "2026-06-15T12:00:00+00:00"


def test_weather_fetch_failure_still_predicts() -> None:
    with patch("core.match_context.fetch_match_weather", return_value=None):
        response = client.post(
            "/api/predict",
            json={
                "home_team": CANADA,
                "away_team": "Bosnia (בוסניה)",
                "neutral_ground": True,
                "venue_city": "Miami",
                "match_date": "2026-06-15",
                "use_match_context": True,
            },
        )
    assert response.status_code == 200
    env = response.json()["environment_diagnostics"]
    assert env["weather_source"] == "unavailable"
    assert "WEATHER_FETCH_UNAVAILABLE" in env["environment_warnings"]


def test_recent_form_provider_diagnostics_sofascore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = _sofascore_fusion_cache(tmp_path)
    monkeypatch.setattr("core.recent_form_fusion.FUSION_CACHE_PATH", cache_path)
    with patch("core.match_context.fetch_match_weather", return_value=None):
        response = client.post(
            "/api/predict",
            json={
                "home_team": BRAZIL,
                "away_team": CANADA,
                "neutral_ground": True,
                "use_match_context": False,
            },
        )
    assert response.status_code == 200
    rf = response.json()["recent_form_provider_diagnostics"]
    assert rf["primary_provider"] == "sofascore_recent_form"
    assert rf["source_mix"].get("sofascore_recent_form", 0) > 0
    assert rf["cache_last_updated_utc"] == "2026-06-20T06:00:00+00:00"
    assert BRAZIL in rf["teams_with_provider_ids"]
