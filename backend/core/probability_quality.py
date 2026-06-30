"""Phase 4E — Probability quality metrics (calibration reports only)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

DEFAULT_BUCKET_EDGES: tuple[float, ...] = (
    0.30,
    0.40,
    0.50,
    0.60,
    0.70,
    0.80,
    0.90,
    1.00,
)

PROB_KEYS = ("home", "draw", "away")
API_TO_INTERNAL = {"home_win": "home", "draw": "draw", "away_win": "away"}

OVERCONFIDENT_GAP_THRESHOLD = 0.08
UNDERCONFIDENT_GAP_THRESHOLD = 0.08
MIN_BUCKET_WARNING_COUNT = 10
LOW_BUCKET_COUNT_THRESHOLD = 5
MIN_CALIBRATION_SAMPLE = 20

WARNING_OVERCONFIDENT_FAVORITES = "OVERCONFIDENT_FAVORITES"
WARNING_UNDERCONFIDENT_FAVORITES = "UNDERCONFIDENT_FAVORITES"
WARNING_LOW_BUCKET_COUNT = "LOW_BUCKET_COUNT"
WARNING_CALIBRATION_SAMPLE_TOO_SMALL = "CALIBRATION_SAMPLE_TOO_SMALL"

BASELINE_WALK_FORWARD_CONFIG: dict[str, str] = {
    "candidate": "baseline",
    "elo_strategy": "internal_only",
    "external_rating_mode": "none",
    "prior_mode": "default_internal",
}

ACTIVE_WALK_FORWARD_CONFIG: dict[str, str] = {
    "candidate": "effective_external_current_formula",
    "elo_strategy": "fifa_points_confidence_weighted",
    "external_rating_mode": "fifa_points_snapshot",
    "prior_mode": "tournament_prior_file",
}

DEFAULT_QUALITY_DATASETS: tuple[str, ...] = (
    "wc2018",
    "wc2022",
    "euro2024",
    "copa2024",
)


@dataclass
class ProbabilityQualityRow:
    predicted_probs: dict[str, float]
    actual_outcome: str
    dataset: str | None = None
    candidate: str | None = None


def _coerce_probs_dict(probs: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for api_key, internal_key in API_TO_INTERNAL.items():
        if api_key in probs:
            out[internal_key] = float(probs[api_key])
        elif internal_key in probs:
            out[internal_key] = float(probs[internal_key])
    if not out:
        return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    return out


def normalize_1x2_probabilities(probs: dict[str, float]) -> dict[str, float]:
    """Normalize home/draw/away probabilities to sum to 1.0."""
    raw = _coerce_probs_dict(probs)
    cleaned: dict[str, float] = {}
    for key in PROB_KEYS:
        value = raw.get(key, 0.0)
        if not math.isfinite(value) or value < 0:
            value = 0.0
        cleaned[key] = value

    total = sum(cleaned.values())
    if total <= 0:
        return {key: 1.0 / 3.0 for key in PROB_KEYS}

    if total > 1.5:
        cleaned = {key: value / 100.0 for key, value in cleaned.items()}
        total = sum(cleaned.values())

    if total <= 0:
        return {key: 1.0 / 3.0 for key in PROB_KEYS}

    return {key: cleaned[key] / total for key in PROB_KEYS}


def predicted_outcome(predicted_probs: dict[str, float]) -> str:
    probs = normalize_1x2_probabilities(predicted_probs)
    return max(PROB_KEYS, key=lambda key: probs[key])


def predicted_confidence(predicted_probs: dict[str, float]) -> float:
    probs = normalize_1x2_probabilities(predicted_probs)
    return max(probs.values())


def brier_score_1x2(predicted_probs: dict[str, float], actual_outcome: str) -> float:
    probs = normalize_1x2_probabilities(predicted_probs)
    actual = actual_outcome if actual_outcome in PROB_KEYS else "draw"
    return sum(
        (probs[key] - (1.0 if key == actual else 0.0)) ** 2 for key in PROB_KEYS
    )


def log_loss_1x2(
    predicted_probs: dict[str, float],
    actual_outcome: str,
    *,
    eps: float = 1e-15,
) -> float:
    probs = normalize_1x2_probabilities(predicted_probs)
    actual = actual_outcome if actual_outcome in PROB_KEYS else "draw"
    p = max(probs.get(actual, 0.0), eps)
    return -math.log(p)


def rps_1x2(predicted_probs: dict[str, float], actual_outcome: str) -> float:
    """Ranked Probability Score with documented order: HOME → DRAW → AWAY."""
    probs = normalize_1x2_probabilities(predicted_probs)
    actual = actual_outcome if actual_outcome in PROB_KEYS else "draw"
    order = PROB_KEYS
    cum_forecast: list[float] = []
    running = 0.0
    for key in order:
        running += probs[key]
        cum_forecast.append(running)
    cum_actual = [
        1.0 if order.index(actual) <= idx else 0.0 for idx in range(len(order))
    ]
    return sum(
        (cum_forecast[i] - cum_actual[i]) ** 2 for i in range(len(order) - 1)
    )


def _bucket_label(edges: tuple[float, ...], confidence: float) -> str:
    for edge in edges:
        if confidence <= edge + 1e-12:
            return f"<= {edge:.2f}"
    return f"> {edges[-1]:.2f}"


def _rows_to_normalized(rows: Iterable[dict[str, Any] | ProbabilityQualityRow]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, ProbabilityQualityRow):
            normalized_rows.append(
                {
                    "predicted_probs": row.predicted_probs,
                    "actual_outcome": row.actual_outcome,
                }
            )
        else:
            normalized_rows.append(
                {
                    "predicted_probs": normalize_1x2_probabilities(row["predicted_probs"]),
                    "actual_outcome": row["actual_outcome"],
                }
            )
    return normalized_rows


def reliability_buckets(
    rows: Iterable[dict[str, Any] | ProbabilityQualityRow],
    bucket_edges: tuple[float, ...] | None = None,
) -> list[dict[str, Any]]:
    edges = bucket_edges or DEFAULT_BUCKET_EDGES
    normalized = _rows_to_normalized(rows)
    grouped: dict[str, list[dict[str, Any]]] = { _bucket_label(edges, edge): [] for edge in edges }
    grouped[f"> {edges[-1]:.2f}"] = []

    for row in normalized:
        confidence = predicted_confidence(row["predicted_probs"])
        label = _bucket_label(edges, confidence)
        grouped.setdefault(label, []).append(row)

    buckets: list[dict[str, Any]] = []
    for label in sorted(grouped.keys(), key=lambda item: item):
        items = grouped[label]
        if not items:
            continue
        confidences = [predicted_confidence(item["predicted_probs"]) for item in items]
        hits = [
            1.0
            if predicted_outcome(item["predicted_probs"]) == item["actual_outcome"]
            else 0.0
            for item in items
        ]
        briers = [
            brier_score_1x2(item["predicted_probs"], item["actual_outcome"])
            for item in items
        ]
        avg_conf = sum(confidences) / len(confidences)
        empirical = sum(hits) / len(hits)
        buckets.append(
            {
                "bucket": label,
                "count": len(items),
                "average_confidence": round(avg_conf, 4),
                "empirical_accuracy": round(empirical, 4),
                "calibration_gap": round(avg_conf - empirical, 4),
                "average_brier": round(sum(briers) / len(briers), 4),
            }
        )
    return buckets


def expected_calibration_error(
    rows: Iterable[dict[str, Any] | ProbabilityQualityRow],
    bucket_edges: tuple[float, ...] | None = None,
) -> float:
    buckets = reliability_buckets(rows, bucket_edges=bucket_edges)
    total = sum(bucket["count"] for bucket in buckets)
    if total == 0:
        return 0.0
    weighted = sum(
        bucket["count"] * abs(bucket["calibration_gap"]) for bucket in buckets
    )
    return round(weighted / total, 4)


def favorite_bucket_calibration(
    rows: Iterable[dict[str, Any] | ProbabilityQualityRow],
) -> list[dict[str, Any]]:
    """Favorite-confidence buckets using legacy-style cutoffs on 0–100 scale."""
    favorite_edges = (50.0, 60.0, 70.0, 80.0, 100.0)
    normalized = _rows_to_normalized(rows)
    grouped: dict[str, list[dict[str, Any]]] = {}

    for row in normalized:
        probs_pct = {
            key: value * 100.0 for key, value in row["predicted_probs"].items()
        }
        fav_prob = max(probs_pct.values()) / 100.0
        label = None
        if fav_prob >= 0.80:
            label = "80+"
        elif fav_prob >= 0.70:
            label = "70-80"
        elif fav_prob >= 0.60:
            label = "60-70"
        elif fav_prob >= 0.50:
            label = "50-60"
        else:
            continue
        grouped.setdefault(label, []).append(row)

    out: list[dict[str, Any]] = []
    for label in ("50-60", "60-70", "70-80", "80+"):
        items = grouped.get(label, [])
        if not items:
            continue
        confidences = [predicted_confidence(item["predicted_probs"]) for item in items]
        hits = [
            1.0
            if predicted_outcome(item["predicted_probs"]) == item["actual_outcome"]
            else 0.0
            for item in items
        ]
        avg_conf = sum(confidences) / len(confidences)
        empirical = sum(hits) / len(hits)
        out.append(
            {
                "bucket": label,
                "count": len(items),
                "average_confidence": round(avg_conf, 4),
                "empirical_accuracy": round(empirical, 4),
                "calibration_gap": round(avg_conf - empirical, 4),
            }
        )
    return out


def evaluate_calibration_warnings(
    rows: Iterable[dict[str, Any] | ProbabilityQualityRow],
    *,
    buckets: list[dict[str, Any]] | None = None,
) -> list[str]:
    normalized = list(_rows_to_normalized(rows))
    warnings: list[str] = []
    if len(normalized) < MIN_CALIBRATION_SAMPLE:
        warnings.append(WARNING_CALIBRATION_SAMPLE_TOO_SMALL)

    bucket_rows = buckets if buckets is not None else reliability_buckets(normalized)
    for bucket in bucket_rows:
        count = int(bucket["count"])
        gap = float(bucket["calibration_gap"])
        if count < LOW_BUCKET_COUNT_THRESHOLD:
            warnings.append(f"{WARNING_LOW_BUCKET_COUNT}:{bucket['bucket']}")
        if count >= MIN_BUCKET_WARNING_COUNT and gap >= OVERCONFIDENT_GAP_THRESHOLD:
            warnings.append(f"{WARNING_OVERCONFIDENT_FAVORITES}:{bucket['bucket']}")
        if count >= MIN_BUCKET_WARNING_COUNT and gap <= -UNDERCONFIDENT_GAP_THRESHOLD:
            warnings.append(f"{WARNING_UNDERCONFIDENT_FAVORITES}:{bucket['bucket']}")
    return warnings


def aggregate_probability_quality(
    rows: Iterable[dict[str, Any] | ProbabilityQualityRow],
    bucket_edges: tuple[float, ...] | None = None,
) -> dict[str, Any]:
    normalized = _rows_to_normalized(rows)
    if not normalized:
        return {
            "count": 0,
            "accuracy_1x2": 0.0,
            "brier": 0.0,
            "log_loss": 0.0,
            "ece": 0.0,
            "buckets": [],
            "favorite_buckets": [],
            "warnings": [WARNING_CALIBRATION_SAMPLE_TOO_SMALL],
        }

    hits = [
        predicted_outcome(row["predicted_probs"]) == row["actual_outcome"]
        for row in normalized
    ]
    briers = [
        brier_score_1x2(row["predicted_probs"], row["actual_outcome"])
        for row in normalized
    ]
    losses = [
        log_loss_1x2(row["predicted_probs"], row["actual_outcome"])
        for row in normalized
    ]
    buckets = reliability_buckets(normalized, bucket_edges=bucket_edges)
    favorite_buckets = favorite_bucket_calibration(normalized)
    warnings = evaluate_calibration_warnings(normalized, buckets=buckets)

    return {
        "count": len(normalized),
        "accuracy_1x2": round(sum(hits) / len(hits), 4),
        "brier": round(sum(briers) / len(briers), 4),
        "log_loss": round(sum(losses) / len(losses), 4),
        "ece": expected_calibration_error(normalized, bucket_edges=bucket_edges),
        "buckets": buckets,
        "favorite_buckets": favorite_buckets,
        "warnings": warnings,
    }


def collect_walk_forward_probability_rows(
    dataset: str,
    *,
    candidate: str = "baseline",
    elo_strategy: str = "internal_only",
    external_rating_mode: str = "none",
    prior_mode: str = "default_internal",
) -> list[ProbabilityQualityRow]:
    """Collect per-match walk-forward probabilities for calibration reports."""
    from core.backtest import _outcome
    from core.external_rating_mode import resolve_external_rating_mode, world_elo_mode_for_resolve
    from core.temporal_backtest import (
        _resolve_snapshot_for_match,
        load_historical_matches,
        matches_before_target,
        run_temporal_shadow_pipeline,
    )
    from data.tournament_data import DATASET_REGISTRY, resolve_dataset_key

    ext_mode = resolve_external_rating_mode(
        external_rating_mode=external_rating_mode,
        world_elo_mode="none",
    )
    resolved_world_mode = world_elo_mode_for_resolve(ext_mode)

    eval_matches = load_historical_matches(dataset)
    full_history = load_historical_matches("all")
    key = resolve_dataset_key(dataset)
    label = DATASET_REGISTRY[key].label if key in DATASET_REGISTRY else key
    pv = "current" if candidate in ("baseline", "current") else candidate

    rows: list[ProbabilityQualityRow] = []
    for match in eval_matches:
        prior = matches_before_target(full_history, match)
        snap = _resolve_snapshot_for_match(
            match,
            full_history,
            dataset_key=key,
            prior_mode=prior_mode,  # type: ignore[arg-type]
        )
        pred = run_temporal_shadow_pipeline(
            match.home_team,
            match.away_team,
            snapshot=snap,
            prior_matches=prior,
            candidate=pv,
            elo_strategy=elo_strategy,
            world_elo_mode=resolved_world_mode,  # type: ignore[arg-type]
            advantage=0.0,
            dataset_key=key,
            match_date=match.date,
        )
        probs = normalize_1x2_probabilities(pred["probabilities_1x2"])
        actual = _outcome(match.home_goals, match.away_goals)
        rows.append(
            ProbabilityQualityRow(
                predicted_probs=probs,
                actual_outcome=actual,
                dataset=label,
                candidate=candidate,
            )
        )
    return rows


def evaluate_candidate_probability_quality(
    datasets: Iterable[str],
    *,
    candidate_label: str,
    walk_forward_config: dict[str, str],
) -> dict[str, Any]:
    per_dataset: dict[str, Any] = {}
    all_rows: list[ProbabilityQualityRow] = []
    for dataset in datasets:
        rows = collect_walk_forward_probability_rows(dataset, **walk_forward_config)
        per_dataset[dataset] = aggregate_probability_quality(rows)
        all_rows.extend(rows)
    overall = aggregate_probability_quality(all_rows)
    return {
        "candidate_label": candidate_label,
        "walk_forward_config": walk_forward_config,
        "per_dataset": per_dataset,
        "overall": overall,
    }
