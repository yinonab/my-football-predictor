"""Expected-goals representative composite selection and base xG API fields."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from api import main as api_main
from core.math_engine import AdvancedDixonColesEngine
from core.scoreline_decision import (
    EXPECTED_GOALS_REPRESENTATIVE_SELECTION,
    _representative_goal_target,
    build_scoreline_decision,
)
from core.strength_result import StrengthResult


def _strength(home_power: float = 900.0, away_power: float = 650.0) -> StrengthResult:
    gap = home_power - away_power
    return StrengthResult(
        home_team="Home",
        away_team="Away",
        baseline_home_power=home_power,
        baseline_away_power=away_power,
        baseline_gap=gap,
        active_home_power=home_power,
        active_away_power=away_power,
        active_gap=gap,
        final_home_power=home_power,
        final_away_power=away_power,
        final_gap=gap,
        activation_enabled=False,
        power_candidate_affects_prediction=False,
        active_candidate=None,
        active_external_rating_mode=None,
        active_external_rating_strategy=None,
        model_version="test",
        baseline_model_version="test",
        fallback_to_baseline=True,
    )


def _matrix(
    home_xg: float,
    away_xg: float,
    *,
    home_power: float = 900.0,
    away_power: float = 650.0,
    alpha: float = 0.25,
) -> dict[str, float]:
    engine = AdvancedDixonColesEngine(rho=-0.15, global_avg=2.6, alpha=alpha)
    return engine.generate_match_prediction(
        home_power,
        away_power,
        0,
        max_goals=8,
        include_all_scores=True,
        top_n=10,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )


def _decision(
    home_xg: float,
    away_xg: float,
    *,
    home_power: float = 900.0,
    away_power: float = 650.0,
):
    payload = _matrix(home_xg, away_xg, home_power=home_power, away_power=away_power)
    probs = payload["probabilities_1x2"]
    return build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=payload["top_scores"],
        all_scores=payload["all_scores"],
        home_xg=home_xg,
        away_xg=away_xg,
        home_team="Home",
        away_team="Away",
        strength=_strength(home_power, away_power),
    )


def _selection(decision) -> dict:
    return decision.representative_selection


def _utilities(decision) -> dict[str, dict]:
    sel = _selection(decision)
    return {row["score"]: row["utility_components"] for row in sel["top_candidate_utilities"]}


def test_representative_goal_target_round_half_up() -> None:
    assert _representative_goal_target(0.49) == 0
    assert _representative_goal_target(0.50) == 1
    assert _representative_goal_target(1.49) == 1
    assert _representative_goal_target(1.50) == 2
    assert _representative_goal_target(2.97) == 3
    assert _representative_goal_target(4.09) == 4
    assert _representative_goal_target(5.50) == 6


def test_uruguay_style_297_077_three_goal_favorite_competes() -> None:
    decision = _decision(2.97, 0.77)
    sel = _selection(decision)
    assert sel["home_target_goals"] == 3
    assert sel["away_target_goals"] == 1
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.home_goals >= 3
    utils = _utilities(decision)
    assert "3-0" in utils or "3-1" in utils
    assert utils.get("3-0", {}).get("expected_goal_target_fit", 0) >= 0.66


def test_spain_style_409_092_four_goal_favorite_competes() -> None:
    decision = _decision(4.09, 0.92)
    sel = _selection(decision)
    assert sel["home_target_goals"] == 4
    assert sel["away_target_goals"] == 1
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.home_goals >= 4
    utils = _utilities(decision)
    assert "4-0" in utils or "4-1" in utils
    if sel["previous_modal_score"] == "3-0":
        assert sel.get("expected_goals_target_influenced") is True
        assert sel.get("selection_reason_code") == EXPECTED_GOALS_REPRESENTATIVE_SELECTION


def test_low_xg_boundary_150_049_two_goal_favorite_competes() -> None:
    decision = _decision(1.50, 0.49)
    sel = _selection(decision)
    assert sel["home_target_goals"] == 2
    assert sel["away_target_goals"] == 0
    primary = decision.primary_predicted_score
    assert primary is not None
    utils = _utilities(decision)
    assert "2-0" in utils
    assert utils["2-0"]["expected_goal_target_fit"] == pytest.approx(1.0, abs=0.01)
    assert primary.score_label in {"2-0", "1-0"}


def test_underdog_half_boundary_210_050_two_one_competes() -> None:
    decision = _decision(2.10, 0.50)
    sel = _selection(decision)
    assert sel["home_target_goals"] == 2
    assert sel["away_target_goals"] == 1
    primary = decision.primary_predicted_score
    assert primary is not None
    utils = _utilities(decision)
    assert "2-1" in utils
    assert utils["2-1"]["expected_goal_target_fit"] == pytest.approx(1.0, abs=0.01)
    assert primary.score_label in {"2-1", "2-0"}


def test_high_extreme_550_080_no_four_goal_cap() -> None:
    decision = _decision(5.50, 0.80)
    sel = _selection(decision)
    assert sel["home_target_goals"] == 6
    assert sel["away_target_goals"] == 1
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.home_goals >= 5
    utils = _utilities(decision)
    assert any(score.startswith("5-") or score.startswith("6-") for score in utils)


def test_equal_low_xg_stability() -> None:
    decision = _decision(1.45, 0.95, home_power=900.0, away_power=620.0)
    sel = _selection(decision)
    assert sel["home_target_goals"] == 1
    assert sel["away_target_goals"] == 1
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.home_goals <= 2
    assert primary.away_goals <= 2


def test_candidate_probability_too_low_cannot_win() -> None:
    payload = _matrix(4.09, 0.92)
    all_scores = dict(payload["all_scores"])
    for label in ("4-0", "4-1", "5-0", "5-1", "6-0"):
        if label in all_scores:
            all_scores[label] = 0.5
    decision = build_scoreline_decision(
        final_probabilities_1x2=payload["probabilities_1x2"],
        top_scores=payload["top_scores"],
        all_scores=all_scores,
        home_xg=4.09,
        away_xg=0.92,
        home_team="Spain",
        away_team="Saudi",
        strength=_strength(),
    )
    assert decision.primary_predicted_score is not None
    assert decision.primary_predicted_score.score_label == "3-0"


@pytest.fixture
def client() -> TestClient:
    return TestClient(api_main.app)


def test_predict_includes_base_xg_fields(client: TestClient) -> None:
    baseline = client.post(
        "/api/predict",
        json={
            "home_team": "Brazil (ברזיל)",
            "away_team": "Haiti (האיטי)",
            "neutral_ground": True,
        },
    ).json()
    assert "home_xg" in baseline
    assert "away_xg" in baseline
    assert "base_home_xg" in baseline
    assert "base_away_xg" in baseline
    assert baseline["adjusted_home_xg"] == baseline["home_xg"]
    assert baseline["adjusted_away_xg"] == baseline["away_xg"]
    probs_before = baseline["probabilities_1x2"]
    assert sum(probs_before.values()) == pytest.approx(100.0, abs=0.2)
