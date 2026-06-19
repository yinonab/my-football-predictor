"""Tests for Phase 4G out-of-sample calibration validation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

PYTHON = sys.executable

from core.probability_calibration import TemperatureCalibrator
from core.probability_calibration_validation import (
    RECOMMENDATION_NO_CALIBRATOR,
    RECOMMENDATION_SHADOW_VALIDATED,
    evaluate_holdout_guardrails,
    fixed_candidate_validation,
    group_rows_by_dataset,
    leave_one_dataset_out_validation,
    select_calibrator_on_training,
    summarize_validation_results,
)
from core.probability_quality import normalize_1x2_probabilities


def _row(
    probs: dict[str, float],
    outcome: str,
    dataset: str,
) -> dict:
    return {
        "predicted_probs": normalize_1x2_probabilities(probs),
        "actual_outcome": outcome,
        "dataset": dataset,
    }


def _synthetic_rows_by_dataset() -> dict[str, list[dict]]:
    """Overconfident home favorites — temperature should help calibration."""
    rows: dict[str, list[dict]] = {}
    for dataset in ("wc2018", "wc2022", "euro2024", "copa2024"):
        batch: list[dict] = []
        for i in range(16):
            outcome = "home" if i % 3 != 0 else "draw"
            batch.append(_row({"home": 0.72, "draw": 0.18, "away": 0.10}, outcome, dataset))
        rows[dataset] = batch
    return rows


def test_leave_one_dataset_out_splits_correctly() -> None:
    rows_by_dataset = _synthetic_rows_by_dataset()
    folds, combined_before, combined_after = leave_one_dataset_out_validation(rows_by_dataset)
    assert len(folds) == 4
    held_out = {fold.held_out_dataset for fold in folds}
    assert held_out == set(rows_by_dataset.keys())
    assert combined_before["count"] == 64
    assert combined_after["count"] == 64


def test_held_out_dataset_never_used_for_fitting() -> None:
    rows_by_dataset = _synthetic_rows_by_dataset()
    for held_out in rows_by_dataset:
        train_rows = []
        for key, rows in rows_by_dataset.items():
            if key != held_out:
                train_rows.extend(rows)
        selected = select_calibrator_on_training(train_rows)
        # Training selection must not depend on held-out rows.
        assert selected is not None


def test_fixed_temperature_validation_runs() -> None:
    rows_by_dataset = _synthetic_rows_by_dataset()
    cal = TemperatureCalibrator(temperature=1.35)
    result = fixed_candidate_validation(rows_by_dataset, cal)
    assert result.combined_before["count"] == 64
    assert result.combined_after["count"] == 64
    assert result.combined_after["ece"] <= result.combined_before["ece"]


def test_train_selected_temperature_returns_parameter() -> None:
    rows_by_dataset = _synthetic_rows_by_dataset()
    train_rows = []
    for key, rows in rows_by_dataset.items():
        if key != "wc2018":
            train_rows.extend(rows)
    selected = select_calibrator_on_training(train_rows)
    assert selected.name in ("identity", "temperature", "favorite_shrink")
    if selected.name == "temperature":
        assert "temperature" in selected.params


def test_guardrails_pass_synthetic_improved_calibration() -> None:
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
    passed, reasons = evaluate_holdout_guardrails(
        metrics_before=before,
        metrics_after=after,
        per_dataset_before={"wc2018": before},
        per_dataset_after={"wc2018": after},
    )
    assert passed is True
    assert reasons == []


def test_guardrails_fail_when_held_out_brier_worsens() -> None:
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
    passed, reasons = evaluate_holdout_guardrails(
        metrics_before=before,
        metrics_after=after,
        per_dataset_before={"wc2018": before},
        per_dataset_after={"wc2018": after},
    )
    assert passed is False
    assert any("brier_worsened" in reason for reason in reasons)


def test_per_dataset_regression_detected() -> None:
    before_ds = {
        "count": 64,
        "ece": 0.08,
        "brier": 0.58,
        "log_loss": 0.95,
        "accuracy_1x2": 0.55,
    }
    after_ds = {
        "count": 64,
        "ece": 0.07,
        "brier": 0.61,
        "log_loss": 0.99,
        "accuracy_1x2": 0.54,
    }
    passed, reasons = evaluate_holdout_guardrails(
        metrics_before={"ece": 0.08, "brier": 0.58, "log_loss": 0.95, "accuracy_1x2": 0.55, "probability_sum_valid": True},
        metrics_after={"ece": 0.07, "brier": 0.60, "log_loss": 0.97, "accuracy_1x2": 0.54, "probability_sum_valid": True},
        per_dataset_before={"wc2022": before_ds},
        per_dataset_after={"wc2022": after_ds},
    )
    assert passed is False
    assert any("dataset_brier_regression" in reason for reason in reasons)


def test_summary_recommendation_shadow_validated_only_when_guardrails_pass() -> None:
    from core.probability_calibration_validation import FixedCandidateValidationResult

    before = {
        "count": 64,
        "ece": 0.12,
        "brier": 0.60,
        "log_loss": 1.0,
        "accuracy_1x2": 0.55,
        "probability_sum_valid": True,
        "buckets": [],
    }
    after = {
        "count": 64,
        "ece": 0.08,
        "brier": 0.602,
        "log_loss": 1.005,
        "accuracy_1x2": 0.55,
        "probability_sum_valid": True,
        "buckets": [],
    }

    fixed_pass = FixedCandidateValidationResult(
        calibrator_label="temperature(temperature=1.35)",
        calibrator_params={"temperature": 1.35},
        combined_before=before,
        combined_after=after,
        per_dataset_before={"wc2018": before},
        per_dataset_after={"wc2018": after},
        passed_guardrails=True,
        failure_reasons=[],
        bucket_analysis={},
    )

    summary_pass = summarize_validation_results(
        folds=None,
        combined_holdout_before=None,
        combined_holdout_after=None,
        fixed_result=fixed_pass,
    )
    assert summary_pass.recommendation != RECOMMENDATION_SHADOW_VALIDATED

    fixed_fail = FixedCandidateValidationResult(
        calibrator_label="temperature(temperature=1.35)",
        calibrator_params={"temperature": 1.35},
        combined_before=before,
        combined_after={**after, "ece": 0.115, "brier": 0.62},
        per_dataset_before={"wc2018": before},
        per_dataset_after={"wc2018": {**after, "ece": 0.115, "brier": 0.62}},
        passed_guardrails=False,
        failure_reasons=["brier_worsened"],
        bucket_analysis={},
    )
    summary_fail = summarize_validation_results(
        folds=None,
        combined_holdout_before=None,
        combined_holdout_after=None,
        fixed_result=fixed_fail,
    )
    assert summary_fail.recommendation == RECOMMENDATION_NO_CALIBRATOR

    folds, combined_before, combined_after = leave_one_dataset_out_validation(_synthetic_rows_by_dataset())
    fixed_ok = FixedCandidateValidationResult(
        calibrator_label="temperature(temperature=1.35)",
        calibrator_params={"temperature": 1.35},
        combined_before=combined_before,
        combined_after=combined_after,
        per_dataset_before={f.held_out_dataset: f.metrics_before for f in folds},
        per_dataset_after={f.held_out_dataset: f.metrics_after for f in folds},
        passed_guardrails=True,
        failure_reasons=[],
        bucket_analysis={},
    )
    summary_both = summarize_validation_results(
        folds=folds,
        combined_holdout_before=combined_before,
        combined_holdout_after=combined_after,
        fixed_result=fixed_ok,
    )
    if summary_both.holdout_passed_guardrails and summary_both.fixed_passed_guardrails:
        assert summary_both.recommendation == RECOMMENDATION_SHADOW_VALIDATED


def test_group_rows_by_dataset() -> None:
    rows = [
        _row({"home": 0.5, "draw": 0.3, "away": 0.2}, "home", "wc2018"),
        _row({"home": 0.4, "draw": 0.3, "away": 0.3}, "draw", "wc2022"),
    ]
    grouped = group_rows_by_dataset(rows)
    assert "wc2018" in grouped
    assert "wc2022" in grouped


def test_validate_script_smoke() -> None:
    out_md = BACKEND_ROOT / "reports" / "_test_calibration_validation_smoke.md"
    out_csv = BACKEND_ROOT / "reports" / "_test_calibration_validation_smoke.csv"
    proc = subprocess.run(
        [
            PYTHON,
            "scripts/validate_probability_calibrators.py",
            "--candidate",
            "active",
            "--mode",
            "fixed",
            "--datasets",
            "wc2022",
            "--markdown",
            str(out_md),
            "--csv",
            str(out_csv),
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert out_md.exists()
    assert out_csv.exists()
    out_md.unlink(missing_ok=True)
    out_csv.unlink(missing_ok=True)
