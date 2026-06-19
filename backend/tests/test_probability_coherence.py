"""Tests for probability coherence helpers."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.probability_coherence import (
    FAVORITE_PROBABILITY_XG_MISMATCH,
    ODDS_BLEND_1X2_SCORELINE_MISMATCH,
    ODDS_BLEND_APPLIED,
    PROBABILITY_SUM_INVALID,
    TOP_SCORE_DIRECTION_MISMATCH,
    build_coherence_warnings,
    detect_odds_blend_applied,
    favorite_from_1x2,
    favorite_from_top_scores,
    favorite_from_xg,
    probability_sum,
    probability_sum_valid,
)


def test_probability_sum_valid_normal() -> None:
    probs = {"home_win": 45.0, "draw": 30.0, "away_win": 25.0}
    assert probability_sum(probs) == 100.0
    assert probability_sum_valid(probs) is True


def test_probability_sum_invalid() -> None:
    probs = {"home_win": 50.0, "draw": 30.0, "away_win": 10.0}
    assert probability_sum_valid(probs) is False


def test_favorite_from_1x2() -> None:
    assert favorite_from_1x2({"home_win": 60.0, "draw": 25.0, "away_win": 15.0}) == "home"
    assert favorite_from_1x2({"home_win": 20.0, "draw": 50.0, "away_win": 30.0}) == "draw"
    assert favorite_from_1x2({"home_win": 30.0, "draw": 35.0, "away_win": 35.0}) is None


def test_favorite_from_xg() -> None:
    assert favorite_from_xg(2.0, 1.0) == "home"
    assert favorite_from_xg(1.0, 2.0) == "away"
    assert favorite_from_xg(1.5, 1.48) is None


def test_favorite_from_top_scores() -> None:
    assert favorite_from_top_scores([{"score": "2-1", "probability": 10.0}]) == "home"
    assert favorite_from_top_scores([{"score": "0-2", "probability": 10.0}]) == "away"
    assert favorite_from_top_scores([{"score": "1-1", "probability": 10.0}]) == "draw"


def test_no_coherence_warning_when_coherent() -> None:
    warnings = build_coherence_warnings(
        raw_probabilities_1x2={"home_win": 55.0, "draw": 25.0, "away_win": 20.0},
        final_probabilities_1x2={"home_win": 55.0, "draw": 25.0, "away_win": 20.0},
        home_xg=2.0,
        away_xg=1.0,
        top_scores=[{"score": "2-1", "probability": 12.0}],
        odds_blend_applied=False,
    )
    assert warnings == []


def test_favorite_probability_xg_mismatch() -> None:
    warnings = build_coherence_warnings(
        raw_probabilities_1x2={"home_win": 70.0, "draw": 20.0, "away_win": 10.0},
        final_probabilities_1x2={"home_win": 70.0, "draw": 20.0, "away_win": 10.0},
        home_xg=0.8,
        away_xg=2.0,
        top_scores=[{"score": "0-2", "probability": 12.0}],
        odds_blend_applied=False,
    )
    assert FAVORITE_PROBABILITY_XG_MISMATCH in warnings
    assert TOP_SCORE_DIRECTION_MISMATCH in warnings


def test_odds_blend_applied_warning() -> None:
    raw = {"home_win": 50.0, "draw": 28.0, "away_win": 22.0}
    final = {"home_win": 55.0, "draw": 25.0, "away_win": 20.0}
    market = {"home_win": 70.0, "draw": 20.0, "away_win": 10.0}
    assert detect_odds_blend_applied(raw, final, market) is True
    warnings = build_coherence_warnings(
        raw_probabilities_1x2=raw,
        final_probabilities_1x2=final,
        home_xg=1.0,
        away_xg=2.0,
        top_scores=[{"score": "0-2", "probability": 12.0}],
        odds_blend_applied=True,
    )
    assert ODDS_BLEND_APPLIED in warnings
    assert ODDS_BLEND_1X2_SCORELINE_MISMATCH in warnings


def test_probability_sum_invalid_warning() -> None:
    warnings = build_coherence_warnings(
        raw_probabilities_1x2={"home_win": 40.0, "draw": 30.0, "away_win": 20.0},
        final_probabilities_1x2={"home_win": 40.0, "draw": 30.0, "away_win": 20.0},
        home_xg=1.5,
        away_xg=1.5,
        top_scores=[{"score": "1-1", "probability": 12.0}],
        odds_blend_applied=False,
    )
    assert PROBABILITY_SUM_INVALID in warnings
