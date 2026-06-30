"""Unified backtest metrics for Priority 1 model evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.probability_quality import (
    PROB_KEYS,
    brier_score_1x2,
    log_loss_1x2,
    normalize_1x2_probabilities,
    predicted_outcome,
    predicted_confidence,
    reliability_buckets,
    rps_1x2,
)

# Ordered 1X2 for Ranked Probability Score (documented assumption).
RPS_OUTCOME_ORDER: tuple[str, ...] = ("home", "draw", "away")

UNIFORM_BUCKET_EDGES: tuple[float, ...] = tuple(i / 10 for i in range(1, 11))


@dataclass
class BacktestMatchRow:
    """One evaluated match for aggregate metrics."""

    predicted_probs: dict[str, float]
    actual_outcome: str
    actual_score: str | None = None
    predicted_scorelines: list[str] = field(default_factory=list)
    dataset: str | None = None
    variant: str | None = None


def outcome_from_goals(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if away_goals > home_goals:
        return "away"
    return "draw"


def accuracy_1x2(predicted_probs: dict[str, float], actual_outcome: str) -> bool:
    return predicted_outcome(predicted_probs) == actual_outcome


def rps_1x2(predicted_probs: dict[str, float], actual_outcome: str) -> float:
    """Re-export from probability_quality for backtest module consumers."""
    from core.probability_quality import rps_1x2 as _rps

    return _rps(predicted_probs, actual_outcome)


def top_k_scoreline_hit(
    predicted_scorelines: list[str],
    actual_score: str,
    *,
    k: int,
) -> bool:
    if not predicted_scorelines or not actual_score:
        return False
    return actual_score in predicted_scorelines[: max(1, k)]


def scorelines_from_matrix(all_scores: dict[str, float], *, top_k: int = 5) -> list[str]:
    """Sort matrix scorelines by probability (percent keys like '2-1')."""
    if not all_scores:
        return []
    ordered = sorted(all_scores.items(), key=lambda item: item[1], reverse=True)
    return [label for label, _ in ordered[:top_k]]


def uniform_reliability_bins(
    rows: Iterable[BacktestMatchRow | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Winner-confidence bins on 0.00–1.00 decile edges."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, BacktestMatchRow):
            normalized.append(
                {
                    "predicted_probs": row.predicted_probs,
                    "actual_outcome": row.actual_outcome,
                }
            )
        else:
            normalized.append(
                {
                    "predicted_probs": normalize_1x2_probabilities(row["predicted_probs"]),
                    "actual_outcome": row["actual_outcome"],
                }
            )

    bins: dict[str, list[dict[str, Any]]] = {}
    for low, high in zip((0.0, *UNIFORM_BUCKET_EDGES[:-1]), UNIFORM_BUCKET_EDGES):
        label = f"{low:.2f}-{high:.2f}"
        bins[label] = []

    for row in normalized:
        conf = predicted_confidence(row["predicted_probs"])
        for low, high in zip((0.0, *UNIFORM_BUCKET_EDGES[:-1]), UNIFORM_BUCKET_EDGES):
            if low - 1e-12 <= conf <= high + 1e-12:
                label = f"{low:.2f}-{high:.2f}"
                bins.setdefault(label, []).append(row)
                break

    out: list[dict[str, Any]] = []
    for label in sorted(bins.keys()):
        items = bins[label]
        if not items:
            continue
        confidences = [predicted_confidence(item["predicted_probs"]) for item in items]
        hits = [
            1.0 if predicted_outcome(item["predicted_probs"]) == item["actual_outcome"] else 0.0
            for item in items
        ]
        out.append(
            {
                "bucket": label,
                "count": len(items),
                "predicted_avg_probability": round(sum(confidences) / len(confidences), 4),
                "actual_hit_rate": round(sum(hits) / len(hits), 4),
                "calibration_gap": round(
                    sum(confidences) / len(confidences) - sum(hits) / len(hits), 4
                ),
            }
        )
    return out


def per_class_calibration_summary(
    rows: Iterable[BacktestMatchRow | dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """Mean predicted vs empirical hit rate per outcome class."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, BacktestMatchRow):
            normalized.append(
                {
                    "predicted_probs": normalize_1x2_probabilities(row.predicted_probs),
                    "actual_outcome": row.actual_outcome,
                }
            )
        else:
            normalized.append(
                {
                    "predicted_probs": normalize_1x2_probabilities(row["predicted_probs"]),
                    "actual_outcome": row["actual_outcome"],
                }
            )

    summary: dict[str, dict[str, float]] = {}
    for key in PROB_KEYS:
        probs = [row["predicted_probs"][key] for row in normalized]
        hits = [1.0 if row["actual_outcome"] == key else 0.0 for row in normalized]
        if not probs:
            continue
        summary[key] = {
            "mean_predicted": round(sum(probs) / len(probs), 4),
            "empirical_rate": round(sum(hits) / len(hits), 4),
            "count": len(probs),
        }
    return summary


