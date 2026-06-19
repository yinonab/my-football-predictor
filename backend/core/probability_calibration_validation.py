"""Phase 4G — Out-of-sample calibration validation (reports/tests only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from core.probability_calibration import (
    BRIER_WORSEN_MAX,
    ECE_IMPROVEMENT_MIN,
    FAVORITE_SHRINK_ALPHAS,
    LOGLOSS_WORSEN_MAX,
    TEMPERATURE_GRID,
    Calibrator,
    FavoriteShrinkCalibrator,
    IdentityCalibrator,
    TemperatureCalibrator,
    apply_calibrator_to_rows,
    evaluate_guardrails,
)
from core.probability_quality import (
    ProbabilityQualityRow,
    aggregate_probability_quality,
    reliability_buckets,
)

ACCURACY_DROP_MAX = 0.01
DATASET_REGRESSION_BRIER_MAX = 0.02
DATASET_REGRESSION_LOGLOSS_MAX = 0.03
DATASET_REGRESSION_ECE_MAX = 0.03
MIN_HOLDOUT_COMBINED_SAMPLE = 50
MIN_HOLDOUT_DATASET_SAMPLE = 20
SMALL_SAMPLE_ECE_EXEMPT = MIN_HOLDOUT_DATASET_SAMPLE

FIXED_PHASE4F_TEMPERATURE = 1.35

RECOMMENDATION_NO_CALIBRATOR = "NO_CALIBRATOR"
RECOMMENDATION_KEEP_REPORT_ONLY = "KEEP_REPORT_ONLY"
RECOMMENDATION_SHADOW_VALIDATED = "SHADOW_VALIDATED_CANDIDATE"
RECOMMENDATION_NEEDS_MORE_DATA = "NEEDS_MORE_DATA"

EXECUTIVE_PASS = "PASS"
EXECUTIVE_HOLD = "HOLD"
EXECUTIVE_NEEDS_MORE_DATA = "NEEDS_MORE_DATA"

# Train-fold selection: lowest ECE among candidates passing in-sample guardrails.
SELECTION_CRITERION = (
    "lowest_post_calibration_ece_among_candidates_passing_in_sample_guardrails"
)


def _rows_as_dicts(rows: Iterable[ProbabilityQualityRow | dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, ProbabilityQualityRow):
            out.append(
                {
                    "predicted_probs": dict(row.predicted_probs),
                    "actual_outcome": row.actual_outcome,
                    "dataset": row.dataset,
                }
            )
        else:
            out.append(dict(row))
    return out


def group_rows_by_dataset(
    rows: Iterable[ProbabilityQualityRow | dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in _rows_as_dicts(rows):
        key = str(row.get("dataset") or "unknown")
        grouped.setdefault(key, []).append(row)
    return grouped


def _per_dataset_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("dataset") or "unknown")
        grouped.setdefault(key, []).append(row)
    return {key: aggregate_probability_quality(items) for key, items in grouped.items()}


def _rows_probability_sums_valid(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        total = sum(float(v) for v in row["predicted_probs"].values())
        if abs(total - 1.0) > 0.02:
            return False
    return True


def _calibrator_label(calibrator: Calibrator) -> str:
    if calibrator.name == "identity":
        return "identity"
    params = ", ".join(f"{k}={v}" for k, v in sorted(calibrator.params.items()))
    return f"{calibrator.name}({params})"


def _training_candidates() -> list[Calibrator]:
    candidates: list[Calibrator] = [IdentityCalibrator()]
    candidates.extend(TemperatureCalibrator(temperature=temp) for temp in TEMPERATURE_GRID)
    candidates.extend(FavoriteShrinkCalibrator(alpha=alpha) for alpha in FAVORITE_SHRINK_ALPHAS)
    return candidates


def select_calibrator_on_training(
    train_rows: Iterable[ProbabilityQualityRow | dict[str, Any]],
) -> Calibrator:
    """Pick calibrator on training folds only (lowest ECE among in-sample guardrail passers)."""
    data = _rows_as_dicts(train_rows)
    if not data:
        return IdentityCalibrator()

    best: Calibrator | None = None
    best_ece = float("inf")
    metrics_before = aggregate_probability_quality(data)

    for calibrator in _training_candidates():
        calibrated = apply_calibrator_to_rows(data, calibrator)
        metrics_after = aggregate_probability_quality(calibrated)
        metrics_after["probability_sum_valid"] = _rows_probability_sums_valid(calibrated)
        per_dataset_before = _per_dataset_metrics(data)
        per_dataset_after = _per_dataset_metrics(calibrated)
        passed, _ = evaluate_guardrails(
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            per_dataset_before=per_dataset_before,
            per_dataset_after=per_dataset_after,
        )
        if passed and float(metrics_after["ece"]) < best_ece:
            best_ece = float(metrics_after["ece"])
            best = calibrator

    return best if best is not None else IdentityCalibrator()


def worst_bucket_pair(
    buckets_before: list[dict[str, Any]],
    buckets_after: list[dict[str, Any]],
) -> dict[str, Any]:
    """Worst over/under-confident buckets before and after calibration."""
    over_before = max(buckets_before, key=lambda b: float(b["calibration_gap"]), default=None)
    under_before = min(buckets_before, key=lambda b: float(b["calibration_gap"]), default=None)
    over_after = max(buckets_after, key=lambda b: float(b["calibration_gap"]), default=None)
    under_after = min(buckets_after, key=lambda b: float(b["calibration_gap"]), default=None)
    return {
        "worst_overconfident_before": over_before,
        "worst_underconfident_before": under_before,
        "worst_overconfident_after": over_after,
        "worst_underconfident_after": under_after,
    }


def evaluate_holdout_guardrails(
    *,
    metrics_before: dict[str, Any],
    metrics_after: dict[str, Any],
    per_dataset_before: dict[str, dict[str, Any]],
    per_dataset_after: dict[str, dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Holdout guardrails with per-dataset log-loss check and small-sample ECE exemption."""
    reasons: list[str] = []

    ece_delta = float(metrics_before["ece"]) - float(metrics_after["ece"])
    if ece_delta < ECE_IMPROVEMENT_MIN:
        reasons.append(f"ece_improvement_insufficient:{ece_delta:.4f}")

    brier_delta = float(metrics_after["brier"]) - float(metrics_before["brier"])
    if brier_delta > BRIER_WORSEN_MAX:
        reasons.append(f"brier_worsened:{brier_delta:.4f}")

    logloss_delta = float(metrics_after["log_loss"]) - float(metrics_before["log_loss"])
    if logloss_delta > LOGLOSS_WORSEN_MAX:
        reasons.append(f"logloss_worsened:{logloss_delta:.4f}")

    acc_delta = float(metrics_before["accuracy_1x2"]) - float(metrics_after["accuracy_1x2"])
    if acc_delta > ACCURACY_DROP_MAX:
        reasons.append(f"accuracy_dropped:{acc_delta:.4f}")

    if not metrics_after.get("probability_sum_valid", True):
        reasons.append("invalid_probability_sums")

    for dataset, before_ds in per_dataset_before.items():
        after_ds = per_dataset_after.get(dataset)
        if not after_ds:
            continue
        ds_brier_delta = float(after_ds["brier"]) - float(before_ds["brier"])
        ds_ece_delta = float(after_ds["ece"]) - float(before_ds["ece"])
        ds_logloss_delta = float(after_ds["log_loss"]) - float(before_ds["log_loss"])
        count = int(before_ds.get("count", 0))

        if ds_brier_delta > DATASET_REGRESSION_BRIER_MAX:
            reasons.append(f"dataset_brier_regression:{dataset}:{ds_brier_delta:.4f}")
        if ds_logloss_delta > DATASET_REGRESSION_LOGLOSS_MAX:
            reasons.append(f"dataset_logloss_regression:{dataset}:{ds_logloss_delta:.4f}")
        if ds_ece_delta > DATASET_REGRESSION_ECE_MAX:
            if count < SMALL_SAMPLE_ECE_EXEMPT:
                reasons.append(
                    f"dataset_ece_regression_small_sample:{dataset}:{ds_ece_delta:.4f}:n={count}"
                )
            else:
                reasons.append(f"dataset_ece_regression:{dataset}:{ds_ece_delta:.4f}")

    blocking = [
        r
        for r in reasons
        if not r.startswith("dataset_ece_regression_small_sample:")
    ]
    return (len(blocking) == 0, reasons)


