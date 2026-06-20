"""Phase 4Q — Scoreline realism and representative primary score tests."""

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
from core.fixture_state import MATCH_ALREADY_COMPLETED
from core.fixture_state_resolver import FixtureStateResolver
from core.scoreline_decision import build_scoreline_decision
from data.football_data import FootballDataClient


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


def _dense_matrix_from_xg(home_xg: float, away_xg: float) -> dict[str, float]:
    from core.math_engine import AdvancedDixonColesEngine

    engine = AdvancedDixonColesEngine()
    result = engine.generate_match_prediction(
        power_home=700,
        power_away=650,
        advantage=0,
        max_goals=8,
        include_all_scores=True,
        top_n=15,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )
    return result["all_scores"]


def test_top_scores_shape_unchanged(client: TestClient) -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Netherlands", "away_team": "Sweden", "neutral_ground": True},
    ).json()
    top = data["top_scores"]
    assert len(top) >= 1
    item = top[0]
    assert set(item.keys()) == {"score", "probability", "explanation"}


def test_high_favorite_xg_considers_four_goal_primary() -> None:
    all_scores = _dense_matrix_from_xg(4.4, 0.9)
    probs = {"home_win": 78.6, "draw": 12.1, "away_win": 9.3}
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[{"score": k, "probability": v} for k, v in list(all_scores.items())[:3]],
        all_scores=all_scores,
        home_xg=4.4,
        away_xg=0.9,
        home_team="Brazil",
        away_team="Haiti",
    )
    assert decision.primary_predicted_score is not None
    assert decision.primary_predicted_score.home_goals >= 3
    assert decision.representative_score_method == "representative_v1_gate"
    assert decision.favorite_goal_band_probabilities.get("favorite_4_plus", 0) > 0


def test_underdog_scoring_considered_when_xg_high() -> None:
    all_scores = _dense_matrix_from_xg(1.6, 1.0)
    probs = {"home_win": 49.3, "draw": 27.8, "away_win": 22.9}
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[{"score": "1-1", "probability": 13.0}],
        all_scores=all_scores,
        home_xg=1.6,
        away_xg=1.0,
        home_team="Switzerland",
        away_team="Canada",
    )
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.outcome == "home_win"
    assert primary.score_label in {"2-0", "2-1", "1-0", "3-0"}


def test_moderate_favorite_not_always_one_nil() -> None:
    all_scores = _dense_matrix_from_xg(1.9, 0.8)
    probs = {"home_win": 61.9, "draw": 23.5, "away_win": 14.6}
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[{"score": "1-0", "probability": 12.0}],
        all_scores=all_scores,
        home_xg=1.9,
        away_xg=0.8,
        home_team="Netherlands",
        away_team="Sweden",
    )
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.home_goals >= 2 or primary.score_label == "1-0"


def test_away_favorite_moderate_considers_multi_goal() -> None:
    all_scores = _dense_matrix_from_xg(0.9, 1.7)
    probs = {"home_win": 18.0, "draw": 26.3, "away_win": 55.7}
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[{"score": "0-1", "probability": 12.0}],
        all_scores=all_scores,
        home_xg=0.9,
        away_xg=1.7,
        home_team="Tunisia",
        away_team="Japan",
    )
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.outcome == "away_win"
    assert primary.score_label in {"0-1", "0-2", "1-2"}


def test_low_scoring_legitimate_one_nil_still_allowed() -> None:
    all_scores = _dense_matrix_from_xg(0.85, 0.55)
    probs = {"home_win": 42.0, "draw": 30.0, "away_win": 28.0}
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[{"score": "1-0", "probability": 14.0}],
        all_scores=all_scores,
        home_xg=0.85,
        away_xg=0.55,
        home_team="TeamA",
        away_team="TeamB",
    )
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.score_label in {"1-0", "0-0", "1-1", "0-1"}


def test_completed_match_behavior_unchanged(client: TestClient, tmp_path: Path) -> None:
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
    data = client.post(
        "/api/predict",
        json={"home_team": "Canada", "away_team": "Qatar", "neutral_ground": True},
    ).json()
    mcd = data["match_context_diagnostics"]
    sd = data["scoreline_decision"]
    assert mcd["fixture_status"] == "completed"
    assert mcd["prediction_valid"] is False
    assert mcd["actual_score"] == {"home": 6, "away": 0}
    assert MATCH_ALREADY_COMPLETED in mcd["warnings"]
    assert sd["confidence_label"] == "low"
    assert "PREDICTION_NOT_VALID" in sd["warnings"]


def test_venue_mode_still_moves_probabilities(client: TestClient) -> None:
    neutral = client.post(
        "/api/predict",
        json={
            "home_team": "United States",
            "away_team": "Australia",
            "venue_mode": "neutral",
        },
    ).json()
    home_adv = client.post(
        "/api/predict",
        json={
            "home_team": "United States",
            "away_team": "Australia",
            "venue_mode": "first_team_home",
        },
    ).json()
    assert home_adv["probabilities_1x2"]["home_win"] > neutral["probabilities_1x2"]["home_win"]
    assert home_adv["match_context_diagnostics"]["host_advantage_applied"] is True


def test_representative_diagnostics_exposed(client: TestClient) -> None:
    data = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Haiti", "neutral_ground": True},
    ).json()
    sd = data["scoreline_decision"]
    assert sd.get("representative_score_method") == "representative_v1_gate"
    assert "both_teams_score_probability" in sd
    assert "underdog_scores_probability" in sd
    assert isinstance(sd.get("primary_score_candidates"), list)


def test_balanced_match_uses_top_exact() -> None:
    all_scores = {"1-1": 14.0, "1-0": 12.0, "0-1": 11.0, "0-0": 9.0}
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 35.0, "draw": 33.0, "away_win": 32.0},
        top_scores=[{"score": "1-1", "probability": 14.0}],
        all_scores=all_scores,
        home_xg=1.2,
        away_xg=1.2,
        home_team="A",
        away_team="B",
    )
    assert decision.primary_predicted_score == decision.top_exact_score_overall


def test_no_live_api_required(client: TestClient) -> None:
    resp = client.post(
        "/api/predict",
        json={"home_team": "Germany", "away_team": "Haiti", "neutral_ground": True},
    )
    assert resp.status_code == 200
