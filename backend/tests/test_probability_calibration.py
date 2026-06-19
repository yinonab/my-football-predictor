"""Tests for Phase 4F shadow probability calibration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from core.probability_calibration import (
    FavoriteShrinkCalibrator,
    IdentityCalibrator,
    TemperatureCalibrator,
    evaluate_calibrator,
    evaluate_guardrails,
    fit_calibrator,
    search_shadow_calibrators,
)
from core.probability_quality import normalize_1x2_probabilities


def _row(probs: dict[str, float], outcome: str, dataset: str = "test") -> dict:
    return {
        "predicted_probs": normalize_1x2_probabilities(probs),
        "actual_outcome": outcome,
        "dataset": dataset,
    }


def test_identity_unchanged() -> None:
    probs = {"home": 0.5, "draw": 0.3, "away": 0.2}
    cal = IdentityCalibrator()
    out = cal.apply(probs)
    assert out == pytest.approx(normalize_1x2_probabilities(probs))


def test_temperature_preserves_sum() -> None:
    probs = {"home": 0.6, "draw": 0.25, "away": 0.15}
    cal = TemperatureCalibrator(temperature=1.2)
    out = cal.apply(probs)
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-6)
    assert all(v >= 0 for v in out.values())


def test_favorite_shrink_preserves_sum() -> None:
    probs = {"home": 0.7, "draw": 0.2, "away": 0.1}
    cal = FavoriteShrinkCalibrator(alpha=0.08)
    out = cal.apply(probs)
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-6)
    assert out["home"] < probs["home"]


def test_calibrators_preserve_keys_and_non_negative() -> None:
    probs = {"home_win": 55.0, "draw": 25.0, "away_win": 20.0}
    for cal in (
        IdentityCalibrator(),
        TemperatureCalibrator(temperature=0.9),
        FavoriteShrinkCalibrator(alpha=0.06),
    ):
        out = cal.apply(probs)
        assert set(out.keys()) == {"home", "draw", "away"}
        assert all(v >= 0 for v in out.values())


def test_apply_accepts_percent_or_unit() -> None:
    percent = {"home_win": 60.0, "draw": 20.0, "away_win": 20.0}
    unit = {"home": 0.6, "draw": 0.2, "away": 0.2}
    cal = TemperatureCalibrator(temperature=1.0)
    assert cal.apply(percent) == pytest.approx(cal.apply(unit), abs=1e-6)


def test_evaluate_calibrator_runs_on_synthetic_rows() -> None:
    rows = [
        _row({"home": 0.7, "draw": 0.2, "away": 0.1}, "home"),
        _row({"home": 0.2, "draw": 0.3, "away": 0.5}, "away"),
        _row({"home": 0.4, "draw": 0.3, "away": 0.3}, "draw"),
    ]
    result = evaluate_calibrator(rows, IdentityCalibrator())
    assert result.metrics_before["count"] == 3
    assert result.metrics_after["count"] == 3


def test_guardrails_pass_synthetic_improved_ece() -> None:
    before = {
        "ece": 0.12,
        "brier": 0.60,
        "log_loss": 1.0,
        "accuracy_1x2": 0.55,
        "probability_sum_valid": True,
    }
    after = {
        "ece": 0.08,
        "brier": 0.602,
        "log_loss": 1.005,
        "accuracy_1x2": 0.55,
        "probability_sum_valid": True,
    }
    passed, reasons = evaluate_guardrails(
        metrics_before=before,
        metrics_after=after,
        per_dataset_before={"test": before},
        per_dataset_after={"test": after},
    )
    assert passed is True
    assert reasons == []


def test_guardrails_fail_when_brier_worsens() -> None:
    before = {
        "ece": 0.10,
        "brier": 0.60,
        "log_loss": 1.0,
        "accuracy_1x2": 0.55,
        "probability_sum_valid": True,
    }
    after = {
        "ece": 0.07,
        "brier": 0.62,
        "log_loss": 1.0,
        "accuracy_1x2": 0.55,
        "probability_sum_valid": True,
    }
    passed, reasons = evaluate_guardrails(
        metrics_before=before,
        metrics_after=after,
        per_dataset_before={"test": before},
        per_dataset_after={"test": after},
    )
    assert passed is False
    assert any("brier_worsened" in reason for reason in reasons)


def test_fit_temperature_returns_grid_value() -> None:
    rows = [_row({"home": 0.8, "draw": 0.1, "away": 0.1}, "home") for _ in range(20)]
    cal = fit_calibrator(rows, "temperature")
    assert "temperature" in cal.params


def test_search_shadow_calibrators_smoke() -> None:
    from core.probability_quality import collect_walk_forward_probability_rows

    rows = collect_walk_forward_probability_rows("wc2022")
    results = search_shadow_calibrators(rows[:12])
    assert len(results) >= 3
    assert results[0].calibrator_name == "identity"
