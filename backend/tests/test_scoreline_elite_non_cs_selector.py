"""Elite mismatch non-clean-sheet candidate selector tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AUDIT_ELO_BASELINE", "production")
os.environ.setdefault("NR3_FCC_SERVED_ENABLED", "true")

from core.scoreline_decision import (  # noqa: E402
    CLEAN_SHEET_GUARD_SWITCHED_TO_BTTS,
    ELITE_NON_CS_SELECTOR_APPLIED,
    NEAR_BALANCED_DRAW_MODAL_APPLIED,
    MatrixStats,
    ScorelineCandidate,
    _apply_elite_mismatch_non_cs_selector,
    _apply_near_balanced_draw_modal,
    build_scoreline_decision,
)
from core.strength_result import StrengthResult  # noqa: E402


def _cand(h: int, a: int, prob: float) -> ScorelineCandidate:
    outcome = "home_win" if h > a else "away_win" if a > h else "draw"
    return ScorelineCandidate(home_goals=h, away_goals=a, probability=prob, outcome=outcome)


def _matrix_stats(
    *,
    btts: float = 40.0,
    ud_score: float = 50.0,
    fav_2_plus: float = 50.0,
    fav_3_plus: float = 28.0,
    fav_4_plus: float = 10.0,
    ud_2_plus: float = 20.0,
    ud_3_plus: float = 9.0,
) -> MatrixStats:
    return MatrixStats(
        btts_probability=btts,
        underdog_scores_probability=ud_score,
        favorite_scores_2_plus=fav_2_plus,
        favorite_scores_3_plus=fav_3_plus,
        favorite_scores_4_plus=fav_4_plus,
        expected_home_goals=1.8,
        expected_away_goals=1.2,
        expected_goal_difference=0.6,
        upset_probability=20.0,
        underdog_scores_2_plus=ud_2_plus,
        underdog_scores_3_plus=ud_3_plus,
    )


def _strength(home_power: float, away_power: float) -> StrengthResult:
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


# --- helper-level unit tests ----------------------------------------------------


def test_app_default_style_1_0_prefers_close_draw_over_far_btts() -> None:
    """App-default France–Colombia shape: 1-1 close, 2-1 too far."""
    primary = _cand(1, 0, 16.18)
    candidates = [
        primary,
        _cand(2, 0, 12.56),
        _cand(1, 1, 12.50),
        _cand(0, 0, 12.26),
        _cand(2, 1, 8.67),
        _cand(0, 1, 7.12),
        _cand(3, 0, 6.20),
        _cand(1, 2, 4.04),
    ]
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=27.1,
        candidates=candidates,
        underdog_scores_probability=49.8,
        both_teams_score_probability=39.2,
        favorite_goal_bands={
            "favorite_2_plus": 43.3,
            "favorite_3_plus": 18.3,
            "favorite_4_plus": 5.9,
        },
        underdog_power=890.0,
        guard_switched_to_btts=False,
        favorite_class="elite_favorite",
        gate_level="BLOCK",
    )
    assert result["applied"] is True
    assert result["primary"].score_label == "1-1"
    assert result["candidate_type"] == "draw"
    assert result["warning"] == ELITE_NON_CS_SELECTOR_APPLIED


def test_audit_style_2_0_prefers_same_fav_btts_over_scoreless_draw() -> None:
    """Audit/Fusion shape: 2-0 must not become 0-0 when fav 2+ is strong."""
    primary = _cand(2, 0, 12.94)
    candidates = [
        _cand(1, 0, 14.63),
        primary,
        _cand(0, 0, 11.07),
        _cand(1, 1, 9.78),
        _cand(3, 0, 8.14),
        _cand(2, 1, 7.75),  # gap 5.19pp; strong fav 2+ → 5.5pp path
        _cand(0, 1, 5.50),
        _cand(3, 1, 4.50),
    ]
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=39.0,
        candidates=candidates,
        underdog_scores_probability=46.3,
        both_teams_score_probability=38.2,
        favorite_goal_bands={
            "favorite_2_plus": 52.4,
            "favorite_3_plus": 28.2,
            "favorite_4_plus": 13.0,
        },
        underdog_power=890.0,
        guard_switched_to_btts=False,
        favorite_class="elite_favorite",
        gate_level="BLOCK",
    )
    assert result["applied"] is True
    assert result["primary"].score_label == "2-1"
    assert result["primary"].score_label != "0-0"


def test_does_not_override_successful_btts_guard() -> None:
    primary = _cand(2, 1, 8.69)
    candidates = [
        _cand(1, 0, 16.25),
        _cand(2, 0, 12.78),
        _cand(1, 1, 12.36),
        primary,
    ]
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=28.2,
        candidates=candidates,
        underdog_scores_probability=49.3,
        both_teams_score_probability=39.1,
        favorite_goal_bands={"favorite_2_plus": 44.0},
        underdog_power=860.0,
        guard_switched_to_btts=True,
        favorite_class="elite_favorite",
        gate_level="BLOCK",
    )
    assert result["applied"] is False
    assert result["reason"] == "btts_guard_already_applied"
    assert result["primary"].score_label == "2-1"


def test_does_not_override_away_btts_guard_result() -> None:
    primary = _cand(1, 2, 8.50)
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="away_win",
        margin_pp=26.8,
        candidates=[_cand(0, 1, 16.0), _cand(1, 1, 12.0), primary],
        underdog_scores_probability=48.8,
        both_teams_score_probability=37.7,
        favorite_goal_bands={"favorite_2_plus": 43.0},
        underdog_power=950.0,
        guard_switched_to_btts=True,
        favorite_class="elite_favorite",
        gate_level="BLOCK",
    )
    assert result["applied"] is False
    assert result["primary"].score_label == "1-2"


def test_ultra_weak_underdog_skipped() -> None:
    primary = _cand(2, 0, 18.0)
    candidates = [
        primary,
        _cand(1, 0, 16.0),
        _cand(1, 1, 11.0),
        _cand(2, 1, 8.0),
    ]
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=35.0,
        candidates=candidates,
        underdog_scores_probability=46.0,
        both_teams_score_probability=30.0,
        favorite_goal_bands={"favorite_2_plus": 55.0},
        underdog_power=720.0,  # Haiti / Curaçao style
        guard_switched_to_btts=False,
        favorite_class="elite_favorite",
        gate_level="BLOCK",
    )
    assert result["applied"] is False
    assert result["reason"] == "ultra_weak_underdog_skipped"


def test_high_total_rejected_without_scoring_tails() -> None:
    primary = _cand(1, 0, 16.0)
    candidates = [
        primary,
        _cand(2, 0, 12.0),
        _cand(3, 2, 13.5),  # high total without tails
        _cand(1, 1, 12.5),
        _cand(2, 1, 8.0),
    ]
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=25.0,
        candidates=candidates,
        underdog_scores_probability=49.0,
        both_teams_score_probability=30.0,
        favorite_goal_bands={
            "favorite_2_plus": 40.0,
            "favorite_3_plus": 10.0,
        },
        underdog_power=880.0,
        guard_switched_to_btts=False,
        favorite_class="elite_favorite",
        gate_level="BLOCK",
    )
    assert result["applied"] is True
    assert result["primary"].score_label == "1-1"
    assert result["primary"].score_label != "3-2"


def test_high_total_4_3_rejected_when_underdog_3_plus_tail_weak() -> None:
    """4-3 / 3-4 require ud 3+ tail when total goals >= 7."""
    primary = _cand(1, 0, 16.0)
    candidates = [
        primary,
        _cand(2, 0, 12.0),
        _cand(4, 3, 13.5),  # gap 2.5pp, rank 3, high_total but ud3 tail weak
        _cand(1, 1, 12.5),
        _cand(3, 2, 8.0),
    ]
    stats = _matrix_stats(btts=42.0, ud_2_plus=20.0, ud_3_plus=5.0)  # < 8%
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=25.0,
        candidates=candidates,
        underdog_scores_probability=49.0,
        both_teams_score_probability=stats.btts_probability,
        favorite_goal_bands={
            "favorite_2_plus": stats.favorite_scores_2_plus,
            "favorite_3_plus": stats.favorite_scores_3_plus,
        },
        underdog_power=880.0,
        guard_switched_to_btts=False,
        favorite_class="elite_favorite",
        gate_level="BLOCK",
        matrix_stats=stats,
    )
    evaluated_scores = [e["score"] for e in result.get("evaluated", [])]
    assert "4-3" not in evaluated_scores
    assert result["applied"] is True
    assert result["primary"].score_label == "1-1"
    assert result["primary"].score_label != "4-3"


def test_high_total_3_2_rejected_when_underdog_2_plus_tail_weak() -> None:
    """3-2 needs ud 2+ and BTTS floor (or alternate tail paths)."""
    primary = _cand(1, 0, 16.0)
    candidates = [
        primary,
        _cand(2, 0, 12.0),
        _cand(3, 2, 13.5),
        _cand(1, 1, 12.5),
    ]
    stats = _matrix_stats(btts=30.0, ud_2_plus=12.0, ud_3_plus=2.0)  # below 18% / 35% BTTS
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=25.0,
        candidates=candidates,
        underdog_scores_probability=49.0,
        both_teams_score_probability=stats.btts_probability,
        favorite_goal_bands={
            "favorite_2_plus": 40.0,
            "favorite_3_plus": 12.0,  # below fav3 strong path
        },
        underdog_power=880.0,
        guard_switched_to_btts=False,
        favorite_class="elite_favorite",
        gate_level="BLOCK",
        matrix_stats=stats,
    )
    evaluated_scores = [e["score"] for e in result.get("evaluated", [])]
    assert "3-2" not in evaluated_scores
    assert result["primary"].score_label == "1-1"


def test_high_total_3_2_evaluated_and_can_win_when_tails_strong() -> None:
    """Synthetic open-goal game: 3-2 eligible and can beat distant draw/BTTS lines."""
    primary = _cand(1, 0, 16.0)
    candidates = [
        primary,
        _cand(2, 0, 12.0),
        _cand(3, 2, 14.5),  # rank 3, gap 1.5pp
        _cand(4, 2, 14.0),  # rank 4, gap 2.0pp
        _cand(1, 1, 9.0),  # gap 7pp — draw ineligible
        _cand(2, 1, 8.0),  # gap 8pp — BTTS ineligible
        _cand(3, 1, 6.0),
        _cand(2, 3, 5.5),
    ]
    stats = _matrix_stats(
        btts=45.0,
        fav_2_plus=58.0,
        fav_3_plus=35.0,
        fav_4_plus=18.0,
        ud_2_plus=24.0,
        ud_3_plus=11.0,
    )
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=28.0,
        candidates=candidates,
        underdog_scores_probability=52.0,
        both_teams_score_probability=stats.btts_probability,
        favorite_goal_bands={
            "favorite_2_plus": stats.favorite_scores_2_plus,
            "favorite_3_plus": stats.favorite_scores_3_plus,
            "favorite_4_plus": stats.favorite_scores_4_plus,
        },
        underdog_power=900.0,
        guard_switched_to_btts=False,
        favorite_class="elite_favorite",
        gate_level="BLOCK",
        matrix_stats=stats,
    )
    evaluated = result.get("evaluated") or []
    evaluated_scores = [e["score"] for e in evaluated]
    assert "3-2" in evaluated_scores
    assert any(e["type"] == "high_total_btts" for e in evaluated)
    assert result["applied"] is True
    assert result["primary"].score_label in {"3-2", "4-2"}
    assert result["candidate_type"] == "high_total_btts"


def test_gap_rejection_when_candidate_too_far() -> None:
    primary = _cand(1, 0, 18.0)
    candidates = [
        primary,
        _cand(2, 0, 14.0),
        _cand(1, 1, 10.0),  # gap 8pp > 4pp draw limit
        _cand(2, 1, 9.0),  # gap 9pp > 5pp BTTS limit
    ]
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=27.0,
        candidates=candidates,
        underdog_scores_probability=50.0,
        both_teams_score_probability=40.0,
        favorite_goal_bands={"favorite_2_plus": 42.0},
        underdog_power=900.0,
        guard_switched_to_btts=False,
        favorite_class="elite_favorite",
        gate_level="BLOCK",
    )
    assert result["applied"] is False
    assert result["reason"] == "no_eligible_non_cs_candidate"


def test_skips_option_c_margin_band() -> None:
    primary = _cand(1, 0, 12.0)
    candidates = [primary, _cand(1, 1, 11.5), _cand(0, 0, 10.0)]
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=8.0,
        candidates=candidates,
        underdog_scores_probability=55.0,
        both_teams_score_probability=42.0,
        favorite_goal_bands={"favorite_2_plus": 35.0},
        underdog_power=950.0,
        guard_switched_to_btts=False,
        favorite_class="weak_or_balanced_favorite",
        gate_level="BALANCED",
    )
    assert result["applied"] is False
    assert result["reason"] == "margin_outside_selector_band"


def test_balanced_gate_defers_to_option_c() -> None:
    primary = _cand(1, 0, 12.0)
    candidates = [primary, _cand(1, 1, 11.0)]
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=15.0,
        candidates=candidates,
        underdog_scores_probability=60.0,
        both_teams_score_probability=44.0,
        favorite_goal_bands={"favorite_2_plus": 32.0},
        underdog_power=955.0,
        guard_switched_to_btts=False,
        favorite_class="weak_or_balanced_favorite",
        gate_level="BALANCED",
    )
    assert result["applied"] is False
    assert result["reason"] == "balanced_gate_deferred_to_option_c"


def test_away_favorite_selects_scored_draw() -> None:
    primary = _cand(0, 1, 16.18)
    candidates = [
        primary,
        _cand(0, 2, 12.56),
        _cand(1, 1, 12.50),
        _cand(0, 0, 12.26),
        _cand(1, 2, 8.67),
    ]
    result = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="away_win",
        margin_pp=27.1,
        candidates=candidates,
        underdog_scores_probability=49.8,
        both_teams_score_probability=39.2,
        favorite_goal_bands={"favorite_2_plus": 43.3},
        underdog_power=890.0,
        guard_switched_to_btts=False,
        favorite_class="elite_favorite",
        gate_level="BLOCK",
    )
    assert result["applied"] is True
    assert result["primary"].score_label == "1-1"


# --- synthetic pipeline regression ---------------------------------------------


def _fra_col_app_matrix() -> dict[str, float]:
    # Ranked mass similar to production app-default diagnosis (top lines).
    return {
        "1-0": 16.18,
        "2-0": 12.56,
        "1-1": 12.50,
        "0-0": 12.26,
        "2-1": 8.67,
        "0-1": 7.12,
        "3-0": 6.20,
        "3-1": 4.50,
        "1-2": 4.04,
        "2-2": 3.50,
        "0-2": 2.80,
        "4-0": 2.00,
        "4-1": 1.50,
        "3-2": 1.20,
        "4-2": 0.80,
        "4-3": 0.40,
    }


def test_pipeline_app_default_style_switches_1_0_to_1_1() -> None:
    all_scores = _fra_col_app_matrix()
    top = [
        {"score": k, "probability": v}
        for k, v in sorted(all_scores.items(), key=lambda x: -x[1])[:10]
    ]
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 52.0, "draw": 24.9, "away_win": 23.1},
        top_scores=top,
        all_scores=all_scores,
        home_xg=1.48,
        away_xg=0.69,
        home_team="France",
        away_team="Colombia",
        strength=_strength(991.0, 890.0),
    )
    assert decision.primary_predicted_score is not None
    assert decision.primary_predicted_score.score_label == "1-1"
    assert ELITE_NON_CS_SELECTOR_APPLIED in decision.warnings


def test_pipeline_preserves_btts_guard_primary() -> None:
    """If CS guard already switched to BTTS, selector must not replace it with a draw."""
    # Construct so elite override finds a close BTTS candidate for primary 2-0.
    all_scores = {
        "2-0": 12.9,
        "1-0": 12.0,
        "2-1": 11.0,  # gap 1.9pp from 2-0 → CS guard switches
        "0-0": 10.0,
        "1-1": 9.8,
        "3-0": 7.5,
        "0-1": 5.0,
        "3-1": 4.0,
        "1-2": 3.0,
        "2-2": 2.5,
    }
    top = [
        {"score": k, "probability": v}
        for k, v in sorted(all_scores.items(), key=lambda x: -x[1])[:10]
    ]
    decision = build_scoreline_decision(
        final_probabilities_1x2={"home_win": 54.0, "draw": 25.0, "away_win": 21.0},
        top_scores=top,
        all_scores=all_scores,
        home_xg=1.50,
        away_xg=0.68,
        home_team="France",
        away_team="Croatia",
        strength=_strength(991.0, 860.0),
    )
    assert decision.primary_predicted_score is not None
    label = decision.primary_predicted_score.score_label
    assert CLEAN_SHEET_GUARD_SWITCHED_TO_BTTS in decision.warnings
    assert label == "2-1"
    assert ELITE_NON_CS_SELECTOR_APPLIED not in decision.warnings
    # Closely ranked 1-1 must not override the guard result.
    assert label != "1-1"

def test_option_c_still_runs_when_margin_in_band() -> None:
    primary = _cand(1, 0, 11.5)
    draw_modal = _cand(1, 1, 10.5)
    overlay = _apply_near_balanced_draw_modal(
        primary,
        favorite="home_win",
        margin_pp=8.0,
        draw_probability=35.0,
        candidates=[draw_modal, primary],
        top_exact=draw_modal,
        used_balanced_modal_path=False,
        guard_switched_to_btts=False,
    )
    assert overlay["applied"] is True
    assert overlay["primary"].score_label == "1-1"

    # Selector itself must not fire in Option C margin band.
    sel = _apply_elite_mismatch_non_cs_selector(
        primary,
        favorite="home_win",
        margin_pp=8.0,
        candidates=[draw_modal, primary],
        underdog_scores_probability=57.0,
        both_teams_score_probability=42.0,
        favorite_goal_bands={"favorite_2_plus": 35.0},
        underdog_power=930.0,
        guard_switched_to_btts=False,
        favorite_class="weak_or_balanced_favorite",
        gate_level="BALANCED",
    )
    assert sel["applied"] is False
    assert NEAR_BALANCED_DRAW_MODAL_APPLIED  # code constant still defined