@dataclass
class HoldoutFoldResult:
    held_out_dataset: str
    train_datasets: list[str]
    train_count: int
    holdout_count: int
    selected_calibrator: str
    selected_params: dict[str, Any]
    metrics_before: dict[str, Any]
    metrics_after: dict[str, Any]
    passed_guardrails: bool
    failure_reasons: list[str]
    bucket_analysis: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "held_out_dataset": self.held_out_dataset,
            "train_datasets": self.train_datasets,
            "train_count": self.train_count,
            "holdout_count": self.holdout_count,
            "selected_calibrator": self.selected_calibrator,
            "selected_params": self.selected_params,
            "metrics_before": self.metrics_before,
            "metrics_after": self.metrics_after,
            "passed_guardrails": self.passed_guardrails,
            "failure_reasons": self.failure_reasons,
            "bucket_analysis": self.bucket_analysis,
        }


@dataclass
class FixedCandidateValidationResult:
    calibrator_label: str
    calibrator_params: dict[str, Any]
    combined_before: dict[str, Any]
    combined_after: dict[str, Any]
    per_dataset_before: dict[str, dict[str, Any]]
    per_dataset_after: dict[str, dict[str, Any]]
    passed_guardrails: bool
    failure_reasons: list[str]
    bucket_analysis: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibrator_label": self.calibrator_label,
            "calibrator_params": self.calibrator_params,
            "combined_before": self.combined_before,
            "combined_after": self.combined_after,
            "per_dataset_before": self.per_dataset_before,
            "per_dataset_after": self.per_dataset_after,
            "passed_guardrails": self.passed_guardrails,
            "failure_reasons": self.failure_reasons,
            "bucket_analysis": self.bucket_analysis,
        }


