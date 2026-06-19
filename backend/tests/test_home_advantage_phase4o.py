"""Phase 4O — Home advantage engine + venue mode tests (offline)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from api import main as api_main
from core.fixture_state import (
    HOST_COUNTRY_AUTO_UNAVAILABLE,
    MATCH_ALREADY_COMPLETED,
    FixtureState,
    apply_fixture_state_rules,
)
from core.fixture_state_resolver import FixtureStateResolver
from core.match_context_diagnostics import build_match_context_diagnostics
from core.venue_advantage import (
    resolve_host_country_advantage_team,
    resolve_venue_advantage,
    resolve_venue_mode,
)
from data.football_data import FootballDataClient


@pytest.fixture
def client() -> TestClient:
    return TestClient(api_main.app)


@pytest.fixture(autouse=True)
def restore_fixture_resolver():
    original = api_main._fixture_state_resolver
    yield
    api_main._fixture_state_resolver = original


def _no_fd() -> FootballDataClient:
    return FootballDataClient(api_key="", enabled=False)


def test_resolve_venue_mode_backward_compat() -> None:
    assert resolve_venue_mode(venue_mode=None, neutral_ground=True) == "neutral"
    assert resolve_venue_mode(venue_mode=None, neutral_ground=False) == "first_team_home"
    assert resolve_venue_mode(venue_mode="second_team_home", neutral_ground=True) == (
        "second_team_home"
    )


def test_neutral_baseline_no_advantage(client: TestClient) -> None:
    api_main._fixture_state_resolver = FixtureStateResolver(
        MagicMock(is_available=False), football_data=_no_fd()
    )
    resp = client.post(
        "/api/predict",
        json={
            "home_team": "USA",
            "away_team": "Australia",
            "neutral_ground": True,
            "venue_mode": "neutral",
        },
    )
    assert resp.status_code == 200
    diag = resp.json()["match_context_diagnostics"]
    assert diag["venue_mode"] == "neutral"
    assert diag["home_advantage_team"] == "none"
    assert diag["host_advantage_applied"] is False
    assert diag["home_advantage_power_delta"] == 0.0


def test_first_team_home_increases_home_win(client: TestClient) -> None:
    api_main._fixture_state_resolver = FixtureStateResolver(
        MagicMock(is_available=False), football_data=_no_fd()
    )
    neutral = client.post(
        "/api/predict",
        json={"home_team": "USA", "away_team": "Australia", "neutral_ground": True},
    ).json()
    home_adv = client.post(
        "/api/predict",
        json={
            "home_team": "USA",
            "away_team": "Australia",
            "venue_mode": "first_team_home",
            "neutral_ground": True,
        },
    ).json()
    nd = neutral["match_context_diagnostics"]
    hd = home_adv["match_context_diagnostics"]
    assert hd["home_advantage_team"] == "home"
    assert hd["host_advantage_applied"] is True
    assert hd["home_advantage_power_delta"] == config.HOME_ADVANTAGE_POWER_POINTS
    assert home_adv["home_power"] > neutral["home_power"]
    assert home_adv["home_xg"] >= neutral["home_xg"]
    assert (
        home_adv["probabilities_1x2"]["home_win"]
        >= neutral["probabilities_1x2"]["home_win"]
    )
    assert (
        home_adv["home_power"] > neutral["home_power"]
        or home_adv["probabilities_1x2"]["home_win"]
        > neutral["probabilities_1x2"]["home_win"]
    )


def test_second_team_home_increases_away_win(client: TestClient) -> None:
    api_main._fixture_state_resolver = FixtureStateResolver(
        MagicMock(is_available=False), football_data=_no_fd()
    )
    neutral = client.post(
        "/api/predict",
        json={"home_team": "USA", "away_team": "Australia", "neutral_ground": True},
    ).json()
    away_home = client.post(
        "/api/predict",
        json={
            "home_team": "USA",
            "away_team": "Australia",
            "venue_mode": "second_team_home",
            "neutral_ground": True,
        },
    ).json()
    diag = away_home["match_context_diagnostics"]
    assert diag["home_advantage_team"] == "away"
    assert diag["host_advantage_applied"] is True
    assert away_home["away_power"] > neutral["away_power"]
    assert away_home["away_xg"] >= neutral["away_xg"]
    assert (
        away_home["probabilities_1x2"]["away_win"]
        >= neutral["probabilities_1x2"]["away_win"]
    )
    assert (
        away_home["away_power"] > neutral["away_power"]
        or away_home["probabilities_1x2"]["away_win"]
        > neutral["probabilities_1x2"]["away_win"]
    )
    assert away_home["home_team"] == "USA"
    assert away_home["away_team"] == "Australia"


def test_neutral_ground_false_maps_first_team_home(client: TestClient) -> None:
    api_main._fixture_state_resolver = FixtureStateResolver(
        MagicMock(is_available=False), football_data=_no_fd()
    )
    resp = client.post(
        "/api/predict",
        json={"home_team": "Germany", "away_team": "Haiti", "neutral_ground": False},
    )
    diag = resp.json()["match_context_diagnostics"]
    assert diag["venue_mode"] == "first_team_home"
    assert diag["host_advantage_applied"] is True


def test_scoreline_decision_uses_updated_probabilities(client: TestClient) -> None:
    api_main._fixture_state_resolver = FixtureStateResolver(
        MagicMock(is_available=False), football_data=_no_fd()
    )
    neutral = client.post(
        "/api/predict",
        json={"home_team": "USA", "away_team": "Australia", "neutral_ground": True},
    ).json()
    home = client.post(
        "/api/predict",
        json={"home_team": "USA", "away_team": "Australia", "venue_mode": "first_team_home"},
    ).json()
    assert "scoreline_decision" in home
    assert "top_scores" in home
    assert home["scoreline_decision"]["favorite_outcome"] in (
        "home_win",
        "draw",
        "away_win",
    )
    if (
        home["scoreline_decision"]["primary_predicted_score"]
        and neutral["scoreline_decision"]["primary_predicted_score"]
    ):
        # Primary may stay 1-0; probabilities must move
        assert (
            home["probabilities_1x2"]["home_win"]
            >= neutral["probabilities_1x2"]["home_win"]
        )


def test_completed_match_diagnostics_still_show_venue_mode(client: TestClient, tmp_path) -> None:
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        '{"fixtures":[{"home_team":"Canada","away_team":"Qatar",'
        '"fixture_status":"completed","actual_home_goals":6,"actual_away_goals":0}]}',
        encoding="utf-8",
    )
    api_main._fixture_state_resolver = FixtureStateResolver(
        MagicMock(is_available=False),
        football_data=_no_fd(),
        overrides_path=overrides,
    )
    resp = client.post(
        "/api/predict",
        json={
            "home_team": "Canada",
            "away_team": "Qatar",
            "venue_mode": "first_team_home",
        },
    )
    body = resp.json()
    diag = body["match_context_diagnostics"]
    assert diag["prediction_valid"] is False
    assert diag["venue_mode"] == "first_team_home"
    assert MATCH_ALREADY_COMPLETED in diag["warnings"]


def test_host_country_auto_with_venue_applies(client: TestClient) -> None:
    api_main._fixture_state_resolver = FixtureStateResolver(
        MagicMock(is_available=False), football_data=_no_fd()
    )
    resp = client.post(
        "/api/predict",
        json={
            "home_team": "USA",
            "away_team": "Australia",
            "venue_mode": "host_country_auto",
            "venue_city": "Miami",
        },
    )
    diag = resp.json()["match_context_diagnostics"]
    assert diag["venue_mode"] == "host_country_auto"
    assert diag["home_advantage_team"] == "home"
    assert diag["host_advantage_applied"] is True


def test_host_country_auto_without_venue_warns() -> None:
    state = FixtureState(
        home_team="USA",
        away_team="Australia",
        fixture_status="scheduled",
        source="unavailable",
        source_available=False,
    )
    ctx = resolve_venue_advantage(
        home_team=state.home_team,
        away_team=state.away_team,
        fixture_state=state,
        venue_mode="host_country_auto",
        neutral_ground=True,
        request_home_advantage=0.0,
        request_venue_city=None,
        request_altitude=0,
    )
    assert ctx.home_advantage_team == "none"
    assert ctx.home_advantage_applied is False
    assert HOST_COUNTRY_AUTO_UNAVAILABLE in ctx.warnings


def test_host_country_auto_canada_toronto() -> None:
    side, candidate, matched, warnings = resolve_host_country_advantage_team(
        home_team="Canada",
        away_team="Qatar",
        venue_city="Toronto",
        venue_country=None,
    )
    assert matched is True
    assert side == "home"
    assert candidate == "Canada"
    assert not warnings


def test_completed_fixture_context_diag() -> None:
    state = apply_fixture_state_rules(
        FixtureState(
            home_team="Canada",
            away_team="Qatar",
            fixture_status="completed",
            actual_home_goals=6,
            actual_away_goals=0,
            actual_score_available=True,
            source="manual_override",
            source_available=True,
        )
    )
    venue_adv = resolve_venue_advantage(
        home_team=state.home_team,
        away_team=state.away_team,
        fixture_state=state,
        venue_mode="neutral",
        neutral_ground=True,
        request_home_advantage=0.0,
        request_venue_city=None,
        request_altitude=0,
    )
    diag = build_match_context_diagnostics(
        fixture_state=state,
        neutral_ground_requested=True,
        venue_advantage=venue_adv,
        request_venue_city=None,
        request_altitude=0,
    )
    assert diag.prediction_valid is False
    assert diag.venue_mode == "neutral"
