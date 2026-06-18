"""Phase 2G — Activation gate semantics and candidate meaningfulness tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import config
from core.model_activation_gate import (
    ActivationGateResult,
    activation_candidate_status,
    activation_diagnostic_fields,
    candidate_meaningfully_improves,
    evaluate_activation_gate,
)
from core.temporal_backtest import WalkForwardBacktestRow

PYTHON = sys.executable


def _wf_row(
    dataset: str,
    candidate: str,
    *,
    log_loss: float,
    brier: float,
    acc: float,
    elo_strategy: str = "internal_only",
) -> WalkForwardBacktestRow:
    return WalkForwardBacktestRow(
        dataset=dataset,
        matches=50,
        candidate=candidate,
        elo_strategy=elo_strategy,
        prior_mode="tournament_prior_file",
        world_elo_mode="none",
        leakage_label="low",
        data_quality="exact_date",
        outcome_accuracy=acc,
        exact_score_accuracy=10.0,
        top3_score_hit_rate=25.0,
        mean_log_loss=log_loss,
        mean_brier=brier,
        favorite_calibration_error=0.45,
    )


def _zero_delta_rows() -> list[WalkForwardBacktestRow]:
    rows: list[WalkForwardBacktestRow] = []
    for ds in ("WC 2018", "WC 2022", "Euro 2024", "Copa America 2024"):
        rows.append(_wf_row(ds, "baseline", log_loss=0.98, brier=0.58, acc=55.0))
        rows.append(
            _wf_row(
                ds,
                "effective_elo_current_formula",
                log_loss=0.98,
                brier=0.58,
                acc=55.0,
                elo_strategy="blended_confidence_weighted",
            )
        )
    return rows


def test_zero_deltas_data_ready_model_neutral() -> None:
    result = evaluate_activation_gate(
        walk_forward_rows=_zero_delta_rows(),
        run_backtests=False,
    )
    assert result.temporal_data_status == "PASS"
    assert result.model_candidate_status in (
        "NO_MEANINGFUL_IMPROVEMENT",
        "NEEDS_MORE_EXTERNAL_SNAPSHOT_DATA",
    )
    assert result.overall_status == "DATA_READY_MODEL_NEUTRAL"
    assert result.recommended_candidate is None


def test_recommended_null_when_no_meaningful_improvement() -> None:
    result = evaluate_activation_gate(
        walk_forward_rows=_zero_delta_rows(),
        run_backtests=False,
    )
    assert result.recommended_candidate is None
    assert result.best_diagnostic_candidate["variant"] == "effective_elo_current_formula"


def test_temporal_pass_independent_of_model_status() -> None:
    result = evaluate_activation_gate(
        walk_forward_rows=_zero_delta_rows(),
        run_backtests=False,
    )
    assert result.temporal_data_status == "PASS"
    assert result.model_candidate_status in (
        "NO_MEANINGFUL_IMPROVEMENT",
        "NEEDS_MORE_EXTERNAL_SNAPSHOT_DATA",
    )


def test_model_activation_pass_requires_meaningful_improvement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.model_activation_gate._external_snapshot_activation_ready",
        lambda: (True, []),
    )
    rows: list[WalkForwardBacktestRow] = []
    for ds in ("WC 2018", "WC 2022", "Euro 2024"):
        rows.append(_wf_row(ds, "baseline", log_loss=0.98, brier=0.58, acc=55.0))
        rows.append(
            _wf_row(
                ds,
                "effective_elo_current_formula",
                log_loss=0.96,
                brier=0.565,
                acc=56.5,
                elo_strategy="blended_confidence_weighted",
            )
        )
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.overall_status == "MODEL_ACTIVATION_PASS"
    assert result.recommended_candidate is not None


def test_high_leakage_blocks_activation() -> None:
    rows = [
        WalkForwardBacktestRow(
            dataset="WC 2022",
            matches=10,
            candidate="baseline",
            elo_strategy="internal_only",
            prior_mode="default_internal",
            world_elo_mode="current_static",
            leakage_label="high",
            data_quality="estimated_order",
            outcome_accuracy=50.0,
            exact_score_accuracy=10.0,
            top3_score_hit_rate=20.0,
            mean_log_loss=1.0,
            mean_brier=0.6,
        )
    ]
    result = evaluate_activation_gate(walk_forward_rows=rows, run_backtests=False)
    assert result.overall_status == "FAIL_HIGH_LEAKAGE"
    assert result.temporal_data_status == "FAIL_HIGH_LEAKAGE"
    assert result.recommended_candidate is None


def test_1x2_only_improvement_can_pass() -> None:
    deltas = {"log_loss": 0.0, "brier": 0.0, "1x2_acc_pp": 1.2}
    assert candidate_meaningfully_improves(deltas) is True


def test_1x2_improvement_with_worse_calibration_fails_meaningful() -> None:
    deltas = {"log_loss": 0.01, "brier": 0.01, "1x2_acc_pp": 2.0}
    assert candidate_meaningfully_improves(deltas) is False


def test_activation_candidate_status_data_ready_model_neutral() -> None:
    result = ActivationGateResult(
        recommended_candidate=None,
        status="DATA_READY_MODEL_NEUTRAL",
        temporal_data_status="PASS",
        model_candidate_status="NO_MEANINGFUL_IMPROVEMENT",
        overall_status="DATA_READY_MODEL_NEUTRAL",
        reasons=[],
        metric_deltas_vs_baseline={},
        dataset_summary=[],
        leakage_risk_level="low",
        balanced_match_warnings=[],
    )
    assert activation_candidate_status(result) == "data_ready_model_neutral"


def test_activation_diagnostic_fields() -> None:
    fields = activation_diagnostic_fields(
        ActivationGateResult(
            recommended_candidate=None,
            status="DATA_READY_MODEL_NEUTRAL",
            temporal_data_status="PASS",
            model_candidate_status="NO_MEANINGFUL_IMPROVEMENT",
            overall_status="DATA_READY_MODEL_NEUTRAL",
            reasons=[],
            metric_deltas_vs_baseline={},
            dataset_summary=[],
            leakage_risk_level="low",
            balanced_match_warnings=[],
        )
    )
    assert fields["activation_overall_status"] == "DATA_READY_MODEL_NEUTRAL"
    assert fields["temporal_data_status"] == "PASS"
    assert fields["model_candidate_status"] == "NO_MEANINGFUL_IMPROVEMENT"


def test_evaluate_activation_gate_cli_prints_separate_statuses() -> None:
    proc = subprocess.run(
        [PYTHON, "scripts/evaluate_activation_gate.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "Overall status:" in proc.stdout or "NEEDS_MORE_DATA" in proc.stdout


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
    body = r.json()
    psc = body.get("global_rating_diagnostics", {}).get("power_shadow_calibration") or {}
    assert psc.get("affects_prediction") is False
    assert "activation_overall_status" in psc or psc.get("activation_candidate_status")