@dataclass
class ValidationSummary:
    executive_summary: str
    recommendation: str
    selection_criterion: str
    combined_holdout_before: dict[str, Any] | None = None
    combined_holdout_after: dict[str, Any] | None = None
    holdout_passed_guardrails: bool = False
    holdout_failure_reasons: list[str] = field(default_factory=list)
    fixed_passed_guardrails: bool = False
    fixed_failure_reasons: list[str] = field(default_factory=list)
    folds: list[HoldoutFoldResult] = field(default_factory=list)
    fixed_result: FixedCandidateValidationResult | None = None
    per_dataset_regressions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "executive_summary": self.executive_summary,
            "recommendation": self.recommendation,
            "selection_criterion": self.selection_criterion,
            "combined_holdout_before": self.combined_holdout_before,
            "combined_holdout_after": self.combined_holdout_after,
            "holdout_passed_guardrails": self.holdout_passed_guardrails,
            "holdout_failure_reasons": self.holdout_failure_reasons,
            "fixed_passed_guardrails": self.fixed_passed_guardrails,
            "fixed_failure_reasons": self.fixed_failure_reasons,
            "folds": [fold.to_dict() for fold in self.folds],
            "fixed_result": self.fixed_result.to_dict() if self.fixed_result else None,
            "per_dataset_regressions": self.per_dataset_regressions,
        }