def aggregate_backtest_metrics(
    rows: Iterable[BacktestMatchRow | dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate 1X2 + scoreline metrics for a list of evaluated matches."""
    materialized: list[BacktestMatchRow] = []
    for row in rows:
        if isinstance(row, BacktestMatchRow):
            materialized.append(row)
        else:
            materialized.append(
                BacktestMatchRow(
                    predicted_probs=row["predicted_probs"],
                    actual_outcome=row["actual_outcome"],
                    actual_score=row.get("actual_score"),
                    predicted_scorelines=list(row.get("predicted_scorelines") or []),
                    dataset=row.get("dataset"),
                    variant=row.get("variant"),
                )
            )

    if not materialized:
        return {
            "count": 0,
            "accuracy_1x2": 0.0,
            "log_loss": 0.0,
            "brier": 0.0,
            "rps": 0.0,
            "top3_scoreline_coverage": 0.0,
            "top5_scoreline_coverage": 0.0,
            "reliability_buckets": [],
            "uniform_bins": [],
            "per_class_calibration": {},
        }

    n = len(materialized)
    hits = [
        accuracy_1x2(row.predicted_probs, row.actual_outcome) for row in materialized
    ]
    briers = [
        brier_score_1x2(row.predicted_probs, row.actual_outcome) for row in materialized
    ]
    losses = [
        log_loss_1x2(row.predicted_probs, row.actual_outcome) for row in materialized
    ]
    rps_vals = [
        rps_1x2(row.predicted_probs, row.actual_outcome) for row in materialized
    ]

    top3_hits = []
    top5_hits = []
    for row in materialized:
        if row.actual_score and row.predicted_scorelines:
            top3_hits.append(
                top_k_scoreline_hit(row.predicted_scorelines, row.actual_score, k=3)
            )
            top5_hits.append(
                top_k_scoreline_hit(row.predicted_scorelines, row.actual_score, k=5)
            )

    dict_rows = [
        {
            "predicted_probs": row.predicted_probs,
            "actual_outcome": row.actual_outcome,
        }
        for row in materialized
    ]

    return {
        "count": n,
        "accuracy_1x2": round(sum(hits) / n, 4),
        "log_loss": round(sum(losses) / n, 4),
        "brier": round(sum(briers) / n, 4),
        "rps": round(sum(rps_vals) / n, 4),
        "top3_scoreline_coverage": round(sum(top3_hits) / len(top3_hits), 4)
        if top3_hits
        else None,
        "top5_scoreline_coverage": round(sum(top5_hits) / len(top5_hits), 4)
        if top5_hits
        else None,
        "reliability_buckets": reliability_buckets(dict_rows),
        "uniform_bins": uniform_reliability_bins(materialized),
        "per_class_calibration": per_class_calibration_summary(materialized),
    }


def compare_metrics_to_baseline(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Delta table for key scalar metrics."""
    keys = (
        "accuracy_1x2",
        "log_loss",
        "brier",
        "rps",
        "top3_scoreline_coverage",
        "top5_scoreline_coverage",
    )
    out: dict[str, dict[str, Any]] = {}
    for key in keys:
        cand_val = candidate.get(key)
        base_val = baseline.get(key)
        if cand_val is None or base_val is None:
            out[key] = {
                "candidate": cand_val,
                "baseline": base_val,
                "delta": None,
                "verdict": "neutral",
            }
            continue
        delta = round(float(cand_val) - float(base_val), 4)
        if key in ("log_loss", "brier", "rps"):
            verdict = "improved" if delta < -1e-6 else "regressed" if delta > 1e-6 else "neutral"
        else:
            verdict = "improved" if delta > 1e-6 else "regressed" if delta < -1e-6 else "neutral"
        out[key] = {
            "candidate": cand_val,
            "baseline": base_val,
            "delta": delta,
            "verdict": verdict,
        }
    return out
