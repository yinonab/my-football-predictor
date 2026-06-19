"""Tests for Phase 4E probability quality metrics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.probability_quality import (
    WARNING_OVERCONFIDENT_FAVORITES,
    aggregate_probability_quality,
    brier_score_1x2,
    evaluate_calibration_warnings,
    expected_calibration_error,
    log_loss_1x2,
    normalize_1x2_probabilities,
    predicted_confidence,
    predicted_outcome,
    reliability_buckets,
)


def test_normalize_accepts_percent_scale() -> None:
    probs = normalize_1x2_probabilities(
        {"home_win": 50.0, "draw": 30.0, "away_win": 20.0}
    )
    assert pytest.approx(sum(probs.values()), abs=1e-6) == 1.0
    assert probs["home"] == pytest.approx(0.5, abs=1e-6)


def test_normalize_accepts_unit_scale() -> None:
    probs = normalize_1x2_probabilities({"home": 0.5, "draw": 0.3, "away": 0.2})
    assert pytest.approx(sum(probs.values()), abs=1e-6) == 1.0


def test_brier_perfect_and_wrong() -> None:
    perfect = {"home": 1.0, "draw": 0.0, "away": 0.0}
    wrong = {"home": 0.9, "draw": 0.05, "away": 0.05}
    assert brier_score_1x2(perfect, "home") == pytest.approx(0.0)
    assert brier_score_1x2(wrong, "away") > brier_score_1x2(perfect, "home")


def test_log_loss_lower_for_better_prediction() -> None:
    good = {"home": 0.8, "draw": 0.1, "away": 0.1}
    bad = {"home": 0.2, "draw": 0.4, "away": 0.4}
    assert log_loss_1x2(good, "home") < log_loss_1x2(bad, "home")


def test_predicted_outcome_and_confidence() -> None:
    probs = {"home": 0.6, "draw": 0.25, "away": 0.15}
    assert predicted_outcome(probs) == "home"
    assert predicted_confidence(probs) == pytest.approx(0.6)


def test_reliability_buckets_group_rows() -> None:
    rows = [
        {"predicted_probs": {"home": 0.75, "draw": 0.15, "away": 0.10}, "actual_outcome": "home"},
        {"predicted_probs": {"home": 0.72, "draw": 0.18, "away": 0.10}, "actual_outcome": "away"},
        {"predicted_probs": {"home": 0.35, "draw": 0.35, "away": 0.30}, "actual_outcome": "draw"},
    ]
    buckets = reliability_buckets(rows)
    assert buckets
    assert sum(bucket["count"] for bucket in buckets) == len(rows)


def test_ece_zero_for_perfect_calibration_synthetic() -> None:
    rows = []
    for i in range(20):
        rows.append(
            {
                "predicted_probs": {"home": 0.70, "draw": 0.20, "away": 0.10},
                "actual_outcome": "home" if i < 14 else "away",
            }
        )
    ece = expected_calibration_error(rows)
    assert ece == pytest.approx(0.0, abs=0.05)


def test_ece_positive_for_miscalibrated_synthetic() -> None:
    rows = []
    for _ in range(30):
        rows.append(
            {
                "predicted_probs": {"home": 0.85, "draw": 0.10, "away": 0.05},
                "actual_outcome": "away",
            }
        )
    ece = expected_calibration_error(rows)
    assert ece > 0.05


def test_aggregate_probability_quality_returns_core_metrics() -> None:
    rows = [
        {"predicted_probs": {"home": 0.6, "draw": 0.2, "away": 0.2}, "actual_outcome": "home"},
        {"predicted_probs": {"home": 0.2, "draw": 0.3, "away": 0.5}, "actual_outcome": "away"},
    ]
    summary = aggregate_probability_quality(rows)
    assert summary["count"] == 2
    assert summary["accuracy_1x2"] == 1.0
    assert "brier" in summary
    assert "log_loss" in summary
    assert "ece" in summary
    assert summary["buckets"]


def test_overconfident_warning_rule() -> None:
    rows = []
    for _ in range(12):
        rows.append(
            {
                "predicted_probs": {"home": 0.80, "draw": 0.10, "away": 0.10},
                "actual_outcome": "away",
            }
        )
    warnings = evaluate_calibration_warnings(rows)
    assert any(WARNING_OVERCONFIDENT_FAVORITES in warning for warning in warnings)


def test_invalid_probabilities_handled_safely() -> None:
    probs = normalize_1x2_probabilities(
        {"home_win": float("nan"), "draw": -5, "away_win": 0}
    )
    assert pytest.approx(sum(probs.values()), abs=1e-6) == 1.0
    assert predicted_outcome(probs) in {"home", "draw", "away"}


def test_collect_walk_forward_smoke_wc2022() -> None:
    from core.probability_quality import collect_walk_forward_probability_rows

    rows = collect_walk_forward_probability_rows("wc2022")
    assert len(rows) > 0
    assert sum(rows[0].predicted_probs.values()) == pytest.approx(1.0, abs=0.01)