def leave_one_dataset_out_validation(
    rows_by_dataset: dict[str, list[ProbabilityQualityRow | dict[str, Any]]],
) -> tuple[list[HoldoutFoldResult], dict[str, Any], dict[str, Any]]:
    """Leave-one-dataset-out: fit on 3 datasets, evaluate on the 4th."""
    folds: list[HoldoutFoldResult] = []
    pooled_before: list[dict[str, Any]] = []
    pooled_after: list[dict[str, Any]] = []

    dataset_keys = sorted(rows_by_dataset.keys())
    for held_out in dataset_keys:
        train_rows: list[dict[str, Any]] = []
        train_datasets: list[str] = []
        for key in dataset_keys:
            if key == held_out:
                continue
            train_datasets.append(key)
            train_rows.extend(_rows_as_dicts(rows_by_dataset[key]))

        holdout_rows = _rows_as_dicts(rows_by_dataset[held_out])
        selected = select_calibrator_on_training(train_rows)
        calibrated = apply_calibrator_to_rows(holdout_rows, selected)

        metrics_before = aggregate_probability_quality(holdout_rows)
        metrics_after = aggregate_probability_quality(calibrated)
        metrics_after["probability_sum_valid"] = _rows_probability_sums_valid(calibrated)
        per_before = {held_out: metrics_before}
        per_after = {held_out: metrics_after}
        passed, failure_reasons = evaluate_holdout_guardrails(
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            per_dataset_before=per_before,
            per_dataset_after=per_after,
        )

        bucket_analysis = worst_bucket_pair(
            metrics_before.get("buckets", []),
            metrics_after.get("buckets", []),
        )

        folds.append(
            HoldoutFoldResult(
                held_out_dataset=held_out,
                train_datasets=train_datasets,
                train_count=len(train_rows),
                holdout_count=len(holdout_rows),
                selected_calibrator=selected.name,
                selected_params=dict(selected.params),
                metrics_before=metrics_before,
                metrics_after=metrics_after,
                passed_guardrails=passed,
                failure_reasons=failure_reasons,
                bucket_analysis=bucket_analysis,
            )
        )
        pooled_before.extend(holdout_rows)
        pooled_after.extend(calibrated)

    combined_before = aggregate_probability_quality(pooled_before)
    combined_after = aggregate_probability_quality(pooled_after)
    combined_after["probability_sum_valid"] = _rows_probability_sums_valid(pooled_after)
    return folds, combined_before, combined_after


def fixed_candidate_validation(
    rows_by_dataset: dict[str, list[ProbabilityQualityRow | dict[str, Any]]],
    calibrator: Calibrator,
) -> FixedCandidateValidationResult:
    """Evaluate a fixed calibrator per dataset without re-fitting."""
    all_rows: list[dict[str, Any]] = []
    per_before: dict[str, dict[str, Any]] = {}
    per_after: dict[str, dict[str, Any]] = {}
    all_calibrated: list[dict[str, Any]] = []

    for dataset, rows in sorted(rows_by_dataset.items()):
        data = _rows_as_dicts(rows)
        calibrated = apply_calibrator_to_rows(data, calibrator)
        per_before[dataset] = aggregate_probability_quality(data)
        per_after[dataset] = aggregate_probability_quality(calibrated)
        all_rows.extend(data)
        all_calibrated.extend(calibrated)

    combined_before = aggregate_probability_quality(all_rows)
    combined_after = aggregate_probability_quality(all_calibrated)
    combined_after["probability_sum_valid"] = _rows_probability_sums_valid(all_calibrated)

    passed, failure_reasons = evaluate_holdout_guardrails(
        metrics_before=combined_before,
        metrics_after=combined_after,
        per_dataset_before=per_before,
        per_dataset_after=per_after,
    )

    bucket_analysis = worst_bucket_pair(
        combined_before.get("buckets", []),
        combined_after.get("buckets", []),
    )

    return FixedCandidateValidationResult(
        calibrator_label=_calibrator_label(calibrator),
        calibrator_params=dict(calibrator.params),
        combined_before=combined_before,
        combined_after=combined_after,
        per_dataset_before=per_before,
        per_dataset_after=per_after,
        passed_guardrails=passed,
        failure_reasons=failure_reasons,
        bucket_analysis=bucket_analysis,
    )


