"""Phase 4F — Shadow-only probability calibration candidates (reports/tests only)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from core.probability_quality import (
    PROB_KEYS,
    ProbabilityQualityRow,
    aggregate_probability_quality,
    brier_score_1x2,
    log_loss_1x2,
    normalize_1x2_probabilities,
    predicted_outcome,
    reliability_buckets,
)

EPS = 1e-15

TEMPERATURE_GRID: tuple[float, ...] = (
    0.75,
    0.85,
    0.95,
    1.00,
    1.05,
    1.10,
    1.20,
    1.35,
    1.50,
)

FAVORITE_SHRINK_ALPHAS: tuple[float, ...] = (0.02, 0.04, 0.06, 0.08, 0.10)

# Shadow candidate guardrails (Phase 4F)
ECE_IMPROVEMENT_MIN = 0.01
BRIER_WORSEN_MAX = 0.005
LOGLOSS_WORSEN_MAX = 0.01
ACCURACY_DROP_MAX = 0.01
DATASET_REGRESSION_BRIER_MAX = 0.02
DATASET_REGRESSION_ECE_MAX = 0.03
MIN_SHADOW_SAMPLE = 50

RECOMMENDATION_NO_CALIBRATOR = "NO_CALIBRATOR"
RECOMMENDATION_SHADOW_CANDIDATE = "SHADOW_CANDIDATE_FOUND"
RECOMMENDATION_NEEDS_MORE_DATA = "NEEDS_MORE_DATA"


class Calibrator(Protocol):
    name: str
    params: dict[str, Any]

    def apply(self, probs: dict[str, float]) -> dict[str, float]: ...


@dataclass(frozen=True)
class IdentityCalibrator:
    name: str = "identity"
    params: dict[str, Any] = field(default_factory=dict)

    def apply(self, probs: dict[str, float]) -> dict[str, float]:
        return normalize_1x2_probabilities(probs)


@dataclass(frozen=True)
class TemperatureCalibrator:
    temperature: float
    name: str = "temperature"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", {"temperature": self.temperature})

    def apply(self, probs: dict[str, float]) -> dict[str, float]:
        p = normalize_1x2_probabilities(probs)
        temp = max(float(self.temperature), EPS)
        logits = [math.log(max(p[key], EPS)) for key in PROB_KEYS]
        scaled = [math.exp(logit / temp) for logit in logits]
        total = sum(scaled)
        if total <= 0:
            return {key: 1.0 / 3.0 for key in PROB_KEYS}
        return {key: scaled[i] / total for i, key in enumerate(PROB_KEYS)}


@dataclass(frozen=True)
class FavoriteShrinkCalibrator:
    alpha: float
    name: str = "favorite_shrink"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", {"alpha": self.alpha})

    def apply(self, probs: dict[str, float]) -> dict[str, float]:
        p = normalize_1x2_probabilities(probs)
        alpha = min(max(float(self.alpha), 0.0), 1.0)
        if alpha <= 0:
            return dict(p)
        favorite = max(PROB_KEYS, key=lambda key: p[key])
        uniform = 1.0 / 3.0
        shift = alpha * max(p[favorite] - uniform, 0.0)
        if shift <= 0:
            return dict(p)
        new = dict(p)
        new[favorite] = p[favorite] - shift
        others = [key for key in PROB_KEYS if key != favorite]
        other_sum = sum(p[key] for key in others)
        if other_sum > EPS:
            for key in others:
                new[key] = p[key] + shift * (p[key] / other_sum)
        else:
            share = shift / len(others)
            for key in others:
                new[key] = p[key] + share
        return normalize_1x2_probabilities(new)


# BucketSmoothingCalibrator — deferred (small-sample overfit risk).
# IsotonicCalibrator — deferred (no sklearn in requirements).


@dataclass
class CalibrationEvaluationResult:
    calibrator_name: str
    params: dict[str, Any]
    metrics_before: dict[str, Any]
    metrics_after: dict[str, Any]
    per_dataset_before: dict[str, dict[str, Any]]
    per_dataset_after: dict[str, dict[str, Any]]
    passed_guardrails: bool
    failure_reasons: list[str]
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibrator_name": self.calibrator_name,
            "params": self.params,
            "metrics_before": self.metrics_before,
            "metrics_after": self.metrics_after,
            "per_dataset_before": self.per_dataset_before,
            "per_dataset_after": self.per_dataset_after,
            "passed_guardrails": self.passed_guardrails,
            "failure_reasons": self.failure_reasons,
            "recommendation": self.recommendation,
        }


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


def apply_calibrator_to_rows(
    rows: Iterable[ProbabilityQualityRow | dict[str, Any]],
    calibrator: Calibrator,
) -> list[dict[str, Any]]:
    normalized = _rows_as_dicts(rows)
    calibrated: list[dict[str, Any]] = []
    for row in normalized:
        calibrated.append(
            {
                "predicted_probs": calibrator.apply(row["predicted_probs"]),
                "actual_outcome": row["actual_outcome"],
                "dataset": row.get("dataset"),
            }
        )
    return calibrated


def _mean_log_loss(rows: list[dict[str, Any]], calibrator: Calibrator) -> float:
    if not rows:
        return float("inf")
    total = 0.0
    for row in rows:
        probs = calibrator.apply(row["predicted_probs"])
        total += log_loss_1x2(probs, row["actual_outcome"])
    return total / len(rows)


def _per_dataset_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("dataset") or "unknown")
        grouped.setdefault(key, []).append(row)
    return {key: aggregate_probability_quality(items) for key, items in grouped.items()}


def _max_calibration_gap(buckets: list[dict[str, Any]]) -> float:
    if not buckets:
        return 0.0
    return round(max(abs(float(bucket["calibration_gap"])) for bucket in buckets), 4)


def fit_calibrator(
    rows: Iterable[ProbabilityQualityRow | dict[str, Any]],
    candidate_type: str,
    params: dict[str, Any] | None = None,
) -> Calibrator:
    data = _rows_as_dicts(rows)
    params = params or {}

    if candidate_type == "identity":
        return IdentityCalibrator()

    if candidate_type == "temperature":
        if "temperature" in params:
            return TemperatureCalibrator(temperature=float(params["temperature"]))
        best_t = 1.0
        best_loss = float("inf")
        for temp in TEMPERATURE_GRID:
            cal = TemperatureCalibrator(temperature=temp)
            loss = _mean_log_loss(data, cal)
            if loss < best_loss:
                best_loss = loss
                best_t = temp
        return TemperatureCalibrator(temperature=best_t)

    if candidate_type == "favorite_shrink":
        if "alpha" in params:
            return FavoriteShrinkCalibrator(alpha=float(params["alpha"]))
        best_alpha = 0.0
        best_ece = float("inf")
        before = aggregate_probability_quality(data)
        for alpha in FAVORITE_SHRINK_ALPHAS:
            cal = FavoriteShrinkCalibrator(alpha=alpha)
            after = aggregate_probability_quality(apply_calibrator_to_rows(data, cal))
            if after["ece"] < best_ece and after["brier"] <= before["brier"] + BRIER_WORSEN_MAX:
                best_ece = after["ece"]
                best_alpha = alpha
        return FavoriteShrinkCalibrator(alpha=best_alpha)

    raise ValueError(f"Unknown calibrator type: {candidate_type}")


def evaluate_guardrails(
    *,
    metrics_before: dict[str, Any],
    metrics_after: dict[str, Any],
    per_dataset_before: dict[str, dict[str, Any]],
    per_dataset_after: dict[str, dict[str, Any]],
) -> tuple[bool, list[str]]:
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
        if ds_brier_delta > DATASET_REGRESSION_BRIER_MAX:
            reasons.append(f"dataset_brier_regression:{dataset}:{ds_brier_delta:.4f}")
        if ds_ece_delta > DATASET_REGRESSION_ECE_MAX:
            reasons.append(f"dataset_ece_regression:{dataset}:{ds_ece_delta:.4f}")

    return (len(reasons) == 0, reasons)


def evaluate_calibrator(
    rows: Iterable[ProbabilityQualityRow | dict[str, Any]],
    calibrator: Calibrator,
) -> CalibrationEvaluationResult:
    data = _rows_as_dicts(rows)
    metrics_before = aggregate_probability_quality(data)
    calibrated = apply_calibrator_to_rows(data, calibrator)
    metrics_after = aggregate_probability_quality(calibrated)
    metrics_after["probability_sum_valid"] = _rows_probability_sums_valid(calibrated)
    per_dataset_before = _per_dataset_metrics(data)
    per_dataset_after = _per_dataset_metrics(calibrated)
    passed, failure_reasons = evaluate_guardrails(
        metrics_before=metrics_before,
        metrics_after=metrics_after,
        per_dataset_before=per_dataset_before,
        per_dataset_after=per_dataset_after,
    )

    metrics_before = dict(metrics_before)
    metrics_before["probability_sum_valid"] = _rows_probability_sums_valid(data)
    metrics_after = dict(metrics_after)
    metrics_before["max_calibration_gap"] = _max_calibration_gap(metrics_before.get("buckets", []))
    metrics_after["max_calibration_gap"] = _max_calibration_gap(metrics_after.get("buckets", []))

    recommendation = RECOMMENDATION_NO_CALIBRATOR
    if len(data) < MIN_SHADOW_SAMPLE:
        recommendation = RECOMMENDATION_NEEDS_MORE_DATA
    elif passed:
        recommendation = RECOMMENDATION_SHADOW_CANDIDATE

    return CalibrationEvaluationResult(
        calibrator_name=calibrator.name,
        params=dict(calibrator.params),
        metrics_before=metrics_before,
        metrics_after=metrics_after,
        per_dataset_before=per_dataset_before,
        per_dataset_after=per_dataset_after,
        passed_guardrails=passed,
        failure_reasons=failure_reasons,
        recommendation=recommendation,
    )


def _rows_probability_sums_valid(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        total = sum(float(v) for v in row["predicted_probs"].values())
        if abs(total - 1.0) > 0.02:
            return False
    return True


def search_shadow_calibrators(
    rows: Iterable[ProbabilityQualityRow | dict[str, Any]],
) -> list[CalibrationEvaluationResult]:
    """Evaluate identity, temperature grid, and favorite-shrink grid."""
    data = list(rows)
    results: list[CalibrationEvaluationResult] = []

    results.append(evaluate_calibrator(data, IdentityCalibrator()))
    for temp in TEMPERATURE_GRID:
        results.append(evaluate_calibrator(data, TemperatureCalibrator(temperature=temp)))
    for alpha in FAVORITE_SHRINK_ALPHAS:
        results.append(evaluate_calibrator(data, FavoriteShrinkCalibrator(alpha=alpha)))

    return results


def pick_best_shadow_calibrator(
    results: list[CalibrationEvaluationResult],
) -> CalibrationEvaluationResult | None:
    passing = [r for r in results if r.passed_guardrails]
    if not passing:
        return None
    return min(passing, key=lambda r: (r.metrics_after["ece"], r.metrics_after["brier"]))


def overall_recommendation(
    rows: list[ProbabilityQualityRow],
    results: list[CalibrationEvaluationResult],
) -> str:
    if len(rows) < MIN_SHADOW_SAMPLE:
        return RECOMMENDATION_NEEDS_MORE_DATA
    if pick_best_shadow_calibrator(results) is not None:
        return RECOMMENDATION_SHADOW_CANDIDATE
    return RECOMMENDATION_NO_CALIBRATOR
