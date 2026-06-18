"""Phase 2C/2D/2G — Model activation gate for shadow Power / effective Elo candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import config
from core.backtest_leakage_audit import audit_backtest_leakage
from core.power_multitournament_backtest import (
    MultiTournamentBacktestRow,
    run_all_multitournament_backtests,
    serious_backtest_candidates,
)
from core.temporal_backtest import WalkForwardBacktestRow

WARNING_BALANCED_SHIFT = "BALANCED_MATCH_SHIFT_TOO_LARGE"

# Legacy single status (prefer overall_status in Phase 2G+)
ActivationStatus = str

TemporalDataStatus = str  # PASS | NEEDS_BETTER_TEMPORAL_DATA | FAIL_HIGH_LEAKAGE
ModelCandidateStatus = str  # PASS | NO_MEANINGFUL_IMPROVEMENT | FAIL_METRICS | ...
OverallActivationStatus = str


@dataclass
class ActivationGateResult:
    recommended_candidate: dict[str, str] | None
    status: ActivationStatus
    temporal_data_status: str
    model_candidate_status: str
    overall_status: str
    reasons: list[str]
    metric_deltas_vs_baseline: dict[str, Any]
    dataset_summary: list[dict[str, Any]]
    leakage_risk_level: str
    balanced_match_warnings: list[str]
    walk_forward_used: bool = False
    dataset_blockers: list[dict[str, Any]] = field(default_factory=list)
    evidence_confidence: str = "unknown"
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    best_candidate_metrics: dict[str, float] | None = None
    best_diagnostic_candidate: dict[str, str] | None = None
    recommendation_reason: str | None = None
    improvement_thresholds: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def improvement_thresholds() -> dict[str, Any]:
    return {
        "min_logloss_improvement": config.ACTIVATION_MIN_LOGLOSS_IMPROVEMENT,
        "min_brier_improvement": config.ACTIVATION_MIN_BRIER_IMPROVEMENT,
        "allow_equal_if_1x2_improves_pp": config.ACTIVATION_ALLOW_EQUAL_IF_1X2_IMPROVES_PP,
        "max_logloss_worsen": config.ACTIVATION_MAX_LOGLOSS_WORSEN,
        "max_brier_worsen": config.ACTIVATION_MAX_BRIER_WORSEN,
        "max_1x2_drop_pp": config.ACTIVATION_MAX_1X2_DROP_PP,
        "treat_zero_delta_as_neutral": config.ACTIVATION_TREAT_ZERO_DELTA_AS_NEUTRAL,
    }


def _deltas_are_neutral(deltas: dict[str, float]) -> bool:
    if not config.ACTIVATION_TREAT_ZERO_DELTA_AS_NEUTRAL:
        return False
    tol = config.ACTIVATION_DELTA_FLOAT_TOLERANCE
    return (
        abs(deltas.get("log_loss", 0.0)) < tol
        and abs(deltas.get("brier", 0.0)) < tol
        and abs(deltas.get("1x2_acc_pp", 0.0)) < tol
    )


def candidate_meaningfully_improves(deltas: dict[str, float]) -> bool:
    """True when candidate beats baseline by configured minimum thresholds."""
    if _deltas_are_neutral(deltas):
        return False
    log_improved = deltas["log_loss"] <= -config.ACTIVATION_MIN_LOGLOSS_IMPROVEMENT
    brier_improved = deltas["brier"] <= -config.ACTIVATION_MIN_BRIER_IMPROVEMENT
    one_x2_pass = (
        deltas["1x2_acc_pp"] >= config.ACTIVATION_ALLOW_EQUAL_IF_1X2_IMPROVES_PP
        and deltas["log_loss"] <= config.ACTIVATION_MAX_LOGLOSS_WORSEN
        and deltas["brier"] <= config.ACTIVATION_MAX_BRIER_WORSEN
    )
    return log_improved or brier_improved or one_x2_pass


def check_balanced_match_shift(
    baseline_probs: dict[str, float],
    candidate_probs: dict[str, float],
    *,
    balanced_max_prob: float | None = None,
    max_shift_pp: float | None = None,
) -> str | None:
    """Warn when a balanced match shifts any 1X2 outcome too much."""
    balanced_max = balanced_max_prob or config.BALANCED_MATCH_MAX_BASE_PROB
    shift_limit = max_shift_pp or config.BALANCED_MATCH_MAX_SHIFT_PP
    max_base = max(baseline_probs.values())
    if max_base >= balanced_max:
        return None
    for key in ("home_win", "draw", "away_win"):
        if abs(candidate_probs[key] - baseline_probs[key]) > shift_limit:
            return WARNING_BALANCED_SHIFT
    return None


def _candidate_key_static(row: MultiTournamentBacktestRow) -> tuple[str, str]:
    return (row.variant, row.elo_strategy)


def _candidate_key_wf(row: WalkForwardBacktestRow) -> tuple[str, str]:
    variant = "current" if row.candidate in ("baseline", "current") else row.candidate
    return (variant, row.elo_strategy)


def _weighted_average_static(rows: list[MultiTournamentBacktestRow], field: str) -> float:
    total_matches = sum(r.matches for r in rows)
    if total_matches == 0:
        return 0.0
    return sum(getattr(r, field) * r.matches for r in rows) / total_matches


def _weighted_average_wf(rows: list[WalkForwardBacktestRow], field: str) -> float:
    total_matches = sum(r.matches for r in rows)
    if total_matches == 0:
        return 0.0
    return sum(getattr(r, field) * r.matches for r in rows) / total_matches


def _low_leakage_walk_forward_rows(
    rows: list[WalkForwardBacktestRow],
) -> list[WalkForwardBacktestRow]:
    return [r for r in rows if r.leakage_label == "low" and r.matches > 0]


def _usable_walk_forward_rows(
    rows: list[WalkForwardBacktestRow],
) -> list[WalkForwardBacktestRow]:
    """Low or medium leakage; excludes high and current_static historical runs."""
    return [
        r
        for r in rows
        if r.matches > 0
        and r.leakage_label in ("low", "medium")
        and r.world_elo_mode != "current_static"
        and r.external_rating_mode != "current_static_world_elo"
    ]


def _promising_candidate_deltas(
    baseline_rows: list[WalkForwardBacktestRow],
    cand_rows: list[WalkForwardBacktestRow],
) -> dict[str, float]:
    return {
        "log_loss": _weighted_average_wf(cand_rows, "mean_log_loss")
        - _weighted_average_wf(baseline_rows, "mean_log_loss"),
        "brier": _weighted_average_wf(cand_rows, "mean_brier")
        - _weighted_average_wf(baseline_rows, "mean_brier"),
        "1x2_acc_pp": _weighted_average_wf(cand_rows, "outcome_accuracy")
        - _weighted_average_wf(baseline_rows, "outcome_accuracy"),
    }


def _candidate_metrics(rows: list[WalkForwardBacktestRow]) -> dict[str, float]:
    return {
        "log_loss": _weighted_average_wf(rows, "mean_log_loss"),
        "brier": _weighted_average_wf(rows, "mean_brier"),
        "1x2_acc": _weighted_average_wf(rows, "outcome_accuracy"),
    }


def _external_snapshot_activation_ready() -> tuple[bool, list[Any]]:
    from core.external_rating_snapshots import external_snapshot_activation_ready

    return external_snapshot_activation_ready()


def _external_fifa_points_activation_ready() -> tuple[bool, list[Any]]:
    from core.external_rating_snapshots import external_fifa_points_activation_ready

    return external_fifa_points_activation_ready()


def _per_dataset_fifa_coverage() -> dict[str, float]:
    from core.external_rating_snapshots import validate_external_rating_snapshot
    from core.fixture_metadata import TOURNAMENT_STARTS

    out: dict[str, float] = {}
    for dk in TOURNAMENT_STARTS:
        report = validate_external_rating_snapshot(
            dk, external_rating_mode="fifa_points_snapshot"
        )
        out[report.dataset] = report.fifa_points_coverage
    return out


def _any_dataset_strongly_hurts(
    baseline_rows: list[WalkForwardBacktestRow],
    cand_rows: list[WalkForwardBacktestRow],
) -> tuple[bool, list[str]]:
    """True when any dataset regresses beyond activation worsen thresholds."""
    hurt: list[str] = []
    for ds in {r.dataset for r in cand_rows}:
        b = next((r for r in baseline_rows if r.dataset == ds), None)
        c = next((r for r in cand_rows if r.dataset == ds), None)
        if not b or not c:
            continue
        if c.mean_log_loss > b.mean_log_loss + config.ACTIVATION_MAX_LOGLOSS_WORSEN:
            hurt.append(f"{ds}: log_loss {c.mean_log_loss:.4f} > {b.mean_log_loss:.4f}")
        elif c.mean_brier > b.mean_brier + config.ACTIVATION_MAX_BRIER_WORSEN:
            hurt.append(f"{ds}: brier {c.mean_brier:.4f} > {b.mean_brier:.4f}")
    return bool(hurt), hurt


def _fifa_candidate_eligible(
    variant: str,
    *,
    fifa_snap_ready: bool,
    per_dataset_cov: dict[str, float],
) -> tuple[bool, list[str]]:
    """FIFA external candidates require coverage threshold; world_elo not required."""
    reasons: list[str] = []
    if not variant.startswith("effective_external"):
        return True, reasons
    if not fifa_snap_ready:
        reasons.append(
            f"FIFA points coverage below {config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION:.0%} "
            "on one or more tournament datasets"
        )
        return False, reasons
    partial = [
        f"{ds}={cov:.2f}"
        for ds, cov in per_dataset_cov.items()
        if cov < 1.0 and cov >= config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION
    ]
    if partial:
        reasons.append(f"Partial FIFA coverage (acceptable): {', '.join(partial)}")
    below = [
        f"{ds}={cov:.2f}"
        for ds, cov in per_dataset_cov.items()
        if cov < config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION
    ]
    if below:
        reasons.append(f"FIFA coverage below threshold: {', '.join(below)}")
        return False, reasons
    return True, reasons


def build_walk_forward_activation_rows(
    *,
    datasets: list[str] | None = None,
    external_rating_mode: str = "none",
    prior_mode: str = "tournament_prior_file",
    candidate_set: str = "serious",
    include_defense_flip: bool = False,
    include_combined: bool = True,
) -> list[WalkForwardBacktestRow]:
    """Run walk-forward rows for activation gate evaluation."""
    from core.external_rating_mode import resolve_external_rating_mode
    from core.fixture_metadata import TOURNAMENT_STARTS
    from core.temporal_backtest import run_walk_forward_backtest
    from core.temporal_match_data import (
        all_shadow_walk_forward_candidates,
        fifa_points_walk_forward_candidates,
        serious_walk_forward_candidates,
    )
    from data.tournament_data import list_dataset_keys, resolve_dataset_key

    ext_mode = resolve_external_rating_mode(external_rating_mode=external_rating_mode)
    if ext_mode == "fifa_points_snapshot" or candidate_set == "fifa-points":
        candidates = fifa_points_walk_forward_candidates()
    elif candidate_set == "all-shadow":
        candidates = all_shadow_walk_forward_candidates(
            include_defense_flip=include_defense_flip
        )
    else:
        candidates = serious_walk_forward_candidates(
            include_defense_flip=include_defense_flip
        )

    if datasets:
        keys = datasets
    elif ext_mode == "fifa_points_snapshot":
        keys = list(TOURNAMENT_STARTS.keys())
    else:
        keys = list_dataset_keys()
    resolved: list[str] = []
    for ds in keys:
        key = resolve_dataset_key(ds)
        if key == "all":
            if include_combined:
                resolved.append("all")
            resolved.extend(list_dataset_keys())
        elif key not in resolved:
            resolved.append(ds)

    rows: list[WalkForwardBacktestRow] = []
    for target in resolved:
        for cand, elo in candidates:
            rows.append(
                run_walk_forward_backtest(
                    target,
                    candidate=cand,
                    elo_strategy=elo,
                    external_rating_mode=external_rating_mode,
                    prior_mode=prior_mode,  # type: ignore[arg-type]
                )
            )
    return rows


def _collect_dataset_blockers(
    *,
    prior_mode: str | None = None,
) -> list[dict[str, Any]]:
    from core.fixture_metadata import TOURNAMENT_STARTS, audit_dataset_coverage
    from data.tournament_data import list_dataset_keys

    rows: list[dict[str, Any]] = []
    for dk in list_dataset_keys():
        pm = (
            "tournament_prior_file" if dk in TOURNAMENT_STARTS else "default_internal"
        )
        cov = audit_dataset_coverage(
            dk,
            prior_mode=pm,
            world_elo_mode="none",
        )
        rows.append(
            {
                "dataset": cov.dataset,
                "leakage_label": cov.leakage_label,
                "low_leakage_ready": cov.low_leakage_ready,
                "blockers": cov.blockers,
                "missing_requirements": cov.blockers,
                "override_coverage": cov.override_coverage,
                "prior_coverage": cov.prior_coverage,
                "data_quality_score": cov.data_quality_score,
            }
        )
    return rows


def _evidence_confidence(
    walk_forward_rows: list[WalkForwardBacktestRow],
    dataset_blockers: list[dict[str, Any]],
) -> str:
    if any(b.get("leakage_label") == "high" for b in dataset_blockers):
        return "high"
    if all(b.get("low_leakage_ready") for b in dataset_blockers) and all(
        r.leakage_label == "low" for r in walk_forward_rows if r.matches > 0
    ):
        return "low"
    if any(r.leakage_label == "medium" for r in walk_forward_rows if r.matches > 0):
        return "medium"
    return "medium"


def _resolve_temporal_data_status(
    *,
    current_static: bool,
    not_ready: list[dict[str, Any]],
    only_medium: bool,
    has_eval_rows: bool,
) -> str:
    if current_static:
        return "FAIL_HIGH_LEAKAGE"
    if not has_eval_rows:
        return "NEEDS_BETTER_TEMPORAL_DATA"
    if not_ready or only_medium:
        return "NEEDS_BETTER_TEMPORAL_DATA"
    return "PASS"


def _legacy_status_from_overall(overall_status: str) -> str:
    """Map Phase 2G overall_status to legacy status field for older callers."""
    mapping = {
        "MODEL_ACTIVATION_PASS": "PASS",
        "DATA_READY_MODEL_NEUTRAL": "DATA_READY_MODEL_NEUTRAL",
        "NEEDS_BETTER_TEMPORAL_DATA": "NEEDS_BETTER_TEMPORAL_DATA",
        "FAIL_HIGH_LEAKAGE": "FAIL_HIGH_LEAKAGE",
        "FAIL_MODEL_METRICS": "FAIL",
        "NEEDS_MORE_DATA": "NEEDS_MORE_DATA",
    }
    return mapping.get(overall_status, overall_status)


def _gate_result(
    *,
    overall_status: str,
    temporal_data_status: str,
    model_candidate_status: str,
    recommended_candidate: dict[str, str] | None,
    reasons: list[str],
    metric_deltas_vs_baseline: dict[str, Any],
    dataset_summary: list[dict[str, Any]],
    leakage_risk_level: str,
    balanced_match_warnings: list[str],
    walk_forward_used: bool,
    dataset_blockers: list[dict[str, Any]] | None = None,
    evidence_confidence: str = "unknown",
    baseline_metrics: dict[str, float] | None = None,
    best_candidate_metrics: dict[str, float] | None = None,
    best_diagnostic_candidate: dict[str, str] | None = None,
    recommendation_reason: str | None = None,
) -> ActivationGateResult:
    return ActivationGateResult(
        recommended_candidate=recommended_candidate,
        status=_legacy_status_from_overall(overall_status),
        temporal_data_status=temporal_data_status,
        model_candidate_status=model_candidate_status,
        overall_status=overall_status,
        reasons=reasons,
        metric_deltas_vs_baseline=metric_deltas_vs_baseline,
        dataset_summary=dataset_summary,
        leakage_risk_level=leakage_risk_level,
        balanced_match_warnings=balanced_match_warnings,
        walk_forward_used=walk_forward_used,
        dataset_blockers=dataset_blockers or [],
        evidence_confidence=evidence_confidence,
        baseline_metrics=baseline_metrics or {},
        best_candidate_metrics=best_candidate_metrics,
        best_diagnostic_candidate=best_diagnostic_candidate,
        recommendation_reason=recommendation_reason,
        improvement_thresholds=improvement_thresholds(),
    )


def _candidate_passes_metric_gates(
    deltas: dict[str, float],
    *,
    balanced_warnings: list[str] | None,
    baseline_rows: list[WalkForwardBacktestRow],
    cand_rows: list[WalkForwardBacktestRow],
) -> bool:
    if balanced_warnings:
        return False
    if deltas["log_loss"] > config.ACTIVATION_MAX_LOGLOSS_WORSEN:
        return False
    if deltas["brier"] > config.ACTIVATION_MAX_BRIER_WORSEN:
        return False
    if deltas["1x2_acc_pp"] < -config.ACTIVATION_MAX_1X2_DROP_PP:
        return False
    if config.ACTIVATION_REQUIRE_MULTI_DATASET_IMPROVEMENT:
        improved = 0
        tested = 0
        for ds in {r.dataset for r in cand_rows}:
            b = next((r for r in baseline_rows if r.dataset == ds), None)
            c = next((r for r in cand_rows if r.dataset == ds), None)
            if not b or not c:
                continue
            tested += 1
            if (
                c.mean_log_loss <= b.mean_log_loss + config.ACTIVATION_MAX_LOGLOSS_WORSEN
                and c.mean_brier <= b.mean_brier + config.ACTIVATION_MAX_BRIER_WORSEN
            ):
                improved += 1
        if tested < 2 or improved < max(2, tested // 2):
            return False
    return True


def _evaluate_walk_forward_gate(
    walk_forward_rows: list[WalkForwardBacktestRow],
    *,
    balanced_warnings: list[str] | None = None,
) -> ActivationGateResult:
    dataset_blockers = _collect_dataset_blockers()
    not_ready = [b for b in dataset_blockers if not b["low_leakage_ready"]]
    blocker_reasons = [
        f"{b['dataset']}: {','.join(b['blockers']) or 'not low-leakage ready'}"
        for b in not_ready
    ]
    thresholds = improvement_thresholds()

    current_static = any(
        r.world_elo_mode == "current_static"
        or r.external_rating_mode == "current_static_world_elo"
        for r in walk_forward_rows
    )
    if current_static:
        temporal = "FAIL_HIGH_LEAKAGE"
        return _gate_result(
            overall_status="FAIL_HIGH_LEAKAGE",
            temporal_data_status=temporal,
            model_candidate_status="NOT_EVALUATED",
            recommended_candidate=None,
            reasons=[
                "current_static World Elo cannot be used for historical activation",
                *blocker_reasons[:5],
            ],
            metric_deltas_vs_baseline={},
            dataset_summary=[],
            leakage_risk_level="high",
            balanced_match_warnings=balanced_warnings or [],
            walk_forward_used=True,
            dataset_blockers=dataset_blockers,
            evidence_confidence="high",
            recommendation_reason="high_leakage_world_elo",
        )

    low_leak = _low_leakage_walk_forward_rows(walk_forward_rows)
    eval_rows = low_leak if low_leak else _usable_walk_forward_rows(walk_forward_rows)
    only_medium = not low_leak

    temporal = _resolve_temporal_data_status(
        current_static=False,
        not_ready=not_ready,
        only_medium=only_medium,
        has_eval_rows=bool(eval_rows),
    )

    if not eval_rows:
        return _gate_result(
            overall_status="NEEDS_BETTER_TEMPORAL_DATA",
            temporal_data_status=temporal,
            model_candidate_status="NOT_EVALUATED",
            recommended_candidate=None,
            reasons=[
                "No low/medium-leakage walk-forward rows available",
                "Run scripts/backtest_walk_forward.py --world-elo-mode none",
                *blocker_reasons[:5],
            ],
            metric_deltas_vs_baseline={},
            dataset_summary=[],
            leakage_risk_level="high",
            balanced_match_warnings=balanced_warnings or [],
            walk_forward_used=True,
            dataset_blockers=dataset_blockers,
            evidence_confidence="high",
            recommendation_reason="no_walk_forward_rows",
        )

    per_tournament = [r for r in eval_rows if r.dataset.lower() != "all combined"]
    if not per_tournament:
        per_tournament = eval_rows

    grouped: dict[tuple[str, str], list[WalkForwardBacktestRow]] = {}
    for row in per_tournament:
        grouped.setdefault(_candidate_key_wf(row), []).append(row)

    baseline_rows = grouped.get(("current", "internal_only"), [])
    if not baseline_rows:
        baseline_rows = [r for r in per_tournament if r.candidate in ("baseline", "current")]

    if not baseline_rows:
        return _gate_result(
            overall_status="NEEDS_MORE_DATA",
            temporal_data_status=temporal,
            model_candidate_status="NEEDS_MORE_DATA",
            recommended_candidate=None,
            reasons=["Walk-forward baseline (baseline + internal_only) missing"],
            metric_deltas_vs_baseline={},
            dataset_summary=[],
            leakage_risk_level="medium" if only_medium else "low",
            balanced_match_warnings=balanced_warnings or [],
            walk_forward_used=True,
            dataset_blockers=dataset_blockers,
            recommendation_reason="baseline_missing",
        )

    baseline_avg = _candidate_metrics(baseline_rows)
    dataset_summary = [
        {
            "dataset": r.dataset,
            "matches": r.matches,
            "baseline_log_loss": r.mean_log_loss,
            "baseline_brier": r.mean_brier,
            "baseline_1x2_acc": r.outcome_accuracy,
            "mode": "walk_forward",
            "leakage_label": r.leakage_label,
            "data_quality": r.data_quality,
            "prior_mode": r.prior_mode,
        }
        for r in sorted(baseline_rows, key=lambda x: x.dataset)
    ]

    from core.temporal_match_data import (
        fifa_points_walk_forward_candidates,
        serious_walk_forward_candidates,
    )

    candidates = serious_walk_forward_candidates(include_defense_flip=False)
    fifa_mode_rows = any(
        r.external_rating_mode == "fifa_points_snapshot" for r in walk_forward_rows
    )
    if fifa_mode_rows:
        candidates = fifa_points_walk_forward_candidates()

    per_dataset_fifa_cov = _per_dataset_fifa_coverage() if fifa_mode_rows else {}
    best_activation: tuple[str, str] | None = None
    best_activation_deltas: dict[str, float] = {}
    best_activation_metrics: dict[str, float] | None = None
    best_activation_log_loss = float("inf")

    best_diagnostic: tuple[str, str] | None = None
    best_diagnostic_deltas: dict[str, float] = {}
    best_diagnostic_metrics: dict[str, float] | None = None
    best_diagnostic_log_loss = float("inf")

    for variant, elo_strategy in candidates:
        if variant in ("current", "baseline") and elo_strategy == "internal_only":
            continue
        cand_key = (variant, elo_strategy)
        cand_rows = grouped.get(cand_key, [])
        if not cand_rows:
            wf_cand = (
                variant.replace("effective_elo_", "")
                if variant.startswith("effective_elo_")
                else variant
            )
            cand_rows = [
                r
                for r in per_tournament
                if r.candidate == variant or r.candidate == wf_cand
            ]
        if not cand_rows:
            continue

        deltas = _promising_candidate_deltas(baseline_rows, cand_rows)
        metrics = _candidate_metrics(cand_rows)
        avg_log = metrics["log_loss"]

        if avg_log < best_diagnostic_log_loss:
            best_diagnostic = (variant, elo_strategy)
            best_diagnostic_deltas = deltas
            best_diagnostic_metrics = metrics
            best_diagnostic_log_loss = avg_log

        if only_medium or temporal != "PASS":
            continue

        if not _candidate_passes_metric_gates(
            deltas,
            balanced_warnings=balanced_warnings,
            baseline_rows=baseline_rows,
            cand_rows=cand_rows,
        ):
            continue

        if not candidate_meaningfully_improves(deltas):
            continue

        world_snap_ready, _ = _external_snapshot_activation_ready()
        fifa_snap_ready, _ = _external_fifa_points_activation_ready()

        if variant.startswith("effective_elo") and not variant.startswith("effective_external"):
            if not world_snap_ready:
                continue
        if variant.startswith("effective_external"):
            eligible, _ = _fifa_candidate_eligible(
                variant,
                fifa_snap_ready=fifa_snap_ready,
                per_dataset_cov=per_dataset_fifa_cov,
            )
            if not eligible:
                continue

        hurts, hurt_reasons = _any_dataset_strongly_hurts(baseline_rows, cand_rows)
        if hurts:
            continue

        if avg_log < best_activation_log_loss:
            best_activation = (variant, elo_strategy)
            best_activation_deltas = {k: round(v, 4) for k, v in deltas.items()}
            best_activation_metrics = metrics
            best_activation_log_loss = avg_log

    evidence_conf = _evidence_confidence(walk_forward_rows, dataset_blockers)
    diag_candidate = (
        {"variant": best_diagnostic[0], "elo_strategy": best_diagnostic[1]}
        if best_diagnostic
        else None
    )

    if temporal != "PASS":
        model_status = "NOT_EVALUATED"
        if best_diagnostic and candidate_meaningfully_improves(best_diagnostic_deltas):
            model_status = "PASS"
        elif best_diagnostic and _deltas_are_neutral(best_diagnostic_deltas):
            model_status = "NO_MEANINGFUL_IMPROVEMENT"
        return _gate_result(
            overall_status="NEEDS_BETTER_TEMPORAL_DATA",
            temporal_data_status=temporal,
            model_candidate_status=model_status,
            recommended_candidate=None,
            reasons=[
                "Temporal data not ready for low-leakage activation",
                *blocker_reasons,
            ],
            metric_deltas_vs_baseline={
                k: round(v, 4) for k, v in best_diagnostic_deltas.items()
            }
            if best_diagnostic
            else {},
            dataset_summary=dataset_summary,
            leakage_risk_level="medium",
            balanced_match_warnings=balanced_warnings or [],
            walk_forward_used=True,
            dataset_blockers=dataset_blockers,
            evidence_confidence=evidence_conf,
            baseline_metrics=baseline_avg,
            best_candidate_metrics=best_diagnostic_metrics,
            best_diagnostic_candidate=diag_candidate,
            recommendation_reason="temporal_data_not_ready",
        )

    if balanced_warnings:
        return _gate_result(
            overall_status="FAIL_MODEL_METRICS",
            temporal_data_status=temporal,
            model_candidate_status="FAIL_BALANCED_MATCH_STABILITY",
            recommended_candidate=None,
            reasons=[
                "Balanced-match stability warnings block activation",
                *balanced_warnings,
            ],
            metric_deltas_vs_baseline={
                k: round(v, 4) for k, v in best_diagnostic_deltas.items()
            }
            if best_diagnostic
            else {},
            dataset_summary=dataset_summary,
            leakage_risk_level="low",
            balanced_match_warnings=balanced_warnings,
            walk_forward_used=True,
            dataset_blockers=dataset_blockers,
            evidence_confidence=evidence_conf,
            baseline_metrics=baseline_avg,
            best_candidate_metrics=best_diagnostic_metrics,
            best_diagnostic_candidate=diag_candidate,
            recommendation_reason="balanced_match_instability",
        )

    if best_activation:
        rec: dict[str, str] = {
            "variant": best_activation[0],
            "elo_strategy": best_activation[1],
        }
        if fifa_mode_rows:
            rec["external_rating_mode"] = "fifa_points_snapshot"
        return _gate_result(
            overall_status="MODEL_ACTIVATION_PASS",
            temporal_data_status=temporal,
            model_candidate_status="PASS",
            recommended_candidate=rec,
            reasons=[
                "Temporal data ready and candidate meaningfully beats baseline",
            ],
            metric_deltas_vs_baseline=best_activation_deltas,
            dataset_summary=dataset_summary,
            leakage_risk_level="low",
            balanced_match_warnings=balanced_warnings or [],
            walk_forward_used=True,
            dataset_blockers=dataset_blockers,
            evidence_confidence=evidence_conf,
            baseline_metrics=baseline_avg,
            best_candidate_metrics=best_activation_metrics,
            best_diagnostic_candidate=diag_candidate,
            recommendation_reason="meaningful_improvement",
        )

    if best_diagnostic and _deltas_are_neutral(best_diagnostic_deltas):
        world_snap_ready, world_snap_reports = _external_snapshot_activation_ready()
        fifa_snap_ready, fifa_snap_reports = _external_fifa_points_activation_ready()
        if (
            not fifa_mode_rows
            and not world_snap_ready
            and best_diagnostic[0].startswith("effective_elo")
            and not best_diagnostic[0].startswith("effective_external")
        ):
            snap_reasons = [
                f"{r.dataset}: world_elo_cov={r.world_elo_coverage:.2f} "
                f"({','.join(r.warnings) or '-'})"
                for r in world_snap_reports
                if r.world_elo_coverage < config.EXTERNAL_SNAPSHOT_MIN_COVERAGE_FOR_ACTIVATION
            ]
            return _gate_result(
                overall_status="DATA_READY_MODEL_NEUTRAL",
                temporal_data_status=temporal,
                model_candidate_status="NEEDS_MORE_EXTERNAL_SNAPSHOT_DATA",
                recommended_candidate=None,
                reasons=[
                    "Effective Elo requires historical World Elo snapshots before fair evaluation",
                    f"Minimum world_elo coverage: {config.EXTERNAL_SNAPSHOT_MIN_COVERAGE_FOR_ACTIVATION:.0%}",
                    *snap_reasons[:5],
                ],
                metric_deltas_vs_baseline={
                    k: round(v, 4) for k, v in best_diagnostic_deltas.items()
                },
                dataset_summary=dataset_summary,
                leakage_risk_level="low",
                balanced_match_warnings=balanced_warnings or [],
                walk_forward_used=True,
                dataset_blockers=dataset_blockers,
                evidence_confidence=evidence_conf,
                baseline_metrics=baseline_avg,
                best_candidate_metrics=best_diagnostic_metrics,
                best_diagnostic_candidate=diag_candidate,
                recommendation_reason="insufficient_world_elo_snapshot_coverage",
            )
        if not fifa_snap_ready and best_diagnostic[0].startswith("effective_external"):
            snap_reasons = [
                f"{r.dataset}: fifa_cov={r.fifa_points_coverage:.2f} "
                f"({','.join(r.warnings) or '-'})"
                for r in fifa_snap_reports
                if r.fifa_points_coverage
                < config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION
            ]
            return _gate_result(
                overall_status="DATA_READY_MODEL_NEUTRAL",
                temporal_data_status=temporal,
                model_candidate_status="NEEDS_MORE_EXTERNAL_SNAPSHOT_DATA",
                recommended_candidate=None,
                reasons=[
                    "FIFA-points external anchor requires sufficient pre-tournament coverage",
                    f"Minimum fifa_points coverage: "
                    f"{config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION:.0%}",
                    *snap_reasons[:5],
                ],
                metric_deltas_vs_baseline={
                    k: round(v, 4) for k, v in best_diagnostic_deltas.items()
                },
                dataset_summary=dataset_summary,
                leakage_risk_level="low",
                balanced_match_warnings=balanced_warnings or [],
                walk_forward_used=True,
                dataset_blockers=dataset_blockers,
                evidence_confidence=evidence_conf,
                baseline_metrics=baseline_avg,
                best_candidate_metrics=best_diagnostic_metrics,
                best_diagnostic_candidate=diag_candidate,
                recommendation_reason="insufficient_fifa_points_snapshot_coverage",
            )
        return _gate_result(
            overall_status="DATA_READY_MODEL_NEUTRAL",
            temporal_data_status=temporal,
            model_candidate_status="NO_MEANINGFUL_IMPROVEMENT",
            recommended_candidate=None,
            reasons=[
                "Candidate metrics match baseline exactly; no activation value",
                f"Walk-forward baseline log-loss={baseline_avg['log_loss']:.4f}, "
                f"Brier={baseline_avg['brier']:.4f}, 1X2={baseline_avg['1x2_acc']:.1f}%",
            ],
            metric_deltas_vs_baseline={
                k: round(v, 4) for k, v in best_diagnostic_deltas.items()
            },
            dataset_summary=dataset_summary,
            leakage_risk_level="low",
            balanced_match_warnings=balanced_warnings or [],
            walk_forward_used=True,
            dataset_blockers=dataset_blockers,
            evidence_confidence=evidence_conf,
            baseline_metrics=baseline_avg,
            best_candidate_metrics=best_diagnostic_metrics,
            best_diagnostic_candidate=diag_candidate,
            recommendation_reason="candidate_matches_baseline_no_activation_value",
        )

    if best_diagnostic and not candidate_meaningfully_improves(best_diagnostic_deltas):
        return _gate_result(
            overall_status="DATA_READY_MODEL_NEUTRAL",
            temporal_data_status=temporal,
            model_candidate_status="NO_MEANINGFUL_IMPROVEMENT",
            recommended_candidate=None,
            reasons=[
                "No candidate meets minimum improvement thresholds",
                f"Best diagnostic log-loss delta={best_diagnostic_deltas['log_loss']:+.4f} "
                f"(need <= -{thresholds['min_logloss_improvement']})",
                f"Brier delta={best_diagnostic_deltas['brier']:+.4f} "
                f"(need <= -{thresholds['min_brier_improvement']})",
            ],
            metric_deltas_vs_baseline={
                k: round(v, 4) for k, v in best_diagnostic_deltas.items()
            },
            dataset_summary=dataset_summary,
            leakage_risk_level="low",
            balanced_match_warnings=balanced_warnings or [],
            walk_forward_used=True,
            dataset_blockers=dataset_blockers,
            evidence_confidence=evidence_conf,
            baseline_metrics=baseline_avg,
            best_candidate_metrics=best_diagnostic_metrics,
            best_diagnostic_candidate=diag_candidate,
            recommendation_reason="below_minimum_improvement_thresholds",
        )

    return _gate_result(
        overall_status="FAIL_MODEL_METRICS",
        temporal_data_status=temporal,
        model_candidate_status="FAIL_METRICS",
        recommended_candidate=None,
        reasons=[
            "No walk-forward candidate passed all gate conditions",
            f"Walk-forward baseline log-loss={baseline_avg['log_loss']:.4f}, "
            f"Brier={baseline_avg['brier']:.4f}, 1X2={baseline_avg['1x2_acc']:.1f}%",
            *blocker_reasons[:5],
        ],
        metric_deltas_vs_baseline={
            k: round(v, 4) for k, v in best_diagnostic_deltas.items()
        }
        if best_diagnostic
        else {},
        dataset_summary=dataset_summary,
        leakage_risk_level="low",
        balanced_match_warnings=balanced_warnings or [],
        walk_forward_used=True,
        dataset_blockers=dataset_blockers,
        evidence_confidence=evidence_conf,
        baseline_metrics=baseline_avg,
        best_candidate_metrics=best_diagnostic_metrics,
        best_diagnostic_candidate=diag_candidate,
        recommendation_reason="fail_metric_gates",
    )


def evaluate_activation_gate(
    backtest_rows: list[MultiTournamentBacktestRow] | None = None,
    *,
    walk_forward_rows: list[WalkForwardBacktestRow] | None = None,
    run_backtests: bool = True,
    run_walk_forward: bool = False,
    include_defense_flip: bool = False,
    balanced_warnings: list[str] | None = None,
    external_rating_mode: str = "none",
    prior_mode: str = "tournament_prior_file",
    candidate_set: str = "serious",
    walk_forward_datasets: list[str] | None = None,
) -> ActivationGateResult:
    """Evaluate activation gate — prefers low-leakage walk-forward when available."""
    leakage = audit_backtest_leakage()

    if walk_forward_rows:
        return _evaluate_walk_forward_gate(
            walk_forward_rows,
            balanced_warnings=balanced_warnings,
        )

    if run_walk_forward:
        wf_rows = build_walk_forward_activation_rows(
            datasets=walk_forward_datasets,
            external_rating_mode=external_rating_mode,
            prior_mode=prior_mode,
            candidate_set=candidate_set,
            include_defense_flip=include_defense_flip,
        )
        return _evaluate_walk_forward_gate(wf_rows, balanced_warnings=balanced_warnings)

    if backtest_rows is None:
        if not run_backtests:
            return _gate_result(
                overall_status="NEEDS_MORE_DATA",
                temporal_data_status="NEEDS_BETTER_TEMPORAL_DATA",
                model_candidate_status="NOT_EVALUATED",
                recommended_candidate=None,
                reasons=[
                    "No walk-forward rows supplied — static-only evaluation blocked",
                    "Run scripts/backtest_walk_forward.py --world-elo-mode none",
                ],
                metric_deltas_vs_baseline={},
                dataset_summary=[],
                leakage_risk_level=leakage.leakage_risk_level,
                balanced_match_warnings=balanced_warnings or [],
                walk_forward_used=False,
                recommendation_reason="walk_forward_required",
            )
        backtest_rows = run_all_multitournament_backtests(
            dataset_keys=["all"],
            include_defense_flip=include_defense_flip,
        )

    if leakage.leakage_risk_level == "high":
        return _gate_result(
            overall_status="FAIL_HIGH_LEAKAGE",
            temporal_data_status="FAIL_HIGH_LEAKAGE",
            model_candidate_status="NOT_EVALUATED",
            recommended_candidate=None,
            reasons=[
                "Static backtest leakage risk is HIGH",
                "Activation requires low-leakage walk-forward results",
                "Run: python scripts/backtest_walk_forward.py --dataset all "
                "--candidate baseline --world-elo-mode none",
            ],
            metric_deltas_vs_baseline={},
            dataset_summary=[],
            leakage_risk_level=leakage.leakage_risk_level,
            balanced_match_warnings=balanced_warnings or [],
            walk_forward_used=False,
            recommendation_reason="static_high_leakage",
        )

    per_tournament = [r for r in backtest_rows if r.dataset != "All Combined"]
    if not per_tournament:
        per_tournament = backtest_rows

    grouped: dict[tuple[str, str], list[MultiTournamentBacktestRow]] = {}
    for row in per_tournament:
        if row.matches == 0:
            continue
        grouped.setdefault(_candidate_key_static(row), []).append(row)

    baseline_rows = grouped.get(("current", "internal_only"), [])
    if not baseline_rows:
        return _gate_result(
            overall_status="NEEDS_MORE_DATA",
            temporal_data_status="NEEDS_BETTER_TEMPORAL_DATA",
            model_candidate_status="NEEDS_MORE_DATA",
            recommended_candidate=None,
            reasons=["Baseline (current + internal_only) has no evaluable dataset rows"],
            metric_deltas_vs_baseline={},
            dataset_summary=[],
            leakage_risk_level=leakage.leakage_risk_level,
            balanced_match_warnings=balanced_warnings or [],
            recommendation_reason="baseline_missing",
        )

    return _gate_result(
        overall_status="NEEDS_MORE_DATA",
        temporal_data_status="NEEDS_BETTER_TEMPORAL_DATA",
        model_candidate_status="NOT_EVALUATED",
        recommended_candidate=None,
        reasons=[
            "Static metrics alone are insufficient for activation",
            "Provide walk_forward_rows or use --run-walk-forward",
        ],
        metric_deltas_vs_baseline={},
        dataset_summary=[],
        leakage_risk_level=leakage.leakage_risk_level,
        balanced_match_warnings=balanced_warnings or [],
        walk_forward_used=False,
        recommendation_reason="walk_forward_required",
    )


def activation_candidate_status(
    gate_result: ActivationGateResult | None = None,
) -> str:
    """API-safe activation status string (no heavy backtest by default)."""
    if not config.POWER_SHADOW_CALIBRATION_ENABLED:
        return "not_evaluated"
    if (
        config.MODEL_ACTIVATION_ENABLED
        and config.POWER_CANDIDATE_AFFECTS_PREDICTION
    ):
        return "active"
    if gate_result is None:
        return "shadow_only"
    if gate_result.overall_status == "MODEL_ACTIVATION_PASS":
        if config.POWER_CANDIDATE_AFFECTS_PREDICTION:
            return "gate_passed"
        return "shadow_only"
    if gate_result.overall_status == "DATA_READY_MODEL_NEUTRAL":
        return "data_ready_model_neutral"
    if gate_result.overall_status in ("FAIL_HIGH_LEAKAGE", "FAIL_MODEL_METRICS"):
        return "gate_failed"
    if gate_result.overall_status == "NEEDS_BETTER_TEMPORAL_DATA":
        return "shadow_only"
    return "shadow_only"


def activation_diagnostic_fields(
    gate_result: ActivationGateResult | None = None,
) -> dict[str, str]:
    """Extended activation diagnostics for API (no prediction impact)."""
    if gate_result is None:
        return {
            "activation_candidate_status": activation_candidate_status(None),
            "activation_overall_status": "not_evaluated",
            "temporal_data_status": "not_evaluated",
            "model_candidate_status": "not_evaluated",
        }
    return {
        "activation_candidate_status": activation_candidate_status(gate_result),
        "activation_overall_status": gate_result.overall_status,
        "temporal_data_status": gate_result.temporal_data_status,
        "model_candidate_status": gate_result.model_candidate_status,
    }


def format_activation_gate_report(result: ActivationGateResult) -> str:
    lines = [
        f"Temporal data status: {result.temporal_data_status}",
        f"Model candidate status: {result.model_candidate_status}",
        f"Overall status: {result.overall_status}",
        f"Legacy status: {result.status}",
        f"Recommended candidate: {result.recommended_candidate}",
    ]
    if result.best_diagnostic_candidate:
        diag = result.best_diagnostic_candidate
        lines.append(
            f"Best diagnostic candidate: {diag.get('variant')} / {diag.get('elo_strategy')}"
        )
    if result.recommendation_reason:
        lines.append(f"Recommendation reason: {result.recommendation_reason}")
    lines.extend(
        [
            f"Leakage risk: {result.leakage_risk_level}",
            f"Evidence confidence: {result.evidence_confidence}",
            f"Walk-forward used: {result.walk_forward_used}",
            "",
            "Reasons:",
        ]
    )
    for reason in result.reasons:
        lines.append(f"  - {reason}")

    if result.baseline_metrics:
        lines.append("")
        lines.append("Baseline metrics:")
        for key, val in result.baseline_metrics.items():
            lines.append(f"  {key}: {val:.4f}" if isinstance(val, float) else f"  {key}: {val}")

    if result.best_candidate_metrics:
        lines.append("")
        lines.append("Best candidate metrics:")
        for key, val in result.best_candidate_metrics.items():
            lines.append(f"  {key}: {val:.4f}" if isinstance(val, float) else f"  {key}: {val}")

    if result.metric_deltas_vs_baseline:
        lines.append("")
        lines.append("Metric deltas vs baseline:")
        for key, val in result.metric_deltas_vs_baseline.items():
            lines.append(f"  {key}: {val}")

    if result.improvement_thresholds:
        lines.append("")
        lines.append("Improvement thresholds:")
        for key, val in result.improvement_thresholds.items():
            lines.append(f"  {key}: {val}")

    if result.dataset_blockers:
        lines.append("")
        lines.append("Dataset low-leakage blockers:")
        for block in result.dataset_blockers:
            ready = "ready" if block.get("low_leakage_ready") else "BLOCKED"
            reqs = ",".join(
                block.get("missing_requirements") or block.get("blockers") or ["-"]
            )
            lines.append(
                f"  {block['dataset']}: {ready} | leak={block.get('leakage_label')} | "
                f"ovr={block.get('override_coverage')} pri={block.get('prior_coverage')} | "
                f"missing: {reqs}"
            )

    if result.dataset_summary:
        lines.append("")
        lines.append("Dataset summary:")
        for ds in result.dataset_summary:
            mode = ds.get("mode", "static")
            lines.append(
                f"  {ds['dataset']} ({mode}): {ds['matches']} matches, "
                f"log_loss={ds['baseline_log_loss']}, brier={ds['baseline_brier']}"
            )
    if result.balanced_match_warnings:
        lines.append("")
        lines.append(f"Balanced-match warnings: {result.balanced_match_warnings}")
    return "\n".join(lines)
