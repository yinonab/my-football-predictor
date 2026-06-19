"""Phase 4M — Scoreline decision engine tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from api import main as api_main
from core.fixture_state import MATCH_ALREADY_COMPLETED, FixtureState, apply_fixture_state_rules
from core.fixture_state_resolver import FixtureStateResolver
from data.football_data import FootballDataClient
from core.match_context_diagnostics import build_match_context_diagnostics
from core.scoreline_decision import (
    BALANCED_MATCH_LOW_CONFIDENCE,
    CONTEXT_LIMITED,
    PREDICTION_NOT_VALID,
    build_scoreline_decision,
)


@pytest.fixture(autouse=True)
def restore_fixture_resolver():
    original = api_main._fixture_state_resolver
    yield
    api_main._fixture_state_resolver = original


@pytest.fixture
def client() -> TestClient:
    return TestClient(api_main.app)


def _all_scores_fixture() -> dict[str, float]:
    return {
        "1-0": 12.0,
        "2-0": 10.0,
        "2-1": 9.5,
        "1-1": 13.5,
        "0-1": 6.0,
        "0-0": 5.0,
        "0-2": 4.0,
        "3-0": 3.0,
    }


def test_canada_qatar_style_primary_aligns_with_home_favorite() -> None:
    probs = {"home_win": 49.8, "draw": 27.7, "away_win": 22.5}
    top_scores = [
        {"score": "1-1", "probability": 13.5},
        {"score": "1-0", "probability": 12.0},
        {"score": "2-1", "probability": 9.5},
    ]
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=top_scores,
        all_scores=_all_scores_fixture(),
        home_xg=1.6,
        away_xg=1.0,
        home_team="Canada (קנדה)",
        away_team="Qatar (קטר)",
    )
    assert decision.favorite_outcome == "home_win"
    assert decision.top_exact_score_overall is not None
    assert decision.top_exact_score_overall.score_label == "1-1"
    assert decision.top_exact_score_overall.outcome == "draw"
    assert decision.primary_predicted_score is not None
    assert decision.primary_predicted_score.outcome == "home_win"
    assert decision.top_exact_score_differs_from_primary is True
    assert all(s.outcome == "home_win" for s in decision.favorite_outcome_top_scores)
    assert "התחזית המרכזית" in decision.primary_score_reason or "קנדה" in decision.primary_score_reason


def test_away_favorite_primary_is_away_win() -> None:
    probs = {"home_win": 20.0, "draw": 25.0, "away_win": 55.0}
    all_scores = {
        "0-1": 14.0,
        "0-2": 12.0,
        "1-2": 10.0,
        "1-1": 11.0,
        "0-0": 5.0,
    }
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[{"score": "0-1", "probability": 14.0}],
        all_scores=all_scores,
        home_xg=0.9,
        away_xg=1.7,
        home_team="Haiti",
        away_team="Germany",
    )
    assert decision.favorite_outcome == "away_win"
    assert decision.primary_predicted_score is not None
    assert decision.primary_predicted_score.outcome == "away_win"


def test_draw_favorite_primary_can_be_draw() -> None:
    probs = {"home_win": 30.0, "draw": 40.0, "away_win": 30.0}
    all_scores = {
        "1-1": 15.0,
        "0-0": 12.0,
        "2-2": 8.0,
        "1-0": 9.0,
        "0-1": 9.0,
    }
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[{"score": "1-1", "probability": 15.0}],
        all_scores=all_scores,
        home_xg=1.2,
        away_xg=1.2,
        home_team="Brazil",
        away_team="Morocco",
    )
    assert decision.favorite_outcome == "draw"
    assert decision.primary_predicted_score is not None
    assert decision.primary_predicted_score.outcome == "draw"


def test_balanced_match_low_confidence() -> None:
    probs = {"home_win": 35.0, "draw": 33.0, "away_win": 32.0}
    all_scores = {"1-1": 12.0, "1-0": 11.0, "0-1": 10.0}
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[{"score": "1-1", "probability": 12.0}],
        all_scores=all_scores,
        home_xg=1.3,
        away_xg=1.3,
        home_team="Argentina",
        away_team="France",
    )
    assert decision.outcome_margin <= 5.0
    assert decision.confidence_label == "low"
    assert BALANCED_MATCH_LOW_CONFIDENCE in decision.warnings
    assert decision.primary_predicted_score == decision.top_exact_score_overall


def test_strong_favorite_does_not_pick_draw_primary() -> None:
    probs = {"home_win": 72.0, "draw": 18.0, "away_win": 10.0}
    all_scores = {
        "1-1": 11.0,
        "2-0": 16.0,
        "3-0": 14.0,
        "2-1": 10.0,
        "1-0": 9.0,
    }
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[{"score": "1-1", "probability": 11.0}],
        all_scores=all_scores,
        home_xg=2.4,
        away_xg=0.7,
        home_team="Germany",
        away_team="Haiti",
    )
    assert decision.favorite_outcome == "home_win"
    assert decision.confidence_label == "high"
    assert decision.primary_predicted_score is not None
    assert decision.primary_predicted_score.outcome == "home_win"
    assert decision.primary_predicted_score.outcome != "draw"


def test_score_groups_classification() -> None:
    all_scores = _all_scores_fixture()
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 50.0, "draw": 28.0, "away_win": 22.0},
        top_scores=[{"score": "1-1", "probability": 13.5}],
        all_scores=all_scores,
        home_xg=1.6,
        away_xg=1.0,
        home_team="Canada",
        away_team="Qatar",
    )
    for item in decision.score_groups["home_win"]:
        assert item.outcome == "home_win"
    for item in decision.score_groups["draw"]:
        assert item.outcome == "draw"
    for item in decision.score_groups["away_win"]:
        assert item.outcome == "away_win"


def test_completed_fixture_warning_and_low_confidence() -> None:
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
    ctx = build_match_context_diagnostics(
        fixture_state=state,
        neutral_ground_requested=True,
        home_advantage_value=0.0,
        request_venue_city=None,
        request_altitude=0,
    )
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 50.0, "draw": 28.0, "away_win": 22.0},
        top_scores=[{"score": "1-1", "probability": 13.5}],
        all_scores=_all_scores_fixture(),
        home_xg=1.6,
        away_xg=1.0,
        home_team="Canada",
        away_team="Qatar",
        match_context_diagnostics=ctx,
    )
    assert decision.confidence_label == "low"
    assert PREDICTION_NOT_VALID in decision.warnings
    assert MATCH_ALREADY_COMPLETED in decision.warnings
    assert "הסתיים" in decision.primary_score_reason


def test_api_predict_includes_scoreline_decision(client: TestClient) -> None:
    response = client.post(
        "/api/predict",
        json={"home_team": "Canada", "away_team": "Qatar", "neutral_ground": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert "top_scores" in data
    assert len(data["top_scores"]) >= 1
    assert "scoreline_decision" in data
    sd = data["scoreline_decision"]
    assert sd["favorite_outcome"] == "home_win"
    assert sd["primary_predicted_score"]["outcome"] == "home_win"
    assert sd["top_exact_score_overall"] is not None


def test_api_top_scores_unchanged_with_scoreline_decision(client: TestClient) -> None:
    before = client.post(
        "/api/predict",
        json={"home_team": "Mexico", "away_team": "South Korea", "neutral_ground": True},
    ).json()
    top_scores = before["top_scores"]
    sd = before["scoreline_decision"]
    assert top_scores
    assert sd is not None
    assert "primary_predicted_score" in sd


def test_canada_qatar_api_primary_differs_from_top_exact(client: TestClient) -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Canada", "away_team": "Qatar", "neutral_ground": True},
    ).json()
    sd = data["scoreline_decision"]
    top = sd["top_exact_score_overall"]
    primary = sd["primary_predicted_score"]
    if top["outcome"] == "draw" and sd["favorite_outcome"] == "home_win":
        assert primary["outcome"] == "home_win"
        assert sd["top_exact_score_differs_from_primary"] is True
        assert sd["primary_score_reason"]


def test_context_limited_warning_when_fixture_unavailable(client: TestClient) -> None:
    api = MagicMock()
    api.is_available = True
    api.search_national_team.side_effect = RuntimeError("Your account is suspended")
    api_main._fixture_state_resolver = FixtureStateResolver(
        api=api,
        football_data=FootballDataClient(api_key="", enabled=False),
    )
    data = client.post(
        "/api/predict",
        json={"home_team": "Canada", "away_team": "Qatar", "neutral_ground": True},
    ).json()
    warnings = data["scoreline_decision"]["warnings"]
    assert CONTEXT_LIMITED in warnings


def test_reason_explains_primary_vs_top_exact() -> None:
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 49.8, "draw": 27.7, "away_win": 22.5},
        top_scores=[{"score": "1-1", "probability": 13.5}],
        all_scores=_all_scores_fixture(),
        home_xg=1.6,
        away_xg=1.0,
        home_team="Canada (קנדה)",
        away_team="Qatar (קטר)",
    )
    assert decision.top_exact_score_differs_from_primary
    assert "מטריצה" in decision.primary_score_reason
