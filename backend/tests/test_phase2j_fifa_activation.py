"""Phase 2J — FIFA points multi-dataset activation evaluation tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.model_activation_gate import (
    build_walk_forward_activation_rows,
    evaluate_activation_gate,
)
from core.regression_diagnostic_matchups import run_all_regression_diagnostics
from core.temporal_backtest import WalkForwardBacktestRow, run_walk_forward_backtest

PYTHON = sys.executable


def test_build_walk_forward_rows_fifa_mode() -> None:
    rows = build_walk_forward_activation_rows(
        datasets=["wc2022"],
        external_rating_mode="fifa_points_snapshot",
        prior_mode="tournament_prior_file",
        candidate_set="serious",
        include_combined=False,
    )
    assert rows
    assert all(r.external_rating_mode == "fifa_points_snapshot" for r in rows)
    assert any(r.candidate.startswith("effective_external") for r in rows)


def test_fifa_activation_does_not_require_world_elo() -> None:
    rows: list[WalkForwardBacktestRow] = []
    for ds, cov in (("WC 2022", 1.0), ("Euro 2024", 0.96)):
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=50,
                candidate="baseline",
                elo_strategy="internal_only",
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                external_rating_mode="fifa_points_snapshot",
                external_rating_type="fifa_points",
                external_coverage=cov,
                fifa_points_coverage=cov,
                leakage_label="low",
                data_quality="exact_date",
                outcome_accuracy=55.0,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=1.0,
                mean_brier=0.6,
            )
        )
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=50,
                candidate="effective_external_current_formula",
                elo_strategy="fifa_points_confidence_weighted",
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                external_rating_mode="fifa_points_snapshot",
                external_rating_type="fifa_points",
                external_coverage=cov,
                fifa_points_coverage=cov,
                leakage_label="low",
                data_quality="exact_date",
                outcome_accuracy=55.0,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=1.0,
                mean_brier=0.6,
            )
        )
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.model_candidate_status != "NEEDS_MORE_EXTERNAL_SNAPSHOT_DATA" or (
        "World Elo" not in " ".join(result.reasons)
    )


def test_fifa_activation_requires_coverage_threshold() -> None:
    rows: list[WalkForwardBacktestRow] = []
    low_cov = config.EXTERNAL_FIFA_POINTS_MIN_COVERAGE_FOR_ACTIVATION - 0.05
    for ds in ("WC 2022",):
        rows.extend(
            [
                WalkForwardBacktestRow(
                    dataset=ds,
                    matches=50,
                    candidate="baseline",
                    elo_strategy="internal_only",
                    prior_mode="tournament_prior_file",
                    world_elo_mode="none",
                    external_rating_mode="fifa_points_snapshot",
                    external_rating_type="fifa_points",
                    external_coverage=low_cov,
                    fifa_points_coverage=low_cov,
                    leakage_label="low",
                    data_quality="exact_date",
                    outcome_accuracy=55.0,
                    exact_score_accuracy=10.0,
                    top3_score_hit_rate=25.0,
                    mean_log_loss=1.0,
                    mean_brier=0.6,
                ),
                WalkForwardBacktestRow(
                    dataset=ds,
                    matches=50,
                    candidate="effective_external_current_formula",
                    elo_strategy="fifa_points_confidence_weighted",
                    prior_mode="tournament_prior_file",
                    world_elo_mode="none",
                    external_rating_mode="fifa_points_snapshot",
                    external_rating_type="fifa_points",
                    external_coverage=low_cov,
                    fifa_points_coverage=low_cov,
                    leakage_label="low",
                    data_quality="exact_date",
                    outcome_accuracy=56.0,
                    exact_score_accuracy=10.0,
                    top3_score_hit_rate=25.0,
                    mean_log_loss=0.99,
                    mean_brier=0.59,
                ),
            ]
        )
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.recommended_candidate is None


def test_mixed_dataset_regression_does_not_recommend() -> None:
    rows: list[WalkForwardBacktestRow] = []
    specs = [
        ("WC 2022", 1.0, 1.0, 0.95, 0.55),
        ("WC 2018", 1.0, 1.05, 0.62, 0.50),
        ("Euro 2024", 0.96, 1.08, 0.65, 0.48),
        ("Copa America 2024", 1.0, 1.06, 0.63, 0.49),
    ]
    for ds, cov, cand_log, cand_brier, cand_1x2 in specs:
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=40,
                candidate="baseline",
                elo_strategy="internal_only",
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                external_rating_mode="fifa_points_snapshot",
                external_rating_type="fifa_points",
                external_coverage=cov,
                fifa_points_coverage=cov,
                leakage_label="low",
                data_quality="exact_date",
                outcome_accuracy=52.0,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=1.0,
                mean_brier=0.6,
            )
        )
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=40,
                candidate="effective_external_current_formula",
                elo_strategy="fifa_points_confidence_weighted",
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                external_rating_mode="fifa_points_snapshot",
                external_rating_type="fifa_points",
                external_coverage=cov,
                fifa_points_coverage=cov,
                leakage_label="low",
                data_quality="exact_date",
                outcome_accuracy=cand_1x2,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=cand_log,
                mean_brier=cand_brier,
            )
        )
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.overall_status != "MODEL_ACTIVATION_PASS"
    assert result.recommended_candidate is None


def test_activation_pass_only_meaningful_multi_dataset() -> None:
    """Marginal per-dataset tweaks that do not beat combined thresholds stay neutral."""
    rows: list[WalkForwardBacktestRow] = []
    for ds in ("WC 2022", "WC 2018", "Euro 2024", "Copa America 2024"):
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=40,
                candidate="baseline",
                elo_strategy="internal_only",
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                external_rating_mode="fifa_points_snapshot",
                external_rating_type="fifa_points",
                external_coverage=0.96,
                fifa_points_coverage=0.96,
                leakage_label="low",
                data_quality="exact_date",
                outcome_accuracy=52.0,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=1.0,
                mean_brier=0.6,
            )
        )
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=40,
                candidate="effective_external_current_formula",
                elo_strategy="fifa_points_confidence_weighted",
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                external_rating_mode="fifa_points_snapshot",
                external_rating_type="fifa_points",
                external_coverage=0.96,
                fifa_points_coverage=0.96,
                leakage_label="low",
                data_quality="exact_date",
                outcome_accuracy=52.0,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=1.0,
                mean_brier=0.6,
            )
        )
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.recommended_candidate is None
    assert result.overall_status == "DATA_READY_MODEL_NEUTRAL"


def test_fifa_strong_multi_dataset_can_pass_gate() -> None:
    rows: list[WalkForwardBacktestRow] = []
    for ds, cand_log, cand_brier, cand_1x2 in (
        ("WC 2022", 0.98, 0.58, 54.0),
        ("WC 2018", 0.92, 0.55, 54.0),
        ("Euro 2024", 0.99, 0.60, 54.0),
        ("Copa America 2024", 0.88, 0.53, 54.0),
    ):
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=40,
                candidate="baseline",
                elo_strategy="internal_only",
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                external_rating_mode="fifa_points_snapshot",
                external_rating_type="fifa_points",
                external_coverage=0.96,
                fifa_points_coverage=0.96,
                leakage_label="low",
                data_quality="exact_date",
                outcome_accuracy=52.0,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=1.0,
                mean_brier=0.6,
            )
        )
        rows.append(
            WalkForwardBacktestRow(
                dataset=ds,
                matches=40,
                candidate="effective_external_current_formula",
                elo_strategy="fifa_points_confidence_weighted",
                prior_mode="tournament_prior_file",
                world_elo_mode="none",
                external_rating_mode="fifa_points_snapshot",
                external_rating_type="fifa_points",
                external_coverage=0.96,
                fifa_points_coverage=0.96,
                leakage_label="low",
                data_quality="exact_date",
                outcome_accuracy=cand_1x2,
                exact_score_accuracy=10.0,
                top3_score_hit_rate=25.0,
                mean_log_loss=cand_log,
                mean_brier=cand_brier,
            )
        )
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.overall_status == "MODEL_ACTIVATION_PASS"
    assert result.recommended_candidate is not None
    assert result.recommended_candidate["external_rating_mode"] == "fifa_points_snapshot"


def test_backtest_all_dataset_fifa_snapshot() -> None:
    row = run_walk_forward_backtest(
        "all",
        candidate="baseline",
        external_rating_mode="fifa_points_snapshot",
        prior_mode="tournament_prior_file",
    )
    assert row.matches > 0
    assert row.external_rating_mode == "fifa_points_snapshot"


def test_regression_diagnostics_fifa_mode() -> None:
    results = run_all_regression_diagnostics(
        external_rating_mode="fifa_points_snapshot",
        power_variant="effective_external_current_formula",
        elo_strategy="fifa_points_confidence_weighted",
    )
    assert len(results) >= 6
    assert all(r.external_rating_mode == "fifa_points_snapshot" for r in results)
    assert all(r.candidate == "effective_external_current_formula" for r in results)


def test_evaluate_activation_gate_cli_accepts_fifa_mode() -> None:
    proc = subprocess.run(
        [
            PYTHON,
            "scripts/evaluate_activation_gate.py",
            "--run-walk-forward",
            "--external-rating-mode",
            "fifa_points_snapshot",
            "--prior-mode",
            "tournament_prior_file",
            "--candidate-set",
            "serious",
            "--dataset",
            "wc2022",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0
    assert "fifa_points_snapshot" in proc.stdout.lower() or "FIFA" in proc.stdout


def test_production_predictions_unchanged() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    r = client.post(
        "/api/predict",
        json={"home_team": "Brazil", "away_team": "Morocco", "neutral_ground": True},
    )
    assert r.status_code == 200
    assert config.POWER_CANDIDATE_AFFECTS_PREDICTION is False
    assert config.GLOBAL_RATINGS_AFFECT_PREDICTION is False
