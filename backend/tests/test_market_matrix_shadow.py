"""Tests for shadow market matrix calibration (Phase 3B)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from core.market_consensus import build_market_consensus
from core.market_parser import build_snapshot_pipeline, parse_rapidapi_odds_feed_audit
from core.market_matrix_shadow import calibrate_market_matrix_shadow, shadow_market_weight
from core.market_quality import BAND_GREEN, BAND_RED, BAND_YELLOW, score_market_quality

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rapidapi_odds_feed_norway_england.json"

NORWAY_ENGLAND_MATRIX = {
    "0-0": 7.5,
    "1-0": 9.5,
    "0-1": 10.5,
    "1-1": 12.0,
    "2-0": 7.0,
    "0-2": 8.5,
    "2-1": 9.0,
    "1-2": 10.0,
    "2-2": 7.5,
    "3-1": 5.0,
    "1-3": 5.5,
    "3-0": 3.5,
    "0-3": 4.0,
}


def _btts_yes_mass(matrix: dict[str, float]) -> float:
    return sum(p for s, p in matrix.items() if "-" in s and all(int(x) > 0 for x in s.split("-", 1)))


def _high_total_mass(matrix: dict[str, float]) -> float:
    return sum(p for s, p in matrix.items() if sum(int(x) for x in s.split("-", 1)) >= 4)


def _low_total_mass(matrix: dict[str, float]) -> float:
    return sum(p for s, p in matrix.items() if sum(int(x) for x in s.split("-", 1)) <= 2)


def _away_win_mass(matrix: dict[str, float]) -> float:
    total = 0.0
    for s, p in matrix.items():
        h, a = (int(x) for x in s.split("-", 1))
        if a > h:
            total += p
    return total


@pytest.fixture
def green_market():
    report = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snap = parse_rapidapi_odds_feed_audit(report)
    consensus, quality = build_snapshot_pipeline(snap)
    return consensus, quality


def test_green_fixture_calibrates_without_mutating_input(green_market) -> None:
    consensus, quality = green_market
    before = copy.deepcopy(NORWAY_ENGLAND_MATRIX)
    result = calibrate_market_matrix_shadow(before, consensus, quality)

    assert quality.band == BAND_GREEN
    assert before == NORWAY_ENGLAND_MATRIX
    assert result.requested_shadow_weight_pct in (50, 60)
    assert result.market_weight_used_for_shadow == result.requested_shadow_weight_pct
    assert abs(sum(result.shadow_calibrated_matrix.values()) - 100.0) < 0.1
    assert result.top_scores_before != [] and result.top_scores_after != []


def test_btts_yes_pressure_increases_both_teams_score_mass(green_market) -> None:
    consensus, quality = green_market
    baseline = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, consensus, quality)

    high_btts = copy.deepcopy(consensus)
    high_btts.btts = {"yes": 70.0, "no": 30.0}
    boosted = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, high_btts, quality)

    assert boosted.implied_btts_after > baseline.implied_btts_after
    assert _btts_yes_mass(boosted.shadow_calibrated_matrix) > _btts_yes_mass(
        baseline.shadow_calibrated_matrix
    )


def test_under_pressure_increases_low_total_scores(green_market) -> None:
    consensus, quality = green_market
    baseline = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, consensus, quality)

    under = copy.deepcopy(consensus)
    under.totals_by_line = {"2.5": {"over": 35.0, "under": 65.0}}
    adjusted = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, under, quality)

    assert adjusted.implied_total_over_2_5_after < baseline.implied_total_over_2_5_after
    assert _low_total_mass(adjusted.shadow_calibrated_matrix) > _low_total_mass(
        baseline.shadow_calibrated_matrix
    )
    assert _high_total_mass(adjusted.shadow_calibrated_matrix) < _high_total_mass(
        baseline.shadow_calibrated_matrix
    )


def test_favorite_pressure_increases_favorite_win_scores(green_market) -> None:
    consensus, quality = green_market
    result = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, consensus, quality)

    assert result.implied_1x2_after["away"] > result.implied_1x2_before["away"]
    assert _away_win_mass(result.shadow_calibrated_matrix) > _away_win_mass(
        result.original_model_matrix
    )
    top_after = [row["score"] for row in result.top_scores_after[:5]]
    assert any(s in top_after for s in ("0-1", "1-2", "1-1", "2-1", "2-2"))


def test_red_quality_uses_lower_shadow_weight() -> None:
    report = {
        "selected_event": {"event_id": "1", "label": "A vs B", "tournament": "T"},
        "market_coverage_table": [
            {
                "provider_market_name": "1X2",
                "mapped_family": "h2h",
                "sample_odds": [
                    {"book": "BET365", "outcome_0": 2.0, "outcome_1": 3.2, "outcome_2": 3.5}
                ],
            }
        ],
    }
    snap = parse_rapidapi_odds_feed_audit(report)
    consensus = build_market_consensus(snap)
    quality = score_market_quality(snap, consensus)
    assert quality.band == BAND_RED
    assert shadow_market_weight(quality) == 30

    green_consensus, green_quality = build_snapshot_pipeline(
        parse_rapidapi_odds_feed_audit(json.loads(FIXTURE.read_text(encoding="utf-8")))
    )
    assert shadow_market_weight(green_quality) >= 50

    red_result = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, consensus, quality)
    green_result = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, green_consensus, green_quality)
    assert red_result.requested_shadow_weight_pct < green_result.requested_shadow_weight_pct


def test_effective_movement_metrics_reported_for_green_fixture(green_market) -> None:
    consensus, quality = green_market
    result = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, consensus, quality)

    assert result.requested_shadow_weight_pct in (50, 60)
    assert result.effective_favorite_side_movement is not None
    fav = result.effective_favorite_side_movement
    assert fav.status in ("ok", "overshoot", "small_gap")
    assert result.effective_over_2_5_movement is not None
    assert result.effective_btts_movement is not None
    assert all(side in result.effective_h2h_movement for side in ("home", "draw", "away"))
    assert "shadow_weight_requested_" in " ".join(result.calibration_notes)
    assert "effective_favorite_side_movement_" in " ".join(result.calibration_notes)
    if fav.status == "ok" and fav.raw_pct is not None:
        assert fav.raw_pct < result.requested_shadow_weight_pct


def test_btts_pressure_reports_effective_movement_or_weak_note(green_market) -> None:
    consensus, quality = green_market
    result = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, consensus, quality)

    assert result.effective_btts_movement.weak_check_value() is not None
    assert result.implied_btts_after > result.implied_btts_before
    notes_text = " ".join(result.calibration_notes + result.warnings)
    assert "effective_btts_movement_" in notes_text
    if result.effective_btts_movement.weak_check_value() is not None and (
        result.effective_btts_movement.weak_check_value() < 35.0
    ):
        assert "btts_effective_movement_weak" in notes_text or "effective_movement_below_requested" in notes_text


def test_requested_weight_not_confused_with_effective_movement(green_market) -> None:
    consensus, quality = green_market
    result = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, consensus, quality)

    assert result.requested_shadow_weight_pct >= 50
    fav = result.effective_favorite_side_movement
    assert fav is not None
    if fav.status == "ok" and fav.raw_pct is not None:
        assert fav.raw_pct < result.requested_shadow_weight_pct
    assert "requested_weight_is_diagnostic_target_not_linear_blend" in result.calibration_notes


def test_probabilities_normalize_to_100(green_market) -> None:
    consensus, quality = green_market
    result = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, consensus, quality)
    assert abs(sum(result.original_model_matrix.values()) - 100.0) < 0.1
    assert abs(sum(result.shadow_calibrated_matrix.values()) - 100.0) < 0.1


def test_top_scores_reported_separately(green_market) -> None:
    consensus, quality = green_market
    result = calibrate_market_matrix_shadow(NORWAY_ENGLAND_MATRIX, consensus, quality)

    assert result.top_scores_before[0]["score"] == "1-1"
    assert result.top_scores_before != result.top_scores_after or any(
        a["probability"] != b["probability"]
        for a, b in zip(result.top_scores_before, result.top_scores_after, strict=False)
    )


def test_no_production_predict_imports() -> None:
    import core.market_matrix_shadow as mms

    source = Path(mms.__file__).read_text(encoding="utf-8")
    assert "api.main" not in source
    assert "scoreline_decision" not in source
    assert "probability_pipeline" not in source
    assert "odds_ensemble" not in source