def _collect_per_dataset_regressions(
    per_before: dict[str, dict[str, Any]],
    per_after: dict[str, dict[str, Any]],
) -> list[str]:
    regressions: list[str] = []
    for dataset, before_ds in per_before.items():
        after_ds = per_after.get(dataset)
        if not after_ds:
            continue
        brier_delta = float(after_ds["brier"]) - float(before_ds["brier"])
        logloss_delta = float(after_ds["log_loss"]) - float(before_ds["log_loss"])
        ece_delta = float(after_ds["ece"]) - float(before_ds["ece"])
        if brier_delta > DATASET_REGRESSION_BRIER_MAX:
            regressions.append(f"brier:{dataset}:{brier_delta:.4f}")
        if logloss_delta > DATASET_REGRESSION_LOGLOSS_MAX:
            regressions.append(f"logloss:{dataset}:{logloss_delta:.4f}")
        count = int(before_ds.get("count", 0))
        if ece_delta > DATASET_REGRESSION_ECE_MAX and count >= SMALL_SAMPLE_ECE_EXEMPT:
            regressions.append(f"ece:{dataset}:{ece_delta:.4f}")
    return regressions


def summarize_validation_results(
    *,
    folds: list[HoldoutFoldResult] | None,
    combined_holdout_before: dict[str, Any] | None,
    combined_holdout_after: dict[str, Any] | None,
    fixed_result: FixedCandidateValidationResult | None,
) -> ValidationSummary:
    """Summarize LOO and fixed-candidate validation with evidence-based recommendation."""
    holdout_passed = False
    holdout_reasons: list[str] = []
    per_dataset_regressions: list[str] = []

    if (
        folds
        and combined_holdout_before is not None
        and combined_holdout_after is not None
    ):
        per_before = {f.held_out_dataset: f.metrics_before for f in folds}
        per_after = {f.held_out_dataset: f.metrics_after for f in folds}
        holdout_passed, holdout_reasons = evaluate_holdout_guardrails(
            metrics_before=combined_holdout_before,
            metrics_after=combined_holdout_after,
            per_dataset_before=per_before,
            per_dataset_after=per_after,
        )
        per_dataset_regressions = _collect_per_dataset_regressions(per_before, per_after)

    fixed_passed = fixed_result.passed_guardrails if fixed_result else False
    fixed_reasons = list(fixed_result.failure_reasons) if fixed_result else []

    total_count = int((combined_holdout_before or {}).get("count", 0))
    if fixed_result and total_count == 0:
        total_count = int(fixed_result.combined_before.get("count", 0))

    recommendation = RECOMMENDATION_NO_CALIBRATOR
    executive = EXECUTIVE_HOLD

    if total_count < MIN_HOLDOUT_COMBINED_SAMPLE:
        recommendation = RECOMMENDATION_NEEDS_MORE_DATA
        executive = EXECUTIVE_NEEDS_MORE_DATA
    elif holdout_passed and fixed_passed:
        recommendation = RECOMMENDATION_SHADOW_VALIDATED
        executive = EXECUTIVE_PASS
    elif holdout_passed or fixed_passed:
        recommendation = RECOMMENDATION_KEEP_REPORT_ONLY
        executive = EXECUTIVE_HOLD
    else:
        recommendation = RECOMMENDATION_NO_CALIBRATOR
        executive = EXECUTIVE_HOLD

    return ValidationSummary(
        executive_summary=executive,
        recommendation=recommendation,
        selection_criterion=SELECTION_CRITERION,
        combined_holdout_before=combined_holdout_before,
        combined_holdout_after=combined_holdout_after,
        holdout_passed_guardrails=holdout_passed,
        holdout_failure_reasons=holdout_reasons,
        fixed_passed_guardrails=fixed_passed,
        fixed_failure_reasons=fixed_reasons,
        folds=folds or [],
        fixed_result=fixed_result,
        per_dataset_regressions=per_dataset_regressions,
    )
