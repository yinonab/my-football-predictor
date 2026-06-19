"""Phase 4L — Fixture state + match context diagnostics tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from api import main as api_main
from core.fixture_state import (
    FIXTURE_STATE_UNAVAILABLE,
    HOST_COUNTRY_AUTO_UNAVAILABLE,
    MATCH_ALREADY_COMPLETED,
    API_FOOTBALL_ACCOUNT_SUSPENDED,
    EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE,
    FixtureState,
    apply_fixture_state_rules,
)
from core.fixture_state_resolver import FixtureStateResolver, classify_api_football_error
from core.match_context_diagnostics import (
    build_match_context_diagnostics,
    detect_host_country_match,
    venue_country_from_city,
)
from core.venue_advantage import resolve_venue_advantage
from data.football_data import FootballDataClient


def _venue_ctx(state: FixtureState, **kwargs):
    return resolve_venue_advantage(
        home_team=state.home_team,
        away_team=state.away_team,
        fixture_state=state,
        venue_mode=kwargs.get("venue_mode"),
        neutral_ground=kwargs.get("neutral_ground", True),
        request_home_advantage=float(kwargs.get("request_home_advantage", 0.0)),
        request_venue_city=kwargs.get("request_venue_city"),
        request_altitude=int(kwargs.get("request_altitude", 0)),
    )


def _no_football_data() -> FootballDataClient:
    return FootballDataClient(api_key="", enabled=False)


@pytest.fixture(autouse=True)
def restore_fixture_resolver():
    original = api_main._fixture_state_resolver
    yield
    api_main._fixture_state_resolver = original


@pytest.fixture
def client() -> TestClient:
    return TestClient(api_main.app)


def test_fixture_state_completed_invalidates_prediction() -> None:
    state = apply_fixture_state_rules(
        FixtureState(
            home_team="Canada (קנדה)",
            away_team="Qatar (קטר)",
            fixture_status="completed",
            actual_home_goals=6,
            actual_away_goals=0,
            actual_score_available=True,
            source="manual_override",
            source_available=True,
        )
    )
    assert state.prediction_valid is False
    assert state.prediction_mode == "historical"
    assert MATCH_ALREADY_COMPLETED in state.warnings


def test_fixture_state_unknown_warns() -> None:
    state = apply_fixture_state_rules(
        FixtureState(
            home_team="Canada (קנדה)",
            away_team="Qatar (קטר)",
            fixture_status="unknown",
            source="unavailable",
            source_available=False,
        )
    )
    assert FIXTURE_STATE_UNAVAILABLE in state.warnings
    assert state.prediction_valid is True


def test_api_football_failure_classifies_suspended() -> None:
    assert classify_api_football_error(RuntimeError("Your account is suspended")) == (
        API_FOOTBALL_ACCOUNT_SUSPENDED
    )


def test_resolver_api_failure_returns_warnings_no_crash(tmp_path: Path) -> None:
    api = MagicMock()
    api.is_available = True
    api.search_national_team.return_value = {"id": 1}
    api.find_h2h_fixtures.side_effect = RuntimeError("Your account is suspended")

    resolver = FixtureStateResolver(
        api, overrides_path=tmp_path / "empty.json", football_data=_no_football_data()
    )
    (tmp_path / "empty.json").write_text(json.dumps({"fixtures": []}), encoding="utf-8")

    state = resolver.resolve("Canada (קנדה)", "Qatar (קטר)")
    assert state.fixture_status == "unknown"
    assert EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE in state.warnings
    assert API_FOOTBALL_ACCOUNT_SUSPENDED in state.warnings


def test_completed_override_includes_actual_score(tmp_path: Path) -> None:
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "home_team": "Canada",
                        "away_team": "Qatar",
                        "fixture_status": "completed",
                        "actual_home_goals": 6,
                        "actual_away_goals": 0,
                        "kickoff_time_utc": "2026-06-12T18:00:00+00:00",
                        "venue_city": "Toronto",
                        "venue_country": "Canada",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    api = MagicMock()
    api.is_available = False
    resolver = FixtureStateResolver(api, overrides_path=overrides, football_data=_no_football_data())
    state = resolver.resolve("Canada (קנדה)", "Qatar (קטר)")

    assert state.fixture_status == "completed"
    assert state.actual_home_goals == 6
    assert state.actual_away_goals == 0
    assert state.prediction_valid is False
    assert MATCH_ALREADY_COMPLETED in state.warnings


def test_host_country_detection_canada_toronto() -> None:
    host, candidate = detect_host_country_match(
        home_team="Canada (קנדה)",
        away_team="Qatar (קטר)",
        venue_city="Toronto",
        venue_country=None,
        neutral_ground_requested=True,
    )
    assert host is True
    assert candidate == "Canada"


def test_first_team_home_applies_advantage_toronto() -> None:
    import config

    state = FixtureState(
        home_team="Canada (קנדה)",
        away_team="Qatar (קטר)",
        fixture_status="unknown",
        source="unavailable",
        source_available=False,
        venue_city="Toronto",
        venue_country="Canada",
    )
    venue_adv = _venue_ctx(
        state,
        neutral_ground=False,
        request_venue_city="Toronto",
    )
    diag = build_match_context_diagnostics(
        fixture_state=state,
        neutral_ground_requested=False,
        venue_advantage=venue_adv,
        request_venue_city="Toronto",
        request_altitude=0,
    )
    assert diag.host_country_match is True
    assert diag.host_advantage_candidate_team == "Canada"
    assert diag.host_advantage_applied is True
    assert diag.home_advantage_power_delta == config.HOME_ADVANTAGE_POWER_POINTS
    assert diag.venue_mode == "first_team_home"


def test_venue_country_from_city() -> None:
    assert venue_country_from_city("Toronto") == "Canada"
    assert venue_country_from_city("Miami") == "USA"
    assert venue_country_from_city("Mexico City") == "Mexico"


def test_neutral_ground_backward_compatible(client: TestClient) -> None:
    payload = {
        "home_team": "Brazil",
        "away_team": "Morocco",
        "neutral_ground": True,
    }
    first = client.post("/api/predict", json=payload)
    assert first.status_code == 200
    body = first.json()
    assert "probabilities_1x2" in body
    assert "top_scores" in body
    assert body["match_context_diagnostics"]["neutral_ground_requested"] is True
    assert body["match_context_diagnostics"]["host_advantage_applied"] is False


def test_predict_includes_match_context_diagnostics(client: TestClient) -> None:
    resp = client.post(
        "/api/predict",
        json={"home_team": "Canada", "away_team": "Qatar", "neutral_ground": True},
    )
    assert resp.status_code == 200
    diag = resp.json()["match_context_diagnostics"]
    assert "fixture_status" in diag
    assert "prediction_valid" in diag
    assert "warnings" in diag
    assert "venue" in diag


def test_canada_qatar_unknown_fixture_warning(client: TestClient) -> None:
    api_main._fixture_state_resolver = FixtureStateResolver(
        MagicMock(is_available=False), football_data=_no_football_data()
    )
    resp = client.post(
        "/api/predict",
        json={"home_team": "Canada", "away_team": "Qatar", "neutral_ground": True},
    )
    assert resp.status_code == 200
    diag = resp.json()["match_context_diagnostics"]
    assert diag["fixture_status"] == "unknown"
    assert FIXTURE_STATE_UNAVAILABLE in diag["warnings"]


def test_canada_qatar_completed_6_0_not_valid_prediction(
    client: TestClient, tmp_path: Path
) -> None:
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "home_team": "Canada",
                        "away_team": "Qatar",
                        "fixture_status": "completed",
                        "actual_home_goals": 6,
                        "actual_away_goals": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    api_main._fixture_state_resolver = FixtureStateResolver(
        MagicMock(is_available=False),
        overrides_path=overrides,
        football_data=_no_football_data(),
    )
    resp = client.post(
        "/api/predict",
        json={"home_team": "Canada", "away_team": "Qatar", "neutral_ground": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    diag = body["match_context_diagnostics"]
    assert diag["prediction_valid"] is False
    assert diag["prediction_mode"] == "historical"
    assert diag["actual_score"] == {"home": 6, "away": 0}
    assert MATCH_ALREADY_COMPLETED in diag["warnings"]
    assert body["probabilities_1x2"]["home_win"] > 0


def test_canada_host_country_toronto_warning(client: TestClient, tmp_path: Path) -> None:
    overrides = tmp_path / "overrides.json"
    overrides.write_text(json.dumps({"fixtures": []}), encoding="utf-8")
    api_main._fixture_state_resolver = FixtureStateResolver(
        MagicMock(is_available=False),
        overrides_path=overrides,
        football_data=_no_football_data(),
    )
    resp = client.post(
        "/api/predict",
        json={
            "home_team": "Canada",
            "away_team": "Qatar",
            "neutral_ground": False,
            "venue_city": "Toronto",
            "home_advantage": 0.0,
        },
    )
    assert resp.status_code == 200
    diag = resp.json()["match_context_diagnostics"]
    assert diag["host_country_match"] is True
    assert diag["host_advantage_candidate_team"] == "Canada"
    assert diag["host_advantage_applied"] is True
    assert diag["home_advantage_power_delta"] > 0


def test_api_failure_predict_still_returns(client: TestClient) -> None:
    api = MagicMock()
    api.is_available = True
    api.search_national_team.return_value = {"id": 10}
    api.find_h2h_fixtures.side_effect = RuntimeError("connection failed")
    api_main._fixture_state_resolver = FixtureStateResolver(api, football_data=_no_football_data())

    resp = client.post(
        "/api/predict",
        json={"home_team": "Germany", "away_team": "Haiti", "neutral_ground": True},
    )
    assert resp.status_code == 200
    diag = resp.json()["match_context_diagnostics"]
    assert EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE in diag["warnings"]
    assert "probabilities_1x2" in resp.json()
