"""Stage 3B — scoreline clean-sheet guard (display-only)."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.scoreline_decision import (
    CLEAN_SHEET_GUARD_LOW_CONFIDENCE,
    CLEAN_SHEET_GUARD_SWITCHED_TO_BTTS,
    ScorelineCandidate,
    _apply_clean_sheet_guard,
    build_scoreline_decision,
)


def _cand(h: int, a: int, prob: float) -> ScorelineCandidate:
    outcome = "home_win" if h > a else "away_win" if a > h else "draw"
    return ScorelineCandidate(home_goals=h, away_goals=a, probability=prob, outcome=outcome)


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


# --- helper-level unit tests ----------------------------------------------------


def test_guard_switches_to_close_btts_when_underdog_scores_high() -> None:
    primary = _cand(3, 0, 9.0)
    pool = [primary, _cand(2, 1, 8.5), _cand(3, 1, 6.0), _cand(2, 0, 8.0)]
    result = _apply_clean_sheet_guard(
        primary,
        "home_win",
        pool,
        underdog_scores_probability=52.0,
        both_teams_score_probability=35.0,
    )
    assert result["applied"] is True
    assert result["warning"] == CLEAN_SHEET_GUARD_SWITCHED_TO_BTTS
    # underdog now scores in the guarded primary
    assert result["primary"].away_goals >= 1
    assert result["original"] == "3-0"


def test_guard_keeps_clean_sheet_low_confidence_when_dominant() -> None:
    primary = _cand(3, 0, 20.0)
    pool = [primary, _cand(3, 1, 4.0), _cand(2, 1, 3.0), _cand(2, 0, 10.0)]
    result = _apply_clean_sheet_guard(
        primary,
        "home_win",
        pool,
        underdog_scores_probability=48.0,
        both_teams_score_probability=30.0,
    )
    assert result["applied"] is True
    assert result["force_low_confidence"] is True
    assert result["warning"] == CLEAN_SHEET_GUARD_LOW_CONFIDENCE
    # primary is not switched away from the clean sheet
    assert result["primary"].score_label == "3-0"


def test_guard_not_triggered_when_underdog_score_prob_low() -> None:
    primary = _cand(3, 0, 12.0)
    pool = [primary, _cand(2, 1, 8.0), _cand(3, 1, 6.0)]
    result = _apply_clean_sheet_guard(
        primary,
        "home_win",
        pool,
        underdog_scores_probability=30.0,
        both_teams_score_probability=20.0,
    )
    assert result["applied"] is False
    assert result["primary"].score_label == "3-0"


def test_guard_ignores_non_clean_sheet_primary() -> None:
    primary = _cand(3, 1, 9.0)
    pool = [primary, _cand(3, 0, 8.0)]
    result = _apply_clean_sheet_guard(
        primary,
        "home_win",
        pool,
        underdog_scores_probability=55.0,
        both_teams_score_probability=45.0,
    )
    assert result["applied"] is False
    assert result["primary"].score_label == "3-1"


def test_guard_away_favorite_clean_sheet() -> None:
    primary = _cand(0, 3, 9.0)
    pool = [primary, _cand(1, 3, 8.5), _cand(1, 2, 7.0)]
    result = _apply_clean_sheet_guard(
        primary,
        "away_win",
        pool,
        underdog_scores_probability=50.0,
        both_teams_score_probability=42.0,
    )
    assert result["applied"] is True
    assert result["primary"].home_goals >= 1


def test_guard_disabled_returns_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(config, "SCORELINE_CLEAN_SHEET_GUARD_ENABLED", False)
    primary = _cand(3, 0, 9.0)
    pool = [primary, _cand(2, 1, 8.9)]
    result = _apply_clean_sheet_guard(
        primary,
        "home_win",
        pool,
        underdog_scores_probability=60.0,
        both_teams_score_probability=45.0,
    )
    assert result["applied"] is False


def test_guard_blocked_by_gate_unless_elite_strong_underdog() -> None:
    primary = _cand(2, 0, 12.9)
    pool = [primary, _cand(1, 0, 13.9), _cand(2, 1, 11.0), _cand(1, 1, 9.2)]
    blocked = _apply_clean_sheet_guard(
        primary,
        "home_win",
        pool,
        underdog_scores_probability=46.0,
        both_teams_score_probability=38.0,
        gate_level="BLOCK",
        favorite_class="elite_favorite",
        underdog_power=700.0,
    )
    assert blocked["applied"] is False
    assert blocked["primary"].score_label == "2-0"

    elite = _apply_clean_sheet_guard(
        primary,
        "home_win",
        pool,
        underdog_scores_probability=46.0,
        both_teams_score_probability=38.0,
        gate_level="BLOCK",
        favorite_class="elite_favorite",
        underdog_power=845.0,
        global_top5_scorelines=frozenset({"2-0", "1-0", "2-1", "1-1", "3-0"}),
    )
    assert elite["applied"] is True
    assert elite["primary"].away_goals >= 1
    assert elite["reason"] == "elite_switched_to_btts_close_utility"

    elite_no_top5 = _apply_clean_sheet_guard(
        primary,
        "home_win",
        pool,
        underdog_scores_probability=46.0,
        both_teams_score_probability=38.0,
        gate_level="BLOCK",
        favorite_class="elite_favorite",
        underdog_power=845.0,
        global_top5_scorelines=frozenset({"2-0", "1-0", "3-0", "4-0", "5-0"}),
    )
    assert elite_no_top5["applied"] is False
    assert elite_no_top5["primary"].score_label == "2-0"


def _strength(home_power: float, away_power: float) -> "StrengthResult":
    from core.strength_result import StrengthResult

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


def test_elite_integration_switches_clean_sheet_when_opponent_strong() -> None:
    all_scores = _dense_matrix_from_xg(0.65, 2.0)
    probs = {"home_win": 12.2, "draw": 22.6, "away_win": 65.2}
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[
            {"score": k, "probability": v} for k, v in list(all_scores.items())[:5]
        ],
        all_scores=all_scores,
        home_xg=0.65,
        away_xg=2.0,
        home_team="Netherlands",
        away_team="Argentina",
        strength=_strength(845.0, 999.0),
    )
    primary = decision.primary_predicted_score
    assert primary is not None
    assert decision.underdog_goal_gate.get("favorite_class") == "elite_favorite"
    assert decision.underdog_goal_gate.get("level") == "BLOCK"
    assert primary.home_goals >= 1
    assert decision.clean_sheet_guard_applied is True


def test_true_mismatch_elite_favorite_keeps_clean_sheet() -> None:
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
        strength=_strength(920.0, 724.0),
    )
    primary = decision.primary_predicted_score
    assert primary is not None
    assert primary.away_goals == 0


# --- integration through build_scoreline_decision -------------------------------


def test_build_decision_competitive_no_churn() -> None:
    all_scores = _dense_matrix_from_xg(1.4, 1.3)
    probs = {"home_win": 38.0, "draw": 30.0, "away_win": 32.0}
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[{"score": k, "probability": v} for k, v in list(all_scores.items())[:3]],
        all_scores=all_scores,
        home_xg=1.4,
        away_xg=1.3,
        home_team="A",
        away_team="B",
    )
    # balanced-ish competitive fixture: guard must not fire.
    assert decision.clean_sheet_guard_applied is False


def test_build_decision_strong_favorite_keeps_diagnostics() -> None:
    all_scores = _dense_matrix_from_xg(2.6, 0.5)
    probs = {"home_win": 82.0, "draw": 12.0, "away_win": 6.0}
    decision = build_scoreline_decision(
        final_probabilities_1x2=probs,
        top_scores=[{"score": k, "probability": v} for k, v in list(all_scores.items())[:3]],
        all_scores=all_scores,
        home_xg=2.6,
        away_xg=0.5,
        home_team="Fav",
        away_team="Dog",
    )
    primary = decision.primary_predicted_score
    assert primary is not None
    # Low underdog xG => underdog P(score) below threshold => guard stays off,
    # clean-sheet primary allowed.
    if decision.clean_sheet_guard_applied:
        assert decision.clean_sheet_guard_reason is not None
