"""High favorite-xG representative composite selection and base xG API fields."""

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
    FAVORITE_HIGH_XG_REPRESENTATIVE_SELECTION,
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


def _matrix(home_xg: float, away_xg: float, *, alpha: float = 0.25) -> dict[str, float]:
    engine = AdvancedDixonColesEngine(rho=-0.15, global_avg=2.6, alpha=alpha)
    return engine.generate_match_prediction(
        900,
        650,
        0,
        max_goals=8,
        include_all_scores=True,
        top_n=10,
        home_xg_override=home_xg,
        away_xg_override=away_xg,
    )


def _decision(home_xg: float, away_xg: float):
    payload = _matrix(home_xg, away_xg)
    probs = payload["probabilities_1x2"]
    return build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=payload["top_scores"],
        all_scores=payload["all_scores"],
        home_xg=home_xg,
        away_xg=away_xg,
        home_team="Spain (ספרד)",
        away_team="Saudi Arabia (ערב הסעודית)",
        strength=_strength(),
    )


def _selection(decision) -> dict:
    return decision.representative_selection


def test_high_favorite_xg_low_underdog_selects_four_zero() -> None:
    decision = _decision(4.09, 0.92)
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.score_label == "4-0"
    sel = _selection(decision)
    assert sel["previous_modal_score"] == "3-0"
    assert sel["selected_primary_score"] == "4-0"
    assert sel["high_favorite_xg_influenced"] is True
    assert sel["selection_reason_code"] == FAVORITE_HIGH_XG_REPRESENTATIVE_SELECTION
    assert FAVORITE_HIGH_XG_REPRESENTATIVE_SELECTION in decision.primary_score_warnings
    utilities = {row["score"]: row["utility_components"] for row in sel["top_candidate_utilities"]}
    assert "4-0" in utilities
    assert utilities["4-0"]["favorite_goal_volume_fit"] >= utilities["3-0"]["favorite_goal_volume_fit"]


def test_high_favorite_xg_mid_underdog_prefers_four_one() -> None:
    decision = _decision(4.09, 1.20)
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.score_label == "4-1"
    sel = _selection(decision)
    utilities = {row["score"]: row["utility_components"] for row in sel["top_candidate_utilities"]}
    assert "4-1" in utilities
    if "4-0" in utilities:
        assert utilities["4-1"]["underdog_goal_fit"] > utilities["4-0"]["underdog_goal_fit"]


def test_favorite_xg_below_threshold_no_high_xg_influence() -> None:
    decision = _decision(3.20, 0.80)
    sel = _selection(decision)
    assert sel.get("high_favorite_xg_influenced") is not True
    assert FAVORITE_HIGH_XG_REPRESENTATIVE_SELECTION not in decision.primary_score_warnings


def test_underdog_xg_too_high_no_clean_sheet_blowout() -> None:
    decision = _decision(4.10, 1.50)
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.score_label != "4-0"
    sel = _selection(decision)
    assert sel.get("high_favorite_xg_influenced") is not True


def test_candidate_probability_too_low_cannot_win() -> None:
    payload = _matrix(4.09, 0.92)
    all_scores = dict(payload["all_scores"])
    for label in ("4-0", "4-1", "5-0", "5-1"):
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
    sel = _selection(decision)
    assert sel["selected_primary_score"] == "3-0"
    assert sel.get("high_favorite_xg_influenced") is not True


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
    if baseline["blowout_adjustment_applied"]:
        assert baseline["base_home_xg"] != baseline["home_xg"] or (
            baseline["base_away_xg"] != baseline["away_xg"]
        )
    probs_before = baseline["probabilities_1x2"]
    assert sum(probs_before.values()) == pytest.approx(100.0, abs=0.2)
